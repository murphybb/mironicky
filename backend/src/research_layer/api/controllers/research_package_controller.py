from __future__ import annotations

from fastapi import Query, Request

from core.di.decorators import controller
from core.interface.controller.base_controller import BaseController, get, post
from research_layer.api.controllers._job_runner import schedule_background_job
from research_layer.api.controllers._state_store import STORE
from research_layer.api.controllers._utils import (
    error_payload_from_exception,
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
from research_layer.api.schemas.export import ResearchExportResponse
from research_layer.api.schemas.package import (
    PackageCreateRequest,
    PackageListResponse,
    PackagePublishRequest,
    PackagePublishResultResponse,
    PackageReplayResponse,
    PackageResponse,
)
from research_layer.config.feature_flags import (
    EXPORT_FLAG,
    feature_disabled_error,
    is_feature_enabled,
)
from research_layer.services.package_build_service import (
    PackageBuildService,
    PackageBuildServiceError,
)
from research_layer.services.research_export_service import ResearchExportService


@controller(name="research_package_controller")
class ResearchPackageController(BaseController):
    def __init__(self) -> None:
        super().__init__(
            prefix="/api/v1/research",
            tags=["Research Package"],
            default_auth="none",
        )
        self._package_service = PackageBuildService(STORE)
        self._export_service = ResearchExportService(STORE)

    @post(
        "/packages",
        response_model=PackageResponse,
        responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    )
    async def create_package(self, request: Request) -> PackageResponse:
        payload = await parse_request_model(request, PackageCreateRequest)
        request_id = get_request_id(request.headers.get("x-request-id"))
        try:
            record = self._package_service.build_snapshot(
                workspace_id=payload.workspace_id,
                title=payload.title,
                summary=payload.summary,
                included_route_ids=payload.included_route_ids,
                included_node_ids=payload.included_node_ids,
                included_validation_ids=payload.included_validation_ids,
                request_id=request_id,
            )
        except PackageBuildServiceError as exc:
            raise_http_error(
                status_code=exc.status_code,
                code=exc.error_code,
                message=exc.message,
                details=exc.details,
            )
        return PackageResponse.model_validate(record)

    @get(
        "/packages",
        response_model=PackageListResponse,
        responses={400: {"model": ErrorResponse}},
    )
    async def list_packages(
        self,
        workspace_id: str | None = Query(default=None),
        status: str | None = Query(default=None),
    ) -> PackageListResponse:
        workspace = validate_workspace_id(workspace_id)
        items = [
            PackageResponse.model_validate(item)
            for item in STORE.list_packages(workspace_id=workspace, status=status)
        ]
        return PackageListResponse(items=items, total=len(items))

    @get(
        "/packages/{package_id}",
        response_model=PackageResponse,
        responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    )
    async def get_package(
        self, package_id: str, workspace_id: str | None = Query(default=None)
    ) -> PackageResponse:
        record = STORE.get_package(package_id)
        ensure(
            record is not None,
            status_code=404,
            code=ResearchErrorCode.NOT_FOUND.value,
            message="package not found",
            details={"package_id": package_id},
        )
        if workspace_id is not None:
            workspace = validate_workspace_id(workspace_id)
            ensure(
                str(record["workspace_id"]) == workspace,
                status_code=409,
                code=ResearchErrorCode.CONFLICT.value,
                message="workspace_id does not match package ownership",
                details={"package_id": package_id},
            )
        return PackageResponse.model_validate(record)

    @get(
        "/packages/{package_id}/replay",
        response_model=PackageReplayResponse,
        responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    )
    async def replay_package(
        self, package_id: str, workspace_id: str | None = Query(default=None)
    ) -> PackageReplayResponse:
        record = STORE.get_package(package_id)
        ensure(
            record is not None,
            status_code=404,
            code=ResearchErrorCode.NOT_FOUND.value,
            message="package not found",
            details={"package_id": package_id},
        )
        if workspace_id is not None:
            workspace = validate_workspace_id(workspace_id)
            ensure(
                str(record["workspace_id"]) == workspace,
                status_code=409,
                code=ResearchErrorCode.CONFLICT.value,
                message="workspace_id does not match package ownership",
                details={"package_id": package_id},
            )
        ensure(
            bool(record.get("replay_ready")),
            status_code=409,
            code=ResearchErrorCode.INVALID_STATE.value,
            message="package snapshot is not replay-ready",
            details={"package_id": package_id},
        )
        return PackageReplayResponse(
            package_id=str(record["package_id"]),
            workspace_id=str(record["workspace_id"]),
            snapshot=dict(record.get("snapshot_payload", {})),
        )

    @get(
        "/packages/{package_id}/export",
        response_model=ResearchExportResponse,
        responses={
            400: {"model": ErrorResponse},
            403: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
        },
    )
    async def export_package(
        self,
        package_id: str,
        request: Request,
        workspace_id: str | None = Query(default=None),
        format: str = Query(default="json"),
    ) -> ResearchExportResponse:
        request_id = get_request_id(request.headers.get("x-request-id"))
        if not is_feature_enabled(EXPORT_FLAG):
            error = feature_disabled_error(EXPORT_FLAG)
            STORE.emit_event(
                event_name="package_export_completed",
                request_id=request_id,
                job_id=None,
                workspace_id=workspace_id,
                component="research_package_controller",
                step="package_export",
                status="failed",
                refs={"package_id": package_id, "format": format},
                error={
                    "error_code": str(error["code"]),
                    "message": str(error["message"]),
                    "details": dict(error.get("details", {})),
                },
            )
            raise_http_error(**error)
        try:
            workspace = validate_workspace_id(workspace_id)
        except Exception as exc:
            STORE.emit_event(
                event_name="package_export_completed",
                request_id=request_id,
                job_id=None,
                workspace_id=workspace_id,
                component="research_package_controller",
                step="package_export",
                status="failed",
                refs={"package_id": package_id, "format": format},
                error=error_payload_from_exception(exc),
            )
            raise
        record = STORE.get_package(package_id)
        if record is None:
            error = {
                "error_code": ResearchErrorCode.NOT_FOUND.value,
                "message": "package not found",
                "details": {"package_id": package_id},
            }
            STORE.emit_event(
                event_name="package_export_completed",
                request_id=request_id,
                job_id=None,
                workspace_id=workspace_id,
                component="research_package_controller",
                step="package_export",
                status="failed",
                refs={"package_id": package_id, "format": format},
                error=error,
            )
            raise_http_error(
                status_code=404,
                code=error["error_code"],
                message=error["message"],
                details=error["details"],
            )
        package_workspace = str(record["workspace_id"])
        if package_workspace != workspace:
            error = {
                "error_code": ResearchErrorCode.CONFLICT.value,
                "message": "workspace_id does not match package ownership",
                "details": {"package_id": package_id},
            }
            STORE.emit_event(
                event_name="package_export_completed",
                request_id=request_id,
                job_id=None,
                workspace_id=workspace,
                component="research_package_controller",
                step="package_export",
                status="failed",
                refs={"package_id": package_id, "format": format},
                error=error,
            )
            raise_http_error(
                status_code=409,
                code=error["error_code"],
                message=error["message"],
                details=error["details"],
            )
        try:
            exported = self._export_service.export_package(
                package_id=package_id, export_format=format
            )
        except ValueError as exc:
            error = {
                "error_code": ResearchErrorCode.INVALID_REQUEST.value,
                "message": str(exc),
                "details": {"format": format},
            }
            STORE.emit_event(
                event_name="package_export_completed",
                request_id=request_id,
                job_id=None,
                workspace_id=workspace,
                component="research_package_controller",
                step="package_export",
                status="failed",
                refs={"package_id": package_id, "format": format},
                error=error,
            )
            raise_http_error(
                status_code=400,
                code=error["error_code"],
                message=error["message"],
                details=error["details"],
            )
        except Exception as exc:
            STORE.emit_event(
                event_name="package_export_completed",
                request_id=request_id,
                job_id=None,
                workspace_id=workspace,
                component="research_package_controller",
                step="package_export",
                status="failed",
                refs={"package_id": package_id, "format": format},
                error=error_payload_from_exception(exc),
            )
            raise
        STORE.emit_event(
            event_name="package_export_completed",
            request_id=request_id,
            job_id=None,
            workspace_id=workspace,
            component="research_package_controller",
            step="package_export",
            status="completed",
            refs={"package_id": package_id, "format": format},
        )
        return ResearchExportResponse.model_validate(exported)

    @post(
        "/packages/{package_id}/publish",
        response_model=AsyncJobAcceptedResponse,
        status_code=202,
        responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    )
    async def publish_package(
        self, package_id: str, request: Request
    ) -> AsyncJobAcceptedResponse:
        payload = await parse_request_model(request, PackagePublishRequest)
        request_id = get_request_id(request.headers.get("x-request-id"))
        ensure(
            payload.async_mode,
            status_code=400,
            code=ResearchErrorCode.INVALID_REQUEST.value,
            message="async_mode must be true for package publish endpoint",
            details={"async_mode": payload.async_mode},
        )
        package = STORE.get_package(package_id)
        ensure(
            package is not None,
            status_code=404,
            code=ResearchErrorCode.NOT_FOUND.value,
            message="package not found",
            details={"package_id": package_id},
        )
        ensure(
            str(package["workspace_id"]) == payload.workspace_id,
            status_code=409,
            code=ResearchErrorCode.CONFLICT.value,
            message="workspace_id does not match package ownership",
            details={"package_id": package_id},
        )
        ensure(
            str(package["status"]) != "published",
            status_code=409,
            code=ResearchErrorCode.INVALID_STATE.value,
            message="package is already published",
            details={"package_id": package_id},
        )
        ensure(
            bool(package.get("replay_ready")),
            status_code=409,
            code=ResearchErrorCode.INVALID_STATE.value,
            message="package snapshot is not replay-ready",
            details={"package_id": package_id},
        )
        job = STORE.create_job(
            job_type="package_publish",
            workspace_id=payload.workspace_id,
            request_id=request_id,
        )
        if payload.async_mode:
            schedule_background_job(
                self._run_package_publish_job(
                    job_id=str(job["job_id"]),
                    workspace_id=payload.workspace_id,
                    request_id=request_id,
                    package_id=package_id,
                ),
                job_id=str(job["job_id"]),
                job_type=str(job["job_type"]),
            )
            latest_job = STORE.get_job(str(job["job_id"]))
            return AsyncJobAcceptedResponse(
                job_id=str(job["job_id"]),
                job_type=str(job["job_type"]),
                status=latest_job["status"] if latest_job is not None else job["status"],
                workspace_id=payload.workspace_id,
                status_url=f"/api/v1/research/jobs/{job['job_id']}",
            )
        try:
            await self._run_package_publish_job(
                job_id=str(job["job_id"]),
                workspace_id=payload.workspace_id,
                request_id=request_id,
                package_id=package_id,
            )
            finished_job = STORE.get_job(str(job["job_id"]))
            return AsyncJobAcceptedResponse(
                job_id=str(job["job_id"]),
                job_type=str(job["job_type"]),
                status=finished_job["status"] if finished_job is not None else "succeeded",
                workspace_id=payload.workspace_id,
                status_url=f"/api/v1/research/jobs/{job['job_id']}",
            )
        except PackageBuildServiceError as exc:
            raise_http_error(
                status_code=exc.status_code,
                code=exc.error_code,
                message=exc.message,
                details={**exc.details, "job_id": job["job_id"]},
            )

    async def _run_package_publish_job(
        self,
        *,
        job_id: str,
        workspace_id: str,
        request_id: str,
        package_id: str,
    ) -> None:
        STORE.start_job(job_id)
        try:
            publish_result = self._package_service.publish_snapshot(
                workspace_id=workspace_id,
                package_id=package_id,
                request_id=request_id,
                job_id=job_id,
                async_mode=True,
            )
            STORE.finish_job_success(
                job_id=job_id,
                result_ref={
                    "resource_type": "package_publish_result",
                    "resource_id": str(publish_result["publish_result_id"]),
                },
            )
        except PackageBuildServiceError as exc:
            STORE.finish_job_failed(
                job_id=job_id,
                error={
                    "error_code": exc.error_code,
                    "message": exc.message,
                    "details": exc.details,
                },
            )
            STORE.emit_event(
                event_name="job_failed",
                request_id=request_id,
                job_id=job_id,
                workspace_id=workspace_id,
                component="research_package_controller",
                step="package_publish",
                status="failed",
                refs={"package_id": package_id},
                error={
                    "error_code": exc.error_code,
                    "message": exc.message,
                    "details": exc.details,
                },
            )
            raise
        except Exception as exc:  # pragma: no cover - defensive fallback
            error = {
                "error_code": "research.package_publish_failed",
                "message": "unexpected package publish failure",
                "details": {"package_id": package_id, "reason": str(exc)},
            }
            STORE.finish_job_failed(job_id=job_id, error=error)
            STORE.emit_event(
                event_name="job_failed",
                request_id=request_id,
                job_id=job_id,
                workspace_id=workspace_id,
                component="research_package_controller",
                step="package_publish",
                status="failed",
                refs={"package_id": package_id},
                error=error,
            )
            raise PackageBuildServiceError(
                status_code=500,
                error_code="research.package_publish_failed",
                message="unexpected package publish failure",
                details={"package_id": package_id, "reason": str(exc)},
            ) from exc

    @get(
        "/packages/{package_id}/publish-results/{publish_result_id}",
        response_model=PackagePublishResultResponse,
        responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    )
    async def get_publish_result(
        self,
        package_id: str,
        publish_result_id: str,
        workspace_id: str | None = Query(default=None),
    ) -> PackagePublishResultResponse:
        package = STORE.get_package(package_id)
        ensure(
            package is not None,
            status_code=404,
            code=ResearchErrorCode.NOT_FOUND.value,
            message="package not found",
            details={"package_id": package_id},
        )
        result = STORE.get_package_publish_result(publish_result_id)
        ensure(
            result is not None,
            status_code=404,
            code=ResearchErrorCode.NOT_FOUND.value,
            message="package publish result not found",
            details={"publish_result_id": publish_result_id},
        )
        ensure(
            str(result["package_id"]) == package_id,
            status_code=409,
            code=ResearchErrorCode.CONFLICT.value,
            message="publish result does not belong to package",
            details={"package_id": package_id, "publish_result_id": publish_result_id},
        )
        if workspace_id is not None:
            workspace = validate_workspace_id(workspace_id)
            ensure(
                str(result["workspace_id"]) == workspace,
                status_code=409,
                code=ResearchErrorCode.CONFLICT.value,
                message="workspace_id does not match publish result ownership",
                details={"publish_result_id": publish_result_id},
            )
        return PackagePublishResultResponse.model_validate(result)
