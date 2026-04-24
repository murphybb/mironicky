from __future__ import annotations

from pydantic import BaseModel, Field


class IdSample(BaseModel):
    total: int
    items: list[str] = Field(default_factory=list)
    truncated: bool


class CompactMappingSummary(BaseModel):
    keys: list[str] = Field(default_factory=list)
    total_keys: int = 0
    truncated: bool = False


class SectionLimits(BaseModel):
    claims: int
    conflicts: int
    historical_recall: int
    routes: int
    challenged_routes: int
    unresolved_gaps: int


class SourceSpan(BaseModel):
    start: int | None = None
    end: int | None = None


class ClaimRefItem(BaseModel):
    claim_id: str | None = None


class ClaimReportItem(BaseModel):
    claim_id: str
    source_id: str
    candidate_id: str
    claim_type: str
    semantic_type: str | None = None
    text: str
    normalized_text: str
    status: str
    source_span: SourceSpan = Field(default_factory=SourceSpan)
    trace_summary: CompactMappingSummary = Field(default_factory=CompactMappingSummary)
    memory_summary: CompactMappingSummary = Field(default_factory=CompactMappingSummary)


class ConflictReportItem(BaseModel):
    conflict_id: str
    new_claim_id: str
    existing_claim_id: str
    conflict_type: str
    status: str
    evidence: dict[str, object] = Field(default_factory=dict)
    source_ref: dict[str, object] = Field(default_factory=dict)
    decision_note: str | None = None
    created_request_id: str | None = None
    resolved_request_id: str | None = None


class HistoricalRecallMemoryItem(BaseModel):
    memory_id: str | None = None
    memory_type: str | None = None
    score: float | None = None
    title: str | None = None
    snippet: str | None = None
    linked_claim_refs: list[ClaimRefItem] = Field(default_factory=list)
    source_ref: dict[str, object] = Field(default_factory=dict)


class HistoricalRecallItem(BaseModel):
    recall_id: str
    source_id: str
    status: str
    reason: str | None = None
    requested_method: str | None = None
    applied_method: str | None = None
    query_text: str
    total: int
    item_total: int
    items: list[HistoricalRecallMemoryItem] = Field(default_factory=list)
    items_truncated: bool
    trace_refs: CompactMappingSummary = Field(default_factory=CompactMappingSummary)
    error: dict[str, object] | None = None
    request_id: str | None = None


class RouteReportItem(BaseModel):
    route_id: str
    title: str
    summary: str
    status: str
    conclusion: str = ""
    claim_ids: list[str] = Field(default_factory=list)
    route_node_ids: IdSample
    route_edge_ids: IdSample
    version_id: str | None = None
    request_id: str | None = None


class ChallengeRefs(BaseModel):
    conflict_count: int
    conflict_ids: IdSample


class ChallengedRouteItem(BaseModel):
    route_id: str
    title: str
    summary: str
    status: str
    claim_ids: list[str] = Field(default_factory=list)
    route_node_ids: IdSample
    route_edge_ids: IdSample
    challenge_status: str
    challenge_refs: ChallengeRefs


class UnresolvedGapItem(BaseModel):
    gap_type: str
    status: str
    conflict_id: str | None = None
    claim_ids: list[str] = Field(default_factory=list)
    recall_id: str | None = None
    source_id: str | None = None
    reason: str | None = None
    route_id: str | None = None
    conflict_ids: IdSample | None = None


class CrossDocumentReportSummary(BaseModel):
    claim_count: int
    conflict_count: int
    source_recall_count: int
    route_count: int
    challenged_route_count: int = 0
    unresolved_gap_count: int = 0
    section_limits: SectionLimits


class CrossDocumentReportSections(BaseModel):
    claims: list[ClaimReportItem] = Field(default_factory=list)
    conflicts: list[ConflictReportItem] = Field(default_factory=list)
    historical_recall: list[HistoricalRecallItem] = Field(default_factory=list)
    routes: list[RouteReportItem] = Field(default_factory=list)
    challenged_routes: list[ChallengedRouteItem] = Field(default_factory=list)
    unresolved_gaps: list[UnresolvedGapItem] = Field(default_factory=list)


class CrossDocumentReportTraceRefs(BaseModel):
    request_id: str
    claim_ids: IdSample
    conflict_ids: IdSample
    source_recall_ids: IdSample
    route_ids: IdSample


class CrossDocumentReportResponse(BaseModel):
    workspace_id: str
    summary: CrossDocumentReportSummary
    sections: CrossDocumentReportSections
    trace_refs: CrossDocumentReportTraceRefs
