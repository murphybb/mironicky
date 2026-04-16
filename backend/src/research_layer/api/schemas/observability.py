from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ExecutionTimelineEvent(BaseModel):
    event_name: str
    timestamp: datetime | None
    request_id: str | None
    job_id: str | None
    workspace_id: str | None
    source_id: str | None = None
    candidate_batch_id: str | None = None
    component: str
    step: str | None = None
    status: str
    refs: dict[str, object] = Field(default_factory=dict)
    metrics: dict[str, object] = Field(default_factory=dict)
    error: dict[str, object] | None = None


class ExecutionBusinessObjects(BaseModel):
    source_ids: list[str] = Field(default_factory=list)
    route_ids: list[str] = Field(default_factory=list)
    version_ids: list[str] = Field(default_factory=list)
    hypothesis_ids: list[str] = Field(default_factory=list)
    package_ids: list[str] = Field(default_factory=list)
    failure_ids: list[str] = Field(default_factory=list)
    candidate_batch_ids: list[str] = Field(default_factory=list)
    request_ids: list[str] = Field(default_factory=list)
    job_ids: list[str] = Field(default_factory=list)


class ExecutionFinalOutcome(BaseModel):
    status: str
    last_event: str | None = None
    last_status: str | None = None
    completed_event_count: int = 0
    failed_event_count: int = 0
    result_refs: list[dict[str, str]] = Field(default_factory=list)


class ExecutionSummaryResponse(BaseModel):
    workspace_id: str
    request_id: str | None = None
    job_id: str | None = None
    timeline: list[ExecutionTimelineEvent] = Field(default_factory=list)
    business_objects: ExecutionBusinessObjects
    final_outcome: ExecutionFinalOutcome
