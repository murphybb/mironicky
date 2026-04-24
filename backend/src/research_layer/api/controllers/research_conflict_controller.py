from __future__ import annotations

from fastapi import Request

from core.di.decorators import controller
from core.interface.controller.base_controller import BaseController, get, patch
from research_layer.api.controllers._state_store import STORE
from research_layer.api.controllers._utils import (
    get_request_id,
    parse_request_model,
    raise_http_error,
    validate_workspace_id,
)
from research_layer.api.schemas.claim_conflict import (
    ClaimConflictListResponse,
    ClaimConflictRecord,
    ClaimConflictUpdateRequest,
)
from research_layer.api.schemas.common import ErrorResponse, ResearchErrorCode


@controller(name="research_conflict_controller")
class ResearchConflictController(BaseController):
    def __init__(self) -> None:
        super().__init__(
            prefix="/api/v1/research",
            tags=["Research Conflicts"],
            default_auth="none",
        )

    @get(
        "/conflicts/{workspace_id}",
        response_model=ClaimConflictListResponse,
        responses={400: {"model": ErrorResponse}},
    )
    async def list_conflicts(self, workspace_id: str) -> ClaimConflictListResponse:
        workspace = validate_workspace_id(workspace_id)
        items = [
            ClaimConflictRecord.model_validate(item)
            for item in STORE.list_claim_conflicts(workspace_id=workspace)
        ]
        return ClaimConflictListResponse(items=items)

    @patch(
        "/conflicts/{conflict_id}",
        response_model=ClaimConflictRecord,
        responses={
            400: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
        },
    )
    async def update_conflict(
        self, conflict_id: str, request: Request
    ) -> ClaimConflictRecord:
        payload = await parse_request_model(request, ClaimConflictUpdateRequest)
        request_id = get_request_id(request.headers.get("x-request-id"))
        updated = STORE.update_claim_conflict_status(
            conflict_id=conflict_id,
            workspace_id=payload.workspace_id,
            status=payload.status,
            decision_note=payload.decision_note,
            resolved_request_id=request_id,
        )
        if updated is None:
            raise_http_error(
                status_code=404,
                code=ResearchErrorCode.NOT_FOUND.value,
                message="claim conflict not found",
                details={
                    "conflict_id": conflict_id,
                    "workspace_id": payload.workspace_id,
                },
            )
        return ClaimConflictRecord.model_validate(updated)
