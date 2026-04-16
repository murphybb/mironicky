from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from research_layer.api.schemas.common import WorkspaceScopedBody


class FactorBreakdownRecord(BaseModel):
    factor_name: str
    score_dimension: str
    normalized_value: float
    weight: float
    weighted_contribution: float
    status: str
    reason: str
    refs: dict[str, object] = Field(default_factory=dict)
    metrics: dict[str, object] = Field(default_factory=dict)
    explanation: str | None = None


class ScoreDimensionBreakdown(BaseModel):
    normalized_score: float
    score: float
    factors: list[FactorBreakdownRecord]


class NodeFactorContribution(BaseModel):
    factor_name: str
    score_dimension: str
    contribution: float


class NodeScoreBreakdownRecord(BaseModel):
    node_id: str
    node_type: str
    status: str
    object_ref_type: str
    object_ref_id: str
    support_contribution: float
    risk_contribution: float
    progressability_contribution: float
    total_contribution: float
    factor_contributions: list[NodeFactorContribution]


class RouteNodeRef(BaseModel):
    node_id: str
    node_type: str
    object_ref_type: str
    object_ref_id: str
    short_label: str
    status: str


class RouteRiskHint(BaseModel):
    node: RouteNodeRef
    hint: str


class RouteTraceRefs(BaseModel):
    version_id: str | None = None
    route_node_ids: list[str] = Field(default_factory=list)
    route_edge_ids: list[str] = Field(default_factory=list)
    conclusion_node_id: str | None = None


class RouteRecord(BaseModel):
    route_id: str
    workspace_id: str
    title: str
    summary: str
    status: str
    support_score: float
    risk_score: float
    progressability_score: float
    confidence_score: float
    confidence_grade: str
    novelty_level: str = "incremental"
    relation_tags: list[str] = Field(default_factory=list)
    top_factors: list[FactorBreakdownRecord] = Field(default_factory=list)
    score_breakdown: dict[str, ScoreDimensionBreakdown] = Field(default_factory=dict)
    node_score_breakdown: list[NodeScoreBreakdownRecord] = Field(default_factory=list)
    scoring_template_id: str | None = None
    scored_at: datetime | None = None
    conclusion: str = ""
    key_supports: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    next_validation_action: str = ""
    conclusion_node_id: str | None = None
    route_node_ids: list[str] = Field(default_factory=list)
    route_edge_ids: list[str] = Field(default_factory=list)
    key_support_node_ids: list[str] = Field(default_factory=list)
    key_assumption_node_ids: list[str] = Field(default_factory=list)
    risk_node_ids: list[str] = Field(default_factory=list)
    next_validation_node_id: str | None = None
    version_id: str | None = None
    summary_generation_mode: str = "llm"
    provider_backend: str | None = None
    provider_model: str | None = None
    request_id: str | None = None
    llm_response_id: str | None = None
    usage: dict[str, object] | None = None
    fallback_used: bool = False
    degraded: bool = False
    degraded_reason: str | None = None
    key_strengths: list[dict[str, object]] = Field(default_factory=list)
    key_risks: list[dict[str, object]] = Field(default_factory=list)
    open_questions: list[dict[str, object]] = Field(default_factory=list)
    rank: int | None = None


class RouteListResponse(BaseModel):
    items: list[RouteRecord]
    total: int


class RoutePreviewResponse(BaseModel):
    route_id: str
    workspace_id: str
    summary: str
    summary_generation_mode: str = "llm"
    degraded: bool = False
    provider_backend: str | None = None
    provider_model: str | None = None
    request_id: str | None = None
    llm_response_id: str | None = None
    usage: dict[str, object] | None = None
    fallback_used: bool = False
    degraded_reason: str | None = None
    key_strengths: list[dict[str, object]] = Field(default_factory=list)
    key_risks: list[dict[str, object]] = Field(default_factory=list)
    open_questions: list[dict[str, object]] = Field(default_factory=list)
    conclusion_node: RouteNodeRef
    key_support_evidence: list[RouteNodeRef] = Field(default_factory=list)
    key_assumptions: list[RouteNodeRef] = Field(default_factory=list)
    conflict_failure_hints: list[RouteRiskHint] = Field(default_factory=list)
    next_validation_action: str
    top_factors: list[FactorBreakdownRecord] = Field(default_factory=list)
    trace_refs: RouteTraceRefs = Field(default_factory=RouteTraceRefs)


class RouteRecomputeRequest(WorkspaceScopedBody):
    failure_id: str | None = Field(default=None, min_length=1)
    reason: str = Field(min_length=1, max_length=256)
    async_mode: bool = True


class RouteGenerateRequest(WorkspaceScopedBody):
    reason: str = Field(min_length=1, max_length=256)
    max_candidates: int = Field(default=8, ge=1, le=20)


class RouteGenerateResponse(BaseModel):
    workspace_id: str
    generated_count: int
    ranked_route_ids: list[str]
    top_route_id: str | None = None


class RouteScoreRequest(WorkspaceScopedBody):
    template_id: str | None = None
    focus_node_ids: list[str] = Field(default_factory=list)


class RouteScoreResponse(RouteRecord):
    pass
