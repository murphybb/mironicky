from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from research_layer.api.schemas.common import WorkspaceScopedBody


class PackageCreateRequest(WorkspaceScopedBody):
    title: str = Field(min_length=1, max_length=256)
    summary: str = Field(min_length=1)
    included_route_ids: list[str] = Field(default_factory=list)
    included_node_ids: list[str] = Field(default_factory=list)
    included_validation_ids: list[str] = Field(default_factory=list)


class PackagePublishRequest(WorkspaceScopedBody):
    async_mode: bool = True


class PrivateDependencyFlagRecord(BaseModel):
    private_node_id: str
    private_object_ref: dict[str, str]
    reason: str
    referenced_by_route_ids: list[str]
    replacement_gap_node_id: str


class PublicGapNodeRecord(BaseModel):
    node_id: str
    workspace_id: str
    node_type: str
    object_ref_type: str
    object_ref_id: str
    short_label: str
    full_description: str
    status: str
    trace_refs: dict[str, object] = Field(default_factory=dict)


class PackageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    package_id: str
    workspace_id: str
    title: str
    summary: str
    included_route_ids: list[str]
    included_node_ids: list[str]
    included_validation_ids: list[str]
    status: str
    snapshot_type: str
    snapshot_version: str
    private_dependency_flags: list[PrivateDependencyFlagRecord]
    public_gap_nodes: list[PublicGapNodeRecord]
    boundary_notes: list[str]
    traceability_refs: dict[str, object]
    replay_ready: bool
    build_request_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    published_at: datetime | None = None


class PackageListResponse(BaseModel):
    items: list[PackageResponse]
    total: int


class PackageReplayResponse(BaseModel):
    package_id: str
    workspace_id: str
    snapshot: dict[str, object]


class PackagePublishResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    publish_result_id: str
    package_id: str
    workspace_id: str
    snapshot_type: str
    snapshot_version: str
    boundary_notes: list[str]
    snapshot_payload: dict[str, object]
    published_at: datetime
    request_id: str | None = None
