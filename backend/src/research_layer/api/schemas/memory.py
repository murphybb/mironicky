from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from research_layer.api.schemas.common import WorkspaceScopedBody
from research_layer.api.schemas.hypothesis import HypothesisResponse
from research_layer.api.schemas.retrieval import RETRIEVAL_VIEW_VALUES, RETRIEVE_METHOD_VALUES


class MemoryListRequest(WorkspaceScopedBody):
    view_types: list[str] = Field(
        default_factory=lambda: sorted(RETRIEVAL_VIEW_VALUES),
        min_length=1,
    )
    query: str = ""
    retrieve_method: str = Field(default="hybrid")
    top_k_per_view: int = Field(default=20, ge=1, le=100)
    metadata_filters_by_view: dict[str, dict[str, object]] = Field(default_factory=dict)


class MemoryRetrievalContext(BaseModel):
    view_type: str
    retrieve_method: str
    query_ref: dict[str, object] = Field(default_factory=dict)
    metadata_filter_refs: dict[str, object] = Field(default_factory=dict)


class MemoryRecord(BaseModel):
    read_model_kind: str = "retrieval_backed"
    memory_id: str
    memory_view_type: str
    score: float
    title: str
    snippet: str
    source_ref: dict[str, object] = Field(default_factory=dict)
    graph_refs: dict[str, object] = Field(default_factory=dict)
    formal_refs: list[dict[str, str]] = Field(default_factory=list)
    supporting_refs: dict[str, object] = Field(default_factory=dict)
    trace_refs: dict[str, object] = Field(default_factory=dict)
    retrieval_context: MemoryRetrievalContext


class MemoryListResponse(BaseModel):
    read_model_kind: str = "retrieval_backed_read_model"
    workspace_id: str
    controlled_action_semantics: dict[str, str] = Field(default_factory=dict)
    tool_capability_refs: dict[str, object] = Field(default_factory=dict)
    total: int
    items: list[MemoryRecord] = Field(default_factory=list)


class MemoryActionRequestBase(WorkspaceScopedBody):
    memory_id: str = Field(min_length=1)
    memory_view_type: str = Field(min_length=1)
    note: str | None = Field(default=None, max_length=256)


class MemoryBindToCurrentRouteRequest(MemoryActionRequestBase):
    route_id: str = Field(min_length=1)


class MemoryValidationAction(BaseModel):
    validation_id: str
    target_object: str
    method: str
    success_signal: str
    weakening_signal: str


class MemoryBindToCurrentRouteResponse(BaseModel):
    action_id: str
    action_type: str
    workspace_id: str
    route_id: str
    memory_id: str
    memory_view_type: str
    binding_status: str
    validation_action: MemoryValidationAction
    trace_refs: dict[str, object] = Field(default_factory=dict)
    note: str | None = None
    created_at: datetime


class MemoryToHypothesisCandidateRequest(MemoryActionRequestBase):
    pass


class MemoryToHypothesisCandidateResponse(BaseModel):
    action_id: str
    action_type: str
    workspace_id: str
    memory_id: str
    memory_view_type: str
    hypothesis: HypothesisResponse
    trace_refs: dict[str, object] = Field(default_factory=dict)
    note: str | None = None
    created_at: datetime


def validate_memory_view_type(value: str) -> str:
    normalized = str(value).strip()
    if normalized not in RETRIEVAL_VIEW_VALUES:
        raise ValueError(f"unsupported memory view_type: {value}")
    return normalized


def validate_retrieve_method(value: str) -> str:
    normalized = str(value).strip().lower()
    if normalized not in RETRIEVE_METHOD_VALUES:
        raise ValueError(f"unsupported retrieve_method: {value}")
    return normalized
