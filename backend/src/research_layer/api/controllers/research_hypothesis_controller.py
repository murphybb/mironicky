from __future__ import annotations

from fastapi import Query, Request

from core.di.decorators import controller
from core.interface.controller.base_controller import BaseController, get, patch, post
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
from research_layer.api.schemas.hypothesis import (
    HypothesisAgentTranscriptListResponse,
    HypothesisAgentTranscriptResponse,
    HypothesisCandidatePatchRequest,
    HypothesisCandidateListResponse,
    HypothesisCandidateResponse,
    HypothesisDecisionRequest,
    HypothesisGenerateRequest,
    HypothesisListResponse,
    HypothesisMatchResponse,
    HypothesisPoolControlRequest,
    HypothesisPoolFinalizeRequest,
    HypothesisPoolResponse,
    HypothesisPoolRoundRequest,
    HypothesisPoolTrajectoryResponse,
    HypothesisResponse,
    HypothesisRoundListResponse,
    HypothesisSearchTreeNodeResponse,
    HypothesisTriggerListResponse,
    HypothesisTriggerRecord,
)
from research_layer.services.hypothesis_service import (
    HypothesisService,
    HypothesisServiceError,
)


@controller(name="research_hypothesis_controller")
class ResearchHypothesisController(BaseController):
    def __init__(self) -> None:
        super().__init__(
            prefix="/api/v1/research", tags=["Research Hypothesis"], default_auth="none"
        )
        self._hypothesis_service = HypothesisService(STORE)

    @get(
        "/hypotheses/triggers/list",
        response_model=HypothesisTriggerListResponse,
        responses={400: {"model": ErrorResponse}},
    )
    async def list_hypothesis_triggers(
        self, workspace_id: str | None = Query(default=None)
    ) -> HypothesisTriggerListResponse:
        workspace = validate_workspace_id(workspace_id)
        items = [
            HypothesisTriggerRecord.model_validate(item)
            for item in self._hypothesis_service.list_triggers(workspace_id=workspace)
        ]
        return HypothesisTriggerListResponse(items=items, total=len(items))

    @get(
        "/hypotheses",
        response_model=HypothesisListResponse,
        responses={400: {"model": ErrorResponse}},
    )
    async def list_hypotheses(
        self, workspace_id: str | None = Query(default=None)
    ) -> HypothesisListResponse:
        workspace = validate_workspace_id(workspace_id)
        items = [
            HypothesisResponse.model_validate(item)
            for item in self._hypothesis_service.list_hypotheses(workspace_id=workspace)
        ]
        return HypothesisListResponse(items=items, total=len(items))

    @post(
        "/hypotheses/generate",
        response_model=AsyncJobAcceptedResponse,
        status_code=202,
        responses={400: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    )
    async def generate_hypothesis(self, request: Request) -> AsyncJobAcceptedResponse:
        payload = await parse_request_model(request, HypothesisGenerateRequest)
        request_id = get_request_id(request.headers.get("x-request-id"))
        ensure(
            payload.async_mode,
            status_code=400,
            code=ResearchErrorCode.INVALID_REQUEST.value,
            message="async_mode must be true for hypothesis generation endpoint",
            details={"async_mode": payload.async_mode},
        )
        failure_mode = request.headers.get("x-research-llm-failure-mode")
        allow_fallback = request.headers.get("x-research-llm-allow-fallback") in {
            "1",
            "true",
            "TRUE",
        }

        job = STORE.create_job(
            job_type="hypothesis_generate",
            workspace_id=payload.workspace_id,
            request_id=request_id,
        )
        if payload.async_mode:
            schedule_background_job(
                self._run_hypothesis_generation_job(
                    job_id=str(job["job_id"]),
                    workspace_id=payload.workspace_id,
                    request_id=request_id,
                    mode=payload.mode,
                    trigger_ids=list(payload.trigger_ids),
                    source_ids=list(payload.source_ids),
                    research_goal=str(payload.research_goal or ""),
                    top_k=int(payload.top_k),
                    frontier_size=int(payload.frontier_size),
                    max_rounds=int(payload.max_rounds),
                    candidate_count=int(payload.candidate_count),
                    constraints=dict(payload.constraints),
                    preference_profile=dict(payload.preference_profile),
                    active_retrieval=payload.active_retrieval.model_dump(),
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
                status=(
                    latest_job["status"] if latest_job is not None else job["status"]
                ),
                workspace_id=payload.workspace_id,
                status_url=f"/api/v1/research/jobs/{job['job_id']}",
            )
        try:
            await self._run_hypothesis_generation_job(
                job_id=str(job["job_id"]),
                workspace_id=payload.workspace_id,
                request_id=request_id,
                mode=payload.mode,
                trigger_ids=list(payload.trigger_ids),
                source_ids=list(payload.source_ids),
                research_goal=str(payload.research_goal or ""),
                top_k=int(payload.top_k),
                frontier_size=int(payload.frontier_size),
                max_rounds=int(payload.max_rounds),
                candidate_count=int(payload.candidate_count),
                constraints=dict(payload.constraints),
                preference_profile=dict(payload.preference_profile),
                active_retrieval=payload.active_retrieval.model_dump(),
                failure_mode=failure_mode,
                allow_fallback=allow_fallback,
            )
            finished_job = STORE.get_job(str(job["job_id"]))
            return AsyncJobAcceptedResponse(
                job_id=job["job_id"],
                job_type=job["job_type"],
                status=(
                    finished_job["status"] if finished_job is not None else "succeeded"
                ),
                workspace_id=payload.workspace_id,
                status_url=f"/api/v1/research/jobs/{job['job_id']}",
            )
        except HypothesisServiceError as exc:
            raise_http_error(
                status_code=exc.status_code,
                code=exc.error_code,
                message=exc.message,
                details={**exc.details, "job_id": job["job_id"]},
            )

    async def _run_hypothesis_generation_job(
        self,
        *,
        job_id: str,
        workspace_id: str,
        request_id: str,
        mode: str,
        trigger_ids: list[str],
        source_ids: list[str],
        research_goal: str,
        top_k: int,
        frontier_size: int,
        max_rounds: int,
        candidate_count: int,
        constraints: dict[str, object],
        preference_profile: dict[str, object],
        active_retrieval: dict[str, object],
        failure_mode: str | None,
        allow_fallback: bool,
    ) -> None:
        STORE.start_job(job_id)
        hypothesis_service = HypothesisService(STORE)
        try:
            if mode == "literature_frontier":
                pool = await hypothesis_service.generate_literature_frontier_pool(
                    workspace_id=workspace_id,
                    source_ids=source_ids,
                    request_id=request_id,
                    generation_job_id=job_id,
                    research_goal=research_goal,
                    frontier_size=frontier_size,
                    max_rounds=max_rounds,
                    constraints=constraints,
                    preference_profile=preference_profile,
                    active_retrieval=active_retrieval,
                )
                result_ref = {
                    "resource_type": "hypothesis_pool",
                    "resource_id": str(pool["pool_id"]),
                }
            elif mode == "multi_agent_pool":
                pool = await hypothesis_service.generate_multi_agent_pool(
                    workspace_id=workspace_id,
                    trigger_ids=trigger_ids,
                    request_id=request_id,
                    generation_job_id=job_id,
                    research_goal=research_goal,
                    top_k=top_k,
                    max_rounds=max_rounds,
                    candidate_count=candidate_count,
                    constraints=constraints,
                    preference_profile=preference_profile,
                    failure_mode=failure_mode,
                    allow_fallback=allow_fallback,
                    active_retrieval=active_retrieval,
                )
                result_ref = {
                    "resource_type": "hypothesis_pool",
                    "resource_id": str(pool["pool_id"]),
                }
            else:
                hypothesis = await hypothesis_service.generate_candidate(
                    workspace_id=workspace_id,
                    trigger_ids=trigger_ids,
                    request_id=request_id,
                    generation_job_id=job_id,
                    async_mode=True,
                    failure_mode=failure_mode,
                    allow_fallback=allow_fallback,
                )
                result_ref = {
                    "resource_type": "hypothesis",
                    "resource_id": str(hypothesis["hypothesis_id"]),
                }
            STORE.finish_job_success(job_id=job_id, result_ref=result_ref)
        except HypothesisServiceError as exc:
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
                component="research_hypothesis_controller",
                step="hypothesis_generate",
                status="failed",
                refs={"trigger_ids": trigger_ids, "mode": mode},
                error=error,
            )
            STORE.finish_job_failed(job_id=job_id, error=error)
            raise
        except Exception as exc:  # pragma: no cover - defensive fallback
            error = {
                "error_code": "research.llm_failed",
                "message": "unexpected hypothesis generation failure",
                "details": {"trigger_ids": trigger_ids, "reason": str(exc)},
            }
            STORE.emit_event(
                event_name="job_failed",
                request_id=request_id,
                job_id=job_id,
                workspace_id=workspace_id,
                component="research_hypothesis_controller",
                step="hypothesis_generate",
                status="failed",
                refs={"trigger_ids": trigger_ids, "mode": mode},
                error=error,
            )
            STORE.finish_job_failed(job_id=job_id, error=error)
            raise HypothesisServiceError(
                status_code=500,
                error_code="research.llm_failed",
                message="unexpected hypothesis generation failure",
                details={"trigger_ids": trigger_ids, "mode": mode, "reason": str(exc)},
            ) from exc

    @get(
        "/hypotheses/pools/{pool_id}",
        response_model=HypothesisPoolResponse,
        responses={404: {"model": ErrorResponse}},
    )
    async def get_hypothesis_pool(self, pool_id: str) -> HypothesisPoolResponse:
        pool = self._hypothesis_service.get_pool(pool_id=pool_id)
        ensure(
            pool is not None,
            status_code=404,
            code=ResearchErrorCode.NOT_FOUND.value,
            message="hypothesis pool not found",
            details={"pool_id": pool_id},
        )
        return HypothesisPoolResponse.model_validate(pool)

    @get(
        "/hypotheses/pools/{pool_id}/candidates",
        response_model=HypothesisCandidateListResponse,
        responses={404: {"model": ErrorResponse}},
    )
    async def list_pool_candidates(
        self, pool_id: str
    ) -> HypothesisCandidateListResponse:
        pool = self._hypothesis_service.get_pool(pool_id=pool_id)
        ensure(
            pool is not None,
            status_code=404,
            code=ResearchErrorCode.NOT_FOUND.value,
            message="hypothesis pool not found",
            details={"pool_id": pool_id},
        )
        items = [
            item
            for item in self._hypothesis_service.list_pool_candidates(pool_id=pool_id)
        ]
        return HypothesisCandidateListResponse(items=items, total=len(items))

    @patch(
        "/hypotheses/candidates/{candidate_id}",
        response_model=HypothesisCandidateResponse,
        responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    )
    async def patch_candidate(
        self, candidate_id: str, request: Request
    ) -> HypothesisCandidateResponse:
        payload = await parse_request_model(request, HypothesisCandidatePatchRequest)
        request_id = get_request_id(request.headers.get("x-request-id"))
        try:
            updated = self._hypothesis_service.patch_candidate_reasoning_chain(
                candidate_id=candidate_id,
                workspace_id=payload.workspace_id,
                request_id=request_id,
                reasoning_chain=payload.reasoning_chain,
                reset_review_state=bool(payload.reset_review_state),
            )
        except HypothesisServiceError as exc:
            raise_http_error(
                status_code=exc.status_code,
                code=exc.error_code,
                message=exc.message,
                details=exc.details,
            )
        return HypothesisCandidateResponse.model_validate(updated)

    @get(
        "/hypotheses/pools/{pool_id}/rounds",
        response_model=HypothesisRoundListResponse,
        responses={404: {"model": ErrorResponse}},
    )
    async def list_pool_rounds(self, pool_id: str) -> HypothesisRoundListResponse:
        pool = self._hypothesis_service.get_pool(pool_id=pool_id)
        ensure(
            pool is not None,
            status_code=404,
            code=ResearchErrorCode.NOT_FOUND.value,
            message="hypothesis pool not found",
            details={"pool_id": pool_id},
        )
        items = [
            item for item in self._hypothesis_service.list_pool_rounds(pool_id=pool_id)
        ]
        return HypothesisRoundListResponse(items=items, total=len(items))

    @post(
        "/hypotheses/pools/{pool_id}/control",
        response_model=HypothesisPoolResponse,
        responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    )
    async def control_pool(
        self, pool_id: str, request: Request
    ) -> HypothesisPoolResponse:
        payload = await parse_request_model(request, HypothesisPoolControlRequest)
        request_id = get_request_id(request.headers.get("x-request-id"))
        try:
            updated = await self._hypothesis_service.control_pool(
                pool_id=pool_id,
                workspace_id=payload.workspace_id,
                request_id=request_id,
                action=payload.action,
                source_ids=payload.source_ids,
                candidate_id=payload.candidate_id,
                node=payload.node.model_dump() if payload.node is not None else None,
                candidate_patch=(
                    payload.candidate_patch.model_dump(exclude_none=True)
                    if payload.candidate_patch is not None
                    else None
                ),
                user_hypothesis=(
                    payload.user_hypothesis.model_dump()
                    if payload.user_hypothesis is not None
                    else None
                ),
                control_reason=payload.control_reason,
            )
        except HypothesisServiceError as exc:
            raise_http_error(
                status_code=exc.status_code,
                code=exc.error_code,
                message=exc.message,
                details=exc.details,
            )
        return HypothesisPoolResponse.model_validate(updated)

    @post(
        "/hypotheses/pools/{pool_id}/run-round",
        response_model=AsyncJobAcceptedResponse,
        status_code=202,
        responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    )
    async def run_pool_round(
        self, pool_id: str, request: Request
    ) -> AsyncJobAcceptedResponse:
        payload = await parse_request_model(request, HypothesisPoolRoundRequest)
        request_id = get_request_id(request.headers.get("x-request-id"))
        ensure(
            payload.async_mode,
            status_code=400,
            code=ResearchErrorCode.INVALID_REQUEST.value,
            message="async_mode must be true for pool run-round endpoint",
            details={"async_mode": payload.async_mode},
        )
        pool = self._hypothesis_service.get_pool(pool_id=pool_id)
        ensure(
            pool is not None,
            status_code=404,
            code=ResearchErrorCode.NOT_FOUND.value,
            message="hypothesis pool not found",
            details={"pool_id": pool_id},
        )
        ensure(
            str(pool["workspace_id"]) == payload.workspace_id,
            status_code=400,
            code=ResearchErrorCode.INVALID_REQUEST.value,
            message="workspace_id does not match pool ownership",
            details={"pool_id": pool_id},
        )
        job = STORE.create_job(
            job_type="hypothesis_pool_run_round",
            workspace_id=payload.workspace_id,
            request_id=request_id,
        )
        schedule_background_job(
            self._run_pool_round_job(
                job_id=str(job["job_id"]),
                request_id=request_id,
                pool_id=pool_id,
                workspace_id=payload.workspace_id,
                max_matches=int(payload.max_matches),
            ),
            job_id=str(job["job_id"]),
            job_type=str(job["job_type"]),
        )
        latest_job = STORE.get_job(str(job["job_id"]))
        return AsyncJobAcceptedResponse(
            job_id=job["job_id"],
            job_type=job["job_type"],
            status=latest_job["status"] if latest_job is not None else job["status"],
            workspace_id=payload.workspace_id,
            status_url=f"/api/v1/research/jobs/{job['job_id']}",
        )

    async def _run_pool_round_job(
        self,
        *,
        job_id: str,
        request_id: str,
        pool_id: str,
        workspace_id: str,
        max_matches: int,
    ) -> None:
        STORE.start_job(job_id)
        try:
            round_record = await self._hypothesis_service.run_pool_round(
                pool_id=pool_id,
                workspace_id=workspace_id,
                request_id=request_id,
                max_matches=max_matches,
            )
            STORE.finish_job_success(
                job_id=job_id,
                result_ref={
                    "resource_type": "hypothesis_round",
                    "resource_id": str(round_record["round_id"]),
                },
            )
        except HypothesisServiceError as exc:
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
                component="research_hypothesis_controller",
                step="hypothesis_pool_run_round",
                status="failed",
                refs={"pool_id": pool_id},
                error=error,
            )
            STORE.finish_job_failed(job_id=job_id, error=error)
        except Exception as exc:  # pragma: no cover - defensive fallback
            error = {
                "error_code": "research.internal_error",
                "message": "unexpected pool round failure",
                "details": {"pool_id": pool_id, "reason": str(exc)},
            }
            STORE.emit_event(
                event_name="job_failed",
                request_id=request_id,
                job_id=job_id,
                workspace_id=workspace_id,
                component="research_hypothesis_controller",
                step="hypothesis_pool_run_round",
                status="failed",
                refs={"pool_id": pool_id},
                error=error,
            )
            STORE.finish_job_failed(job_id=job_id, error=error)

    @post(
        "/hypotheses/pools/{pool_id}/finalize",
        response_model=AsyncJobAcceptedResponse,
        status_code=202,
        responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    )
    async def finalize_pool(
        self, pool_id: str, request: Request
    ) -> AsyncJobAcceptedResponse:
        payload = await parse_request_model(request, HypothesisPoolFinalizeRequest)
        request_id = get_request_id(request.headers.get("x-request-id"))
        ensure(
            payload.async_mode,
            status_code=400,
            code=ResearchErrorCode.INVALID_REQUEST.value,
            message="async_mode must be true for pool finalize endpoint",
            details={"async_mode": payload.async_mode},
        )
        pool = self._hypothesis_service.get_pool(pool_id=pool_id)
        ensure(
            pool is not None,
            status_code=404,
            code=ResearchErrorCode.NOT_FOUND.value,
            message="hypothesis pool not found",
            details={"pool_id": pool_id},
        )
        ensure(
            str(pool["workspace_id"]) == payload.workspace_id,
            status_code=400,
            code=ResearchErrorCode.INVALID_REQUEST.value,
            message="workspace_id does not match pool ownership",
            details={"pool_id": pool_id},
        )
        job = STORE.create_job(
            job_type="hypothesis_pool_finalize",
            workspace_id=payload.workspace_id,
            request_id=request_id,
        )
        schedule_background_job(
            self._run_pool_finalize_job(
                job_id=str(job["job_id"]),
                request_id=request_id,
                pool_id=pool_id,
                workspace_id=payload.workspace_id,
            ),
            job_id=str(job["job_id"]),
            job_type=str(job["job_type"]),
        )
        latest_job = STORE.get_job(str(job["job_id"]))
        return AsyncJobAcceptedResponse(
            job_id=job["job_id"],
            job_type=job["job_type"],
            status=latest_job["status"] if latest_job is not None else job["status"],
            workspace_id=payload.workspace_id,
            status_url=f"/api/v1/research/jobs/{job['job_id']}",
        )

    async def _run_pool_finalize_job(
        self, *, job_id: str, request_id: str, pool_id: str, workspace_id: str
    ) -> None:
        STORE.start_job(job_id)
        try:
            finalized = await self._hypothesis_service.finalize_pool(
                pool_id=pool_id, workspace_id=workspace_id, request_id=request_id
            )
            resource_id = ""
            if finalized:
                resource_id = str(finalized[0].get("hypothesis_id", ""))
            STORE.finish_job_success(
                job_id=job_id,
                result_ref={"resource_type": "hypothesis", "resource_id": resource_id},
            )
        except HypothesisServiceError as exc:
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
                component="research_hypothesis_controller",
                step="hypothesis_pool_finalize",
                status="failed",
                refs={"pool_id": pool_id},
                error=error,
            )
            STORE.finish_job_failed(job_id=job_id, error=error)
        except Exception as exc:  # pragma: no cover - defensive fallback
            error = {
                "error_code": "research.internal_error",
                "message": "unexpected pool finalize failure",
                "details": {"pool_id": pool_id, "reason": str(exc)},
            }
            STORE.emit_event(
                event_name="job_failed",
                request_id=request_id,
                job_id=job_id,
                workspace_id=workspace_id,
                component="research_hypothesis_controller",
                step="hypothesis_pool_finalize",
                status="failed",
                refs={"pool_id": pool_id},
                error=error,
            )
            STORE.finish_job_failed(job_id=job_id, error=error)

    @get(
        "/hypotheses/matches/{match_id}",
        response_model=HypothesisMatchResponse,
        responses={404: {"model": ErrorResponse}},
    )
    async def get_pool_match(self, match_id: str) -> HypothesisMatchResponse:
        match = self._hypothesis_service.get_pool_match(match_id=match_id)
        ensure(
            match is not None,
            status_code=404,
            code=ResearchErrorCode.NOT_FOUND.value,
            message="hypothesis match not found",
            details={"match_id": match_id},
        )
        return HypothesisMatchResponse.model_validate(match)

    @get(
        "/hypotheses/pools/{pool_id}/transcripts",
        response_model=HypothesisAgentTranscriptListResponse,
        responses={404: {"model": ErrorResponse}},
    )
    async def list_pool_agent_transcripts(
        self, pool_id: str
    ) -> HypothesisAgentTranscriptListResponse:
        pool = self._hypothesis_service.get_pool(pool_id=pool_id)
        ensure(
            pool is not None,
            status_code=404,
            code=ResearchErrorCode.NOT_FOUND.value,
            message="hypothesis pool not found",
            details={"pool_id": pool_id},
        )
        items = [
            HypothesisAgentTranscriptResponse.model_validate(item)
            for item in STORE.list_hypothesis_agent_transcripts(pool_id=pool_id)
        ]
        return HypothesisAgentTranscriptListResponse(items=items, total=len(items))

    @get(
        "/hypotheses/pools/{pool_id}/trajectory",
        response_model=HypothesisPoolTrajectoryResponse,
        responses={404: {"model": ErrorResponse}},
    )
    async def get_pool_trajectory(
        self, pool_id: str
    ) -> HypothesisPoolTrajectoryResponse:
        trajectory = self._hypothesis_service.get_pool_trajectory(pool_id=pool_id)
        ensure(
            trajectory is not None,
            status_code=404,
            code=ResearchErrorCode.NOT_FOUND.value,
            message="hypothesis pool not found",
            details={"pool_id": pool_id},
        )
        return HypothesisPoolTrajectoryResponse.model_validate(trajectory)

    @get(
        "/hypotheses/search-tree/{node_id}",
        response_model=HypothesisSearchTreeNodeResponse,
        responses={404: {"model": ErrorResponse}},
    )
    async def get_search_tree_node(
        self, node_id: str
    ) -> HypothesisSearchTreeNodeResponse:
        node = self._hypothesis_service.get_search_tree_node(tree_node_id=node_id)
        ensure(
            node is not None,
            status_code=404,
            code=ResearchErrorCode.NOT_FOUND.value,
            message="search tree node not found",
            details={"node_id": node_id},
        )
        return HypothesisSearchTreeNodeResponse.model_validate(node)

    @get(
        "/hypotheses/{hypothesis_id}",
        response_model=HypothesisResponse,
        responses={404: {"model": ErrorResponse}},
    )
    async def get_hypothesis(self, hypothesis_id: str) -> HypothesisResponse:
        hypothesis = STORE.get_hypothesis(hypothesis_id)
        ensure(
            hypothesis is not None,
            status_code=404,
            code=ResearchErrorCode.NOT_FOUND.value,
            message="hypothesis not found",
            details={"hypothesis_id": hypothesis_id},
        )
        return HypothesisResponse.model_validate(hypothesis)

    @post(
        "/hypotheses/{hypothesis_id}/promote",
        response_model=HypothesisResponse,
        responses={
            400: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
        },
    )
    async def promote_hypothesis(
        self, hypothesis_id: str, request: Request
    ) -> HypothesisResponse:
        payload = await parse_request_model(request, HypothesisDecisionRequest)
        request_id = get_request_id(request.headers.get("x-request-id"))
        try:
            updated = self._hypothesis_service.promote_hypothesis(
                hypothesis_id=hypothesis_id,
                workspace_id=payload.workspace_id,
                note=payload.note,
                decision_source_type=payload.decision_source_type,
                decision_source_ref=payload.decision_source_ref,
                request_id=request_id,
            )
        except HypothesisServiceError as exc:
            raise_http_error(
                status_code=exc.status_code,
                code=exc.error_code,
                message=exc.message,
                details=exc.details,
            )
        return HypothesisResponse.model_validate(updated)

    @post(
        "/hypotheses/{hypothesis_id}/reject",
        response_model=HypothesisResponse,
        responses={
            400: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
        },
    )
    async def reject_hypothesis(
        self, hypothesis_id: str, request: Request
    ) -> HypothesisResponse:
        payload = await parse_request_model(request, HypothesisDecisionRequest)
        request_id = get_request_id(request.headers.get("x-request-id"))
        try:
            updated = self._hypothesis_service.reject_hypothesis(
                hypothesis_id=hypothesis_id,
                workspace_id=payload.workspace_id,
                note=payload.note,
                decision_source_type=payload.decision_source_type,
                decision_source_ref=payload.decision_source_ref,
                request_id=request_id,
            )
        except HypothesisServiceError as exc:
            raise_http_error(
                status_code=exc.status_code,
                code=exc.error_code,
                message=exc.message,
                details=exc.details,
            )
        return HypothesisResponse.model_validate(updated)

    @post(
        "/hypotheses/{hypothesis_id}/defer",
        response_model=HypothesisResponse,
        responses={
            400: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
        },
    )
    async def defer_hypothesis(
        self, hypothesis_id: str, request: Request
    ) -> HypothesisResponse:
        payload = await parse_request_model(request, HypothesisDecisionRequest)
        request_id = get_request_id(request.headers.get("x-request-id"))
        try:
            updated = self._hypothesis_service.defer_hypothesis(
                hypothesis_id=hypothesis_id,
                workspace_id=payload.workspace_id,
                note=payload.note,
                decision_source_type=payload.decision_source_type,
                decision_source_ref=payload.decision_source_ref,
                request_id=request_id,
            )
        except HypothesisServiceError as exc:
            raise_http_error(
                status_code=exc.status_code,
                code=exc.error_code,
                message=exc.message,
                details=exc.details,
            )
        return HypothesisResponse.model_validate(updated)
