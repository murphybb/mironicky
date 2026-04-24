from __future__ import annotations

from pydantic import BaseModel, Field


class CrossDocumentReportSummary(BaseModel):
    claim_count: int
    conflict_count: int
    source_recall_count: int
    route_count: int
    challenged_route_count: int = 0
    unresolved_gap_count: int = 0
    section_limits: dict[str, int] = Field(default_factory=dict)


class CrossDocumentReportSections(BaseModel):
    claims: list[dict[str, object]] = Field(default_factory=list)
    conflicts: list[dict[str, object]] = Field(default_factory=list)
    historical_recall: list[dict[str, object]] = Field(default_factory=list)
    routes: list[dict[str, object]] = Field(default_factory=list)
    challenged_routes: list[dict[str, object]] = Field(default_factory=list)
    unresolved_gaps: list[dict[str, object]] = Field(default_factory=list)


class CrossDocumentReportResponse(BaseModel):
    workspace_id: str
    summary: CrossDocumentReportSummary
    sections: CrossDocumentReportSections
    trace_refs: dict[str, object] = Field(default_factory=dict)
