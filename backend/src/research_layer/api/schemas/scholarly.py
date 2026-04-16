from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from research_layer.api.schemas.common import WorkspaceScopedBody


class ScholarlyLookupRequest(WorkspaceScopedBody):
    force_refresh: bool = False


class ScholarlyProviderTrace(BaseModel):
    provider_name: str
    cache_hit: bool = False
    request_id: str | None = None
    request_url: str | None = None
    http_status: int | None = None


class ScholarlyCacheRecordResponse(BaseModel):
    cache_id: str
    normalized_query: str
    provider_name: str
    provider_record_id: str
    title: str
    doi: str | None = None
    url: str | None = None
    venue: str | None = None
    publication_year: int | None = None
    authors: list[str] = Field(default_factory=list)
    abstract_excerpt: str | None = None
    authority_tier: str
    authority_score: float
    metadata: dict[str, object] = Field(default_factory=dict)
    created_at: datetime


class SourceScholarlyLookupResponse(BaseModel):
    source_id: str
    workspace_id: str
    query: str
    cache_hit: bool
    provider_trace: list[ScholarlyProviderTrace] = Field(default_factory=list)
    cache_records: list[ScholarlyCacheRecordResponse] = Field(default_factory=list)
    source_metadata: dict[str, object] = Field(default_factory=dict)


class EvidenceRefResponse(BaseModel):
    ref_id: str
    workspace_id: str
    source_id: str
    object_type: str
    object_id: str
    ref_type: str
    layer: str
    title: str
    doi: str | None = None
    url: str | None = None
    venue: str | None = None
    publication_year: int | None = None
    authors: list[str] = Field(default_factory=list)
    excerpt: str
    locator: dict[str, object] = Field(default_factory=dict)
    authority_score: float
    authority_tier: str
    metadata: dict[str, object] = Field(default_factory=dict)
    confirmed_at: datetime | None = None
    created_at: datetime


class AuthoritySummaryResponse(BaseModel):
    top_authority_tier: str | None = None
    mean_authority_score: float = 0.0
    source_count: int = 0
