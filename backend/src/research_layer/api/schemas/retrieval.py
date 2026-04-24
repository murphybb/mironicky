from __future__ import annotations

from pydantic import BaseModel, Field

from research_layer.api.schemas.common import WorkspaceScopedBody
from research_layer.api.schemas.memory import MemoryRecallResponse
from research_layer.api.schemas.scholarly import (
    AuthoritySummaryResponse,
    EvidenceRefResponse,
)

RETRIEVAL_VIEW_VALUES = {
    "evidence",
    "contradiction",
    "failure_pattern",
    "validation_history",
    "hypothesis_support",
}
RETRIEVE_METHOD_VALUES = {"keyword", "vector", "hybrid", "logical"}


class RetrievalViewRequest(WorkspaceScopedBody):
    query: str = ""
    retrieve_method: str = Field(default="hybrid")
    top_k: int = Field(default=20, ge=1, le=100)
    metadata_filters: dict[str, object] = Field(default_factory=dict)


class RetrievalResultItem(BaseModel):
    result_id: str
    score: float
    title: str
    snippet: str
    source_ref: dict[str, object] = Field(default_factory=dict)
    graph_refs: dict[str, object] = Field(default_factory=dict)
    formal_refs: list[dict[str, str]] = Field(default_factory=list)
    supporting_refs: dict[str, object] = Field(default_factory=dict)
    trace_refs: dict[str, object] = Field(default_factory=dict)
    evidence_refs: list[EvidenceRefResponse] = Field(default_factory=list)
    # Backward-compatible extension: structured claim/span highlights for audit use.
    evidence_highlight_spans: list[dict[str, object]] = Field(default_factory=list)
    # Backward-compatible extension: relation/edge hit traces for mechanism reasoning.
    mechanism_relation_highlights: list[dict[str, object]] = Field(default_factory=list)
    authority_summary: AuthoritySummaryResponse = Field(
        default_factory=AuthoritySummaryResponse
    )


class RetrievalViewResponse(BaseModel):
    view_type: str
    workspace_id: str
    retrieve_method: str
    query_ref: dict[str, object] = Field(default_factory=dict)
    metadata_filter_refs: dict[str, object] = Field(default_factory=dict)
    total: int
    items: list[RetrievalResultItem] = Field(default_factory=list)
    memory_recall: MemoryRecallResponse | None = None
