from __future__ import annotations

from collections.abc import Iterable

from fastapi import Query, Request
from fastapi.responses import HTMLResponse

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
from research_layer.api.schemas.observability import (
    ExecutionBusinessObjects,
    ExecutionFinalOutcome,
    ExecutionSummaryResponse,
)
from research_layer.api.schemas.scholarly import (
    ScholarlyLookupRequest,
    SourceScholarlyLookupResponse,
)
from research_layer.api.schemas.source import (
    CANDIDATE_STATUS_VALUES,
    CANDIDATE_TYPE_VALUES,
    SOURCE_INPUT_MODE_VALUES,
    SOURCE_TYPE_VALUES,
    CandidateActionResponse,
    CandidateConfirmRequest,
    CandidateDetailResponse,
    CandidateListResponse,
    CandidateRecord,
    CandidateRejectRequest,
    ExtractionResultResponse,
    SourceExtractRequest,
    SourceBootstrapRequest,
    SourceBootstrapResponse,
    SourceListResponse,
    SourceImportRequest,
    SourceResponse,
    WorkspaceSummaryListResponse,
    WorkspaceSummaryRecord,
)
from research_layer.config.feature_flags import (
    RAW_BOOTSTRAP_FLAG,
    feature_disabled_error,
    is_feature_enabled,
)
from research_layer.services.raw_material_bootstrap_service import (
    RawMaterialBootstrapService,
)
from research_layer.services.source_import_service import SourceImportError, SourceImportService
from research_layer.services.candidate_confirmation_service import (
    CandidateConfirmationError,
    CandidateConfirmationService,
)
from research_layer.services.scholarly_connector import ScholarlyProviderError
from research_layer.services.scholarly_source_service import ScholarlySourceService
from research_layer.workers.extraction_worker import ExtractionWorker


@controller(name="research_source_controller")
class ResearchSourceController(BaseController):
    def __init__(self) -> None:
        super().__init__(
            prefix="/api/v1/research", tags=["Research Source"], default_auth="none"
        )
        self._import_service = SourceImportService(STORE)
        self._extraction_worker = ExtractionWorker(STORE)
        self._confirmation_service = CandidateConfirmationService(STORE)
        self._scholarly_source_service = ScholarlySourceService(STORE)
        self._bootstrap_service = RawMaterialBootstrapService(STORE)

    @post(
        "/sources/import",
        response_model=SourceResponse,
        responses={400: {"model": ErrorResponse}},
    )
    async def import_source(self, request: Request) -> SourceResponse:
        payload = await parse_request_model(request, SourceImportRequest)
        ensure(
            payload.source_type in SOURCE_TYPE_VALUES,
            status_code=400,
            code=ResearchErrorCode.INVALID_REQUEST.value,
            message="unsupported source_type",
            details={"allowed": sorted(SOURCE_TYPE_VALUES)},
        )
        ensure(
            payload.source_input_mode in SOURCE_INPUT_MODE_VALUES,
            status_code=400,
            code=ResearchErrorCode.INVALID_REQUEST.value,
            message="unsupported source_input_mode",
            details={"allowed": sorted(SOURCE_INPUT_MODE_VALUES)},
        )
        request_id = get_request_id(request.headers.get("x-request-id"))
        try:
            source = self._import_service.import_source(
                workspace_id=payload.workspace_id,
                source_type=payload.source_type,
                title=payload.title,
                content=payload.content,
                metadata=payload.metadata,
                source_input_mode=payload.source_input_mode,
                source_input=payload.source_input,
                source_url=payload.source_url,
                local_file=(
                    payload.local_file.model_dump()
                    if payload.local_file is not None
                    else None
                ),
                request_id=request_id,
            )
        except SourceImportError as exc:
            raise_http_error(
                status_code=exc.status_code,
                code=exc.error_code,
                message=exc.message,
                details=exc.details,
            )
        return SourceResponse.model_validate(source)

    @post(
        "/sources/bootstrap",
        response_model=SourceBootstrapResponse,
        responses={400: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    )
    async def bootstrap_sources(self, request: Request) -> SourceBootstrapResponse:
        if not is_feature_enabled(RAW_BOOTSTRAP_FLAG):
            raise_http_error(**feature_disabled_error(RAW_BOOTSTRAP_FLAG))
        payload = await parse_request_model(request, SourceBootstrapRequest)
        request_id = get_request_id(request.headers.get("x-request-id"))
        result = self._bootstrap_service.bootstrap(
            workspace_id=payload.workspace_id,
            materials=[item.model_dump() for item in payload.materials],
            request_id=request_id,
            run_extract=payload.run_extract,
        )
        return SourceBootstrapResponse.model_validate(result)

    @post(
        "/sources/{source_id}/extract",
        response_model=AsyncJobAcceptedResponse,
        status_code=202,
        responses={
            400: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
        },
    )
    async def extract_source(
        self, source_id: str, request: Request
    ) -> AsyncJobAcceptedResponse:
        payload = await parse_request_model(request, SourceExtractRequest)
        request_id = get_request_id(request.headers.get("x-request-id"))
        ensure(
            payload.async_mode,
            status_code=400,
            code=ResearchErrorCode.INVALID_REQUEST.value,
            message="async_mode must be true for extract endpoint",
            details={"async_mode": payload.async_mode},
        )
        failure_mode_header = request.headers.get("x-research-llm-failure-mode")
        fallback_header = str(
            request.headers.get("x-research-llm-allow-fallback") or ""
        ).strip().lower()
        allow_fallback = fallback_header in {"1", "true", "yes", "on", "enabled"}
        source = STORE.get_source(source_id)
        ensure(
            source is not None,
            status_code=404,
            code=ResearchErrorCode.NOT_FOUND.value,
            message="source not found",
            details={"source_id": source_id},
        )
        ensure(
            source["workspace_id"] == payload.workspace_id,
            status_code=409,
            code=ResearchErrorCode.CONFLICT.value,
            message="workspace_id does not match source ownership",
            details={"source_id": source_id},
        )

        job = STORE.create_job(
            job_type="source_extract",
            workspace_id=payload.workspace_id,
            request_id=request_id,
        )
        if payload.async_mode:
            schedule_background_job(
                self._run_source_extract_job(
                    request_id=request_id,
                    job_id=str(job["job_id"]),
                    workspace_id=payload.workspace_id,
                    source_id=source_id,
                    failure_mode=failure_mode_header,
                    allow_fallback=allow_fallback,
                ),
                job_id=str(job["job_id"]),
                job_type=str(job["job_type"]),
            )
        else:
            await self._run_source_extract_job(
                request_id=request_id,
                job_id=str(job["job_id"]),
                workspace_id=payload.workspace_id,
                source_id=source_id,
                failure_mode=failure_mode_header,
                allow_fallback=allow_fallback,
            )
        latest_job = STORE.get_job(str(job["job_id"]))

        return AsyncJobAcceptedResponse(
            job_id=job["job_id"],
            job_type=job["job_type"],
            status=latest_job["status"] if latest_job is not None else job["status"],
            workspace_id=payload.workspace_id,
            status_url=f"/api/v1/research/jobs/{job['job_id']}",
        )

    async def _run_source_extract_job(
        self,
        *,
        request_id: str,
        job_id: str,
        workspace_id: str,
        source_id: str,
        failure_mode: str | None,
        allow_fallback: bool,
    ) -> None:
        try:
            await self._extraction_worker.run(
                request_id=request_id,
                job_id=job_id,
                workspace_id=workspace_id,
                source_id=source_id,
                failure_mode=failure_mode,
                allow_fallback=allow_fallback,
            )
        except Exception as exc:  # pragma: no cover - defensive fallback
            error = {
                "error_code": "research.extract_failure",
                "message": "unexpected extraction failure",
                "details": {"source_id": source_id, "reason": str(exc)},
            }
            STORE.finish_job_failed(job_id=job_id, error=error)
            STORE.update_source_processing(
                source_id=source_id,
                status="extract_failed",
                last_extract_job_id=job_id,
            )
            STORE.emit_event(
                event_name="job_failed",
                request_id=request_id,
                job_id=job_id,
                workspace_id=workspace_id,
                source_id=source_id,
                component="research_source_controller",
                step="source_extract",
                status="failed",
                refs={"source_id": source_id},
                error=error,
            )

    @get(
        "/sources",
        response_model=SourceListResponse,
        responses={400: {"model": ErrorResponse}},
    )
    async def list_sources(
        self, workspace_id: str | None = Query(default=None)
    ) -> SourceListResponse:
        workspace = validate_workspace_id(workspace_id)
        items = [
            SourceResponse.model_validate(item)
            for item in STORE.list_sources(workspace_id=workspace)
        ]
        return SourceListResponse(items=items, total=len(items))

    @get("/workspaces", response_model=WorkspaceSummaryListResponse)
    async def list_workspaces(self) -> WorkspaceSummaryListResponse:
        items = [
            WorkspaceSummaryRecord.model_validate(item)
            for item in STORE.list_workspaces()
        ]
        return WorkspaceSummaryListResponse(items=items, total=len(items))

    @get(
        "/sources/{source_id}",
        response_model=SourceResponse,
        responses={404: {"model": ErrorResponse}},
    )
    async def get_source(self, source_id: str) -> SourceResponse:
        source = STORE.get_source(source_id)
        ensure(
            source is not None,
            status_code=404,
            code=ResearchErrorCode.NOT_FOUND.value,
            message="source not found",
            details={"source_id": source_id},
        )
        return SourceResponse.model_validate(source)

    @post(
        "/sources/{source_id}/scholarly/lookup",
        response_model=SourceScholarlyLookupResponse,
        responses={
            400: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
            500: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
    )
    async def lookup_scholarly_source(
        self, source_id: str, request: Request
    ) -> SourceScholarlyLookupResponse:
        payload = await parse_request_model(request, ScholarlyLookupRequest)
        request_id = get_request_id(request.headers.get("x-request-id"))
        try:
            result = self._scholarly_source_service.lookup_and_cache_source(
                workspace_id=payload.workspace_id,
                source_id=source_id,
                request_id=request_id,
                force_refresh=payload.force_refresh,
            )
        except ScholarlyProviderError as exc:
            raise_http_error(
                status_code=exc.status_code,
                code=exc.error_code,
                message=exc.message,
                details=exc.details,
            )
        return SourceScholarlyLookupResponse.model_validate(result)

    @get(
        "/sources/{source_id}/extraction-results/{candidate_batch_id}",
        response_model=ExtractionResultResponse,
        responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    )
    async def get_extraction_result(
        self,
        source_id: str,
        candidate_batch_id: str,
        workspace_id: str | None = Query(default=None),
    ) -> ExtractionResultResponse:
        workspace = validate_workspace_id(workspace_id)
        result = STORE.get_candidate_batch_for_source(
            source_id=source_id,
            candidate_batch_id=candidate_batch_id,
            workspace_id=workspace,
        )
        ensure(
            result is not None,
            status_code=404,
            code=ResearchErrorCode.NOT_FOUND.value,
            message="extraction result not found",
            details={"source_id": source_id, "candidate_batch_id": candidate_batch_id},
        )
        return ExtractionResultResponse.model_validate(result)

    @get(
        "/candidates",
        response_model=CandidateListResponse,
        responses={400: {"model": ErrorResponse}},
    )
    async def list_candidates(
        self,
        workspace_id: str | None = Query(default=None),
        source_id: str | None = Query(default=None),
        candidate_type: str | None = Query(default=None),
        status: str | None = Query(default=None),
    ) -> CandidateListResponse:
        validate_workspace_id(workspace_id)
        if candidate_type is not None and candidate_type not in CANDIDATE_TYPE_VALUES:
            raise_http_error(
                status_code=400,
                code=ResearchErrorCode.INVALID_REQUEST.value,
                message="unsupported candidate_type",
                details={"allowed": sorted(CANDIDATE_TYPE_VALUES)},
            )
        if status is not None and status not in CANDIDATE_STATUS_VALUES:
            raise_http_error(
                status_code=400,
                code=ResearchErrorCode.INVALID_REQUEST.value,
                message="unsupported candidate status",
                details={"allowed": sorted(CANDIDATE_STATUS_VALUES)},
            )

        items = [
            CandidateRecord.model_validate(item)
            for item in STORE.list_candidates(
                workspace_id=workspace_id,
                source_id=source_id,
                candidate_type=candidate_type,
                status=status,
            )
        ]
        return CandidateListResponse(items=items, total=len(items))

    @get(
        "/candidates/{candidate_id}",
        response_model=CandidateDetailResponse,
        responses={
            400: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
        },
    )
    async def get_candidate_detail(
        self, candidate_id: str, workspace_id: str | None = Query(default=None)
    ) -> CandidateDetailResponse:
        workspace = validate_workspace_id(workspace_id)
        candidate = STORE.get_candidate(candidate_id)
        ensure(
            candidate is not None,
            status_code=404,
            code=ResearchErrorCode.NOT_FOUND.value,
            message="candidate not found",
            details={"candidate_id": candidate_id},
        )
        ensure(
            candidate["workspace_id"] == workspace,
            status_code=409,
            code=ResearchErrorCode.CONFLICT.value,
            message="workspace_id does not match candidate ownership",
            details={"candidate_id": candidate_id},
        )
        return CandidateDetailResponse.model_validate(candidate)

    @get(
        "/executions/summary",
        response_model=ExecutionSummaryResponse,
        responses={400: {"model": ErrorResponse}},
    )
    async def get_execution_summary(
        self,
        workspace_id: str | None = Query(default=None),
        request_id: str | None = Query(default=None),
        job_id: str | None = Query(default=None),
        limit: int = Query(default=500, ge=1, le=5000),
    ) -> ExecutionSummaryResponse:
        workspace = validate_workspace_id(workspace_id)
        normalized_request_id = (
            request_id.strip() if request_id and request_id.strip() else None
        )
        normalized_job_id = job_id.strip() if job_id and job_id.strip() else None
        events = STORE.list_events(
            workspace_id=workspace,
            request_id=normalized_request_id,
            job_id=normalized_job_id,
            limit=limit,
        )
        jobs = STORE.list_jobs(
            workspace_id=workspace,
            request_id=normalized_request_id,
            job_id=normalized_job_id,
        )
        business_objects = self._collect_execution_business_objects(
            events=events, jobs=jobs
        )
        final_outcome = self._build_execution_final_outcome(events=events, jobs=jobs)
        return ExecutionSummaryResponse(
            workspace_id=workspace,
            request_id=normalized_request_id,
            job_id=normalized_job_id,
            timeline=events,
            business_objects=ExecutionBusinessObjects.model_validate(business_objects),
            final_outcome=ExecutionFinalOutcome.model_validate(final_outcome),
        )

    @get("/dev-console")
    async def research_dev_console(self) -> HTMLResponse:
        return HTMLResponse(
            content="""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Research Dev Console</title>
  <style>
    body { font-family: sans-serif; margin: 24px; max-width: 960px; }
    section { border: 1px solid #ddd; padding: 16px; margin-bottom: 16px; border-radius: 8px; }
    input, textarea, select { width: 100%; margin-top: 4px; margin-bottom: 8px; }
    button { padding: 8px 14px; margin-right: 8px; }
    pre { background: #f7f7f7; padding: 12px; border-radius: 6px; overflow-x: auto; }
  </style>
</head>
<body>
  <h1>Research Dev Console</h1>
  <section>
    <h2>Import Source</h2>
    <label>Workspace ID<input id="workspace" value="ws_slice3_console" /></label>
    <label>Source Type
      <select id="sourceType">
        <option>paper</option>
        <option>note</option>
        <option>failure_record</option>
        <option>feedback</option>
        <option>dialogue</option>
      </select>
    </label>
    <label>Title<input id="title" value="Console Source" /></label>
    <label>Content<textarea id="content" rows="6">Claim: retrieval helps. Assumption: cache is warm. Conflict: latency spikes. Failure: queue timeout. Validation: run ablation.</textarea></label>
    <button onclick="importSource()">Import</button>
  </section>
  <section>
    <h2>Trigger Extract</h2>
    <label>Source ID<input id="sourceId" /></label>
    <button onclick="triggerExtract()">Extract</button>
  </section>
  <section>
    <h2>Candidate List</h2>
    <button onclick="loadCandidates()">Refresh Candidates</button>
  </section>
  <section>
    <h2>Candidate Detail</h2>
    <label>Candidate ID<input id="candidateId" /></label>
    <button onclick="loadCandidateDetail()">Load Candidate</button>
  </section>
  <section>
    <h2>Confirm Candidate</h2>
    <button onclick="confirmCandidate()">Confirm</button>
  </section>
  <section>
    <h2>Reject Candidate</h2>
    <label>Reject Reason<input id="rejectReason" value="manual reject" /></label>
    <button onclick="rejectCandidate()">Reject</button>
  </section>
  <section>
    <h2>Graph Workspace</h2>
    <button onclick="buildGraph()">Build Graph from Confirmed Objects</button>
    <button onclick="loadGraphWorkspace()">Load Graph Workspace</button>
  </section>
  <section>
    <h2>Graph Query</h2>
    <label>Center Node ID<input id="centerNodeId" /></label>
    <label>Max Hops<input id="maxHops" type="number" min="1" max="5" value="1" /></label>
    <button onclick="queryGraph()">Query Local Subgraph</button>
    <button onclick="loadFullGraph()">Load Full Graph</button>
  </section>
  <section>
    <h2>Graph Node Create / Update</h2>
    <label>Node Type<input id="graphNodeType" value="evidence" /></label>
    <label>Object Ref Type<input id="graphNodeObjectRefType" value="manual_note" /></label>
    <label>Object Ref ID<input id="graphNodeObjectRefId" value="obj_manual_001" /></label>
    <label>Short Label<input id="graphNodeLabel" value="Manual Graph Node" /></label>
    <label>Full Description<textarea id="graphNodeDesc" rows="3">Manual node created via real graph API.</textarea></label>
    <label>Claim ID<input id="graphNodeClaimId" placeholder="required claim_id from this workspace" /></label>
    <label>Node ID For Update<input id="graphNodeIdForUpdate" /></label>
    <label>Node Status For Update<input id="graphNodeStatusUpdate" value="weakened" /></label>
    <button onclick="createGraphNode()">Create Node</button>
    <button onclick="updateGraphNode()">Update Node</button>
  </section>
  <section>
    <h2>Graph Edge Create / Update</h2>
    <label>Source Node ID<input id="edgeSourceNodeId" /></label>
    <label>Target Node ID<input id="edgeTargetNodeId" /></label>
    <label>Edge Type<input id="edgeType" value="supports" /></label>
    <label>Edge Object Ref Type<input id="edgeObjectRefType" value="manual_link" /></label>
    <label>Edge Object Ref ID<input id="edgeObjectRefId" value="obj_link_001" /></label>
    <label>Strength<input id="edgeStrength" type="number" min="0" max="1" step="0.1" value="0.8" /></label>
    <label>Claim ID<input id="edgeClaimId" placeholder="required claim_id from this workspace" /></label>
    <label>Edge ID For Update<input id="edgeIdForUpdate" /></label>
    <label>Edge Status For Update<input id="edgeStatusUpdate" value="weakened" /></label>
    <button onclick="createGraphEdge()">Create Edge</button>
    <button onclick="updateGraphEdge()">Update Edge</button>
  </section>
  <section>
    <h2>Route Generation + Ranking + Preview</h2>
    <p><strong>Route Scoring</strong> controls remain available for slice-6 compatibility.</p>
    <label>Route ID<input id="routeId" /></label>
    <label>Scoring Template ID (optional)<input id="scoreTemplateId" placeholder="general_research_v1" /></label>
    <label>Focus Node IDs (comma-separated, optional)<input id="focusNodeIds" /></label>
    <label>Recompute Reason<input id="recomputeReason" value="run ablation for retrieval precision and compare baseline" /></label>
    <label>Max Candidates<input id="maxCandidates" type="number" min="1" max="20" value="8" /></label>
    <button onclick="generateRoutes()">Generate Routes</button>
    <button onclick="recomputeRoute()">Recompute Route</button>
    <button onclick="scoreRoute()">Score Route</button>
    <button onclick="loadRoutes()">Load Routes</button>
    <button onclick="loadRoutePreview()">Load Route Preview</button>
    <p><strong>Top 3 Factors</strong> will appear in route score / route preview response.</p>
  </section>
  <section>
    <h2>Failure Loop + Recompute + Version Diff</h2>
    <label>Failure Target Type
      <select id="failureTargetType">
        <option value="node">node</option>
        <option value="edge">edge</option>
      </select>
    </label>
    <label>Failure Target ID<input id="failureTargetId" /></label>
    <label>Failure ID<input id="failureId" /></label>
    <label>Last Job ID<input id="lastJobId" /></label>
    <label>Version ID<input id="versionId" /></label>
    <button onclick="attachFailure()">Attach Failure</button>
    <button onclick="loadFailure()">Load Failure</button>
    <button onclick="recomputeFromFailure()">Recompute From Failure</button>
    <button onclick="loadJobStatus()">Load Job Status</button>
    <button onclick="loadVersionDiff()">Load Version Diff</button>
  </section>
  <section>
    <h2>Hypothesis Engine</h2>
    <label>Trigger IDs (comma-separated)<input id="hypothesisTriggerIds" /></label>
    <label>Hypothesis ID<input id="hypothesisId" /></label>
    <label>Decision Note<input id="hypothesisDecisionNote" value="reviewed by dev console" /></label>
    <label>Decision Source Type<input id="hypothesisDecisionSourceType" value="manual" /></label>
    <label>Decision Source Ref<input id="hypothesisDecisionSourceRef" value="research_dev_console" /></label>
    <button onclick="loadHypothesisTriggers()">Load Hypothesis Triggers</button>
    <button onclick="loadHypothesisInbox()">Load Hypothesis Inbox</button>
    <button onclick="generateHypothesis()">Generate Hypothesis</button>
    <button onclick="loadHypothesis()">Load Hypothesis</button>
    <button onclick="promoteHypothesis()">Promote Hypothesis</button>
    <button onclick="rejectHypothesis()">Reject Hypothesis</button>
    <button onclick="deferHypothesis()">Defer Hypothesis</button>
  </section>
  <section>
    <h2>Research Retrieval Views</h2>
    <label>Retrieval Query<input id="retrievalQuery" value="retrieval precision benchmark" /></label>
    <label>Retrieve Method
      <select id="retrievalMethod">
        <option value="hybrid">hybrid</option>
        <option value="keyword">keyword</option>
        <option value="vector">vector</option>
      </select>
    </label>
    <label>Top K<input id="retrievalTopK" type="number" min="1" max="100" value="20" /></label>
    <label>Metadata Filters (JSON)<textarea id="retrievalFilters" rows="4">{}</textarea></label>
    <button onclick="retrieveView('evidence')">Retrieve Evidence View</button>
    <button onclick="retrieveView('contradiction')">Retrieve Contradiction View</button>
    <button onclick="retrieveView('failure_pattern')">Retrieve Failure Pattern View</button>
    <button onclick="retrieveView('validation_history')">Retrieve Validation History View</button>
    <button onclick="retrieveView('hypothesis_support')">Retrieve Hypothesis Support View</button>
    <button onclick="runRetrievalQueryChange()">Run Retrieval Query Change</button>
    <label>Memory View Types (comma-separated)<input id="memoryViewTypes" value="evidence,contradiction,failure_pattern" /></label>
    <label>Memory Top K Per View<input id="memoryTopK" type="number" min="1" max="100" value="20" /></label>
    <label>Memory ID<input id="memoryResultId" /></label>
    <label>Memory View Type<input id="memoryResultViewType" /></label>
    <button onclick="loadMemoryVault()">Load Memory Vault</button>
    <button onclick="bindMemoryToCurrentRoute()">Bind Memory To Current Route</button>
    <button onclick="memoryToHypothesisCandidateAction()">Memory -> Hypothesis Candidate</button>
  </section>
  <section>
    <h2>Research Package</h2>
    <label>Package ID<input id="packageId" /></label>
    <label>Package Title<input id="packageTitle" value="Console Package Snapshot" /></label>
    <label>Package Summary<textarea id="packageSummary" rows="3">Snapshot package generated from real API state for Slice 11 acceptance.</textarea></label>
    <label>Included Route IDs (comma-separated)<input id="packageRouteIds" /></label>
    <label>Included Node IDs (comma-separated)<input id="packageNodeIds" /></label>
    <label>Included Validation IDs (comma-separated)<input id="packageValidationIds" /></label>
    <label>Publish Result ID<input id="publishResultId" /></label>
    <button onclick="createPackageSnapshot()">Create Package Snapshot</button>
    <button onclick="queryPackages()">Query Packages</button>
    <button onclick="loadPackage()">Load Package</button>
    <button onclick="loadPackageReplay()">Load Package Replay</button>
    <button onclick="publishPackage()">Publish Package</button>
    <button onclick="loadPackagePublishResult()">Load Publish Result</button>
  </section>
  <section>
    <h2>Slice 12 E2E Closed Loop</h2>
    <p>Thin wrapper over real APIs for source -> route, failure -> diff, and trigger -> hypothesis.</p>
    <label>Execution Request ID Filter (optional)<input id="executionRequestId" /></label>
    <button onclick="runSlice12ClosedLoop()">Run Closed Loop (Source -> Route -> Failure -> Diff -> Hypothesis)</button>
    <button onclick="loadExecutionSummary()">Load Execution Summary</button>
  </section>
  <pre id="output"></pre>
  <script>
    const output = document.getElementById("output");
    const setOutput = (label, payload) => {
      output.textContent = label + "\\n" + JSON.stringify(payload, null, 2);
    };
    const parseCsv = (raw) => raw
      .split(",")
      .map(item => item.trim())
      .filter(Boolean);

    async function importSource() {
      const body = {
        workspace_id: document.getElementById("workspace").value,
        source_type: document.getElementById("sourceType").value,
        title: document.getElementById("title").value,
        content: document.getElementById("content").value
      };
      const res = await fetch("/api/v1/research/sources/import", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(body)
      });
      const payload = await res.json();
      if (payload.source_id) {
        document.getElementById("sourceId").value = payload.source_id;
      }
      setOutput("import source", payload);
    }

    async function triggerExtract() {
      const workspaceId = document.getElementById("workspace").value;
      const sourceId = document.getElementById("sourceId").value;
      const startRes = await fetch(`/api/v1/research/sources/${sourceId}/extract`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({workspace_id: workspaceId, async_mode: true})
      });
      const startPayload = await startRes.json();
      const jobRes = await fetch(`/api/v1/research/jobs/${startPayload.job_id}`);
      const jobPayload = await jobRes.json();
      setOutput("extract + job status", {start: startPayload, job: jobPayload});
    }

    async function loadCandidates() {
      const workspaceId = document.getElementById("workspace").value;
      const sourceId = document.getElementById("sourceId").value;
      const res = await fetch(`/api/v1/research/candidates?workspace_id=${encodeURIComponent(workspaceId)}&source_id=${encodeURIComponent(sourceId)}`);
      const payload = await res.json();
      if (payload.items && payload.items.length > 0) {
        document.getElementById("candidateId").value = payload.items[0].candidate_id;
      }
      setOutput("candidate list", payload);
    }

    async function loadCandidateDetail() {
      const workspaceId = document.getElementById("workspace").value;
      const candidateId = document.getElementById("candidateId").value;
      const res = await fetch(`/api/v1/research/candidates/${candidateId}?workspace_id=${encodeURIComponent(workspaceId)}`);
      const payload = await res.json();
      setOutput("candidate detail", payload);
    }

    async function confirmCandidate() {
      const workspaceId = document.getElementById("workspace").value;
      const candidateId = document.getElementById("candidateId").value;
      const res = await fetch("/api/v1/research/candidates/confirm", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({workspace_id: workspaceId, candidate_ids: [candidateId]})
      });
      const payload = await res.json();
      setOutput("confirm candidate", payload);
    }

    async function rejectCandidate() {
      const workspaceId = document.getElementById("workspace").value;
      const candidateId = document.getElementById("candidateId").value;
      const reason = document.getElementById("rejectReason").value;
      const res = await fetch("/api/v1/research/candidates/reject", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({workspace_id: workspaceId, candidate_ids: [candidateId], reason})
      });
      const payload = await res.json();
      setOutput("reject candidate", payload);
    }

    async function buildGraph() {
      const workspaceId = document.getElementById("workspace").value;
      const res = await fetch(`/api/v1/research/graph/${workspaceId}/build`, {method: "POST"});
      const payload = await res.json();
      setOutput("graph build", payload);
    }

    async function loadGraphWorkspace() {
      const workspaceId = document.getElementById("workspace").value;
      const res = await fetch(`/api/v1/research/graph/${workspaceId}/workspace`);
      const payload = await res.json();
      setOutput("graph workspace", payload);
    }

    async function loadFullGraph() {
      const workspaceId = document.getElementById("workspace").value;
      const res = await fetch(`/api/v1/research/graph/${workspaceId}`);
      const payload = await res.json();
      if (payload.nodes && payload.nodes.length > 0) {
        document.getElementById("centerNodeId").value = payload.nodes[0].node_id;
        document.getElementById("graphNodeIdForUpdate").value = payload.nodes[0].node_id;
        document.getElementById("edgeSourceNodeId").value = payload.nodes[0].node_id;
        document.getElementById("failureTargetType").value = "node";
        document.getElementById("failureTargetId").value = payload.nodes[0].node_id;
        if (payload.nodes.length > 1) {
          document.getElementById("edgeTargetNodeId").value = payload.nodes[1].node_id;
        }
      }
      if (payload.edges && payload.edges.length > 0) {
        document.getElementById("edgeIdForUpdate").value = payload.edges[0].edge_id;
      }
      setOutput("full graph", payload);
    }

    async function queryGraph() {
      const workspaceId = document.getElementById("workspace").value;
      const centerNodeId = document.getElementById("centerNodeId").value;
      const maxHops = Number(document.getElementById("maxHops").value || 1);
      const res = await fetch(`/api/v1/research/graph/${workspaceId}/query`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({center_node_id: centerNodeId, max_hops: maxHops})
      });
      const payload = await res.json();
      setOutput("local graph query", payload);
    }

    async function createGraphNode() {
      const workspaceId = document.getElementById("workspace").value;
      const claimId = document.getElementById("graphNodeClaimId").value.trim();
      if (!claimId) {
        setOutput("create graph node blocked", {
          error_code: "research.invalid_request",
          message: "graph projection requires claim_id",
          details: {reason: "missing_claim_id", workspace_id: workspaceId}
        });
        return;
      }
      const res = await fetch("/api/v1/research/graph/nodes", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          workspace_id: workspaceId,
          node_type: document.getElementById("graphNodeType").value,
          object_ref_type: document.getElementById("graphNodeObjectRefType").value,
          object_ref_id: document.getElementById("graphNodeObjectRefId").value,
          short_label: document.getElementById("graphNodeLabel").value,
          full_description: document.getElementById("graphNodeDesc").value,
          claim_id: claimId
        })
      });
      const payload = await res.json();
      if (payload.node_id) {
        document.getElementById("graphNodeIdForUpdate").value = payload.node_id;
      }
      setOutput("create graph node", payload);
    }

    async function updateGraphNode() {
      const workspaceId = document.getElementById("workspace").value;
      const nodeId = document.getElementById("graphNodeIdForUpdate").value;
      const res = await fetch(`/api/v1/research/graph/nodes/${nodeId}`, {
        method: "PATCH",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          workspace_id: workspaceId,
          short_label: document.getElementById("graphNodeLabel").value,
          status: document.getElementById("graphNodeStatusUpdate").value
        })
      });
      const payload = await res.json();
      setOutput("update graph node", payload);
    }

    async function createGraphEdge() {
      const workspaceId = document.getElementById("workspace").value;
      const claimId = document.getElementById("edgeClaimId").value.trim();
      if (!claimId) {
        setOutput("create graph edge blocked", {
          error_code: "research.invalid_request",
          message: "graph projection requires claim_id",
          details: {reason: "missing_claim_id", workspace_id: workspaceId}
        });
        return;
      }
      const res = await fetch("/api/v1/research/graph/edges", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          workspace_id: workspaceId,
          source_node_id: document.getElementById("edgeSourceNodeId").value,
          target_node_id: document.getElementById("edgeTargetNodeId").value,
          edge_type: document.getElementById("edgeType").value,
          object_ref_type: document.getElementById("edgeObjectRefType").value,
          object_ref_id: document.getElementById("edgeObjectRefId").value,
          strength: Number(document.getElementById("edgeStrength").value || 0.8),
          claim_id: claimId
        })
      });
      const payload = await res.json();
      if (payload.edge_id) {
        document.getElementById("edgeIdForUpdate").value = payload.edge_id;
      }
      setOutput("create graph edge", payload);
    }

    async function updateGraphEdge() {
      const workspaceId = document.getElementById("workspace").value;
      const edgeId = document.getElementById("edgeIdForUpdate").value;
      const res = await fetch(`/api/v1/research/graph/edges/${edgeId}`, {
        method: "PATCH",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          workspace_id: workspaceId,
          status: document.getElementById("edgeStatusUpdate").value,
          strength: Number(document.getElementById("edgeStrength").value || 0.8)
        })
      });
      const payload = await res.json();
      setOutput("update graph edge", payload);
    }

    async function recomputeRoute() {
      const workspaceId = document.getElementById("workspace").value;
      const reason = document.getElementById("recomputeReason").value;
      const startRes = await fetch("/api/v1/research/routes/recompute", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({workspace_id: workspaceId, reason, async_mode: true})
      });
      const startPayload = await startRes.json();
      if (startPayload.job_id) {
        document.getElementById("lastJobId").value = startPayload.job_id;
      }
      let jobPayload = null;
      if (startPayload.job_id) {
        const jobRes = await fetch(`/api/v1/research/jobs/${startPayload.job_id}`);
        jobPayload = await jobRes.json();
        const routeId = jobPayload?.result_ref?.resource_id;
        if (routeId) {
          document.getElementById("routeId").value = routeId;
        }
      }
      setOutput("route recompute + job", {start: startPayload, job: jobPayload});
    }

    async function attachFailure() {
      const workspaceId = document.getElementById("workspace").value;
      const targetType = document.getElementById("failureTargetType").value;
      const targetId = document.getElementById("failureTargetId").value;
      const res = await fetch("/api/v1/research/failures", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          workspace_id: workspaceId,
          attached_targets: [{target_type: targetType, target_id: targetId}],
          observed_outcome: "Observed failure from Dev Console",
          expected_difference: "Expected stable route behavior",
          failure_reason: "Console-triggered failure attach",
          severity: "high",
          reporter: "research_dev_console"
        })
      });
      const payload = await res.json();
      if (payload.failure_id) {
        document.getElementById("failureId").value = payload.failure_id;
      }
      setOutput("attach failure", payload);
    }

    async function loadFailure() {
      const failureId = document.getElementById("failureId").value;
      const res = await fetch(`/api/v1/research/failures/${failureId}`);
      const payload = await res.json();
      setOutput("failure detail", payload);
    }

    async function recomputeFromFailure() {
      const workspaceId = document.getElementById("workspace").value;
      const failureId = document.getElementById("failureId").value;
      const reason = document.getElementById("recomputeReason").value;
      const startRes = await fetch("/api/v1/research/routes/recompute", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({workspace_id: workspaceId, failure_id: failureId, reason, async_mode: true})
      });
      const startPayload = await startRes.json();
      if (startPayload.job_id) {
        document.getElementById("lastJobId").value = startPayload.job_id;
      }
      let jobPayload = null;
      if (startPayload.job_id) {
        const jobRes = await fetch(`/api/v1/research/jobs/${startPayload.job_id}`);
        jobPayload = await jobRes.json();
        if (jobPayload?.result_ref?.resource_type === "graph_version") {
          document.getElementById("versionId").value = jobPayload.result_ref.resource_id;
        }
      }
      setOutput("failure recompute + job", {start: startPayload, job: jobPayload});
    }

    async function loadJobStatus() {
      const jobId = document.getElementById("lastJobId").value;
      const res = await fetch(`/api/v1/research/jobs/${jobId}`);
      const payload = await res.json();
      if (payload?.result_ref?.resource_type === "graph_version") {
        document.getElementById("versionId").value = payload.result_ref.resource_id;
      }
      setOutput("job status", payload);
    }

    async function loadVersionDiff() {
      const versionId = document.getElementById("versionId").value;
      const res = await fetch(`/api/v1/research/versions/${versionId}/diff`);
      const payload = await res.json();
      setOutput("version diff", payload);
    }

    async function loadHypothesisTriggers() {
      const workspaceId = document.getElementById("workspace").value;
      const res = await fetch(`/api/v1/research/hypotheses/triggers/list?workspace_id=${encodeURIComponent(workspaceId)}`);
      const payload = await res.json();
      if (payload.items && payload.items.length > 0) {
        const selected = payload.items.slice(0, 2).map(item => item.trigger_id).join(",");
        document.getElementById("hypothesisTriggerIds").value = selected;
      }
      setOutput("hypothesis triggers", payload);
    }

    async function loadHypothesisInbox() {
      const workspaceId = document.getElementById("workspace").value;
      const res = await fetch(`/api/v1/research/hypotheses?workspace_id=${encodeURIComponent(workspaceId)}`);
      const payload = await res.json();
      if (payload.items && payload.items.length > 0) {
        document.getElementById("hypothesisId").value = payload.items[0].hypothesis_id;
      }
      setOutput("hypothesis inbox", payload);
    }

    async function generateHypothesis() {
      const workspaceId = document.getElementById("workspace").value;
      const triggerIds = document.getElementById("hypothesisTriggerIds").value
        .split(",")
        .map(item => item.trim())
        .filter(Boolean);
      const startRes = await fetch("/api/v1/research/hypotheses/generate", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({workspace_id: workspaceId, trigger_ids: triggerIds, async_mode: true})
      });
      const startPayload = await startRes.json();
      if (startPayload.job_id) {
        document.getElementById("lastJobId").value = startPayload.job_id;
      }
      let jobPayload = null;
      if (startPayload.job_id) {
        const jobRes = await fetch(`/api/v1/research/jobs/${startPayload.job_id}`);
        jobPayload = await jobRes.json();
        if (jobPayload?.result_ref?.resource_type === "hypothesis") {
          document.getElementById("hypothesisId").value = jobPayload.result_ref.resource_id;
        }
      }
      setOutput("hypothesis generate + job", {start: startPayload, job: jobPayload});
    }

    async function loadHypothesis() {
      const hypothesisId = document.getElementById("hypothesisId").value;
      const res = await fetch(`/api/v1/research/hypotheses/${hypothesisId}`);
      const payload = await res.json();
      setOutput("hypothesis detail", payload);
    }

    async function promoteHypothesis() {
      const workspaceId = document.getElementById("workspace").value;
      const hypothesisId = document.getElementById("hypothesisId").value;
      const note = document.getElementById("hypothesisDecisionNote").value;
      const decisionSourceType = document.getElementById("hypothesisDecisionSourceType").value;
      const decisionSourceRef = document.getElementById("hypothesisDecisionSourceRef").value;
      const res = await fetch(`/api/v1/research/hypotheses/${hypothesisId}/promote`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          workspace_id: workspaceId,
          note,
          decision_source_type: decisionSourceType,
          decision_source_ref: decisionSourceRef
        })
      });
      const payload = await res.json();
      setOutput("promote hypothesis", payload);
    }

    async function rejectHypothesis() {
      const workspaceId = document.getElementById("workspace").value;
      const hypothesisId = document.getElementById("hypothesisId").value;
      const note = document.getElementById("hypothesisDecisionNote").value;
      const decisionSourceType = document.getElementById("hypothesisDecisionSourceType").value;
      const decisionSourceRef = document.getElementById("hypothesisDecisionSourceRef").value;
      const res = await fetch(`/api/v1/research/hypotheses/${hypothesisId}/reject`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          workspace_id: workspaceId,
          note,
          decision_source_type: decisionSourceType,
          decision_source_ref: decisionSourceRef
        })
      });
      const payload = await res.json();
      setOutput("reject hypothesis", payload);
    }

    async function deferHypothesis() {
      const workspaceId = document.getElementById("workspace").value;
      const hypothesisId = document.getElementById("hypothesisId").value;
      const note = document.getElementById("hypothesisDecisionNote").value;
      const decisionSourceType = document.getElementById("hypothesisDecisionSourceType").value;
      const decisionSourceRef = document.getElementById("hypothesisDecisionSourceRef").value;
      const res = await fetch(`/api/v1/research/hypotheses/${hypothesisId}/defer`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          workspace_id: workspaceId,
          note,
          decision_source_type: decisionSourceType,
          decision_source_ref: decisionSourceRef
        })
      });
      const payload = await res.json();
      setOutput("defer hypothesis", payload);
    }

    async function retrieveView(viewType) {
      const workspaceId = document.getElementById("workspace").value;
      const query = document.getElementById("retrievalQuery").value;
      const retrieveMethod = document.getElementById("retrievalMethod").value;
      const topK = Number(document.getElementById("retrievalTopK").value || 20);
      let metadataFilters = {};
      try {
        metadataFilters = JSON.parse(document.getElementById("retrievalFilters").value || "{}");
      } catch (error) {
        setOutput("retrieval parse error", {error: "invalid metadata filter JSON"});
        return;
      }
      const res = await fetch(`/api/v1/research/retrieval/views/${viewType}`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          workspace_id: workspaceId,
          query,
          retrieve_method: retrieveMethod,
          top_k: topK,
          metadata_filters: metadataFilters
        })
      });
      const payload = await res.json();
      setOutput(`retrieval ${viewType}`, payload);
    }

    async function runRetrievalQueryChange() {
      const beforeQuery = document.getElementById("retrievalQuery").value;
      await retrieveView("evidence");
      document.getElementById("retrievalQuery").value = "timeout latency pattern";
      await retrieveView("evidence");
      document.getElementById("retrievalQuery").value = beforeQuery;
    }

    async function loadMemoryVault() {
      const workspaceId = document.getElementById("workspace").value;
      const query = document.getElementById("retrievalQuery").value;
      const retrieveMethod = document.getElementById("retrievalMethod").value;
      const viewTypes = parseCsv(document.getElementById("memoryViewTypes").value);
      const topKPerView = Number(document.getElementById("memoryTopK").value || 20);
      const res = await fetch("/api/v1/research/memory/list", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          workspace_id: workspaceId,
          view_types: viewTypes,
          query,
          retrieve_method: retrieveMethod,
          top_k_per_view: topKPerView
        })
      });
      const payload = await res.json();
      const firstItem = payload?.items?.[0];
      if (firstItem?.memory_id) {
        document.getElementById("memoryResultId").value = firstItem.memory_id;
        document.getElementById("memoryResultViewType").value = firstItem.memory_view_type || "";
      }
      setOutput("memory list", payload);
    }

    async function bindMemoryToCurrentRoute() {
      const workspaceId = document.getElementById("workspace").value;
      const routeId = document.getElementById("routeId").value.trim();
      const memoryId = document.getElementById("memoryResultId").value.trim();
      const memoryViewType = document.getElementById("memoryResultViewType").value.trim();
      const res = await fetch("/api/v1/research/memory/actions/bind-to-current-route", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          workspace_id: workspaceId,
          route_id: routeId,
          memory_id: memoryId,
          memory_view_type: memoryViewType,
          note: "bound from dev console memory vault"
        })
      });
      const payload = await res.json();
      setOutput("memory bind to route", payload);
    }

    async function memoryToHypothesisCandidateAction() {
      const workspaceId = document.getElementById("workspace").value;
      const memoryId = document.getElementById("memoryResultId").value.trim();
      const memoryViewType = document.getElementById("memoryResultViewType").value.trim();
      const res = await fetch("/api/v1/research/memory/actions/memory-to-hypothesis-candidate", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          workspace_id: workspaceId,
          memory_id: memoryId,
          memory_view_type: memoryViewType,
          note: "spawned from dev console memory vault"
        })
      });
      const payload = await res.json();
      if (payload?.hypothesis?.hypothesis_id) {
        document.getElementById("hypothesisId").value = payload.hypothesis.hypothesis_id;
      }
      setOutput("memory to hypothesis candidate", payload);
    }

    async function createPackageSnapshot() {
      const workspaceId = document.getElementById("workspace").value;
      const routeId = document.getElementById("routeId").value.trim();
      const defaultRouteIds = routeId ? [routeId] : [];
      const routeIdsInput = parseCsv(document.getElementById("packageRouteIds").value);
      const routeIds = routeIdsInput.length > 0 ? routeIdsInput : defaultRouteIds;
      const nodeIds = parseCsv(document.getElementById("packageNodeIds").value);
      const validationIds = parseCsv(document.getElementById("packageValidationIds").value);
      const res = await fetch("/api/v1/research/packages", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          workspace_id: workspaceId,
          title: document.getElementById("packageTitle").value,
          summary: document.getElementById("packageSummary").value,
          included_route_ids: routeIds,
          included_node_ids: nodeIds,
          included_validation_ids: validationIds
        })
      });
      const payload = await res.json();
      if (payload.package_id) {
        document.getElementById("packageId").value = payload.package_id;
      }
      setOutput("create package snapshot", payload);
    }

    async function queryPackages() {
      const workspaceId = document.getElementById("workspace").value;
      const res = await fetch(`/api/v1/research/packages?workspace_id=${encodeURIComponent(workspaceId)}`);
      const payload = await res.json();
      if (payload.items && payload.items.length > 0) {
        document.getElementById("packageId").value = payload.items[0].package_id;
      }
      setOutput("query packages", payload);
    }

    async function loadPackage() {
      const workspaceId = document.getElementById("workspace").value;
      const packageId = document.getElementById("packageId").value;
      const res = await fetch(`/api/v1/research/packages/${packageId}?workspace_id=${encodeURIComponent(workspaceId)}`);
      const payload = await res.json();
      setOutput("load package", payload);
    }

    async function loadPackageReplay() {
      const workspaceId = document.getElementById("workspace").value;
      const packageId = document.getElementById("packageId").value;
      const res = await fetch(`/api/v1/research/packages/${packageId}/replay?workspace_id=${encodeURIComponent(workspaceId)}`);
      const payload = await res.json();
      setOutput("load package replay", payload);
    }

    async function publishPackage() {
      const workspaceId = document.getElementById("workspace").value;
      const packageId = document.getElementById("packageId").value;
      const startRes = await fetch(`/api/v1/research/packages/${packageId}/publish`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({workspace_id: workspaceId, async_mode: true})
      });
      const startPayload = await startRes.json();
      if (startPayload.job_id) {
        document.getElementById("lastJobId").value = startPayload.job_id;
      }
      let jobPayload = null;
      if (startPayload.job_id) {
        const jobRes = await fetch(`/api/v1/research/jobs/${startPayload.job_id}`);
        jobPayload = await jobRes.json();
        if (jobPayload?.result_ref?.resource_type === "package_publish_result") {
          document.getElementById("publishResultId").value = jobPayload.result_ref.resource_id;
        }
      }
      setOutput("publish package + job", {start: startPayload, job: jobPayload});
    }

    async function loadPackagePublishResult() {
      const workspaceId = document.getElementById("workspace").value;
      const packageId = document.getElementById("packageId").value;
      const publishResultId = document.getElementById("publishResultId").value;
      const res = await fetch(`/api/v1/research/packages/${packageId}/publish-results/${publishResultId}?workspace_id=${encodeURIComponent(workspaceId)}`);
      const payload = await res.json();
      setOutput("load package publish result", payload);
    }

    async function generateRoutes() {
      const workspaceId = document.getElementById("workspace").value;
      const reason = document.getElementById("recomputeReason").value;
      const maxCandidates = Number(document.getElementById("maxCandidates").value || 8);
      const res = await fetch("/api/v1/research/routes/generate", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({workspace_id: workspaceId, reason, max_candidates: maxCandidates})
      });
      const payload = await res.json();
      if (payload.ranked_route_ids && payload.ranked_route_ids.length > 0) {
        document.getElementById("routeId").value = payload.ranked_route_ids[0];
      }
      setOutput("route generation", payload);
    }

    async function scoreRoute() {
      const workspaceId = document.getElementById("workspace").value;
      const routeId = document.getElementById("routeId").value;
      const templateId = document.getElementById("scoreTemplateId").value.trim();
      const focusNodeIdsRaw = document.getElementById("focusNodeIds").value;
      const focusNodeIds = focusNodeIdsRaw
        .split(",")
        .map(item => item.trim())
        .filter(Boolean);
      const body = {
        workspace_id: workspaceId,
        focus_node_ids: focusNodeIds
      };
      if (templateId) {
        body.template_id = templateId;
      }
      const res = await fetch(`/api/v1/research/routes/${routeId}/score`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(body)
      });
      const payload = await res.json();
      setOutput("route score", payload);
    }

    async function loadRoutes() {
      const workspaceId = document.getElementById("workspace").value;
      const res = await fetch(`/api/v1/research/routes?workspace_id=${encodeURIComponent(workspaceId)}`);
      const payload = await res.json();
      if (payload.items && payload.items.length > 0) {
        document.getElementById("routeId").value = payload.items[0].route_id;
      }
      setOutput("route list", payload);
    }

    async function loadRoutePreview() {
      const workspaceId = document.getElementById("workspace").value;
      const routeId = document.getElementById("routeId").value;
      const res = await fetch(`/api/v1/research/routes/${routeId}/preview?workspace_id=${encodeURIComponent(workspaceId)}`);
      const payload = await res.json();
      setOutput("route preview", payload);
    }

    async function loadExecutionSummary() {
      const workspaceId = document.getElementById("workspace").value;
      const requestId = document.getElementById("executionRequestId").value.trim();
      const jobId = document.getElementById("lastJobId").value.trim();
      const query = new URLSearchParams({workspace_id: workspaceId});
      if (requestId) {
        query.set("request_id", requestId);
      }
      if (jobId) {
        query.set("job_id", jobId);
      }
      const res = await fetch(`/api/v1/research/executions/summary?${query.toString()}`);
      const payload = await res.json();
      setOutput("execution summary", payload);
    }

    async function runSlice12ClosedLoop() {
      const workspaceId = document.getElementById("workspace").value;
      const steps = {};

      const imported = await fetch("/api/v1/research/sources/import", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          workspace_id: workspaceId,
          source_type: "paper",
          title: "Slice12 Closed Loop Source",
          content: "Claim: retrieval precision improves. Assumption: cache remains warm. Conflict: latency can regress. Failure: timeout spikes. Validation: run replay benchmark."
        })
      });
      const importPayload = await imported.json();
      steps.import = importPayload;
      if (!importPayload.source_id) {
        setOutput("slice12 closed loop", {steps});
        return;
      }
      document.getElementById("sourceId").value = importPayload.source_id;

      const extractRes = await fetch(`/api/v1/research/sources/${importPayload.source_id}/extract`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({workspace_id: workspaceId, async_mode: true})
      });
      const extractStart = await extractRes.json();
      steps.extract = extractStart;
      if (extractStart.job_id) {
        document.getElementById("lastJobId").value = extractStart.job_id;
        const extractJobRes = await fetch(`/api/v1/research/jobs/${extractStart.job_id}`);
        steps.extract_job = await extractJobRes.json();
      }

      const candidateRes = await fetch(`/api/v1/research/candidates?workspace_id=${encodeURIComponent(workspaceId)}&source_id=${encodeURIComponent(importPayload.source_id)}`);
      const candidatePayload = await candidateRes.json();
      steps.candidates = candidatePayload;
      const firstCandidate = candidatePayload?.items?.[0];
      if (!firstCandidate) {
        setOutput("slice12 closed loop", {steps});
        return;
      }
      document.getElementById("candidateId").value = firstCandidate.candidate_id;

      const confirmRes = await fetch("/api/v1/research/candidates/confirm", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          workspace_id: workspaceId,
          candidate_ids: candidatePayload.items.map(item => item.candidate_id)
        })
      });
      steps.confirm = await confirmRes.json();

      const buildRes = await fetch(`/api/v1/research/graph/${workspaceId}/build`, {method: "POST"});
      steps.graph_build = await buildRes.json();

      const generateRes = await fetch("/api/v1/research/routes/generate", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({workspace_id: workspaceId, reason: "slice12 closed loop", max_candidates: 8})
      });
      const generated = await generateRes.json();
      steps.route_generate = generated;
      const routeId = generated?.ranked_route_ids?.[0];
      if (routeId) {
        document.getElementById("routeId").value = routeId;
        const previewRes = await fetch(`/api/v1/research/routes/${routeId}/preview?workspace_id=${encodeURIComponent(workspaceId)}`);
        steps.route_preview = await previewRes.json();
      }

      const graphRes = await fetch(`/api/v1/research/graph/${workspaceId}`);
      const graphPayload = await graphRes.json();
      const evidenceNode = (graphPayload.nodes || []).find(node => node.node_type === "evidence");
      if (evidenceNode) {
        document.getElementById("failureTargetType").value = "node";
        document.getElementById("failureTargetId").value = evidenceNode.node_id;
        const failureRes = await fetch("/api/v1/research/failures", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            workspace_id: workspaceId,
            attached_targets: [{target_type: "node", target_id: evidenceNode.node_id}],
            observed_outcome: "closed loop observed failure",
            expected_difference: "support should remain stable",
            failure_reason: "closed loop injected failure",
            severity: "high",
            reporter: "research_dev_console"
          })
        });
        const failurePayload = await failureRes.json();
        steps.failure_attach = failurePayload;
        if (failurePayload.failure_id) {
          document.getElementById("failureId").value = failurePayload.failure_id;
          const recomputeRes = await fetch("/api/v1/research/routes/recompute", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
              workspace_id: workspaceId,
              failure_id: failurePayload.failure_id,
              reason: "slice12 closed loop recompute",
              async_mode: true
            })
          });
          const recomputePayload = await recomputeRes.json();
          steps.recompute = recomputePayload;
          if (recomputePayload.job_id) {
            document.getElementById("lastJobId").value = recomputePayload.job_id;
            const recomputeJobRes = await fetch(`/api/v1/research/jobs/${recomputePayload.job_id}`);
            const recomputeJobPayload = await recomputeJobRes.json();
            steps.recompute_job = recomputeJobPayload;
            if (recomputeJobPayload?.result_ref?.resource_type === "graph_version") {
              document.getElementById("versionId").value = recomputeJobPayload.result_ref.resource_id;
              const diffRes = await fetch(`/api/v1/research/versions/${recomputeJobPayload.result_ref.resource_id}/diff`);
              steps.version_diff = await diffRes.json();
            }
          }
        }
      }

      const triggerRes = await fetch(`/api/v1/research/hypotheses/triggers/list?workspace_id=${encodeURIComponent(workspaceId)}`);
      const triggerPayload = await triggerRes.json();
      steps.hypothesis_triggers = triggerPayload;
      const triggerIds = (triggerPayload.items || []).slice(0, 3).map(item => item.trigger_id);
      if (triggerIds.length > 0) {
        document.getElementById("hypothesisTriggerIds").value = triggerIds.join(",");
        const hypothesisRes = await fetch("/api/v1/research/hypotheses/generate", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({workspace_id: workspaceId, trigger_ids: triggerIds, async_mode: true})
        });
        const hypothesisStart = await hypothesisRes.json();
        steps.hypothesis_generate = hypothesisStart;
        if (hypothesisStart.job_id) {
          document.getElementById("lastJobId").value = hypothesisStart.job_id;
          const hypothesisJobRes = await fetch(`/api/v1/research/jobs/${hypothesisStart.job_id}`);
          const hypothesisJobPayload = await hypothesisJobRes.json();
          steps.hypothesis_job = hypothesisJobPayload;
          if (hypothesisJobPayload?.result_ref?.resource_type === "hypothesis") {
            document.getElementById("hypothesisId").value = hypothesisJobPayload.result_ref.resource_id;
          }
        }
      }

      const summaryRes = await fetch(`/api/v1/research/executions/summary?workspace_id=${encodeURIComponent(workspaceId)}`);
      steps.execution_summary = await summaryRes.json();
      setOutput("slice12 closed loop", steps);
    }
  </script>
</body>
</html>
            """.strip()
        )

    @post(
        "/candidates/confirm",
        response_model=CandidateActionResponse,
        responses={
            400: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
        },
    )
    async def confirm_candidates(self, request: Request) -> CandidateActionResponse:
        payload = await parse_request_model(request, CandidateConfirmRequest)
        request_id = get_request_id(request.headers.get("x-request-id"))
        updated: list[str] = []
        for candidate_id in payload.candidate_ids:
            try:
                self._confirmation_service.confirm(
                    workspace_id=payload.workspace_id,
                    candidate_id=candidate_id,
                    request_id=request_id,
                )
                updated.append(candidate_id)
            except CandidateConfirmationError as exc:
                raise_http_error(
                    status_code=exc.status_code,
                    code=exc.error_code,
                    message=exc.message,
                    details=exc.details,
                )

        return CandidateActionResponse(updated_ids=updated, status="confirmed")

    @post(
        "/candidates/reject",
        response_model=CandidateActionResponse,
        responses={
            400: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
        },
    )
    async def reject_candidates(self, request: Request) -> CandidateActionResponse:
        payload = await parse_request_model(request, CandidateRejectRequest)
        request_id = get_request_id(request.headers.get("x-request-id"))
        updated: list[str] = []
        for candidate_id in payload.candidate_ids:
            try:
                self._confirmation_service.reject(
                    workspace_id=payload.workspace_id,
                    candidate_id=candidate_id,
                    reason=payload.reason,
                    request_id=request_id,
                )
                updated.append(candidate_id)
            except CandidateConfirmationError as exc:
                raise_http_error(
                    status_code=exc.status_code,
                    code=exc.error_code,
                    message=exc.message,
                    details=exc.details,
                )

        return CandidateActionResponse(updated_ids=updated, status="rejected")

    def _collect_execution_business_objects(
        self, *, events: list[dict[str, object]], jobs: list[dict[str, object]]
    ) -> dict[str, list[str]]:
        buckets: dict[str, set[str]] = {
            "source_ids": set(),
            "route_ids": set(),
            "version_ids": set(),
            "hypothesis_ids": set(),
            "package_ids": set(),
            "failure_ids": set(),
            "candidate_batch_ids": set(),
            "request_ids": set(),
            "job_ids": set(),
        }
        refs_key_map = {
            "source_ids": ("source_id", "source_ids"),
            "route_ids": (
                "route_id",
                "route_ids",
                "ranked_route_ids",
                "referenced_by_route_ids",
            ),
            "version_ids": ("version_id", "base_version_id", "new_version_id"),
            "hypothesis_ids": ("hypothesis_id", "hypothesis_ids"),
            "package_ids": ("package_id", "package_ids"),
            "failure_ids": ("failure_id", "failure_ids"),
            "candidate_batch_ids": ("candidate_batch_id", "candidate_batch_ids"),
        }

        def add_value(bucket_name: str, value: object) -> None:
            if isinstance(value, str) and value.strip():
                buckets[bucket_name].add(value.strip())
                return
            if isinstance(value, Iterable) and not isinstance(
                value, (str, bytes, dict)
            ):
                for item in value:
                    add_value(bucket_name, item)

        for event in events:
            add_value("source_ids", event.get("source_id"))
            add_value("candidate_batch_ids", event.get("candidate_batch_id"))
            add_value("request_ids", event.get("request_id"))
            add_value("job_ids", event.get("job_id"))
            refs = event.get("refs")
            if not isinstance(refs, dict):
                continue
            for bucket_name, keys in refs_key_map.items():
                for key in keys:
                    if key in refs:
                        add_value(bucket_name, refs.get(key))

        for job in jobs:
            add_value("request_ids", job.get("request_id"))
            add_value("job_ids", job.get("job_id"))
            result_ref = job.get("result_ref")
            if not isinstance(result_ref, dict):
                continue
            resource_type = str(result_ref.get("resource_type", ""))
            resource_id = result_ref.get("resource_id")
            if resource_type == "graph_version":
                add_value("version_ids", resource_id)
            elif resource_type == "hypothesis":
                add_value("hypothesis_ids", resource_id)
            elif resource_type == "route":
                add_value("route_ids", resource_id)
            elif resource_type in {"package", "package_publish_result"}:
                add_value("package_ids", resource_id)
            elif resource_type == "candidate_batch":
                add_value("candidate_batch_ids", resource_id)

        return {key: sorted(values) for key, values in buckets.items()}

    def _build_execution_final_outcome(
        self, *, events: list[dict[str, object]], jobs: list[dict[str, object]]
    ) -> dict[str, object]:
        completed_event_count = sum(
            1 for event in events if str(event.get("status", "")) == "completed"
        ) + sum(1 for job in jobs if str(job.get("status", "")) == "succeeded")
        failed_event_count = sum(
            1 for event in events if str(event.get("status", "")) == "failed"
        ) + sum(1 for job in jobs if str(job.get("status", "")) == "failed")
        running_job_count = sum(
            1
            for job in jobs
            if str(job.get("status", "")).strip().lower() in {"queued", "running"}
        )
        if running_job_count > 0 and failed_event_count == 0:
            status = "running"
        elif failed_event_count > 0 and completed_event_count == 0:
            status = "failed"
        elif failed_event_count > 0 and completed_event_count > 0:
            status = "partial"
        else:
            status = "completed"

        last_event_name = None
        last_event_status = None
        if events:
            last_event_name = str(events[-1].get("event_name", ""))
            last_event_status = str(events[-1].get("status", ""))

        result_refs: list[dict[str, str]] = []
        for job in jobs:
            result_ref = job.get("result_ref")
            if not isinstance(result_ref, dict):
                continue
            resource_type = str(result_ref.get("resource_type", "")).strip()
            resource_id = str(result_ref.get("resource_id", "")).strip()
            if not resource_type or not resource_id:
                continue
            result_refs.append(
                {
                    "job_id": str(job.get("job_id", "")),
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                }
            )
        return {
            "status": status,
            "last_event": last_event_name,
            "last_status": last_event_status,
            "completed_event_count": completed_event_count,
            "failed_event_count": failed_event_count,
            "result_refs": result_refs,
        }
