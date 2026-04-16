from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from research_layer.api.schemas.common import WorkspaceScopedBody


class FailureTargetRef(BaseModel):
    target_type: str = Field(pattern=r"^(node|edge)$")
    target_id: str = Field(min_length=1)


class FailureCreateRequest(WorkspaceScopedBody):
    attached_targets: list[FailureTargetRef] = Field(min_length=1)
    observed_outcome: str = Field(min_length=1)
    expected_difference: str = Field(min_length=1)
    failure_reason: str = Field(min_length=1)
    severity: Literal["low", "medium", "high", "critical"]
    reporter: str = Field(min_length=1)


class FailureResponse(BaseModel):
    failure_id: str
    workspace_id: str
    attached_targets: list[FailureTargetRef]
    observed_outcome: str
    expected_difference: str
    failure_reason: str
    severity: str
    reporter: str
    created_at: datetime
    impact_summary: dict[str, object] = Field(default_factory=dict)
    impact_updated_at: datetime | None = None
    derived_from_validation_id: str | None = None
    derived_from_validation_result_id: str | None = None


class ValidationCreateRequest(WorkspaceScopedBody):
    target_object: str = Field(min_length=1)
    method: str = Field(min_length=1)
    success_signal: str = Field(min_length=1)
    weakening_signal: str = Field(min_length=1)


class ValidationResponse(BaseModel):
    validation_id: str
    workspace_id: str
    target_object: str
    method: str
    success_signal: str
    weakening_signal: str
    status: str = "pending"
    latest_outcome: str | None = None
    latest_result_id: str | None = None
    updated_at: datetime | None = None


class ValidationResultSubmitRequest(WorkspaceScopedBody):
    outcome: Literal["validated", "weakened", "failed"]
    note: str | None = None
    target_type: str | None = Field(default=None, pattern=r"^(route|node|edge)$")
    target_id: str | None = Field(default=None, min_length=1)
    reporter: str = Field(default="validation_feedback", min_length=1, max_length=64)


class ValidationResultResponse(BaseModel):
    result_id: str
    validation_id: str
    workspace_id: str
    outcome: str
    target_type: str | None = None
    target_id: str | None = None
    note: str | None = None
    request_id: str | None = None
    triggered_failure_id: str | None = None
    recompute_job_id: str | None = None
    created_at: datetime
    triggered_failure: FailureResponse | None = None
