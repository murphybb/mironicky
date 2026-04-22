from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from research_layer.api.schemas.common import WorkspaceScopedBody

HYPOTHESIS_STATUS_PATTERN = r"^(candidate|deferred|promoted_for_validation|rejected)$"
HYPOTHESIS_POOL_STATUS_PATTERN = (
    r"^(queued|running|paused|stopping|stopped|finalizing|finalized|failed|cancelled)$"
)
HYPOTHESIS_CANDIDATE_STATUS_PATTERN = r"^(alive|pruned|finalized|rejected)$"
HYPOTHESIS_ROUND_STATUS_PATTERN = (
    r"^(running|completed|failed|cancelled)$"
)


class HypothesisActiveRetrievalConfig(BaseModel):
    enabled: bool = True
    max_papers_per_burst: int = Field(default=3, ge=1, le=10)
    max_bursts: int = Field(default=2, ge=0, le=10)


class HypothesisTriggerRecord(BaseModel):
    trigger_id: str
    trigger_type: str = Field(pattern=r"^(gap|conflict|failure|weak_support)$")
    workspace_id: str
    object_ref_type: str
    object_ref_id: str
    summary: str
    trace_refs: dict[str, object] = Field(default_factory=dict)
    related_object_ids: list[dict[str, str]] = Field(default_factory=list)
    metrics: dict[str, object] = Field(default_factory=dict)


class HypothesisTriggerListResponse(BaseModel):
    items: list[HypothesisTriggerRecord]
    total: int


class HypothesisListResponse(BaseModel):
    items: list["HypothesisResponse"]
    total: int


class HypothesisGenerateRequest(WorkspaceScopedBody):
    trigger_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    async_mode: bool = True
    mode: str = Field(
        default="single_candidate",
        pattern=r"^(single_candidate|multi_agent_pool|literature_frontier)$",
    )
    research_goal: str = ""
    top_k: int = Field(default=3, ge=1, le=10)
    max_rounds: int = Field(default=3, ge=1, le=20)
    candidate_count: int = Field(default=8, ge=2, le=30)
    frontier_size: int = Field(default=3, ge=3, le=5)
    active_retrieval: HypothesisActiveRetrievalConfig = Field(
        default_factory=HypothesisActiveRetrievalConfig
    )
    constraints: dict[str, object] = Field(default_factory=dict)
    preference_profile: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_mode_inputs(self) -> "HypothesisGenerateRequest":
        if self.mode == "literature_frontier":
            if not self.source_ids:
                raise ValueError(
                    "source_ids must not be empty when mode is literature_frontier"
                )
            if any(not str(source_id).strip() for source_id in self.source_ids):
                raise ValueError(
                    "source_ids must not contain blank entries when mode is literature_frontier"
                )
            if not str(self.research_goal).strip():
                raise ValueError(
                    "research_goal must not be empty when mode is literature_frontier"
                )
            return self
        if not self.trigger_ids:
            raise ValueError("trigger_ids must not be empty for trigger-driven modes")
        return self


class HypothesisPoolRoundRequest(WorkspaceScopedBody):
    async_mode: bool = True
    max_matches: int = Field(default=12, ge=1, le=200)


class HypothesisPoolFinalizeRequest(WorkspaceScopedBody):
    async_mode: bool = True


class HypothesisPoolControlRequest(WorkspaceScopedBody):
    action: str = Field(
        pattern=r"^(pause|resume|stop|force_finalize|disable_retrieval|add_sources)$"
    )
    source_ids: list[str] = Field(default_factory=list)


class HypothesisCandidatePatchRequest(WorkspaceScopedBody):
    reasoning_chain: dict[str, object] = Field(default_factory=dict)
    reset_review_state: bool = True


class HypothesisDecisionRequest(WorkspaceScopedBody):
    note: str = Field(min_length=1, max_length=256)
    decision_source_type: str = Field(min_length=1, max_length=64)
    decision_source_ref: str = Field(min_length=1, max_length=128)


class HypothesisRelatedObject(BaseModel):
    object_type: str
    object_id: str


class HypothesisValidationAction(BaseModel):
    validation_id: str
    target_object: str
    method: str
    success_signal: str
    weakening_signal: str
    cost_level: str
    time_level: str


class HypothesisWeakeningSignal(BaseModel):
    signal_type: str
    signal_text: str
    severity_hint: str
    trace_refs: dict[str, object] = Field(default_factory=dict)


class HypothesisResponse(BaseModel):
    hypothesis_id: str
    workspace_id: str
    statement: str = ""
    title: str
    summary: str
    premise: str
    rationale: str
    testability_hint: str = ""
    novelty_hint: str = ""
    suggested_next_steps: list[str] = Field(default_factory=list)
    confidence_hint: float | None = None
    status: str = Field(pattern=HYPOTHESIS_STATUS_PATTERN)
    stage: str
    trigger_object_ids: list[str] = Field(default_factory=list)
    trigger_refs: list[HypothesisTriggerRecord] = Field(default_factory=list)
    related_object_ids: list[HypothesisRelatedObject] = Field(default_factory=list)
    novelty_typing: str
    minimum_validation_action: HypothesisValidationAction
    weakening_signal: HypothesisWeakeningSignal
    decision_note: str | None = None
    decision_source_type: str | None = None
    decision_source_ref: str | None = None
    decided_at: datetime | None = None
    decided_request_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    generation_job_id: str | None = None
    provider_backend: str | None = None
    provider_model: str | None = None
    request_id: str | None = None
    llm_response_id: str | None = None
    usage: dict[str, object] | None = None
    fallback_used: bool = False
    degraded: bool = False
    degraded_reason: str | None = None
    source_pool_id: str | None = None
    source_candidate_id: str | None = None
    source_round_id: str | None = None
    finalizing_match_id: str | None = None
    search_tree_node_id: str | None = None
    reasoning_chain_id: str | None = None
    weakest_step_ref: dict[str, object] = Field(default_factory=dict)


class HypothesisPoolResponse(BaseModel):
    pool_id: str
    workspace_id: str
    status: str = Field(pattern=HYPOTHESIS_POOL_STATUS_PATTERN)
    orchestration_mode: str
    trigger_refs: list[HypothesisTriggerRecord] = Field(default_factory=list)
    top_k: int
    max_rounds: int
    candidate_count: int
    current_round_number: int
    research_goal: str
    reasoning_subgraph: dict[str, object] = Field(default_factory=dict)
    constraints: dict[str, object] = Field(default_factory=dict)
    preference_profile: dict[str, object] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class HypothesisPoolListResponse(BaseModel):
    items: list[HypothesisPoolResponse]
    total: int


class HypothesisCandidateResponse(BaseModel):
    candidate_id: str
    pool_id: str
    workspace_id: str
    title: str
    statement: str
    summary: str
    rationale: str
    trigger_refs: list[HypothesisTriggerRecord] = Field(default_factory=list)
    related_object_ids: list[HypothesisRelatedObject] = Field(default_factory=list)
    reasoning_chain: dict[str, object] = Field(default_factory=dict)
    minimum_validation_action: HypothesisValidationAction
    weakening_signal: HypothesisWeakeningSignal
    novelty_typing: str
    status: str = Field(pattern=HYPOTHESIS_CANDIDATE_STATUS_PATTERN)
    origin_type: str
    origin_round_number: int
    elo_rating: float
    survival_score: float
    lineage: dict[str, object] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class HypothesisCandidateListResponse(BaseModel):
    items: list[HypothesisCandidateResponse]
    total: int


class HypothesisRoundResponse(BaseModel):
    round_id: str
    pool_id: str
    round_number: int
    status: str = Field(pattern=HYPOTHESIS_ROUND_STATUS_PATTERN)
    start_reason: str
    stop_reason: str | None = None
    generation_count: int
    review_count: int
    match_count: int
    evolution_count: int
    meta_review_id: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None


class HypothesisRoundListResponse(BaseModel):
    items: list[HypothesisRoundResponse]
    total: int


class HypothesisMatchResponse(BaseModel):
    match_id: str
    pool_id: str
    round_id: str
    left_candidate_id: str
    right_candidate_id: str
    winner_candidate_id: str
    loser_candidate_id: str
    match_reason: str
    compare_vector: dict[str, object] = Field(default_factory=dict)
    left_elo_before: float
    right_elo_before: float
    left_elo_after: float
    right_elo_after: float
    judge_trace: dict[str, object] = Field(default_factory=dict)
    created_at: datetime | None = None


class HypothesisSearchTreeNodeResponse(BaseModel):
    tree_node_id: str
    pool_id: str
    parent_tree_node_id: str | None = None
    candidate_id: str | None = None
    node_role: str
    depth: int
    visits: int
    mean_reward: float
    uct_score: float
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    child_edges: list[dict[str, object]] = Field(default_factory=list)
