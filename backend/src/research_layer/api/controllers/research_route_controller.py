from __future__ import annotations

from fastapi import Query, Request

from core.di.decorators import controller
from core.interface.controller.base_controller import BaseController, get, post
from research_layer.api.controllers._job_runner import schedule_background_job
from research_layer.api.controllers._state_store import STORE
from research_layer.api.controllers._utils import (
    ensure,
    get_request_id,
    parse_request_model,
    raise_http_error,
    validate_workspace_id,
)
from research_layer.api.schemas.common import (
    AsyncJobAcceptedResponse,
    ErrorResponse,
    ResearchErrorCode,
)
from research_layer.api.schemas.route import (
    RouteGenerateRequest,
    RouteGenerateResponse,
    RouteListResponse,
    RoutePreviewResponse,
    RouteRecomputeRequest,
    RouteRecord,
    RouteScoreRequest,
    RouteScoreResponse,
)
from research_layer.routing.ranker import RouteRanker
from research_layer.routing.summarizer import RouteSummarizer
from research_layer.services.route_generation_service import (
    RouteGenerationService,
    RouteGenerationServiceError,
)
from research_layer.services.route_challenge_service import RouteChallengeService
from research_layer.services.recompute_service import (
    RecomputeService,
    RecomputeServiceError,
)
from research_layer.services.evermemos_bridge_service import EverMemOSRecallService
from research_layer.services.score_service import ScoreService, ScoreServiceError


@controller(name="research_route_controller")
class ResearchRouteController(BaseController):
    def __init__(self) -> None:
        super().__init__(
            prefix="/api/v1/research", tags=["Research Route"], default_auth="none"
        )
        self._score_service = ScoreService(STORE)
        self._route_generation_service = RouteGenerationService(STORE)
        self._route_challenge_service = RouteChallengeService(STORE)
        self._recompute_service = RecomputeService(STORE)
        self._route_ranker = RouteRanker()
        self._route_summarizer = RouteSummarizer()
        self._memory_recall_service = EverMemOSRecallService(STORE)

    def _route_scope_claim_ids(
        self,
        *,
        route: dict[str, object],
        node_map: dict[str, dict[str, object]],
    ) -> list[str]:
        claim_ids: list[str] = []
        seen: set[str] = set()
        for node_id in route.get("route_node_ids", []):
            node = node_map.get(str(node_id))
            if node is None:
                continue
            claim_id = str(node.get("claim_id") or "").strip()
            if not claim_id or claim_id in seen:
                continue
            seen.add(claim_id)
            claim_ids.append(claim_id)
        return claim_ids

    def _route_query_text(
        self,
        *,
        route: dict[str, object],
        node_map: dict[str, dict[str, object]],
        claim_ids: list[str],
    ) -> str:
        parts: list[str] = []
        for field in ("title", "summary", "conclusion", "next_validation_action"):
            value = str(route.get(field) or "").strip()
            if value and value not in parts:
                parts.append(value)
        for claim_id in claim_ids[:4]:
            claim = STORE.get_claim(claim_id)
            if claim is None:
                continue
            claim_text = str(claim.get("text") or "").strip()
            if claim_text and claim_text not in parts:
                parts.append(claim_text)
        for node_id in route.get("route_node_ids", [])[:4]:
            node = node_map.get(str(node_id))
            if node is None:
                continue
            label = str(node.get("short_label") or "").strip()
            if label and label not in parts:
                parts.append(label)
        return " ".join(parts[:6]).strip()

    def _route_memory_recall(
        self,
        *,
        route: dict[str, object],
        node_map: dict[str, dict[str, object]],
        request_id: str,
    ) -> dict[str, object]:
        claim_ids = self._route_scope_claim_ids(route=route, node_map=node_map)
        if not claim_ids:
            return self._memory_recall_service.failed(
                workspace_id=str(route["workspace_id"]),
                requested_method="logical",
                reason="route_missing_claim_scope",
                query_text=None,
                request_id=request_id,
                trace_refs={"route_id": str(route["route_id"])},
            )
        query_text = self._route_query_text(
            route=route,
            node_map=node_map,
            claim_ids=claim_ids,
        )
        if not query_text:
            return self._memory_recall_service.failed(
                workspace_id=str(route["workspace_id"]),
                requested_method="logical",
                reason="route_missing_recall_query",
                query_text=None,
                request_id=request_id,
                trace_refs={
                    "route_id": str(route["route_id"]),
                    "route_node_ids": route.get("route_node_ids", []),
                },
            )
        return self._memory_recall_service.recall(
            workspace_id=str(route["workspace_id"]),
            query_text=query_text,
            requested_method="logical",
            scope_claim_ids=claim_ids,
            scope_mode="require",
            top_k=8,
            request_id=request_id,
            trace_refs={"route_id": str(route["route_id"])},
        )

    def _route_node_map(self, *, workspace_id: str) -> dict[str, dict[str, object]]:
        return {str(node["node_id"]): node for node in STORE.list_graph_nodes(workspace_id)}

    def _materialize_route_challenge(
        self,
        *,
        route: dict[str, object],
        node_map: dict[str, dict[str, object]],
        conflicts: list[dict[str, object]] | None = None,
        conflict_index: dict[str, list[dict[str, object]]] | None = None,
    ) -> dict[str, object]:
        claim_ids = self._route_scope_claim_ids(route=route, node_map=node_map)
        challenge_route = {**route, "claim_ids": claim_ids}
        workspace_id = str(route["workspace_id"])
        if conflict_index is not None:
            challenge = self._route_challenge_service.evaluate_route_with_conflict_index(
                route=challenge_route,
                conflict_index=conflict_index,
            )
        elif conflicts is None:
            challenge = self._route_challenge_service.evaluate_route(
                workspace_id=workspace_id,
                route=challenge_route,
            )
        else:
            challenge = self._route_challenge_service.evaluate_route_with_conflicts(
                workspace_id=workspace_id,
                route=challenge_route,
                conflicts=conflicts,
            )
        return {
            **route,
            "claim_ids": claim_ids,
            "challenge_status": challenge["challenge_status"],
            "challenge_refs": {
                "conflict_count": challenge["conflict_count"],
                "conflict_ids": challenge["conflict_ids"],
            },
        }

    @get("/routes", response_model=RouteListResponse)
    async def list_routes(
        self, workspace_id: str | None = Query(default=None)
    ) -> RouteListResponse:
        workspace = validate_workspace_id(workspace_id)
        ranked_routes = self._route_ranker.rank_routes(STORE.list_routes(workspace))
        materialized: list[dict[str, object]] = []
        for index, route in enumerate(ranked_routes, start=1):
            persisted = route
            if int(route.get("rank") or 0) != index:
                updated = STORE.update_route_rank(
                    route_id=str(route["route_id"]),
                    rank=index,
                )
                if updated is not None:
                    persisted = updated
                else:
                    persisted = {**route, "rank": index}
            materialized.append(persisted)

        node_map = self._route_node_map(workspace_id=workspace)
        conflicts = STORE.list_claim_conflicts(workspace_id=workspace)
        conflict_index = self._route_challenge_service.build_conflict_index(
            workspace_id=workspace,
            conflicts=conflicts,
        )
        items = [
            RouteRecord.model_validate(
                self._materialize_route_challenge(
                    route=route,
                    node_map=node_map,
                    conflict_index=conflict_index,
                )
            )
            for route in materialized
        ]
        return RouteListResponse(items=items, total=len(items))

    @get(
        "/routes/{route_id}",
        response_model=RouteRecord,
        responses={
            400: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
        },
    )
    async def get_route(
        self, route_id: str, request: Request, workspace_id: str | None = Query(default=None)
    ) -> RouteRecord:
        workspace = validate_workspace_id(workspace_id)
        request_id = get_request_id(request.headers.get("x-request-id"))
        route = STORE.get_route(route_id)
        ensure(
            route is not None,
            status_code=404,
            code=ResearchErrorCode.NOT_FOUND.value,
            message="route not found",
            details={"route_id": route_id},
        )
        ensure(
            str(route["workspace_id"]) == workspace,
            status_code=409,
            code=ResearchErrorCode.CONFLICT.value,
            message="workspace_id does not match route ownership",
            details={"route_id": route_id},
        )
        node_map = self._route_node_map(workspace_id=str(route["workspace_id"]))
        challenged_route = self._materialize_route_challenge(
            route=route,
            node_map=node_map,
        )
        return RouteRecord.model_validate(
            {
                **challenged_route,
                "memory_recall": self._route_memory_recall(
                    route=route,
                    node_map=node_map,
                    request_id=request_id,
                ),
            }
        )

    @get(
        "/routes/{route_id}/preview",
        response_model=RoutePreviewResponse,
        responses={
            400: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
        },
    )
    async def preview_route(
        self, route_id: str, request: Request, workspace_id: str | None = Query(default=None)
    ) -> RoutePreviewResponse:
        workspace = validate_workspace_id(workspace_id)
        request_id = get_request_id(request.headers.get("x-request-id"))
        route = STORE.get_route(route_id)
        ensure(
            route is not None,
            status_code=404,
            code=ResearchErrorCode.NOT_FOUND.value,
            message="route not found",
            details={"route_id": route_id},
        )
        ensure(
            str(route["workspace_id"]) == workspace,
            status_code=409,
            code=ResearchErrorCode.CONFLICT.value,
            message="workspace_id does not match route ownership",
            details={"route_id": route_id},
        )
        node_map = self._route_node_map(workspace_id=str(route["workspace_id"]))
        def node_ref(node_id: str) -> dict[str, object]:
            node = node_map.get(node_id)
            if node is None:
                return {
                    "node_id": node_id,
                    "node_type": "unknown",
                    "object_ref_type": "unknown",
                    "object_ref_id": "",
                    "short_label": node_id,
                    "status": "unknown",
                }
            return {
                "node_id": str(node.get("node_id", node_id)),
                "node_type": str(node.get("node_type", "unknown")),
                "object_ref_type": str(node.get("object_ref_type", "unknown")),
                "object_ref_id": str(node.get("object_ref_id", "")),
                "short_label": str(node.get("short_label", "")),
                "status": str(node.get("status", "unknown")),
            }

        conclusion_node = node_ref(str(route.get("conclusion_node_id") or ""))
        key_support_evidence = [
            node_ref(str(node_id)) for node_id in route.get("key_support_node_ids", [])
        ]
        key_assumptions = [
            node_ref(str(node_id)) for node_id in route.get("key_assumption_node_ids", [])
        ]
        conflict_failure_hints = []
        for node_id in route.get("risk_node_ids", []):
            ref = node_ref(str(node_id))
            conflict_failure_hints.append(
                {"node": ref, "hint": f"Risk signal from {ref['short_label'] or ref['node_id']}"}
            )
        return RoutePreviewResponse.model_validate(
            {
                "route_id": route_id,
                "workspace_id": route["workspace_id"],
                "summary": str(route.get("summary", "")),
                "summary_generation_mode": str(
                    route.get("summary_generation_mode", "llm")
                ),
                "degraded": bool(route.get("degraded", False)),
                "provider_backend": route.get("provider_backend"),
                "provider_model": route.get("provider_model"),
                "request_id": route.get("request_id"),
                "llm_response_id": route.get("llm_response_id"),
                "usage": route.get("usage"),
                "fallback_used": bool(route.get("fallback_used", False)),
                "degraded_reason": route.get("degraded_reason"),
                "key_strengths": route.get("key_strengths", []),
                "key_risks": route.get("key_risks", []),
                "open_questions": route.get("open_questions", []),
                "conclusion_node": conclusion_node,
                "key_support_evidence": key_support_evidence,
                "key_assumptions": key_assumptions,
                "conflict_failure_hints": conflict_failure_hints,
                "next_validation_action": route.get("next_validation_action"),
                "top_factors": route.get("top_factors", []),
                "trace_refs": {
                    "version_id": route.get("version_id"),
                    "route_node_ids": route.get("route_node_ids", []),
                    "route_edge_ids": route.get("route_edge_ids", []),
                    "conclusion_node_id": route.get("conclusion_node_id"),
                },
                "memory_recall": self._route_memory_recall(
                    route=route,
                    node_map=node_map,
                    request_id=request_id,
                ),
            }
        )

    @post(
        "/routes/generate",
        response_model=RouteGenerateResponse,
        responses={400: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    )
    async def generate_routes(self, request: Request) -> RouteGenerateResponse:
        payload = await parse_request_model(request, RouteGenerateRequest)
        request_id = get_request_id(request.headers.get("x-request-id"))
        failure_mode = request.headers.get("x-research-llm-failure-mode")
        allow_fallback = request.headers.get("x-research-llm-allow-fallback") in {
            "1",
            "true",
            "TRUE",
        }
        try:
            generated = await self._route_generation_service.generate_routes(
                workspace_id=payload.workspace_id,
                request_id=request_id,
                reason=payload.reason,
                max_candidates=payload.max_candidates,
                failure_mode=failure_mode,
                allow_fallback=allow_fallback,
            )
        except RouteGenerationServiceError as exc:
            raise_http_error(
                status_code=exc.status_code,
                code=exc.error_code,
                message=exc.message,
                details=exc.details,
            )
        return RouteGenerateResponse.model_validate(generated)

    @post(
        "/routes/{route_id}/score",
        response_model=RouteScoreResponse,
        responses={
            400: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
        },
    )
    async def score_route(self, route_id: str, request: Request) -> RouteScoreResponse:
        payload = await parse_request_model(request, RouteScoreRequest)
        request_id = get_request_id(request.headers.get("x-request-id"))
        try:
            scored = self._score_service.score_route(
                workspace_id=payload.workspace_id,
                route_id=route_id,
                request_id=request_id,
                template_id=payload.template_id,
                focus_node_ids=payload.focus_node_ids,
            )
        except ScoreServiceError as exc:
            raise_http_error(
                status_code=exc.status_code,
                code=exc.error_code,
                message=exc.message,
                details=exc.details,
            )
        return RouteScoreResponse.model_validate(scored)

    @post(
        "/routes/recompute",
        response_model=AsyncJobAcceptedResponse,
        status_code=202,
        responses={
            400: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
        },
    )
    async def recompute_routes(self, request: Request) -> AsyncJobAcceptedResponse:
        payload = await parse_request_model(request, RouteRecomputeRequest)
        request_id = get_request_id(request.headers.get("x-request-id"))
        ensure(
            payload.async_mode,
            status_code=400,
            code=ResearchErrorCode.INVALID_REQUEST.value,
            message="async_mode must be true for route recompute endpoint",
            details={"async_mode": payload.async_mode},
        )
        failure_mode = request.headers.get("x-research-llm-failure-mode")
        allow_fallback = request.headers.get("x-research-llm-allow-fallback") in {
            "1",
            "true",
            "TRUE",
        }
        workspace_id = validate_workspace_id(payload.workspace_id)
        if payload.failure_id:
            failure = STORE.get_failure(payload.failure_id)
            ensure(
                failure is not None,
                status_code=404,
                code=ResearchErrorCode.NOT_FOUND.value,
                message="failure not found",
                details={"failure_id": payload.failure_id},
            )
            ensure(
                str(failure["workspace_id"]) == workspace_id,
                status_code=409,
                code=ResearchErrorCode.CONFLICT.value,
                message="workspace_id does not match failure ownership",
                details={"failure_id": payload.failure_id},
            )
            job = STORE.create_job(
                job_type="failure_recompute",
                workspace_id=workspace_id,
                request_id=request_id,
            )
            if payload.async_mode:
                schedule_background_job(
                    self._run_failure_recompute_job(
                        job_id=str(job["job_id"]),
                        workspace_id=workspace_id,
                        request_id=request_id,
                        failure_id=str(payload.failure_id),
                        reason=payload.reason,
                    ),
                    job_id=str(job["job_id"]),
                    job_type=str(job["job_type"]),
                )
                latest_job = STORE.get_job(str(job["job_id"]))
                return AsyncJobAcceptedResponse(
                    job_id=job["job_id"],
                    job_type=job["job_type"],
                    status=latest_job["status"] if latest_job is not None else job["status"],
                    workspace_id=workspace_id,
                    status_url=f"/api/v1/research/jobs/{job['job_id']}",
                )
            try:
                await self._run_failure_recompute_job(
                    job_id=str(job["job_id"]),
                    workspace_id=workspace_id,
                    request_id=request_id,
                    failure_id=str(payload.failure_id),
                    reason=payload.reason,
                )
            except RecomputeServiceError as exc:
                raise_http_error(
                    status_code=exc.status_code,
                    code=exc.error_code,
                    message=exc.message,
                    details={**exc.details, "job_id": job["job_id"]},
                )
            finished_job = STORE.get_job(str(job["job_id"]))
            return AsyncJobAcceptedResponse(
                job_id=job["job_id"],
                job_type=job["job_type"],
                status=finished_job["status"] if finished_job is not None else "succeeded",
                workspace_id=workspace_id,
                status_url=f"/api/v1/research/jobs/{job['job_id']}",
            )

        job = STORE.create_job(
            job_type="route_recompute", workspace_id=workspace_id, request_id=request_id
        )
        if payload.async_mode:
            schedule_background_job(
                self._run_route_recompute_job(
                    job_id=str(job["job_id"]),
                    workspace_id=workspace_id,
                    request_id=request_id,
                    reason=payload.reason,
                    failure_mode=failure_mode,
                    allow_fallback=allow_fallback,
                ),
                job_id=str(job["job_id"]),
                job_type=str(job["job_type"]),
            )
            latest_job = STORE.get_job(str(job["job_id"]))
            return AsyncJobAcceptedResponse(
                job_id=job["job_id"],
                job_type=job["job_type"],
                status=latest_job["status"] if latest_job is not None else job["status"],
                workspace_id=workspace_id,
                status_url=f"/api/v1/research/jobs/{job['job_id']}",
            )
        try:
            await self._run_route_recompute_job(
                job_id=str(job["job_id"]),
                workspace_id=workspace_id,
                request_id=request_id,
                reason=payload.reason,
                failure_mode=failure_mode,
                allow_fallback=allow_fallback,
            )
        except RouteGenerationServiceError as exc:
            raise_http_error(
                status_code=exc.status_code,
                code=exc.error_code,
                message=exc.message,
                details=exc.details,
            )
        finished_job = STORE.get_job(str(job["job_id"]))
        return AsyncJobAcceptedResponse(
            job_id=job["job_id"],
            job_type=job["job_type"],
            status=finished_job["status"] if finished_job is not None else "succeeded",
            workspace_id=workspace_id,
            status_url=f"/api/v1/research/jobs/{job['job_id']}",
        )

    async def _run_failure_recompute_job(
        self,
        *,
        job_id: str,
        workspace_id: str,
        request_id: str,
        failure_id: str,
        reason: str,
    ) -> None:
        STORE.start_job(job_id)
        try:
            recomputed = await self._recompute_service.recompute_from_failure(
                workspace_id=workspace_id,
                failure_id=failure_id,
                reason=reason,
                request_id=request_id,
                job_id=job_id,
            )
            STORE.finish_job_success(
                job_id=job_id,
                result_ref={
                    "resource_type": "graph_version",
                    "resource_id": str(recomputed["version_id"]),
                },
            )
        except RecomputeServiceError as exc:
            error = {
                "error_code": exc.error_code,
                "message": exc.message,
                "details": exc.details,
            }
            STORE.emit_event(
                event_name="job_failed",
                request_id=request_id,
                job_id=job_id,
                workspace_id=workspace_id,
                component="research_route_controller",
                step="failure_recompute",
                status="failed",
                refs={"failure_id": failure_id},
                error=error,
            )
            STORE.finish_job_failed(job_id=job_id, error=error)
            raise
        except Exception as exc:  # pragma: no cover - defensive fallback
            error = {
                "error_code": "research.recompute_failed",
                "message": "unexpected recompute failure",
                "details": {"failure_id": failure_id, "reason": str(exc)},
            }
            STORE.emit_event(
                event_name="job_failed",
                request_id=request_id,
                job_id=job_id,
                workspace_id=workspace_id,
                component="research_route_controller",
                step="failure_recompute",
                status="failed",
                refs={"failure_id": failure_id},
                error=error,
            )
            STORE.finish_job_failed(job_id=job_id, error=error)
            raise RecomputeServiceError(
                status_code=500,
                error_code="research.recompute_failed",
                message="unexpected recompute failure",
                details={"failure_id": failure_id, "reason": str(exc)},
            ) from exc

    async def _run_route_recompute_job(
        self,
        *,
        job_id: str,
        workspace_id: str,
        request_id: str,
        reason: str,
        failure_mode: str | None,
        allow_fallback: bool,
    ) -> None:
        STORE.start_job(job_id)
        route_generation_service = RouteGenerationService(STORE)
        try:
            generated = await route_generation_service.generate_routes(
                workspace_id=workspace_id,
                request_id=request_id,
                reason=reason,
                max_candidates=8,
                failure_mode=failure_mode,
                allow_fallback=allow_fallback,
            )
            top_route_id = generated.get("top_route_id")
            ensure(
                bool(top_route_id),
                status_code=409,
                code=ResearchErrorCode.INVALID_STATE.value,
                message="route generation did not return top route",
                details={"workspace_id": workspace_id},
            )
            STORE.finish_job_success(
                job_id=job_id,
                result_ref={"resource_type": "route", "resource_id": str(top_route_id)},
            )
        except RouteGenerationServiceError as exc:
            error = {
                "error_code": exc.error_code,
                "message": exc.message,
                "details": exc.details,
            }
            STORE.emit_event(
                event_name="job_failed",
                request_id=request_id,
                job_id=job_id,
                workspace_id=workspace_id,
                component="research_route_controller",
                step="route_recompute",
                status="failed",
                refs={"reason": reason},
                error=error,
            )
            STORE.finish_job_failed(job_id=job_id, error=error)
            raise
        except Exception as exc:  # pragma: no cover - defensive fallback
            error = {
                "error_code": "research.recompute_failed",
                "message": "unexpected route recompute failure",
                "details": {"workspace_id": workspace_id, "reason": str(exc)},
            }
            STORE.emit_event(
                event_name="job_failed",
                request_id=request_id,
                job_id=job_id,
                workspace_id=workspace_id,
                component="research_route_controller",
                step="route_recompute",
                status="failed",
                refs={"reason": reason},
                error=error,
            )
            STORE.finish_job_failed(job_id=job_id, error=error)
            raise RouteGenerationServiceError(
                status_code=500,
                error_code="research.recompute_failed",
                message="unexpected route recompute failure",
                details={"workspace_id": workspace_id, "reason": str(exc)},
            ) from exc
