from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from research_layer.api.schemas.common import WorkspaceScopedBody


class ClaimConflictRecord(BaseModel):
    conflict_id: str
    workspace_id: str
    new_claim_id: str
    existing_claim_id: str
    conflict_type: str
    status: str
    evidence: dict[str, object] = Field(default_factory=dict)
    source_ref: dict[str, object] = Field(default_factory=dict)
    decision_note: str | None = None
    created_request_id: str | None = None
    resolved_request_id: str | None = None
    created_at: datetime
    updated_at: datetime


class ClaimConflictListResponse(BaseModel):
    items: list[ClaimConflictRecord]


class ClaimConflictUpdateRequest(WorkspaceScopedBody):
    status: str = Field(pattern=r"^(needs_review|accepted|rejected|resolved)$")
    decision_note: str | None = None
