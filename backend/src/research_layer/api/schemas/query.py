from __future__ import annotations

from pydantic import BaseModel, Field

from research_layer.api.schemas.common import WorkspaceScopedBody


class QueryToolRecord(BaseModel):
    name: str
    description: str


class QueryToolsResponse(BaseModel):
    tools: list[QueryToolRecord]


class QueryRunRequest(WorkspaceScopedBody):
    tool_name: str = Field(min_length=1)
    arguments: dict[str, object] = Field(default_factory=dict)


class QueryRunResponse(BaseModel):
    workspace_id: str
    tool_name: str
    result: dict[str, object]
