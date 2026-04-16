from __future__ import annotations

from dataclasses import dataclass

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.routing.candidate_builder import RouteCandidateBuilder
from research_layer.routing.ranker import RouteRanker
from research_layer.routing.summarizer import RouteSummarizer
from research_layer.services.llm_gateway import ResearchLLMError
from research_layer.services.llm_trace import build_event_trace_parts
from research_layer.services.score_service import ScoreService, ScoreServiceError


@dataclass(slots=True)
class RouteGenerationServiceError(Exception):
    status_code: int
    error_code: str
    message: str
    details: dict[str, object]

    def __str__(self) -> str:
        return self.message


class RouteGenerationService:
    def __init__(self, store: ResearchApiStateStore) -> None:
        self._store = store
        self._builder = RouteCandidateBuilder()
        self._ranker = RouteRanker()
        self._summarizer = RouteSummarizer()
        self._score_service = ScoreService(store)

    def _raise(
        self,
        *,
        status_code: int,
        error_code: str,
        message: str,
        details: dict[str, object] | None = None,
    ) -> None:
        raise RouteGenerationServiceError(
            status_code=status_code,
            error_code=error_code,
            message=message,
            details=details or {},
        )

    async def generate_routes(
        self,
        *,
        workspace_id: str,
        request_id: str,
        reason: str,
        max_candidates: int,
        failure_mode: str | None = None,
        allow_fallback: bool = True,
    ) -> dict[str, object]:
        if max_candidates <= 0 or max_candidates > 20:
            self._raise(
                status_code=400,
                error_code="research.invalid_request",
                message="max_candidates must be in [1, 20]",
                details={"max_candidates": max_candidates},
            )

        graph_nodes = self._store.list_graph_nodes(workspace_id)
        graph_edges = self._store.list_graph_edges(workspace_id)
        if not graph_nodes:
            self._raise(
                status_code=409,
                error_code="research.invalid_state",
                message="graph is not ready for route generation",
                details={"workspace_id": workspace_id},
            )
        node_map = {str(node["node_id"]): node for node in graph_nodes}
        workspace_snapshot = self._store.get_graph_workspace(workspace_id)
        version_id = (
            str(workspace_snapshot.get("latest_version_id"))
            if workspace_snapshot and workspace_snapshot.get("latest_version_id")
            else None
        )

        self._store.emit_event(
            event_name="route_generation_started",
            request_id=request_id,
            job_id=None,
            workspace_id=workspace_id,
            component="route_generation_service",
            step="generate",
            status="started",
            refs={"version_id": version_id},
            metrics={
                "graph_node_count": len(graph_nodes),
                "graph_edge_count": len(graph_edges),
                "max_candidates": max_candidates,
                "reason": reason,
            },
        )

        existing_route_ids = [
            str(route["route_id"])
            for route in self._store.list_routes(workspace_id)
            if route.get("route_id")
        ]
        generated_route_ids: list[str] = []

        try:
            candidates = self._builder.build_candidates(
                workspace_id=workspace_id,
                graph_nodes=graph_nodes,
                graph_edges=graph_edges,
                version_id=version_id,
                max_candidates=max_candidates,
            )
            if not candidates:
                self._raise(
                    status_code=409,
                    error_code="research.invalid_state",
                    message="no route candidates can be built from current graph",
                    details={"workspace_id": workspace_id},
                )

            generated_routes: list[dict[str, object]] = []
            total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            latest_trace_refs: dict[str, object] = {}
            latest_trace_metrics: dict[str, object] = {}

            for index, candidate in enumerate(candidates):
                seed_summary, _ = await self._summarizer.summarize(
                    candidate=candidate,
                    node_map=node_map,
                    top_factors=[],
                    request_id=request_id,
                    failure_mode=failure_mode,
                    allow_fallback=allow_fallback,
                )
                relation_tags = self._build_relation_tags(
                    candidate=candidate,
                    node_map=node_map,
                )
                route = self._store.create_route(
                    workspace_id=workspace_id,
                    title=seed_summary["title"],
                    summary=seed_summary["summary"],
                    status="candidate",
                    support_score=0.0,
                    risk_score=0.0,
                    progressability_score=0.0,
                    novelty_level="incremental",
                    relation_tags=relation_tags,
                    conclusion=seed_summary["conclusion"],
                    key_supports=seed_summary["key_supports"],
                    assumptions=seed_summary["assumptions"],
                    risks=seed_summary["risks"],
                    next_validation_action=seed_summary["next_validation_action"],
                    conclusion_node_id=str(candidate.get("conclusion_node_id") or ""),
                    route_node_ids=[
                        str(node_id) for node_id in candidate.get("route_node_ids", [])
                    ],
                    route_edge_ids=[
                        str(edge_id)
                        for edge_id in (
                            (candidate.get("trace_refs") or {}).get("route_edge_ids", [])
                        )
                    ],
                    key_support_node_ids=[
                        str(node_id) for node_id in candidate.get("key_support_node_ids", [])
                    ],
                    key_assumption_node_ids=[
                        str(node_id)
                        for node_id in candidate.get("key_assumption_node_ids", [])
                    ],
                    risk_node_ids=[
                        str(node_id) for node_id in candidate.get("risk_node_ids", [])
                    ],
                    next_validation_node_id=(
                        str(candidate["next_validation_node_id"])
                        if candidate.get("next_validation_node_id")
                        else None
                    ),
                    version_id=version_id,
                    summary_generation_mode=seed_summary.get(
                        "summary_generation_mode", "llm"
                    ),
                    key_strengths=seed_summary.get("key_strengths", []),
                    key_risks=seed_summary.get("key_risks", []),
                    open_questions=seed_summary.get("open_questions", []),
                    degraded=bool(seed_summary.get("degraded", False)),
                    fallback_used=bool(seed_summary.get("fallback_used", False)),
                    degraded_reason=seed_summary.get("degraded_reason"),
                )
                route_id = str(route["route_id"])
                generated_route_ids.append(route_id)
                scored = self._score_service.score_route(
                    workspace_id=workspace_id,
                    route_id=route_id,
                    request_id=request_id,
                    focus_node_ids=[
                        str(node_id) for node_id in candidate.get("route_node_ids", [])
                    ],
                )
                final_summary, llm_trace = await self._summarizer.summarize(
                    candidate=candidate,
                    node_map=node_map,
                    top_factors=scored.get("top_factors", []),
                    request_id=request_id,
                    failure_mode=failure_mode,
                    allow_fallback=allow_fallback,
                )
                trace_refs, trace_metrics = build_event_trace_parts(llm_trace)
                latest_trace_refs = trace_refs
                latest_trace_metrics = trace_metrics
                total_usage["prompt_tokens"] += int(trace_metrics.get("prompt_tokens") or 0)
                total_usage["completion_tokens"] += int(
                    trace_metrics.get("completion_tokens") or 0
                )
                total_usage["total_tokens"] += int(trace_metrics.get("total_tokens") or 0)
                updated = self._store.update_route_projection(
                    route_id=route_id,
                    title=f"{final_summary['title']} #{index + 1}",
                    summary=final_summary["summary"],
                    conclusion=final_summary["conclusion"],
                    key_supports=final_summary["key_supports"],
                    assumptions=final_summary["assumptions"],
                    risks=final_summary["risks"],
                    next_validation_action=final_summary["next_validation_action"],
                    conclusion_node_id=str(candidate.get("conclusion_node_id") or ""),
                    route_node_ids=[
                        str(node_id) for node_id in candidate.get("route_node_ids", [])
                    ],
                    route_edge_ids=[
                        str(edge_id)
                        for edge_id in (
                            (candidate.get("trace_refs") or {}).get("route_edge_ids", [])
                        )
                    ],
                    key_support_node_ids=[
                        str(node_id) for node_id in candidate.get("key_support_node_ids", [])
                    ],
                    key_assumption_node_ids=[
                        str(node_id)
                        for node_id in candidate.get("key_assumption_node_ids", [])
                    ],
                    risk_node_ids=[
                        str(node_id) for node_id in candidate.get("risk_node_ids", [])
                    ],
                    next_validation_node_id=(
                        str(candidate["next_validation_node_id"])
                        if candidate.get("next_validation_node_id")
                        else None
                    ),
                    version_id=version_id,
                    provider_backend=llm_trace.provider_backend,
                    provider_model=llm_trace.provider_model,
                    llm_request_id=llm_trace.request_id,
                    llm_response_id=llm_trace.llm_response_id,
                    usage=llm_trace.usage,
                    fallback_used=llm_trace.fallback_used,
                    degraded=llm_trace.degraded,
                    degraded_reason=llm_trace.degraded_reason,
                    summary_generation_mode=final_summary.get(
                        "summary_generation_mode", "llm"
                    ),
                    key_strengths=final_summary.get("key_strengths", []),
                    key_risks=final_summary.get("key_risks", []),
                    open_questions=final_summary.get("open_questions", []),
                )
                if updated is not None:
                    generated_routes.append(updated)

            ranked_routes = self._ranker.rank_routes(generated_routes)
            persisted_ranked_routes: list[dict[str, object]] = []
            for rank, route in enumerate(ranked_routes, start=1):
                updated = self._store.update_route_rank(
                    route_id=str(route["route_id"]),
                    rank=rank,
                )
                if updated is not None:
                    persisted_ranked_routes.append(updated)
                else:
                    persisted_ranked_routes.append({**route, "rank": rank})

            top_route = persisted_ranked_routes[0] if persisted_ranked_routes else None
            top_factor_names: list[str] = []
            if top_route:
                for factor in top_route.get("top_factors", []):
                    if isinstance(factor, dict):
                        top_factor_names.append(str(factor.get("factor_name", "")))
                top_factor_names = top_factor_names[:3]

            self._store.emit_event(
                event_name="route_generation_completed",
                request_id=request_id,
                job_id=None,
                workspace_id=workspace_id,
                component="route_generation_service",
                step="generate",
                status="completed",
                refs={
                    "route_id": top_route.get("route_id") if top_route else None,
                    "version_id": version_id,
                    "provider_backend": latest_trace_refs.get("provider_backend"),
                    "provider_model": latest_trace_refs.get("provider_model"),
                    "request_id": latest_trace_refs.get("request_id", request_id),
                    "llm_response_id": latest_trace_refs.get("llm_response_id"),
                },
                metrics={
                    "graph_node_count": len(graph_nodes),
                    "graph_edge_count": len(graph_edges),
                    "candidate_count": len(candidates),
                    "generated_route_count": len(persisted_ranked_routes),
                    "ranked_route_ids": [
                        str(route["route_id"]) for route in persisted_ranked_routes
                    ],
                    "top_factors": top_factor_names,
                    "prompt_tokens": total_usage["prompt_tokens"],
                    "completion_tokens": total_usage["completion_tokens"],
                    "total_tokens": total_usage["total_tokens"],
                    "fallback_used": bool(latest_trace_metrics.get("fallback_used", False)),
                    "degraded": bool(latest_trace_metrics.get("degraded", False)),
                    "degraded_reason": latest_trace_metrics.get("degraded_reason"),
                },
            )
            for old_route_id in existing_route_ids:
                self._store.delete_route(old_route_id)
            return {
                "workspace_id": workspace_id,
                "generated_count": len(persisted_ranked_routes),
                "ranked_route_ids": [
                    str(route["route_id"]) for route in persisted_ranked_routes
                ],
                "top_route_id": str(top_route["route_id"]) if top_route else None,
            }
        except (RouteGenerationServiceError, ScoreServiceError, ResearchLLMError) as exc:
            for generated_route_id in generated_route_ids:
                self._store.delete_route(generated_route_id)
            self._store.emit_event(
                event_name="route_generation_completed",
                request_id=request_id,
                job_id=None,
                workspace_id=workspace_id,
                component="route_generation_service",
                step="generate",
                status="failed",
                error={
                    "error_code": exc.error_code,
                    "message": exc.message,
                    "details": exc.details,
                },
            )
            if isinstance(exc, RouteGenerationServiceError):
                raise
            self._raise(
                status_code=exc.status_code,
                error_code=exc.error_code,
                message=exc.message,
                details=exc.details,
            )

    def _build_relation_tags(
        self,
        *,
        candidate: dict[str, object],
        node_map: dict[str, dict[str, object]],
    ) -> list[str]:
        tags: list[str] = []
        key_support_node_ids = [
            str(node_id) for node_id in candidate.get("key_support_node_ids", [])
        ]
        if key_support_node_ids:
            tags.append("direct_support")

        route_node_ids = [str(node_id) for node_id in candidate.get("route_node_ids", [])]
        route_nodes = [
            node_map[node_id]
            for node_id in route_node_ids
            if node_id in node_map
        ]
        semantic_object_types = {
            str(node.get("object_ref_type", "")).strip()
            for node in route_nodes
            if str(node.get("node_type", "")) not in {"failure", "conflict"}
        }
        key_assumption_node_ids = [
            str(node_id) for node_id in candidate.get("key_assumption_node_ids", [])
        ]
        if len(semantic_object_types) >= 2 or (
            key_support_node_ids and key_assumption_node_ids
        ):
            tags.append("recombination")

        if not key_support_node_ids and (
            key_assumption_node_ids or candidate.get("risk_node_ids")
        ):
            tags.append("upstream_inspiration")

        if not tags:
            tags.append("upstream_inspiration")
        return tags
