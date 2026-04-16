from __future__ import annotations

from pydantic import BaseModel, Field

from research_layer.api.schemas.common import WorkspaceScopedBody


class ResearchCommandRequestItem(BaseModel):
    name: str = Field(min_length=1)
    args: dict[str, object] = Field(default_factory=dict)


class ResearchCommandRunRequest(WorkspaceScopedBody):
    commands: list[ResearchCommandRequestItem] = Field(min_length=1)


class ResearchCommandStepResponse(BaseModel):
    index: int
    name: str
    status: str
    resource_refs: list[dict[str, object]] = Field(default_factory=list)
    job_refs: list[dict[str, object]] = Field(default_factory=list)
    result: dict[str, object] = Field(default_factory=dict)
    error: dict[str, object] | None = None


class ResearchCommandRunResponse(BaseModel):
    workspace_id: str
    status: str
    steps: list[ResearchCommandStepResponse]
