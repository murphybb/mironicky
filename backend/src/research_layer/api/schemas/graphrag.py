from __future__ import annotations

from pydantic import BaseModel, Field

from research_layer.api.schemas.common import WorkspaceScopedBody
from research_layer.api.schemas.memory import MemoryRecallResponse


class GraphRAGQueryRequest(WorkspaceScopedBody):
    question: str = Field(min_length=1)
    limit: int = Field(default=8, ge=1, le=25)


class GraphRAGCitation(BaseModel):
    claim_id: str
    text: str
    source_ref: dict[str, object] = Field(default_factory=dict)
    score: float
    graph_refs: dict[str, object] = Field(default_factory=dict)
    source_artifact_refs: list[dict[str, object]] = Field(default_factory=list)
    retrieval_result_id: str | None = None
    view_type: str | None = None
    formal_refs: list[dict[str, str]] = Field(default_factory=list)
    trace_refs: dict[str, object] = Field(default_factory=dict)


class GraphRAGQueryResponse(BaseModel):
    workspace_id: str
    question: str
    answer: str
    citations: list[GraphRAGCitation] = Field(default_factory=list)
    memory_recall: MemoryRecallResponse
    trace_refs: dict[str, object] = Field(default_factory=dict)
