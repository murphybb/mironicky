from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from research_layer.api.schemas.common import WorkspaceScopedBody
from research_layer.api.schemas.memory import MemoryRecallResponse


class GraphNodeCreateRequest(WorkspaceScopedBody):
    node_type: str = Field(min_length=1)
    object_ref_type: str = Field(min_length=1)
    object_ref_id: str = Field(min_length=1)
    short_label: str = Field(min_length=1, max_length=128)
    full_description: str = Field(min_length=1)
    claim_id: str | None = Field(default=None)
    short_tags: list[str] = Field(default_factory=list)
    visibility: str = Field(default="workspace", pattern=r"^(private|workspace|package_public)$")
    source_refs: list[dict[str, object]] = Field(default_factory=list)


class GraphNodePatchRequest(WorkspaceScopedBody):
    short_label: str | None = Field(default=None, min_length=1, max_length=128)
    full_description: str | None = Field(default=None, min_length=1)
    short_tags: list[str] | None = None
    visibility: str | None = Field(default=None, pattern=r"^(private|workspace|package_public)$")
    source_refs: list[dict[str, object]] | None = None
    status: str | None = Field(default=None, min_length=1)


class GraphNodeResponse(BaseModel):
    node_id: str
    workspace_id: str
    node_type: str
    object_ref_type: str
    object_ref_id: str
    short_label: str
    full_description: str
    short_tags: list[str] = Field(default_factory=list)
    visibility: str = "workspace"
    source_refs: list[dict[str, object]] = Field(default_factory=list)
    claim_id: str | None = None
    source_ref: dict[str, object] = Field(default_factory=dict)
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class GraphEdgeCreateRequest(WorkspaceScopedBody):
    source_node_id: str = Field(min_length=1)
    target_node_id: str = Field(min_length=1)
    edge_type: str = Field(min_length=1)
    object_ref_type: str = Field(min_length=1)
    object_ref_id: str = Field(min_length=1)
    strength: float = Field(ge=0.0, le=1.0)
    claim_id: str | None = Field(default=None)


class GraphEdgePatchRequest(WorkspaceScopedBody):
    status: str | None = Field(default=None, min_length=1)
    strength: float | None = Field(default=None, ge=0.0, le=1.0)


class GraphArchiveRequest(WorkspaceScopedBody):
    reason: str | None = Field(default=None, min_length=1, max_length=512)


class GraphEdgeResponse(BaseModel):
    edge_id: str
    workspace_id: str
    source_node_id: str
    target_node_id: str
    edge_type: str
    object_ref_type: str
    object_ref_id: str
    strength: float
    claim_id: str | None = None
    source_ref: dict[str, object] = Field(default_factory=dict)
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class GraphResponse(BaseModel):
    workspace_id: str
    nodes: list[GraphNodeResponse]
    edges: list[GraphEdgeResponse]
    memory_recall: MemoryRecallResponse | None = None


class GraphBuildResponse(BaseModel):
    workspace_id: str
    version_id: str
    node_count: int
    edge_count: int


class GraphWorkspaceResponse(BaseModel):
    workspace_id: str
    latest_version_id: str | None = None
    status: str
    node_count: int
    edge_count: int
    updated_at: datetime | None = None


class GraphQueryRequest(BaseModel):
    center_node_id: str | None = Field(default=None, min_length=1)
    max_hops: int = Field(default=1, ge=1, le=5)


class GraphSupportChainsRequest(WorkspaceScopedBody):
    conclusion_node_id: str = Field(min_length=1)
    max_chains: int = Field(default=5, ge=1, le=20)


class GraphPredictedLinksRequest(WorkspaceScopedBody):
    node_id: str = Field(min_length=1)
    top_k: int = Field(default=8, ge=1, le=50)


class GraphDeepChainsRequest(WorkspaceScopedBody):
    node_id: str = Field(min_length=1)
    max_chains: int = Field(default=5, ge=1, le=20)


class GraphVersionRecord(BaseModel):
    version_id: str
    workspace_id: str
    trigger_type: str
    change_summary: str
    created_at: datetime | None = None
    request_id: str | None = None


class GraphVersionListResponse(BaseModel):
    items: list[GraphVersionRecord]
    total: int


class GraphVersionDiffResponse(BaseModel):
    version_id: str
    workspace_id: str
    diff_payload: dict[str, object]


class GraphArchiveResponse(BaseModel):
    workspace_id: str
    target_type: str
    target_id: str
    status: str
    version_id: str
    diff_payload: dict[str, object]


class GraphReportResponse(BaseModel):
    workspace_id: str
    summary: dict[str, object]
    top_nodes: list[dict[str, object]]
    risk_nodes: list[dict[str, object]]
    dangling_nodes: list[dict[str, object]]
    unvalidated_assumptions: list[dict[str, object]]
    trace_refs: dict[str, object]
