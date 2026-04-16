from __future__ import annotations

from fastapi import Request

from core.di.decorators import controller
from core.interface.controller.base_controller import BaseController, get, post
from research_layer.api.controllers._state_store import STORE
from research_layer.api.controllers._utils import (
    ensure,
    get_request_id,
    parse_request_model,
    raise_http_error,
    validate_workspace_id,
)
from research_layer.api.schemas.common import ErrorResponse, ResearchErrorCode
from research_layer.api.schemas.failure import (
    FailureCreateRequest,
    FailureResponse,
    ValidationCreateRequest,
    ValidationResultResponse,
    ValidationResultSubmitRequest,
    ValidationResponse,
)
from research_layer.services.failure_impact_service import (
    FailureImpactError,
    FailureImpactService,
)
from research_layer.services.recompute_service import (
    RecomputeService,
    RecomputeServiceError,
)


@controller(name="research_failure_controller")
class ResearchFailureController(BaseController):
    def __init__(self) -> None:
        super().__init__(
            prefix="/api/v1/research",
            tags=["Research Failure"],
            default_auth="none",
        )
        self._failure_impact_service = FailureImpactService(STORE)
        self._recompute_service = RecomputeService(STORE)

    def _resolve_validation_target(
        self,
        *,
        validation: dict[str, object],
        explicit_target_type: str | None,
        explicit_target_id: str | None,
    ) -> tuple[str, str]:
        if explicit_target_type is not None and explicit_target_id is not None:
            return explicit_target_type, explicit_target_id
        ensure(
            explicit_target_type is None and explicit_target_id is None,
            status_code=400,
            code=ResearchErrorCode.INVALID_REQUEST.value,
            message="target_type and target_id must be provided together",
            details={"validation_id": str(validation["validation_id"])},
        )
        raw_target = str(validation.get("target_object") or "")
        ensure(
            ":" in raw_target,
            status_code=400,
            code=ResearchErrorCode.INVALID_REQUEST.value,
            message="validation target_object must be in '<target_type>:<target_id>' format",
            details={
                "validation_id": str(validation["validation_id"]),
                "target_object": raw_target,
            },
        )
        target_type, target_id = raw_target.split(":", 1)
        target_type = target_type.strip().lower()
        target_id = target_id.strip()
        ensure(
            target_type in {"route", "node", "edge"} and bool(target_id),
            status_code=400,
            code=ResearchErrorCode.INVALID_REQUEST.value,
            message="validation target_object contains unsupported target",
            details={
                "validation_id": str(validation["validation_id"]),
                "target_object": raw_target,
            },
        )
        return target_type, target_id

    def _build_failure_targets_from_target(
        self,
        *,
        workspace_id: str,
        target_type: str,
        target_id: str,
    ) -> list[dict[str, str]]:
        if target_type in {"node", "edge"}:
            target = (
                STORE.get_graph_node(target_id)
                if target_type == "node"
                else STORE.get_graph_edge(target_id)
            )
            ensure(
                target is not None,
                status_code=404,
                code=ResearchErrorCode.NOT_FOUND.value,
                message=f"{target_type} not found",
                details={"target_type": target_type, "target_id": target_id},
            )
            ensure(
                str(target["workspace_id"]) == workspace_id,
                status_code=409,
                code=ResearchErrorCode.CONFLICT.value,
                message="workspace_id does not match target ownership",
                details={"target_type": target_type, "target_id": target_id},
            )
            return [{"target_type": target_type, "target_id": target_id}]

        route = STORE.get_route(target_id)
        ensure(
            route is not None,
            status_code=404,
            code=ResearchErrorCode.NOT_FOUND.value,
            message="route not found",
            details={"target_type": target_type, "target_id": target_id},
        )
        ensure(
            str(route["workspace_id"]) == workspace_id,
            status_code=409,
            code=ResearchErrorCode.CONFLICT.value,
            message="workspace_id does not match route ownership",
            details={"target_type": target_type, "target_id": target_id},
        )
        route_edge_ids = [str(edge_id) for edge_id in route.get("route_edge_ids", [])]
        for edge_id in route_edge_ids:
            edge = STORE.get_graph_edge(edge_id)
            if edge is not None and str(edge["workspace_id"]) == workspace_id:
                return [{"target_type": "edge", "target_id": edge_id}]
        route_node_ids = [str(node_id) for node_id in route.get("route_node_ids", [])]
        if route.get("conclusion_node_id"):
            route_node_ids.append(str(route["conclusion_node_id"]))
        for node_id in route_node_ids:
            node = STORE.get_graph_node(node_id)
            if node is not None and str(node["workspace_id"]) == workspace_id:
                return [{"target_type": "node", "target_id": node_id}]
        ensure(
            False,
            status_code=409,
            code=ResearchErrorCode.INVALID_STATE.value,
            message="route has no attachable graph targets for failure propagation",
            details={"route_id": target_id},
        )
        return []

    @post(
        "/failures",
        response_model=FailureResponse,
        responses={400: {"model": ErrorResponse}},
    )
    async def create_failure(self, request: Request) -> FailureResponse:
        payload = await parse_request_model(request, FailureCreateRequest)
        request_id = get_request_id(request.headers.get("x-request-id"))
        try:
            targets = self._failure_impact_service.validate_targets_for_create(
                workspace_id=payload.workspace_id,
                attached_targets=[
                    {"target_type": item.target_type, "target_id": item.target_id}
                    for item in payload.attached_targets
                ],
            )
        except FailureImpactError as exc:
            ensure(
                False,
                status_code=exc.status_code,
                code=exc.error_code,
                message=exc.message,
                details=exc.details,
            )
        record = STORE.create_failure(
            workspace_id=payload.workspace_id,
            attached_targets=targets,
            observed_outcome=payload.observed_outcome,
            expected_difference=payload.expected_difference,
            failure_reason=payload.failure_reason,
            severity=payload.severity,
            reporter=payload.reporter,
        )
        STORE.emit_event(
            event_name="failure_recorded",
            request_id=request_id,
            job_id=None,
            workspace_id=payload.workspace_id,
            component="research_failure_controller",
            step="failure_record",
            status="completed",
            refs={
                "failure_id": str(record["failure_id"]),
                "attached_targets": targets,
            },
            metrics={"target_count": len(targets)},
        )
        return FailureResponse.model_validate(record)

    @post(
        "/validations",
        response_model=ValidationResponse,
        responses={400: {"model": ErrorResponse}},
    )
    async def create_validation(self, request: Request) -> ValidationResponse:
        payload = await parse_request_model(request, ValidationCreateRequest)
        record = STORE.create_validation(
            workspace_id=payload.workspace_id,
            target_object=payload.target_object,
            method=payload.method,
            success_signal=payload.success_signal,
            weakening_signal=payload.weakening_signal,
        )
        return ValidationResponse.model_validate(record)

    @post(
        "/validations/{validation_id}/results",
        response_model=ValidationResultResponse,
        responses={
            400: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
        },
    )
    async def submit_validation_result(
        self,
        validation_id: str,
        request: Request,
    ) -> ValidationResultResponse:
        payload = await parse_request_model(request, ValidationResultSubmitRequest)
        request_id = get_request_id(request.headers.get("x-request-id"))
        workspace_id = validate_workspace_id(payload.workspace_id)
        validation = STORE.get_validation(validation_id)
        ensure(
            validation is not None,
            status_code=404,
            code=ResearchErrorCode.NOT_FOUND.value,
            message="validation not found",
            details={"validation_id": validation_id},
        )
        ensure(
            str(validation["workspace_id"]) == workspace_id,
            status_code=409,
            code=ResearchErrorCode.CONFLICT.value,
            message="workspace_id does not match validation ownership",
            details={"validation_id": validation_id},
        )
        target_type, target_id = self._resolve_validation_target(
            validation=validation,
            explicit_target_type=payload.target_type,
            explicit_target_id=payload.target_id,
        )

        triggered_failure_id: str | None = None
        recompute_job_id: str | None = None
        if payload.outcome in {"weakened", "failed"}:
            attached_targets = self._build_failure_targets_from_target(
                workspace_id=workspace_id,
                target_type=target_type,
                target_id=target_id,
            )
            failure = STORE.create_failure(
                workspace_id=workspace_id,
                attached_targets=attached_targets,
                observed_outcome=payload.note
                or f"validation outcome is {payload.outcome}",
                expected_difference=str(validation["success_signal"]),
                failure_reason=f"validation_result:{payload.outcome}",
                severity="medium" if payload.outcome == "weakened" else "high",
                reporter=payload.reporter,
                derived_from_validation_id=validation_id,
            )
            triggered_failure_id = str(failure["failure_id"])
            job = STORE.create_job(
                job_type="validation_recompute",
                workspace_id=workspace_id,
                request_id=request_id,
            )
            recompute_job_id = str(job["job_id"])

        result = STORE.create_validation_result(
            validation_id=validation_id,
            workspace_id=workspace_id,
            outcome=payload.outcome,
            target_type=target_type,
            target_id=target_id,
            note=payload.note,
            request_id=request_id,
            triggered_failure_id=triggered_failure_id,
            recompute_job_id=recompute_job_id,
        )
        if triggered_failure_id is not None:
            STORE.update_failure_provenance(
                failure_id=triggered_failure_id,
                derived_from_validation_result_id=str(result["result_id"]),
            )
        STORE.emit_event(
            event_name="validation_result_recorded",
            request_id=request_id,
            job_id=recompute_job_id,
            workspace_id=workspace_id,
            component="research_failure_controller",
            step="validation_feedback",
            status="completed",
            refs={
                "validation_id": validation_id,
                "result_id": result["result_id"],
                "target_type": target_type,
                "target_id": target_id,
                "triggered_failure_id": triggered_failure_id,
                "recompute_job_id": recompute_job_id,
            },
            metrics={"outcome": payload.outcome},
        )
        if payload.outcome in {"weakened", "failed"} and recompute_job_id is not None:
            STORE.start_job(recompute_job_id)
            try:
                recomputed = await self._recompute_service.recompute_from_failure(
                    workspace_id=workspace_id,
                    failure_id=str(triggered_failure_id),
                    reason=f"validation result {payload.outcome}",
                    request_id=request_id,
                    job_id=recompute_job_id,
                )
                STORE.finish_job_success(
                    job_id=recompute_job_id,
                    result_ref={
                        "resource_type": "graph_version",
                        "resource_id": str(recomputed["version_id"]),
                    },
                )
            except RecomputeServiceError as exc:
                STORE.finish_job_failed(
                    job_id=recompute_job_id,
                    error={
                        "error_code": exc.error_code,
                        "message": exc.message,
                        "details": exc.details,
                    },
                )
                raise_http_error(
                    status_code=exc.status_code,
                    code=exc.error_code,
                    message=exc.message,
                    details={
                        **exc.details,
                        "validation_id": validation_id,
                        "result_id": result["result_id"],
                        "triggered_failure_id": triggered_failure_id,
                        "recompute_job_id": recompute_job_id,
                    },
                )
        triggered_failure = (
            STORE.get_failure(triggered_failure_id)
            if triggered_failure_id is not None
            else None
        )
        return ValidationResultResponse.model_validate(
            {**result, "triggered_failure": triggered_failure}
        )

    @get(
        "/failures/{failure_id}",
        response_model=FailureResponse,
        responses={404: {"model": ErrorResponse}},
    )
    async def get_failure(self, failure_id: str) -> FailureResponse:
        record = STORE.get_failure(failure_id)
        ensure(
            record is not None,
            status_code=404,
            code=ResearchErrorCode.NOT_FOUND.value,
            message="failure not found",
            details={"failure_id": failure_id},
        )
        return FailureResponse.model_validate(record)
