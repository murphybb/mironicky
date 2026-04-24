from __future__ import annotations

from fastapi import Request

from core.di.decorators import controller
from core.interface.controller.base_controller import BaseController, get
from research_layer.api.controllers._state_store import STORE
from research_layer.api.controllers._utils import get_request_id, validate_workspace_id
from research_layer.api.schemas.common import ErrorResponse
from research_layer.services.cross_document_report_service import (
    CrossDocumentReportService,
)


@controller(name="research_cross_document_report_controller")
class ResearchCrossDocumentReportController(BaseController):
    def __init__(self) -> None:
        super().__init__(
            prefix="/api/v1/research",
            tags=["Research Reports"],
            default_auth="none",
        )
        self._service = CrossDocumentReportService(STORE)

    @get(
        "/reports/{workspace_id}/cross-document",
        responses={400: {"model": ErrorResponse}},
    )
    async def get_cross_document_report(
        self, workspace_id: str, request: Request
    ) -> dict[str, object]:
        workspace = validate_workspace_id(workspace_id)
        return self._service.build(
            workspace_id=workspace,
            request_id=get_request_id(request.headers.get("x-request-id")),
        )
