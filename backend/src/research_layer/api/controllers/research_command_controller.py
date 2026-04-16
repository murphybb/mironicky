from __future__ import annotations

from fastapi import Request

from core.di.decorators import controller
from core.interface.controller.base_controller import BaseController, post
from research_layer.api.controllers._state_store import STORE
from research_layer.api.controllers._utils import (
    get_request_id,
    parse_request_model,
    raise_http_error,
    validate_workspace_id,
)
from research_layer.api.schemas.command import (
    ResearchCommandRunRequest,
    ResearchCommandRunResponse,
)
from research_layer.api.schemas.common import ErrorResponse
from research_layer.config.feature_flags import (
    COMMANDS_FLAG,
    feature_disabled_error,
    is_feature_enabled,
)
from research_layer.services.research_command_service import ResearchCommandService


@controller(name="research_command_controller")
class ResearchCommandController(BaseController):
    def __init__(self) -> None:
        super().__init__(
            prefix="/api/v1/research", tags=["Research Commands"], default_auth="none"
        )
        self._command_service = ResearchCommandService(STORE)

    @post(
        "/commands/run",
        response_model=ResearchCommandRunResponse,
        responses={400: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    )
    async def run_commands(self, request: Request) -> ResearchCommandRunResponse:
        if not is_feature_enabled(COMMANDS_FLAG):
            raise_http_error(**feature_disabled_error(COMMANDS_FLAG))
        payload = await parse_request_model(request, ResearchCommandRunRequest)
        request_id = get_request_id(request.headers.get("x-request-id"))
        workspace = validate_workspace_id(payload.workspace_id)
        result = await self._command_service.run(
            workspace_id=workspace,
            commands=[item.model_dump() for item in payload.commands],
            request_id=request_id,
        )
        return ResearchCommandRunResponse.model_validate(result)
