from __future__ import annotations

from fastapi import Request

from core.di.decorators import controller
from core.interface.controller.base_controller import BaseController, get, post
from research_layer.api.controllers._state_store import STORE
from research_layer.api.controllers._utils import (
    error_payload_from_exception,
    get_request_id,
    parse_request_model,
    raise_http_error,
    validate_workspace_id,
)
from research_layer.api.schemas.common import ErrorResponse, ResearchErrorCode
from research_layer.api.schemas.query import (
    QueryRunRequest,
    QueryRunResponse,
    QueryToolsResponse,
)
from research_layer.config.feature_flags import (
    QUERY_API_FLAG,
    feature_disabled_error,
    is_feature_enabled,
)
from research_layer.services.research_query_service import ResearchQueryService


@controller(name="research_query_controller")
class ResearchQueryController(BaseController):
    def __init__(self) -> None:
        super().__init__(
            prefix="/api/v1/research", tags=["Research Query"], default_auth="none"
        )
        self._query_service = ResearchQueryService(STORE)

    @get(
        "/query/tools",
        response_model=QueryToolsResponse,
        responses={403: {"model": ErrorResponse}},
    )
    async def list_query_tools(self) -> QueryToolsResponse:
        request_id = get_request_id(None)
        try:
            self._ensure_enabled()
            tools = self._query_service.list_tools()
        except Exception as exc:
            STORE.emit_event(
                event_name="research_query_tools",
                request_id=request_id,
                job_id=None,
                workspace_id=None,
                component="research_query_controller",
                step="query_tools",
                status="failed",
                error=error_payload_from_exception(exc),
            )
            raise
        STORE.emit_event(
            event_name="research_query_tools",
            request_id=request_id,
            job_id=None,
            workspace_id=None,
            component="research_query_controller",
            step="query_tools",
            status="completed",
            metrics={"tool_count": len(tools)},
        )
        return QueryToolsResponse(tools=tools)

    @post(
        "/query/run",
        response_model=QueryRunResponse,
        responses={400: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    )
    async def run_query_tool(self, request: Request) -> QueryRunResponse:
        request_id = get_request_id(request.headers.get("x-request-id"))
        payload: QueryRunRequest | None = None
        workspace: str | None = None
        try:
            self._ensure_enabled()
            payload = await parse_request_model(request, QueryRunRequest)
            workspace = validate_workspace_id(payload.workspace_id)
        except Exception as exc:
            refs: dict[str, object] = {}
            if payload is not None:
                refs["tool_name"] = payload.tool_name
            STORE.emit_event(
                event_name="research_query_completed",
                request_id=request_id,
                job_id=None,
                workspace_id=workspace,
                component="research_query_controller",
                step="query_run",
                status="failed",
                refs=refs,
                error=error_payload_from_exception(exc),
            )
            raise
        try:
            result = self._query_service.run_tool(
                workspace_id=workspace,
                tool_name=payload.tool_name,
                arguments=payload.arguments,
            )
        except ValueError as exc:
            error = {
                "error_code": ResearchErrorCode.INVALID_REQUEST.value,
                "message": str(exc),
                "details": {"tool_name": payload.tool_name},
            }
            STORE.emit_event(
                event_name="research_query_completed",
                request_id=request_id,
                job_id=None,
                workspace_id=workspace,
                component="research_query_controller",
                step="query_run",
                status="failed",
                refs={"tool_name": payload.tool_name},
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
                event_name="research_query_completed",
                request_id=request_id,
                job_id=None,
                workspace_id=workspace,
                component="research_query_controller",
                step="query_run",
                status="failed",
                refs={"tool_name": payload.tool_name},
                error=error_payload_from_exception(exc),
            )
            raise
        STORE.emit_event(
            event_name="research_query_completed",
            request_id=request_id,
            job_id=None,
            workspace_id=workspace,
            component="research_query_controller",
            step="query_run",
            status="completed",
            refs={"tool_name": payload.tool_name},
        )
        return QueryRunResponse.model_validate(result)

    def _ensure_enabled(self) -> None:
        if is_feature_enabled(QUERY_API_FLAG):
            return
        raise_http_error(**feature_disabled_error(QUERY_API_FLAG))
