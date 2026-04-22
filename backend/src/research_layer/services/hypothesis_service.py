from __future__ import annotations

import json
import re
from dataclasses import dataclass

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.services.hypothesis_multi_agent_orchestrator import (
    HypothesisMultiAgentOrchestrator,
)
from research_layer.services.hypothesis_trigger_detector import (
    HypothesisTriggerDetector,
)
from research_layer.services.llm_gateway import ResearchLLMError
from research_layer.services.llm_trace import build_event_trace_parts
from research_layer.services.prompt_renderer import (
    build_messages_from_prompt,
    load_prompt_template,
    render_prompt_with_ontology_paths,
)
from research_layer.services.research_llm_dependencies import (
    build_research_llm_gateway,
    resolve_research_backend_and_model,
)
from research_layer.services.tool_capability_graph_service import (
    ToolCapabilityGraphService,
)


@dataclass(slots=True)
class HypothesisServiceError(Exception):
    status_code: int
    error_code: str
    message: str
    details: dict[str, object]

    def __str__(self) -> str:
        return self.message


class HypothesisService:
    _DECISION_ALLOWED_FROM = {"candidate", "deferred"}
    _DETERMINISTIC_FALLBACK_ERROR_CODES = {
        "research.llm_failed",
        "research.llm_timeout",
        "research.llm_invalid_output",
    }
    _MEMORY_TRIGGER_TYPE_BY_VIEW = {
        "evidence": "weak_support",
        "contradiction": "conflict",
        "failure_pattern": "failure",
        "validation_history": "weak_support",
        "hypothesis_support": "weak_support",
    }

    def __init__(self, store: ResearchApiStateStore) -> None:
        self._store = store
        self._trigger_detector = HypothesisTriggerDetector(store)
        self._llm_gateway = build_research_llm_gateway()
        self._prompt_template = load_prompt_template("hypothesis_generation.txt")
        self._tool_capability_graph = ToolCapabilityGraphService()
        orchestrator = getattr(store, "_hypothesis_multi_orchestrator", None)
        if orchestrator is None:
            orchestrator = HypothesisMultiAgentOrchestrator(store)
            setattr(store, "_hypothesis_multi_orchestrator", orchestrator)
        self._multi_orchestrator = orchestrator

    def _raise(
        self,
        *,
        status_code: int,
        error_code: str,
        message: str,
        details: dict[str, object] | None = None,
    ) -> None:
        raise HypothesisServiceError(
            status_code=status_code,
            error_code=error_code,
            message=message,
            details=details or {},
        )

    def list_triggers(self, *, workspace_id: str) -> list[dict[str, object]]:
        return self._trigger_detector.list_triggers(workspace_id=workspace_id)

    def list_hypotheses(self, *, workspace_id: str) -> list[dict[str, object]]:
        return self._store.list_hypotheses(workspace_id=workspace_id)

    def get_pool(self, *, pool_id: str) -> dict[str, object] | None:
        return self._multi_orchestrator.get_pool(pool_id=pool_id)

    def list_pool_candidates(self, *, pool_id: str) -> list[dict[str, object]]:
        return self._multi_orchestrator.list_pool_candidates(pool_id=pool_id)

    def list_pool_rounds(self, *, pool_id: str) -> list[dict[str, object]]:
        return self._multi_orchestrator.list_pool_rounds(pool_id=pool_id)

    def get_pool_match(self, *, match_id: str) -> dict[str, object] | None:
        return self._multi_orchestrator.get_match(match_id=match_id)

    def get_search_tree_node(self, *, tree_node_id: str) -> dict[str, object] | None:
        return self._multi_orchestrator.get_search_tree_node(tree_node_id=tree_node_id)

    def get_candidate(self, *, candidate_id: str) -> dict[str, object] | None:
        return self._multi_orchestrator.get_candidate(candidate_id=candidate_id)

    async def control_pool(
        self,
        *,
        pool_id: str,
        workspace_id: str,
        request_id: str,
        action: str,
        source_ids: list[str],
    ) -> dict[str, object]:
        del source_ids
        pool = self._multi_orchestrator.get_pool(pool_id=pool_id)
        if pool is None:
            self._raise(
                status_code=404,
                error_code="research.not_found",
                message="hypothesis pool not found",
                details={"pool_id": pool_id},
            )
        if str(pool.get("workspace_id")) != workspace_id:
            self._raise(
                status_code=409,
                error_code="research.conflict",
                message="workspace_id does not match pool ownership",
                details={"pool_id": pool_id},
            )
        try:
            updated = self._multi_orchestrator.control_pool(
                pool_id=pool_id,
                request_id=request_id,
                action=action,
            )
        except ValueError as exc:
            self._raise(
                status_code=409,
                error_code="research.invalid_state",
                message="pool control action failed",
                details={"pool_id": pool_id, "action": action, "reason": str(exc)},
            )
        return updated

    def patch_candidate_reasoning_chain(
        self,
        *,
        candidate_id: str,
        workspace_id: str,
        request_id: str,
        reasoning_chain: dict[str, object],
        reset_review_state: bool = True,
    ) -> dict[str, object]:
        existing = self._multi_orchestrator.get_candidate(candidate_id=candidate_id)
        if existing is None:
            self._raise(
                status_code=404,
                error_code="research.not_found",
                message="hypothesis candidate not found",
                details={"candidate_id": candidate_id},
            )
        if str(existing.get("workspace_id")) != workspace_id:
            self._raise(
                status_code=409,
                error_code="research.conflict",
                message="workspace_id does not match candidate ownership",
                details={"candidate_id": candidate_id},
            )
        candidate = self._multi_orchestrator.patch_candidate_reasoning_chain(
            candidate_id=candidate_id,
            reasoning_chain=reasoning_chain,
            reset_review_state=reset_review_state,
        )
        if candidate is None:
            self._raise(
                status_code=404,
                error_code="research.not_found",
                message="hypothesis candidate not found",
                details={"candidate_id": candidate_id},
            )
        self._store.emit_event(
            event_name="hypothesis_candidate_reasoning_chain_patched",
            request_id=request_id,
            job_id=None,
            workspace_id=workspace_id,
            component="hypothesis_service",
            step="candidate_patch",
            status="completed",
            refs={
                "pool_id": str(candidate.get("pool_id") or ""),
                "candidate_id": candidate_id,
            },
        )
        return candidate

    async def generate_multi_agent_pool(
        self,
        *,
        workspace_id: str,
        trigger_ids: list[str],
        request_id: str,
        generation_job_id: str | None,
        research_goal: str,
        top_k: int,
        max_rounds: int,
        candidate_count: int,
        constraints: dict[str, object],
        preference_profile: dict[str, object],
        failure_mode: str | None,
        allow_fallback: bool,
    ) -> dict[str, object]:
        del failure_mode, allow_fallback
        if not trigger_ids:
            self._raise(
                status_code=400,
                error_code="research.invalid_request",
                message="trigger_ids must not be empty",
            )
        resolved_triggers = self._trigger_detector.resolve_trigger_ids(
            workspace_id=workspace_id, trigger_ids=trigger_ids
        )
        if len(resolved_triggers) != len(trigger_ids):
            found_ids = {str(item["trigger_id"]) for item in resolved_triggers}
            missing_ids = sorted(
                trigger_id for trigger_id in trigger_ids if trigger_id not in found_ids
            )
            self._raise(
                status_code=400,
                error_code="research.invalid_request",
                message="trigger_ids contain unsupported or missing triggers",
                details={"missing_trigger_ids": missing_ids},
            )
        novelty_typing = self._derive_novelty_typing(triggers=resolved_triggers)
        related_object_ids = self._merge_related_object_ids(triggers=resolved_triggers)
        minimum_validation_action = self._build_minimum_validation_action(
            workspace_id=workspace_id,
            triggers=resolved_triggers,
            novelty_typing=novelty_typing,
        )
        weakening_signal = self._build_weakening_signal(triggers=resolved_triggers)
        try:
            pool = await self._multi_orchestrator.create_pool(
                workspace_id=workspace_id,
                request_id=request_id,
                trigger_refs=resolved_triggers,
                research_goal=research_goal,
                top_k=top_k,
                max_rounds=max_rounds,
                candidate_count=candidate_count,
                constraints=constraints,
                preference_profile=preference_profile,
                novelty_typing=novelty_typing,
                related_object_ids=related_object_ids,
                minimum_validation_action=minimum_validation_action,
                weakening_signal=weakening_signal,
            )
        except ValueError as exc:
            self._raise(
                status_code=409,
                error_code="research.invalid_state",
                message="multi agent pool creation failed",
                details={"reason": str(exc)},
            )
        self._store.emit_event(
            event_name="hypothesis_pool_created",
            request_id=request_id,
            job_id=generation_job_id,
            workspace_id=workspace_id,
            component="hypothesis_service",
            step="multi_agent_pool_create",
            status="completed",
            refs={
                "pool_id": pool["pool_id"],
                "trigger_ids": trigger_ids,
                "orchestration_mode": pool["orchestration_mode"],
            },
            metrics={
                "top_k": top_k,
                "max_rounds": max_rounds,
                "candidate_count": candidate_count,
            },
        )
        return pool

    async def generate_literature_frontier_pool(
        self,
        *,
        workspace_id: str,
        source_ids: list[str],
        request_id: str,
        generation_job_id: str | None,
        research_goal: str,
        frontier_size: int,
        max_rounds: int,
        constraints: dict[str, object],
        preference_profile: dict[str, object],
        active_retrieval: dict[str, object],
    ) -> dict[str, object]:
        canonical_source_ids = [
            source_id.strip() for source_id in source_ids if source_id.strip()
        ]
        if not canonical_source_ids:
            self._raise(
                status_code=400,
                error_code="research.invalid_request",
                message="source_ids must not be empty",
            )
        trigger_refs = self._build_literature_trigger_refs(
            workspace_id=workspace_id,
            source_ids=canonical_source_ids,
        )
        if not trigger_refs:
            self._raise(
                status_code=409,
                error_code="research.invalid_state",
                message="literature_frontier requires confirmed source candidates",
                details={"source_ids": canonical_source_ids},
            )
        related_object_ids = [
            {"object_type": "source", "object_id": source_id}
            for source_id in canonical_source_ids
        ]
        minimum_validation_action = self._build_minimum_validation_action(
            workspace_id=workspace_id,
            triggers=trigger_refs,
            novelty_typing="literature_frontier",
        )
        weakening_signal = self._build_weakening_signal(triggers=trigger_refs)
        try:
            pool = await self._multi_orchestrator.create_pool(
                workspace_id=workspace_id,
                request_id=request_id,
                trigger_refs=trigger_refs,
                research_goal=research_goal,
                top_k=frontier_size,
                max_rounds=max_rounds,
                candidate_count=max(6, frontier_size * 2),
                constraints=constraints,
                preference_profile={
                    **preference_profile,
                    "active_retrieval": dict(active_retrieval),
                },
                novelty_typing="literature_frontier",
                related_object_ids=related_object_ids,
                minimum_validation_action=minimum_validation_action,
                weakening_signal=weakening_signal,
                orchestration_mode="literature_frontier",
            )
        except ValueError as exc:
            self._raise(
                status_code=409,
                error_code="research.invalid_state",
                message="literature frontier pool creation failed",
                details={"reason": str(exc)},
            )
        self._store.emit_event(
            event_name="hypothesis_pool_created",
            request_id=request_id,
            job_id=generation_job_id,
            workspace_id=workspace_id,
            component="hypothesis_service",
            step="literature_frontier_pool_create",
            status="completed",
            refs={
                "pool_id": pool["pool_id"],
                "source_ids": canonical_source_ids,
                "orchestration_mode": pool["orchestration_mode"],
            },
            metrics={
                "frontier_size": frontier_size,
                "max_rounds": max_rounds,
                "trigger_ref_count": len(trigger_refs),
            },
        )
        return pool

    async def run_pool_round(
        self,
        *,
        pool_id: str,
        workspace_id: str,
        request_id: str,
        max_matches: int,
    ) -> dict[str, object]:
        pool = self._multi_orchestrator.get_pool(pool_id=pool_id)
        if pool is None:
            self._raise(
                status_code=404,
                error_code="research.not_found",
                message="hypothesis pool not found",
                details={"pool_id": pool_id},
            )
        if str(pool.get("workspace_id")) != workspace_id:
            self._raise(
                status_code=409,
                error_code="research.conflict",
                message="workspace_id does not match pool ownership",
                details={"pool_id": pool_id},
            )
        try:
            result = await self._multi_orchestrator.run_round(
                pool_id=pool_id,
                request_id=request_id,
                max_matches=max_matches,
                start_reason="manual_api_run_round",
            )
        except ValueError as exc:
            self._raise(
                status_code=409,
                error_code="research.invalid_state",
                message="pool round failed",
                details={"pool_id": pool_id, "reason": str(exc)},
            )
        self._store.emit_event(
            event_name="hypothesis_pool_round_completed",
            request_id=request_id,
            job_id=None,
            workspace_id=workspace_id,
            component="hypothesis_service",
            step="multi_agent_pool_round",
            status="completed",
            refs={
                "pool_id": pool_id,
                "round_id": result["round_id"],
                "round_number": result["round_number"],
            },
            metrics={
                "review_count": result["review_count"],
                "match_count": result["match_count"],
                "evolution_count": result["evolution_count"],
            },
        )
        return result

    async def finalize_pool(
        self,
        *,
        pool_id: str,
        workspace_id: str,
        request_id: str,
    ) -> list[dict[str, object]]:
        pool = self._multi_orchestrator.get_pool(pool_id=pool_id)
        if pool is None:
            self._raise(
                status_code=404,
                error_code="research.not_found",
                message="hypothesis pool not found",
                details={"pool_id": pool_id},
            )
        if str(pool.get("workspace_id")) != workspace_id:
            self._raise(
                status_code=409,
                error_code="research.conflict",
                message="workspace_id does not match pool ownership",
                details={"pool_id": pool_id},
            )
        existing = [
            item
            for item in self._store.list_hypotheses(workspace_id=workspace_id)
            if str(item.get("source_pool_id") or "") == pool_id
        ]
        if existing:
            return existing
        try:
            selected_candidates = await self._multi_orchestrator.finalize_pool(
                pool_id=pool_id,
                request_id=request_id,
            )
        except ValueError as exc:
            self._raise(
                status_code=409,
                error_code="research.invalid_state",
                message="pool finalize failed",
                details={"pool_id": pool_id, "reason": str(exc)},
            )
        results: list[dict[str, object]] = []
        for candidate in selected_candidates:
            min_validation = candidate.get("minimum_validation_action", {})
            weakening_signal = candidate.get("weakening_signal", {})
            latest_reflection = candidate.get("last_reflection", {})
            created = self._store.create_hypothesis(
                workspace_id=workspace_id,
                statement=str(candidate.get("statement", "")).strip()
                or str(candidate.get("summary", "")),
                title=str(candidate.get("title", "")).strip() or "multi-agent hypothesis",
                summary=str(candidate.get("summary", "")).strip()
                or str(candidate.get("statement", "")),
                premise=str(candidate.get("testability_hint", "")).strip()
                or str(candidate.get("summary", "")),
                rationale=str(candidate.get("rationale", "")).strip() or "multi-agent finalized",
                testability_hint=str(candidate.get("testability_hint", "")).strip(),
                novelty_hint=str(candidate.get("novelty_hint", "")).strip(),
                suggested_next_steps=list(candidate.get("suggested_next_steps", [])),
                confidence_hint=self._coerce_confidence_hint(candidate.get("confidence_hint")),
                trigger_refs=list(candidate.get("trigger_refs", [])),
                related_object_ids=list(candidate.get("related_object_ids", [])),
                novelty_typing=str(candidate.get("novelty_typing", "incremental")),
                minimum_validation_action=(
                    min_validation if isinstance(min_validation, dict) else {}
                ),
                weakening_signal=(
                    weakening_signal if isinstance(weakening_signal, dict) else {}
                ),
                generation_job_id=None,
                provider_backend="multi_agent_orchestrator",
                provider_model="paper_faithful_v1",
                llm_request_id=request_id,
                llm_response_id=None,
                usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                fallback_used=False,
                degraded=False,
                degraded_reason=None,
                source_pool_id=pool_id,
                source_candidate_id=str(candidate.get("candidate_id", "")),
                source_round_id=None,
                finalizing_match_id=None,
                search_tree_node_id=str(candidate.get("search_tree_node_id", "")) or None,
                reasoning_chain_id=str(
                    candidate.get("reasoning_chain", {}).get("chain_id", "")
                )
                or None,
                weakest_step_ref=(
                    latest_reflection.get("weakest_step_ref", {})
                    if isinstance(latest_reflection, dict)
                    else {}
                ),
            )
            results.append(created)
        self._store.emit_event(
            event_name="hypothesis_pool_finalized",
            request_id=request_id,
            job_id=None,
            workspace_id=workspace_id,
            component="hypothesis_service",
            step="multi_agent_pool_finalize",
            status="completed",
            refs={
                "pool_id": pool_id,
                "hypothesis_ids": [str(item["hypothesis_id"]) for item in results],
            },
            metrics={"finalized_count": len(results)},
        )
        return results

    async def generate_candidate(
        self,
        *,
        workspace_id: str,
        trigger_ids: list[str],
        request_id: str,
        generation_job_id: str | None,
        async_mode: bool = True,
        failure_mode: str | None = None,
        allow_fallback: bool = False,
    ) -> dict[str, object]:
        if not trigger_ids:
            self._raise(
                status_code=400,
                error_code="research.invalid_request",
                message="trigger_ids must not be empty",
            )

        self._store.emit_event(
            event_name="hypothesis_generation_started",
            request_id=request_id,
            job_id=generation_job_id,
            workspace_id=workspace_id,
            component="hypothesis_service",
            step="generate",
            status="started",
            refs={
                "trigger_ids": trigger_ids,
                "trigger_types": self._infer_trigger_types(
                    triggers=self._trigger_detector.list_triggers(
                        workspace_id=workspace_id
                    ),
                    trigger_ids=trigger_ids,
                ),
            },
            metrics={
                "trigger_count": len(trigger_ids),
                "async_mode": async_mode,
                "allow_fallback": allow_fallback,
            },
        )

        try:
            resolved_triggers = self._trigger_detector.resolve_trigger_ids(
                workspace_id=workspace_id, trigger_ids=trigger_ids
            )
            if len(resolved_triggers) != len(trigger_ids):
                found_ids = {str(item["trigger_id"]) for item in resolved_triggers}
                missing_ids = sorted(
                    trigger_id
                    for trigger_id in trigger_ids
                    if trigger_id not in found_ids
                )
                self._raise(
                    status_code=400,
                    error_code="research.invalid_request",
                    message="trigger_ids contain unsupported or missing triggers",
                    details={"missing_trigger_ids": missing_ids},
                )

            try:
                llm_fields, llm_refs, llm_metrics = await self._generate_with_llm(
                    workspace_id=workspace_id,
                    request_id=request_id,
                    resolved_triggers=resolved_triggers,
                    failure_mode=failure_mode,
                )
            except ResearchLLMError as exc:
                if (
                    not allow_fallback
                    or exc.error_code not in self._DETERMINISTIC_FALLBACK_ERROR_CODES
                ):
                    raise
                llm_fields, llm_refs, llm_metrics = (
                    self._build_deterministic_fallback_candidate(
                        workspace_id=workspace_id,
                        request_id=request_id,
                        resolved_triggers=resolved_triggers,
                        error=exc,
                    )
                )
            novelty_typing = self._derive_novelty_typing(triggers=resolved_triggers)
            title = llm_fields["title"]
            statement = llm_fields["statement"]
            summary = statement
            premise = llm_fields.get("testability_hint") or self._build_premise(
                triggers=resolved_triggers
            )
            rationale = llm_fields["rationale"]
            testability_hint = llm_fields.get("testability_hint") or premise
            novelty_hint = llm_fields.get("novelty_hint") or ""
            confidence_hint = self._coerce_confidence_hint(
                llm_fields.get("confidence_hint")
            )
            suggested_next_steps = llm_fields.get("suggested_next_steps") or []
            duplicate = self._find_duplicate_hypothesis(
                workspace_id=workspace_id,
                title=title,
                statement=statement,
                trigger_ids=trigger_ids,
            )
            if duplicate is not None:
                self._raise(
                    status_code=409,
                    error_code="research.duplicate_hypothesis_candidate",
                    message="duplicate hypothesis candidate under the same trigger set",
                    details={
                        "existing_hypothesis_id": duplicate["hypothesis_id"],
                        "duplicate_reason": duplicate["reason"],
                    },
                )
            related_object_ids = self._merge_related_object_ids(
                triggers=resolved_triggers
            )
            minimum_validation_action = self._build_minimum_validation_action(
                workspace_id=workspace_id,
                triggers=resolved_triggers,
                novelty_typing=novelty_typing,
            )
            weakening_signal = self._build_weakening_signal(triggers=resolved_triggers)

            hypothesis = self._store.create_hypothesis(
                workspace_id=workspace_id,
                statement=statement,
                title=title,
                summary=summary,
                premise=premise,
                rationale=rationale,
                testability_hint=testability_hint,
                novelty_hint=novelty_hint,
                confidence_hint=confidence_hint,
                suggested_next_steps=suggested_next_steps,
                trigger_refs=resolved_triggers,
                related_object_ids=related_object_ids,
                novelty_typing=novelty_typing,
                minimum_validation_action=minimum_validation_action,
                weakening_signal=weakening_signal,
                generation_job_id=generation_job_id,
                provider_backend=llm_refs.get("provider_backend"),
                provider_model=llm_refs.get("provider_model"),
                llm_request_id=llm_refs.get("request_id", request_id),
                llm_response_id=llm_refs.get("llm_response_id"),
                usage={
                    "prompt_tokens": llm_metrics.get("prompt_tokens", 0),
                    "completion_tokens": llm_metrics.get("completion_tokens", 0),
                    "total_tokens": llm_metrics.get("total_tokens", 0),
                },
                fallback_used=bool(llm_metrics.get("fallback_used", False)),
                degraded=bool(llm_metrics.get("degraded", False)),
                degraded_reason=(
                    str(llm_metrics.get("degraded_reason"))
                    if llm_metrics.get("degraded_reason") is not None
                    else None
                ),
            )
            self._store.emit_event(
                event_name="hypothesis_generation_completed",
                request_id=request_id,
                job_id=generation_job_id,
                workspace_id=workspace_id,
                component="hypothesis_service",
                step="generate",
                status="completed",
                refs={
                    "hypothesis_id": hypothesis["hypothesis_id"],
                    "trigger_ids": trigger_ids,
                    "trigger_types": [
                        item["trigger_type"] for item in resolved_triggers
                    ],
                    "provider_backend": llm_refs.get("provider_backend"),
                    "provider_model": llm_refs.get("provider_model"),
                    "request_id": llm_refs.get("request_id", request_id),
                    "llm_response_id": llm_refs.get("llm_response_id"),
                    "graph_latest_version_id": llm_metrics.get(
                        "graph_latest_version_id"
                    ),
                },
                metrics={
                    "novelty_typing": novelty_typing,
                    "validation_action_id": minimum_validation_action["validation_id"],
                    "related_object_count": len(related_object_ids),
                    "prompt_tokens": llm_metrics.get("prompt_tokens", 0),
                    "completion_tokens": llm_metrics.get("completion_tokens", 0),
                    "total_tokens": llm_metrics.get("total_tokens", 0),
                    "fallback_used": bool(llm_metrics.get("fallback_used", False)),
                    "degraded": bool(llm_metrics.get("degraded", False)),
                    "degraded_reason": llm_metrics.get("degraded_reason"),
                    "graph_node_count": llm_metrics.get("graph_node_count", 0),
                    "graph_edge_count": llm_metrics.get("graph_edge_count", 0),
                    "recent_failure_count": llm_metrics.get("recent_failure_count", 0),
                    "existing_hypothesis_count": llm_metrics.get(
                        "existing_hypothesis_count", 0
                    ),
                },
            )
            return hypothesis
        except ResearchLLMError as exc:
            self._store.emit_event(
                event_name="hypothesis_generation_completed",
                request_id=request_id,
                job_id=generation_job_id,
                workspace_id=workspace_id,
                component="hypothesis_service",
                step="generate",
                status="failed",
                refs={"trigger_ids": trigger_ids},
                error={
                    "error_code": exc.error_code,
                    "message": exc.message,
                    "details": exc.details,
                },
            )
            raise HypothesisServiceError(
                status_code=exc.status_code,
                error_code=exc.error_code,
                message=exc.message,
                details=exc.details,
            ) from exc
        except HypothesisServiceError as exc:
            self._store.emit_event(
                event_name="hypothesis_generation_completed",
                request_id=request_id,
                job_id=generation_job_id,
                workspace_id=workspace_id,
                component="hypothesis_service",
                step="generate",
                status="failed",
                refs={"trigger_ids": trigger_ids},
                error={
                    "error_code": exc.error_code,
                    "message": exc.message,
                    "details": exc.details,
                },
            )
            raise

    async def _generate_with_llm(
        self,
        *,
        workspace_id: str,
        request_id: str,
        resolved_triggers: list[dict[str, object]],
        failure_mode: str | None,
    ) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
        existing = self._store.list_hypotheses(workspace_id=workspace_id)[:5]
        graph_workspace = self._store.get_graph_workspace(workspace_id)
        graph_versions = self._store.list_graph_versions(workspace_id)
        recent_versions = graph_versions[-3:]
        recent_failures = self._store.list_failures(workspace_id=workspace_id)[-3:]
        graph_nodes = self._store.list_graph_nodes(workspace_id)
        graph_edges = self._store.list_graph_edges(workspace_id)
        tool_plan = self._tool_capability_graph.plan_for_hypothesis(
            trigger_types=[
                str(item.get("trigger_type", "")).strip() for item in resolved_triggers
            ],
            retrieve_method="logical",
        )
        existing_summary = "\n".join(
            f"- {item.get('hypothesis_id')}: {item.get('title')}" for item in existing
        ).strip()
        workspace_context = {
            "graph_workspace": {
                "latest_version_id": (
                    graph_workspace.get("latest_version_id")
                    if graph_workspace
                    else None
                ),
                "status": graph_workspace.get("status") if graph_workspace else None,
                "node_count": (
                    graph_workspace.get("node_count") if graph_workspace else 0
                ),
                "edge_count": (
                    graph_workspace.get("edge_count") if graph_workspace else 0
                ),
            },
            "recent_graph_versions": [
                {
                    "version_id": item.get("version_id"),
                    "trigger_type": item.get("trigger_type"),
                    "change_summary": item.get("change_summary"),
                    "request_id": item.get("request_id"),
                }
                for item in recent_versions
            ],
            "recent_failures": [
                {
                    "failure_id": item.get("failure_id"),
                    "severity": item.get("severity"),
                    "failure_reason": item.get("failure_reason"),
                }
                for item in recent_failures
            ],
            "selected_trigger_ids": [
                str(item.get("trigger_id", "")) for item in resolved_triggers
            ],
            "graph_snapshot": {
                "node_count": len(graph_nodes),
                "edge_count": len(graph_edges),
            },
            "tool_capability_context": {
                "graph": self._tool_capability_graph.graph_definition(),
                "selected_plan": tool_plan,
            },
        }
        prompt_result = render_prompt_with_ontology_paths(
            template=self._prompt_template,
            variables={
                "workspace_id": workspace_id,
                "request_id": request_id,
                "existing_hypotheses_summary": (
                    existing_summary if existing_summary else "(none)"
                ),
                "workspace_context_summary": (
                    json.dumps(workspace_context, ensure_ascii=False, default=str)
                ),
                "trigger_context_json": json.dumps(
                    resolved_triggers, ensure_ascii=False, default=str
                ),
            },
            resolved_triggers=resolved_triggers,
            graph_nodes=graph_nodes,
            graph_edges=graph_edges,
            max_depth=3,
            max_paths=12,
        )
        rendered = prompt_result.rendered_prompt
        ontology_path_context = prompt_result.ontology_path_context
        backend, model = resolve_research_backend_and_model()
        llm_result = await self._llm_gateway.invoke_json(
            request_id=request_id,
            prompt_name="hypothesis_generation",
            messages=build_messages_from_prompt(rendered),
            backend=backend,
            model=model,
            expected_container="dict",
            allow_fallback=False,
            failure_mode=failure_mode,
        )
        parsed = llm_result.parsed_json
        if not isinstance(parsed, dict):
            raise ResearchLLMError(
                status_code=502,
                error_code="research.llm_invalid_output",
                message="hypothesis output must be object JSON",
                details={},
            )
        fields = self._pick_hypothesis_candidate(parsed, resolved_triggers)
        refs, metrics = build_event_trace_parts(llm_result)
        return (
            fields,
            refs,
            {
                "prompt_tokens": int(metrics.get("prompt_tokens") or 0),
                "completion_tokens": int(metrics.get("completion_tokens") or 0),
                "total_tokens": int(metrics.get("total_tokens") or 0),
                "degraded": bool(metrics.get("degraded", False)),
                "degraded_reason": metrics.get("degraded_reason"),
                "graph_latest_version_id": (
                    graph_workspace.get("latest_version_id")
                    if graph_workspace
                    else None
                ),
                "graph_node_count": len(graph_nodes),
                "graph_edge_count": len(graph_edges),
                "recent_failure_count": len(recent_failures),
                "existing_hypothesis_count": len(existing),
                "ontology_path_count": int(
                    ontology_path_context.get("path_count") or 0
                ),
                "ontology_seed_count": len(
                    ontology_path_context.get("seed_node_ids") or []
                ),
                "ontology_depth_clipped": bool(
                    ontology_path_context.get("depth_clipped", False)
                ),
                "ontology_path_count_clipped": bool(
                    ontology_path_context.get("path_count_clipped", False)
                ),
                "tool_capability_chain_length": int(
                    tool_plan.get("chain_length") or 0
                ),
            },
        )

    def _build_deterministic_fallback_candidate(
        self,
        *,
        workspace_id: str,
        request_id: str,
        resolved_triggers: list[dict[str, object]],
        error: ResearchLLMError,
    ) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
        primary = resolved_triggers[0]
        trigger_ids = [str(item["trigger_id"]) for item in resolved_triggers]
        trigger_types = [str(item["trigger_type"]) for item in resolved_triggers]
        trigger_id_text = ", ".join(trigger_ids)
        trigger_type_text = ", ".join(trigger_types)
        primary_target = f"{primary['object_ref_type']}:{primary['object_ref_id']}"
        summaries = [
            str(item.get("summary", "")).strip()
            for item in resolved_triggers[:3]
            if str(item.get("summary", "")).strip()
        ]
        evidence_text = "; ".join(summaries) if summaries else trigger_id_text
        graph_workspace = self._store.get_graph_workspace(workspace_id)
        graph_nodes = self._store.list_graph_nodes(workspace_id)
        graph_edges = self._store.list_graph_edges(workspace_id)
        recent_failures = self._store.list_failures(workspace_id=workspace_id)[-3:]
        existing = self._store.list_hypotheses(workspace_id=workspace_id)[:5]
        backend, model = resolve_research_backend_and_model()
        return (
            {
                "title": f"Fallback candidate from {primary['trigger_type']}: {primary['object_ref_id']}",
                "statement": (
                    f"If the selected trigger set ({trigger_id_text}) is causal for "
                    f"{primary_target}, then a focused validation should change the "
                    "affected research route or evidence state."
                ),
                "rationale": (
                    f"Deterministic fallback used after {error.error_code}; it binds the "
                    f"candidate to trigger types {trigger_type_text} and evidence: {evidence_text}."
                ),
                "testability_hint": (
                    f"Validate the primary trigger {primary['trigger_id']} against "
                    f"{primary_target} before promoting this candidate."
                ),
                "novelty_hint": (
                    f"Fallback synthesis only; novelty depends on the selected trigger "
                    f"combination: {trigger_type_text}."
                ),
                "confidence_hint": 0.35,
                "suggested_next_steps": [
                    f"inspect trigger {trigger_id_text}",
                    f"run validation against {primary_target}",
                ],
            },
            {
                "provider_backend": backend,
                "provider_model": model,
                "request_id": request_id,
                "llm_response_id": "",
            },
            {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "fallback_used": True,
                "degraded": True,
                "degraded_reason": error.error_code,
                "graph_latest_version_id": (
                    graph_workspace.get("latest_version_id")
                    if graph_workspace
                    else None
                ),
                "graph_node_count": len(graph_nodes),
                "graph_edge_count": len(graph_edges),
                "recent_failure_count": len(recent_failures),
                "existing_hypothesis_count": len(existing),
            },
        )

    def _pick_hypothesis_candidate(
        self, payload: dict[str, object], resolved_triggers: list[dict[str, object]]
    ) -> dict[str, object]:
        candidates = payload.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ResearchLLMError(
                status_code=502,
                error_code="research.llm_invalid_output",
                message="hypothesis candidates list is empty",
                details={},
            )
        allowed_ids = {str(item["trigger_id"]) for item in resolved_triggers}
        for item in candidates:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            statement = str(item.get("statement", "")).strip()
            rationale = str(item.get("rationale", "")).strip()
            testability_hint = str(item.get("testability_hint", "")).strip()
            novelty_hint = str(item.get("novelty_hint", "")).strip()
            trigger_refs = item.get("trigger_refs")
            suggested_next_steps_raw = item.get("suggested_next_steps")
            suggested_next_steps = [
                str(step).strip()
                for step in (
                    suggested_next_steps_raw
                    if isinstance(suggested_next_steps_raw, list)
                    else []
                )
                if str(step).strip()
            ]
            confidence_hint_raw = item.get("confidence_hint")
            confidence_hint: float | None = None
            if confidence_hint_raw is not None:
                try:
                    converted = float(confidence_hint_raw)
                except (TypeError, ValueError):
                    converted = -1.0
                if 0.0 <= converted <= 1.0:
                    confidence_hint = converted
            if (
                not title
                or not statement
                or not rationale
                or not isinstance(trigger_refs, list)
                or not trigger_refs
            ):
                continue
            if title.startswith("Hypothesis from "):
                continue
            normalized_refs = {str(ref) for ref in trigger_refs}
            if not normalized_refs.issubset(allowed_ids):
                continue
            return {
                "title": title,
                "statement": statement,
                "rationale": rationale,
                "testability_hint": (
                    testability_hint
                    if testability_hint
                    else f"Validate against trigger set: {', '.join(sorted(normalized_refs))}"
                ),
                "novelty_hint": novelty_hint,
                "confidence_hint": confidence_hint,
                "suggested_next_steps": suggested_next_steps,
            }
        raise ResearchLLMError(
            status_code=502,
            error_code="research.llm_invalid_output",
            message="hypothesis candidate missing required fields",
            details={},
        )

    def promote_hypothesis(
        self,
        *,
        hypothesis_id: str,
        workspace_id: str,
        note: str,
        decision_source_type: str,
        decision_source_ref: str,
        request_id: str,
    ) -> dict[str, object]:
        hypothesis = self._get_hypothesis_checked(
            hypothesis_id=hypothesis_id, workspace_id=workspace_id
        )
        if str(hypothesis["status"]) not in self._DECISION_ALLOWED_FROM:
            self._raise(
                status_code=409,
                error_code="research.invalid_state",
                message="hypothesis cannot be promoted in current status",
                details={
                    "hypothesis_id": hypothesis_id,
                    "status": hypothesis["status"],
                },
            )
        updated = self._store.update_hypothesis_status(
            hypothesis_id=hypothesis_id,
            status="promoted_for_validation",
            decision_note=note,
            decision_source_type=decision_source_type,
            decision_source_ref=decision_source_ref,
            decided_request_id=request_id,
        )
        if updated is None:
            self._raise(
                status_code=404,
                error_code="research.not_found",
                message="hypothesis not found",
                details={"hypothesis_id": hypothesis_id},
            )
        self._store.emit_event(
            event_name="hypothesis_promoted",
            request_id=request_id,
            job_id=None,
            workspace_id=workspace_id,
            component="hypothesis_service",
            step="promote",
            status="completed",
            refs={
                "hypothesis_id": hypothesis_id,
                "decision_source_type": decision_source_type,
                "decision_source_ref": decision_source_ref,
            },
        )
        return updated

    def reject_hypothesis(
        self,
        *,
        hypothesis_id: str,
        workspace_id: str,
        note: str,
        decision_source_type: str,
        decision_source_ref: str,
        request_id: str,
    ) -> dict[str, object]:
        hypothesis = self._get_hypothesis_checked(
            hypothesis_id=hypothesis_id, workspace_id=workspace_id
        )
        if str(hypothesis["status"]) not in self._DECISION_ALLOWED_FROM:
            self._raise(
                status_code=409,
                error_code="research.invalid_state",
                message="hypothesis cannot be rejected in current status",
                details={
                    "hypothesis_id": hypothesis_id,
                    "status": hypothesis["status"],
                },
            )
        updated = self._store.update_hypothesis_status(
            hypothesis_id=hypothesis_id,
            status="rejected",
            decision_note=note,
            decision_source_type=decision_source_type,
            decision_source_ref=decision_source_ref,
            decided_request_id=request_id,
        )
        if updated is None:
            self._raise(
                status_code=404,
                error_code="research.not_found",
                message="hypothesis not found",
                details={"hypothesis_id": hypothesis_id},
            )
        self._store.emit_event(
            event_name="hypothesis_rejected",
            request_id=request_id,
            job_id=None,
            workspace_id=workspace_id,
            component="hypothesis_service",
            step="reject",
            status="completed",
            refs={
                "hypothesis_id": hypothesis_id,
                "decision_source_type": decision_source_type,
                "decision_source_ref": decision_source_ref,
            },
        )
        return updated

    def defer_hypothesis(
        self,
        *,
        hypothesis_id: str,
        workspace_id: str,
        note: str,
        decision_source_type: str,
        decision_source_ref: str,
        request_id: str,
    ) -> dict[str, object]:
        hypothesis = self._get_hypothesis_checked(
            hypothesis_id=hypothesis_id, workspace_id=workspace_id
        )
        current_status = str(hypothesis["status"])
        if current_status == "deferred":
            self._raise(
                status_code=409,
                error_code="research.invalid_state",
                message="hypothesis cannot be deferred in current status",
                details={"hypothesis_id": hypothesis_id, "status": current_status},
            )
        if current_status not in self._DECISION_ALLOWED_FROM:
            self._raise(
                status_code=409,
                error_code="research.invalid_state",
                message="hypothesis cannot be deferred in current status",
                details={"hypothesis_id": hypothesis_id, "status": current_status},
            )
        updated = self._store.update_hypothesis_status(
            hypothesis_id=hypothesis_id,
            status="deferred",
            decision_note=note,
            decision_source_type=decision_source_type,
            decision_source_ref=decision_source_ref,
            decided_request_id=request_id,
        )
        if updated is None:
            self._raise(
                status_code=404,
                error_code="research.not_found",
                message="hypothesis not found",
                details={"hypothesis_id": hypothesis_id},
            )
        self._store.emit_event(
            event_name="hypothesis_deferred",
            request_id=request_id,
            job_id=None,
            workspace_id=workspace_id,
            component="hypothesis_service",
            step="defer",
            status="completed",
            refs={
                "hypothesis_id": hypothesis_id,
                "decision_source_type": decision_source_type,
                "decision_source_ref": decision_source_ref,
            },
        )
        return updated

    def _get_hypothesis_checked(
        self, *, hypothesis_id: str, workspace_id: str
    ) -> dict[str, object]:
        hypothesis = self._store.get_hypothesis(hypothesis_id)
        if hypothesis is None:
            self._raise(
                status_code=404,
                error_code="research.not_found",
                message="hypothesis not found",
                details={"hypothesis_id": hypothesis_id},
            )
        if str(hypothesis["workspace_id"]) != workspace_id:
            self._raise(
                status_code=409,
                error_code="research.conflict",
                message="workspace_id does not match hypothesis ownership",
                details={"hypothesis_id": hypothesis_id},
            )
        return hypothesis

    def _derive_novelty_typing(self, *, triggers: list[dict[str, object]]) -> str:
        trigger_types = {str(item["trigger_type"]) for item in triggers}
        if "failure" in trigger_types and "gap" in trigger_types:
            return "breakthrough"
        if len(trigger_types) >= 3:
            return "novel"
        if "conflict" in trigger_types or "failure" in trigger_types:
            return "incremental"
        return "conservative"

    def _build_title(self, *, triggers: list[dict[str, object]]) -> str:
        primary = triggers[0]
        trigger_type = str(primary["trigger_type"]).replace("_", " ")
        object_ref_id = str(primary["object_ref_id"])
        return f"Hypothesis from {trigger_type}: {object_ref_id}"

    def _build_summary(
        self, *, triggers: list[dict[str, object]], novelty_typing: str
    ) -> str:
        summaries = [str(item.get("summary", "")) for item in triggers[:3]]
        joined = "; ".join(text for text in summaries if text)
        return (
            f"Generated from {len(triggers)} trigger(s) with {novelty_typing} novelty. "
            f"{joined}".strip()
        )

    def _build_premise(self, *, triggers: list[dict[str, object]]) -> str:
        trigger_types = ", ".join(str(item["trigger_type"]) for item in triggers)
        return f"Observed trigger pattern: {trigger_types}."

    def _build_rationale(self, *, triggers: list[dict[str, object]]) -> str:
        first = triggers[0]
        return (
            "The hypothesis is constrained by traceable trigger evidence and must remain "
            f"exploratory until validated. Primary trigger: {first['trigger_id']}."
        )

    def _build_minimum_validation_action(
        self,
        *,
        workspace_id: str,
        triggers: list[dict[str, object]],
        novelty_typing: str,
    ) -> dict[str, object]:
        primary = triggers[0]
        trigger_type = str(primary["trigger_type"])
        object_ref_type = str(primary["object_ref_type"])
        object_ref_id = str(primary["object_ref_id"])
        target_object = f"{object_ref_type}:{object_ref_id}"
        method_map = {
            "gap": "collect one additional supporting source and rerun extraction",
            "conflict": "run contradiction-focused validation against both sides",
            "failure": "reproduce failure and isolate the failing condition",
            "weak_support": "execute focused benchmark to strengthen support evidence",
        }
        success_signal_map = {
            "gap": "new confirmed evidence links to the same conclusion node",
            "conflict": "conflict pressure decreases without creating new critical conflicts",
            "failure": "reproduced failure root cause is mitigated in rerun",
            "weak_support": "support_score improves and missing support factors disappear",
        }
        weakening_signal_map = {
            "gap": "no new support appears after targeted evidence search",
            "conflict": "conflict severity persists or worsens after validation",
            "failure": "failure reproduces under controlled rollback conditions",
            "weak_support": "support_score drops further after the same validation action",
        }
        cost_level = "medium" if novelty_typing in {"novel", "breakthrough"} else "low"
        time_level = "high" if novelty_typing == "breakthrough" else "medium"
        method = method_map[trigger_type]
        success_signal = success_signal_map[trigger_type]
        weakening_signal = weakening_signal_map[trigger_type]
        validation = self._store.create_validation(
            workspace_id=workspace_id,
            target_object=target_object,
            method=method,
            success_signal=success_signal,
            weakening_signal=weakening_signal,
        )
        return {
            "validation_id": validation["validation_id"],
            "target_object": target_object,
            "method": method,
            "success_signal": success_signal,
            "weakening_signal": weakening_signal,
            "cost_level": cost_level,
            "time_level": time_level,
        }

    def _build_literature_trigger_refs(
        self, *, workspace_id: str, source_ids: list[str]
    ) -> list[dict[str, object]]:
        triggers: list[dict[str, object]] = []
        seen: set[str] = set()
        for source_id in source_ids:
            source = self._store.get_source(source_id)
            if source is None or str(source.get("workspace_id")) != workspace_id:
                continue
            confirmed = [
                item
                for item in self._store.list_candidates(
                    workspace_id=workspace_id,
                    source_id=source_id,
                    candidate_type=None,
                    status="confirmed",
                )
            ]
            if not confirmed:
                continue
            sample = confirmed[:5]
            summary = "; ".join(str(item.get("text", "")).strip() for item in sample)
            trigger_id = f"literature_frontier:{source_id}"
            if trigger_id in seen:
                continue
            seen.add(trigger_id)
            triggers.append(
                {
                    "trigger_id": trigger_id,
                    "trigger_type": "weak_support",
                    "workspace_id": workspace_id,
                    "object_ref_type": "source",
                    "object_ref_id": source_id,
                    "summary": summary[:500]
                    or f"Confirmed literature candidates from source {source_id}.",
                    "trace_refs": {
                        "source_id": source_id,
                        "candidate_ids": [
                            str(item.get("candidate_id", "")) for item in sample
                        ],
                    },
                    "related_object_ids": [
                        {"object_type": "source", "object_id": source_id},
                        *[
                            {
                                "object_type": str(item.get("candidate_type", "candidate")),
                                "object_id": str(item.get("candidate_id", "")),
                            }
                            for item in sample
                            if str(item.get("candidate_id", "")).strip()
                        ],
                    ],
                    "metrics": {"confirmed_candidate_count": len(confirmed)},
                }
            )
        return triggers

    def _build_weakening_signal(
        self, *, triggers: list[dict[str, object]]
    ) -> dict[str, object]:
        primary = triggers[0]
        trigger_type = str(primary["trigger_type"])
        object_ref_id = str(primary["object_ref_id"])
        severity_hint = (
            "high" if trigger_type in {"failure", "weak_support"} else "medium"
        )
        return {
            "signal_type": trigger_type,
            "signal_text": (
                f"If repeated checks keep failing around {object_ref_id}, this hypothesis should weaken."
            ),
            "severity_hint": severity_hint,
            "trace_refs": dict(primary.get("trace_refs", {})),
        }

    def _merge_related_object_ids(
        self, *, triggers: list[dict[str, object]]
    ) -> list[dict[str, str]]:
        dedup: set[tuple[str, str]] = set()
        merged: list[dict[str, str]] = []
        for trigger in triggers:
            for item in trigger.get("related_object_ids", []):
                if not isinstance(item, dict):
                    continue
                object_type = str(item.get("object_type", "")).strip()
                object_id = str(item.get("object_id", "")).strip()
                if not object_type or not object_id:
                    continue
                key = (object_type, object_id)
                if key in dedup:
                    continue
                dedup.add(key)
                merged.append({"object_type": object_type, "object_id": object_id})
        return merged

    def _infer_trigger_types(
        self, *, triggers: list[dict[str, object]], trigger_ids: list[str]
    ) -> list[str]:
        trigger_map = {
            str(item["trigger_id"]): str(item["trigger_type"]) for item in triggers
        }
        return [
            trigger_map[trigger_id]
            for trigger_id in trigger_ids
            if trigger_id in trigger_map
        ]

    def _find_duplicate_hypothesis(
        self, *, workspace_id: str, title: str, statement: str, trigger_ids: list[str]
    ) -> dict[str, str] | None:
        normalized_title = self._normalize_text(title)
        normalized_statement = self._normalize_text(statement)
        incoming_trigger_set = {str(trigger_id) for trigger_id in trigger_ids}
        incoming_title_tokens = self._tokenize_for_similarity(normalized_title)
        incoming_statement_tokens = self._tokenize_for_similarity(normalized_statement)

        for existing in self._store.list_hypotheses(workspace_id=workspace_id):
            existing_trigger_set = {
                str(item.get("trigger_id", ""))
                for item in existing.get("trigger_refs", [])
                if isinstance(item, dict) and item.get("trigger_id")
            }
            if existing_trigger_set != incoming_trigger_set:
                continue

            existing_title = self._normalize_text(str(existing.get("title", "")))
            existing_statement = self._normalize_text(
                str(existing.get("statement", ""))
            )
            if existing_title and existing_title == normalized_title:
                return {
                    "hypothesis_id": str(existing["hypothesis_id"]),
                    "reason": "same_normalized_title",
                }
            if existing_statement and existing_statement == normalized_statement:
                return {
                    "hypothesis_id": str(existing["hypothesis_id"]),
                    "reason": "same_normalized_statement",
                }

            title_similarity = self._token_similarity(
                incoming_title_tokens, self._tokenize_for_similarity(existing_title)
            )
            statement_similarity = self._token_similarity(
                incoming_statement_tokens,
                self._tokenize_for_similarity(existing_statement),
            )
            if title_similarity >= 0.9 or statement_similarity >= 0.9:
                return {
                    "hypothesis_id": str(existing["hypothesis_id"]),
                    "reason": "near_duplicate_statement_or_title",
                }
        return None

    def _normalize_text(self, raw: str) -> str:
        return re.sub(r"\s+", " ", raw.strip().lower())

    def _tokenize_for_similarity(self, normalized_text: str) -> set[str]:
        return {
            token
            for token in re.split(r"[^a-z0-9_]+", normalized_text)
            if token and len(token) > 1
        }

    def _token_similarity(self, left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        intersection = left.intersection(right)
        union = left.union(right)
        if not union:
            return 0.0
        return len(intersection) / len(union)

    def _coerce_confidence_hint(self, value: object) -> float | None:
        if value is None:
            return None
        try:
            converted = float(value)
        except (TypeError, ValueError):
            return None
        if 0.0 <= converted <= 1.0:
            return converted
        return None

    def create_candidate_from_memory(
        self,
        *,
        workspace_id: str,
        memory_view_type: str,
        memory_result_id: str,
        memory_title: str,
        memory_snippet: str,
        memory_trace_refs: dict[str, object],
        memory_formal_refs: list[dict[str, str]],
        request_id: str,
        note: str | None = None,
    ) -> dict[str, object]:
        trigger_type = self._MEMORY_TRIGGER_TYPE_BY_VIEW.get(memory_view_type)
        if trigger_type is None:
            self._raise(
                status_code=400,
                error_code="research.invalid_request",
                message="unsupported memory_view_type for hypothesis generation",
                details={"memory_view_type": memory_view_type},
            )
        formal_refs = []
        for item in memory_formal_refs:
            if not isinstance(item, dict):
                continue
            object_type = str(item.get("object_type", "")).strip()
            object_id = str(item.get("object_id", "")).strip()
            if not object_type or not object_id:
                continue
            formal_refs.append({"object_type": object_type, "object_id": object_id})
        primary_formal_ref = (
            formal_refs[0]
            if formal_refs
            else {"object_type": "memory_result", "object_id": memory_result_id}
        )
        target_object = (
            f"{primary_formal_ref['object_type']}:{primary_formal_ref['object_id']}"
        )
        validation = self._store.create_validation(
            workspace_id=workspace_id,
            target_object=target_object,
            method=f"memory_vault_hypothesis:{memory_view_type}",
            success_signal="new evidence confirms memory-linked hypothesis branch",
            weakening_signal="memory-linked hypothesis fails targeted validation",
        )
        minimum_validation_action = {
            "validation_id": validation["validation_id"],
            "target_object": target_object,
            "method": validation["method"],
            "success_signal": validation["success_signal"],
            "weakening_signal": validation["weakening_signal"],
            "cost_level": "low",
            "time_level": "medium",
        }
        trigger_ref = {
            "trigger_id": f"memory_{memory_view_type}_{memory_result_id}",
            "trigger_type": trigger_type,
            "workspace_id": workspace_id,
            "object_ref_type": primary_formal_ref["object_type"],
            "object_ref_id": primary_formal_ref["object_id"],
            "summary": f"memory-backed trigger from {memory_title}",
            "trace_refs": {
                **memory_trace_refs,
                "memory_result_id": memory_result_id,
                "memory_view_type": memory_view_type,
            },
            "related_object_ids": formal_refs,
            "metrics": {},
        }
        weakening_signal = {
            "signal_type": trigger_type,
            "signal_text": (
                f"If validations keep failing for memory result {memory_result_id}, this hypothesis should weaken."
            ),
            "severity_hint": "medium",
            "trace_refs": {
                "memory_result_id": memory_result_id,
                "memory_view_type": memory_view_type,
            },
        }
        note_suffix = f" note: {note.strip()}" if note and note.strip() else ""
        hypothesis = self._store.create_hypothesis(
            workspace_id=workspace_id,
            title=f"Memory Candidate: {memory_title}",
            summary=f"{memory_snippet}{note_suffix}".strip(),
            premise=(
                f"Derived from memory view {memory_view_type} "
                f"and memory result {memory_result_id}."
            ),
            rationale=(
                "Memory Vault controlled action proposed this candidate; "
                "it remains in hypothesis candidate state until explicit promote/reject/defer."
            ),
            trigger_refs=[trigger_ref],
            related_object_ids=formal_refs,
            novelty_typing="incremental",
            minimum_validation_action=minimum_validation_action,
            weakening_signal=weakening_signal,
            generation_job_id=None,
        )
        self._store.emit_event(
            event_name="hypothesis_memory_candidate_created",
            request_id=request_id,
            job_id=None,
            workspace_id=workspace_id,
            component="hypothesis_service",
            step="memory_to_hypothesis_candidate",
            status="completed",
            refs={
                "hypothesis_id": hypothesis["hypothesis_id"],
                "memory_result_id": memory_result_id,
                "memory_view_type": memory_view_type,
            },
        )
        return hypothesis
