from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from research_layer.domain.enums.research_enums import (
    AssumptionStatus,
    AssumptionType,
    ConflictSeverity,
    EvidenceType,
    FailureSeverity,
    GraphEdgeStatus,
    GraphEdgeType,
    GraphNodeStatus,
    GraphNodeType,
    GraphTriggerType,
    NoveltyLevel,
    PriorWorkRelation,
    ResearchSourceStatus,
    ResearchSourceType,
    RouteStatus,
    ValidationLevel,
    VisibilityLevel,
)
from research_layer.domain.value_objects.research_value_objects import (
    ScoreMeta,
    TopFactor,
    WorkspaceId,
)


_SOURCE_TRANSITIONS: dict[ResearchSourceStatus, set[ResearchSourceStatus]] = {
    ResearchSourceStatus.RAW: {ResearchSourceStatus.RAW, ResearchSourceStatus.PARSED},
    ResearchSourceStatus.PARSED: {
        ResearchSourceStatus.PARSED,
        ResearchSourceStatus.INDEXED,
    },
    ResearchSourceStatus.INDEXED: {
        ResearchSourceStatus.INDEXED,
        ResearchSourceStatus.EXTRACTED,
    },
    ResearchSourceStatus.EXTRACTED: {ResearchSourceStatus.EXTRACTED},
}

_ASSUMPTION_TRANSITIONS: dict[AssumptionStatus, set[AssumptionStatus]] = {
    AssumptionStatus.ACTIVE: {
        AssumptionStatus.ACTIVE,
        AssumptionStatus.CHALLENGED,
        AssumptionStatus.INVALIDATED,
        AssumptionStatus.ARCHIVED,
    },
    AssumptionStatus.CHALLENGED: {
        AssumptionStatus.CHALLENGED,
        AssumptionStatus.ACTIVE,
        AssumptionStatus.INVALIDATED,
        AssumptionStatus.ARCHIVED,
    },
    AssumptionStatus.INVALIDATED: {
        AssumptionStatus.INVALIDATED,
        AssumptionStatus.ARCHIVED,
    },
    AssumptionStatus.ARCHIVED: {AssumptionStatus.ARCHIVED},
}

_ROUTE_TRANSITIONS: dict[RouteStatus, set[RouteStatus]] = {
    RouteStatus.CANDIDATE: {
        RouteStatus.CANDIDATE,
        RouteStatus.ACTIVE,
        RouteStatus.FAILED,
        RouteStatus.SUPERSEDED,
    },
    RouteStatus.ACTIVE: {
        RouteStatus.ACTIVE,
        RouteStatus.WEAKENED,
        RouteStatus.VALIDATED,
        RouteStatus.FAILED,
        RouteStatus.SUPERSEDED,
    },
    RouteStatus.WEAKENED: {
        RouteStatus.WEAKENED,
        RouteStatus.ACTIVE,
        RouteStatus.FAILED,
        RouteStatus.SUPERSEDED,
    },
    RouteStatus.VALIDATED: {RouteStatus.VALIDATED, RouteStatus.SUPERSEDED},
    RouteStatus.FAILED: {RouteStatus.FAILED, RouteStatus.SUPERSEDED},
    RouteStatus.SUPERSEDED: {RouteStatus.SUPERSEDED},
}

_GRAPH_NODE_TRANSITIONS: dict[GraphNodeStatus, set[GraphNodeStatus]] = {
    GraphNodeStatus.ACTIVE: {
        GraphNodeStatus.ACTIVE,
        GraphNodeStatus.WEAKENED,
        GraphNodeStatus.CONFLICTED,
        GraphNodeStatus.FAILED,
        GraphNodeStatus.SUPERSEDED,
        GraphNodeStatus.ARCHIVED,
    },
    GraphNodeStatus.WEAKENED: {
        GraphNodeStatus.WEAKENED,
        GraphNodeStatus.ACTIVE,
        GraphNodeStatus.CONFLICTED,
        GraphNodeStatus.FAILED,
        GraphNodeStatus.SUPERSEDED,
        GraphNodeStatus.ARCHIVED,
    },
    GraphNodeStatus.CONFLICTED: {
        GraphNodeStatus.CONFLICTED,
        GraphNodeStatus.WEAKENED,
        GraphNodeStatus.FAILED,
        GraphNodeStatus.SUPERSEDED,
        GraphNodeStatus.ARCHIVED,
    },
    GraphNodeStatus.FAILED: {
        GraphNodeStatus.FAILED,
        GraphNodeStatus.SUPERSEDED,
        GraphNodeStatus.ARCHIVED,
    },
    GraphNodeStatus.SUPERSEDED: {
        GraphNodeStatus.SUPERSEDED,
        GraphNodeStatus.ARCHIVED,
    },
    GraphNodeStatus.ARCHIVED: {GraphNodeStatus.ARCHIVED},
}

_GRAPH_EDGE_TRANSITIONS: dict[GraphEdgeStatus, set[GraphEdgeStatus]] = {
    GraphEdgeStatus.ACTIVE: {
        GraphEdgeStatus.ACTIVE,
        GraphEdgeStatus.WEAKENED,
        GraphEdgeStatus.CONFLICTED,
        GraphEdgeStatus.INVALIDATED,
        GraphEdgeStatus.SUPERSEDED,
        GraphEdgeStatus.ARCHIVED,
    },
    GraphEdgeStatus.WEAKENED: {
        GraphEdgeStatus.WEAKENED,
        GraphEdgeStatus.ACTIVE,
        GraphEdgeStatus.CONFLICTED,
        GraphEdgeStatus.INVALIDATED,
        GraphEdgeStatus.SUPERSEDED,
        GraphEdgeStatus.ARCHIVED,
    },
    GraphEdgeStatus.CONFLICTED: {
        GraphEdgeStatus.CONFLICTED,
        GraphEdgeStatus.WEAKENED,
        GraphEdgeStatus.INVALIDATED,
        GraphEdgeStatus.SUPERSEDED,
        GraphEdgeStatus.ARCHIVED,
    },
    GraphEdgeStatus.INVALIDATED: {
        GraphEdgeStatus.INVALIDATED,
        GraphEdgeStatus.SUPERSEDED,
        GraphEdgeStatus.ARCHIVED,
    },
    GraphEdgeStatus.SUPERSEDED: {
        GraphEdgeStatus.SUPERSEDED,
        GraphEdgeStatus.ARCHIVED,
    },
    GraphEdgeStatus.ARCHIVED: {GraphEdgeStatus.ARCHIVED},
}


def _coerce_enum(enum_cls: type, value: Any):
    if isinstance(value, enum_cls):
        return value
    return enum_cls(value)


def _non_empty(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _validate_workspace_id(workspace_id: str) -> str:
    return str(WorkspaceId.parse(workspace_id))


def _serialize_datetime(value: datetime) -> str:
    return value.isoformat()


def _parse_datetime(raw: str) -> datetime:
    return datetime.fromisoformat(raw)


def _check_transition(current: Any, target: Any, table: dict[Any, set[Any]]) -> None:
    if target not in table[current]:
        raise ValueError(f"invalid transition: {current.value} -> {target.value}")


@dataclass(eq=True, slots=True)
class ResearchSource:
    source_id: str
    workspace_id: str
    source_type: ResearchSourceType
    title: str
    raw_content: str
    normalized_content: str
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    status: ResearchSourceStatus = ResearchSourceStatus.RAW

    def __post_init__(self) -> None:
        self.source_id = _non_empty(self.source_id, "source_id")
        self.workspace_id = _validate_workspace_id(self.workspace_id)
        self.source_type = _coerce_enum(ResearchSourceType, self.source_type)
        self.title = _non_empty(self.title, "title")
        self.raw_content = _non_empty(self.raw_content, "raw_content")
        self.normalized_content = _non_empty(self.normalized_content, "normalized_content")
        self.status = _coerce_enum(ResearchSourceStatus, self.status)

    def transition_to(self, target_status: ResearchSourceStatus) -> None:
        target = _coerce_enum(ResearchSourceStatus, target_status)
        _check_transition(self.status, target, _SOURCE_TRANSITIONS)
        self.status = target

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "workspace_id": self.workspace_id,
            "source_type": self.source_type.value,
            "title": self.title,
            "raw_content": self.raw_content,
            "normalized_content": self.normalized_content,
            "metadata": self.metadata,
            "status": self.status.value,
            "created_at": _serialize_datetime(self.created_at),
            "updated_at": _serialize_datetime(self.updated_at),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ResearchSource":
        return cls(
            source_id=payload["source_id"],
            workspace_id=payload["workspace_id"],
            source_type=ResearchSourceType(payload["source_type"]),
            title=payload["title"],
            raw_content=payload["raw_content"],
            normalized_content=payload["normalized_content"],
            metadata=dict(payload["metadata"]),
            status=ResearchSourceStatus(payload["status"]),
            created_at=_parse_datetime(payload["created_at"]),
            updated_at=_parse_datetime(payload["updated_at"]),
        )


@dataclass(eq=True, slots=True)
class ResearchEvidence:
    evidence_id: str
    workspace_id: str
    source_id: str
    evidence_type: EvidenceType
    span_text: str
    normalized_text: str
    citation_ref: str
    relation_to_prior_work: PriorWorkRelation
    user_confirmed: bool
    confidence_hint: float

    def __post_init__(self) -> None:
        self.evidence_id = _non_empty(self.evidence_id, "evidence_id")
        self.workspace_id = _validate_workspace_id(self.workspace_id)
        self.source_id = _non_empty(self.source_id, "source_id")
        self.evidence_type = _coerce_enum(EvidenceType, self.evidence_type)
        self.span_text = _non_empty(self.span_text, "span_text")
        self.normalized_text = _non_empty(self.normalized_text, "normalized_text")
        self.citation_ref = _non_empty(self.citation_ref, "citation_ref")
        self.relation_to_prior_work = _coerce_enum(
            PriorWorkRelation, self.relation_to_prior_work
        )
        if not 0.0 <= self.confidence_hint <= 1.0:
            raise ValueError("confidence_hint must be in [0, 1]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "workspace_id": self.workspace_id,
            "source_id": self.source_id,
            "evidence_type": self.evidence_type.value,
            "span_text": self.span_text,
            "normalized_text": self.normalized_text,
            "citation_ref": self.citation_ref,
            "relation_to_prior_work": self.relation_to_prior_work.value,
            "user_confirmed": self.user_confirmed,
            "confidence_hint": self.confidence_hint,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ResearchEvidence":
        return cls(
            evidence_id=payload["evidence_id"],
            workspace_id=payload["workspace_id"],
            source_id=payload["source_id"],
            evidence_type=EvidenceType(payload["evidence_type"]),
            span_text=payload["span_text"],
            normalized_text=payload["normalized_text"],
            citation_ref=payload["citation_ref"],
            relation_to_prior_work=PriorWorkRelation(payload["relation_to_prior_work"]),
            user_confirmed=bool(payload["user_confirmed"]),
            confidence_hint=float(payload["confidence_hint"]),
        )


@dataclass(eq=True, slots=True)
class ResearchAssumption:
    assumption_id: str
    workspace_id: str
    text: str
    assumption_type: AssumptionType
    depends_on_evidence_ids: list[str]
    burden_score: float
    status: AssumptionStatus = AssumptionStatus.ACTIVE

    def __post_init__(self) -> None:
        self.assumption_id = _non_empty(self.assumption_id, "assumption_id")
        self.workspace_id = _validate_workspace_id(self.workspace_id)
        self.text = _non_empty(self.text, "text")
        self.assumption_type = _coerce_enum(AssumptionType, self.assumption_type)
        if self.burden_score < 0.0:
            raise ValueError("burden_score must be >= 0")
        self.status = _coerce_enum(AssumptionStatus, self.status)

    def transition_to(self, target_status: AssumptionStatus) -> None:
        target = _coerce_enum(AssumptionStatus, target_status)
        _check_transition(self.status, target, _ASSUMPTION_TRANSITIONS)
        self.status = target

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_id": self.assumption_id,
            "workspace_id": self.workspace_id,
            "text": self.text,
            "assumption_type": self.assumption_type.value,
            "depends_on_evidence_ids": self.depends_on_evidence_ids,
            "burden_score": self.burden_score,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ResearchAssumption":
        return cls(
            assumption_id=payload["assumption_id"],
            workspace_id=payload["workspace_id"],
            text=payload["text"],
            assumption_type=AssumptionType(payload["assumption_type"]),
            depends_on_evidence_ids=list(payload["depends_on_evidence_ids"]),
            burden_score=float(payload["burden_score"]),
            status=AssumptionStatus(payload["status"]),
        )


@dataclass(eq=True, slots=True)
class ResearchConflict:
    conflict_id: str
    workspace_id: str
    involved_object_ids: list[str]
    reason: str
    severity: ConflictSeverity
    resolved: bool
    resolution_note: str

    def __post_init__(self) -> None:
        self.conflict_id = _non_empty(self.conflict_id, "conflict_id")
        self.workspace_id = _validate_workspace_id(self.workspace_id)
        if len(self.involved_object_ids) < 2:
            raise ValueError("involved_object_ids must include at least two objects")
        self.reason = _non_empty(self.reason, "reason")
        self.severity = _coerce_enum(ConflictSeverity, self.severity)
        if self.resolved and not self.resolution_note.strip():
            raise ValueError("resolution_note is required when resolved=True")

    def to_dict(self) -> dict[str, Any]:
        return {
            "conflict_id": self.conflict_id,
            "workspace_id": self.workspace_id,
            "involved_object_ids": self.involved_object_ids,
            "reason": self.reason,
            "severity": self.severity.value,
            "resolved": self.resolved,
            "resolution_note": self.resolution_note,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ResearchConflict":
        return cls(
            conflict_id=payload["conflict_id"],
            workspace_id=payload["workspace_id"],
            involved_object_ids=list(payload["involved_object_ids"]),
            reason=payload["reason"],
            severity=ConflictSeverity(payload["severity"]),
            resolved=bool(payload["resolved"]),
            resolution_note=payload["resolution_note"],
        )


@dataclass(eq=True, slots=True)
class FailureReport:
    failure_id: str
    workspace_id: str
    attached_targets: list[str]
    observed_outcome: str
    expected_difference: str
    failure_reason: str
    severity: FailureSeverity
    reporter: str
    timestamp: datetime

    def __post_init__(self) -> None:
        self.failure_id = _non_empty(self.failure_id, "failure_id")
        self.workspace_id = _validate_workspace_id(self.workspace_id)
        if not self.attached_targets:
            raise ValueError("attached_targets cannot be empty")
        self.observed_outcome = _non_empty(self.observed_outcome, "observed_outcome")
        self.expected_difference = _non_empty(
            self.expected_difference, "expected_difference"
        )
        self.failure_reason = _non_empty(self.failure_reason, "failure_reason")
        self.severity = _coerce_enum(FailureSeverity, self.severity)
        self.reporter = _non_empty(self.reporter, "reporter")

    def to_dict(self) -> dict[str, Any]:
        return {
            "failure_id": self.failure_id,
            "workspace_id": self.workspace_id,
            "attached_targets": self.attached_targets,
            "observed_outcome": self.observed_outcome,
            "expected_difference": self.expected_difference,
            "failure_reason": self.failure_reason,
            "severity": self.severity.value,
            "reporter": self.reporter,
            "timestamp": _serialize_datetime(self.timestamp),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FailureReport":
        return cls(
            failure_id=payload["failure_id"],
            workspace_id=payload["workspace_id"],
            attached_targets=list(payload["attached_targets"]),
            observed_outcome=payload["observed_outcome"],
            expected_difference=payload["expected_difference"],
            failure_reason=payload["failure_reason"],
            severity=FailureSeverity(payload["severity"]),
            reporter=payload["reporter"],
            timestamp=_parse_datetime(payload["timestamp"]),
        )


@dataclass(eq=True, slots=True)
class ValidationAction:
    action_id: str
    workspace_id: str
    target_object: str
    method: str
    success_signal: str
    weakening_signal: str
    cost_level: ValidationLevel
    time_level: ValidationLevel
    domain_template: str

    def __post_init__(self) -> None:
        self.action_id = _non_empty(self.action_id, "action_id")
        self.workspace_id = _validate_workspace_id(self.workspace_id)
        self.target_object = _non_empty(self.target_object, "target_object")
        self.method = _non_empty(self.method, "method")
        self.success_signal = _non_empty(self.success_signal, "success_signal")
        self.weakening_signal = _non_empty(self.weakening_signal, "weakening_signal")
        self.cost_level = _coerce_enum(ValidationLevel, self.cost_level)
        self.time_level = _coerce_enum(ValidationLevel, self.time_level)
        self.domain_template = _non_empty(self.domain_template, "domain_template")

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "workspace_id": self.workspace_id,
            "target_object": self.target_object,
            "method": self.method,
            "success_signal": self.success_signal,
            "weakening_signal": self.weakening_signal,
            "cost_level": self.cost_level.value,
            "time_level": self.time_level.value,
            "domain_template": self.domain_template,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ValidationAction":
        return cls(
            action_id=payload["action_id"],
            workspace_id=payload["workspace_id"],
            target_object=payload["target_object"],
            method=payload["method"],
            success_signal=payload["success_signal"],
            weakening_signal=payload["weakening_signal"],
            cost_level=ValidationLevel(payload["cost_level"]),
            time_level=ValidationLevel(payload["time_level"]),
            domain_template=payload["domain_template"],
        )


@dataclass(eq=True, slots=True)
class Route:
    route_id: str
    workspace_id: str
    title: str
    summary: str
    support_score: float
    risk_score: float
    progressability_score: float
    novelty_level: NoveltyLevel | str
    relation_tags: list[str]
    top_factors: list[TopFactor] = field(default_factory=list)
    conclusion_node_id: str = ""
    next_validation_action_id: str = ""
    version_id: str = ""
    status: RouteStatus = RouteStatus.CANDIDATE

    def __post_init__(self) -> None:
        self.route_id = _non_empty(self.route_id, "route_id")
        self.workspace_id = _validate_workspace_id(self.workspace_id)
        self.title = _non_empty(self.title, "title")
        self.summary = _non_empty(self.summary, "summary")
        for name, score in (
            ("support_score", self.support_score),
            ("risk_score", self.risk_score),
            ("progressability_score", self.progressability_score),
        ):
            if not 0.0 <= score <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")
        self.novelty_level = _coerce_enum(NoveltyLevel, self.novelty_level)
        self.conclusion_node_id = _non_empty(self.conclusion_node_id, "conclusion_node_id")
        self.next_validation_action_id = _non_empty(
            self.next_validation_action_id, "next_validation_action_id"
        )
        self.version_id = _non_empty(self.version_id, "version_id")
        self.status = _coerce_enum(RouteStatus, self.status)
        self.top_factors = [
            factor if isinstance(factor, TopFactor) else TopFactor.from_dict(factor)
            for factor in self.top_factors
        ]

    def transition_to(self, target_status: RouteStatus) -> None:
        target = _coerce_enum(RouteStatus, target_status)
        _check_transition(self.status, target, _ROUTE_TRANSITIONS)
        self.status = target

    def to_dict(self) -> dict[str, Any]:
        return {
            "route_id": self.route_id,
            "workspace_id": self.workspace_id,
            "title": self.title,
            "summary": self.summary,
            "support_score": self.support_score,
            "risk_score": self.risk_score,
            "progressability_score": self.progressability_score,
            "novelty_level": self.novelty_level.value,
            "relation_tags": self.relation_tags,
            "top_factors": [factor.to_dict() for factor in self.top_factors],
            "conclusion_node_id": self.conclusion_node_id,
            "next_validation_action_id": self.next_validation_action_id,
            "status": self.status.value,
            "version_id": self.version_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Route":
        return cls(
            route_id=payload["route_id"],
            workspace_id=payload["workspace_id"],
            title=payload["title"],
            summary=payload["summary"],
            support_score=float(payload["support_score"]),
            risk_score=float(payload["risk_score"]),
            progressability_score=float(payload["progressability_score"]),
            novelty_level=NoveltyLevel(payload["novelty_level"]),
            relation_tags=list(payload["relation_tags"]),
            top_factors=[TopFactor.from_dict(item) for item in payload["top_factors"]],
            conclusion_node_id=payload["conclusion_node_id"],
            next_validation_action_id=payload["next_validation_action_id"],
            status=RouteStatus(payload["status"]),
            version_id=payload["version_id"],
        )


@dataclass(eq=True, slots=True)
class GraphNode:
    node_id: str
    workspace_id: str
    node_type: GraphNodeType
    object_ref_type: str
    object_ref_id: str
    short_label: str
    full_description: str
    short_tags: list[str]
    visibility: VisibilityLevel
    score_meta: ScoreMeta
    status: GraphNodeStatus = GraphNodeStatus.ACTIVE

    def __post_init__(self) -> None:
        self.node_id = _non_empty(self.node_id, "node_id")
        self.workspace_id = _validate_workspace_id(self.workspace_id)
        self.node_type = _coerce_enum(GraphNodeType, self.node_type)
        self.object_ref_type = _non_empty(self.object_ref_type, "object_ref_type")
        self.object_ref_id = _non_empty(self.object_ref_id, "object_ref_id")
        self.short_label = _non_empty(self.short_label, "short_label")
        self.full_description = _non_empty(self.full_description, "full_description")
        self.visibility = _coerce_enum(VisibilityLevel, self.visibility)
        if not isinstance(self.score_meta, ScoreMeta):
            self.score_meta = ScoreMeta.from_dict(self.score_meta)
        self.status = _coerce_enum(GraphNodeStatus, self.status)

    def transition_to(self, target_status: GraphNodeStatus) -> None:
        target = _coerce_enum(GraphNodeStatus, target_status)
        _check_transition(self.status, target, _GRAPH_NODE_TRANSITIONS)
        self.status = target

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "workspace_id": self.workspace_id,
            "node_type": self.node_type.value,
            "object_ref_type": self.object_ref_type,
            "object_ref_id": self.object_ref_id,
            "short_label": self.short_label,
            "full_description": self.full_description,
            "short_tags": self.short_tags,
            "visibility": self.visibility.value,
            "status": self.status.value,
            "score_meta": self.score_meta.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GraphNode":
        return cls(
            node_id=payload["node_id"],
            workspace_id=payload["workspace_id"],
            node_type=GraphNodeType(payload["node_type"]),
            object_ref_type=payload["object_ref_type"],
            object_ref_id=payload["object_ref_id"],
            short_label=payload["short_label"],
            full_description=payload["full_description"],
            short_tags=list(payload["short_tags"]),
            visibility=VisibilityLevel(payload["visibility"]),
            status=GraphNodeStatus(payload["status"]),
            score_meta=ScoreMeta.from_dict(payload["score_meta"]),
        )


@dataclass(eq=True, slots=True)
class GraphEdge:
    edge_id: str
    workspace_id: str
    source_node_id: str
    target_node_id: str
    edge_type: GraphEdgeType
    strength: float
    attached_evidence_ids: list[str]
    affected_by_failure_ids: list[str]
    status: GraphEdgeStatus = GraphEdgeStatus.ACTIVE

    def __post_init__(self) -> None:
        self.edge_id = _non_empty(self.edge_id, "edge_id")
        self.workspace_id = _validate_workspace_id(self.workspace_id)
        self.source_node_id = _non_empty(self.source_node_id, "source_node_id")
        self.target_node_id = _non_empty(self.target_node_id, "target_node_id")
        self.edge_type = _coerce_enum(GraphEdgeType, self.edge_type)
        if not 0.0 <= self.strength <= 1.0:
            raise ValueError("strength must be in [0, 1]")
        self.status = _coerce_enum(GraphEdgeStatus, self.status)

    def transition_to(self, target_status: GraphEdgeStatus) -> None:
        target = _coerce_enum(GraphEdgeStatus, target_status)
        _check_transition(self.status, target, _GRAPH_EDGE_TRANSITIONS)
        self.status = target

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "workspace_id": self.workspace_id,
            "source_node_id": self.source_node_id,
            "target_node_id": self.target_node_id,
            "edge_type": self.edge_type.value,
            "strength": self.strength,
            "status": self.status.value,
            "attached_evidence_ids": self.attached_evidence_ids,
            "affected_by_failure_ids": self.affected_by_failure_ids,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GraphEdge":
        return cls(
            edge_id=payload["edge_id"],
            workspace_id=payload["workspace_id"],
            source_node_id=payload["source_node_id"],
            target_node_id=payload["target_node_id"],
            edge_type=GraphEdgeType(payload["edge_type"]),
            strength=float(payload["strength"]),
            status=GraphEdgeStatus(payload["status"]),
            attached_evidence_ids=list(payload["attached_evidence_ids"]),
            affected_by_failure_ids=list(payload["affected_by_failure_ids"]),
        )


@dataclass(eq=True, slots=True)
class GraphVersion:
    version_id: str
    workspace_id: str
    trigger_type: GraphTriggerType
    change_summary: str
    diff_payload: dict[str, Any]
    created_at: datetime

    def __post_init__(self) -> None:
        self.version_id = _non_empty(self.version_id, "version_id")
        self.workspace_id = _validate_workspace_id(self.workspace_id)
        self.trigger_type = _coerce_enum(GraphTriggerType, self.trigger_type)
        self.change_summary = _non_empty(self.change_summary, "change_summary")

    def to_dict(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "workspace_id": self.workspace_id,
            "trigger_type": self.trigger_type.value,
            "change_summary": self.change_summary,
            "diff_payload": self.diff_payload,
            "created_at": _serialize_datetime(self.created_at),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GraphVersion":
        return cls(
            version_id=payload["version_id"],
            workspace_id=payload["workspace_id"],
            trigger_type=GraphTriggerType(payload["trigger_type"]),
            change_summary=payload["change_summary"],
            diff_payload=dict(payload["diff_payload"]),
            created_at=_parse_datetime(payload["created_at"]),
        )


@dataclass(eq=True, slots=True)
class ResearchPackage:
    package_id: str
    workspace_id: str
    title: str
    summary: str
    included_route_ids: list[str]
    included_node_ids: list[str]
    included_validation_ids: list[str]
    private_dependency_flags: list[dict[str, Any]]
    public_gap_nodes: list[dict[str, Any]]
    snapshot_type: str = "research_package_snapshot"
    snapshot_version: str = "slice11.v1"
    boundary_notes: list[str] = field(default_factory=list)
    traceability_refs: dict[str, Any] = field(default_factory=dict)
    replay_ready: bool = True
    status: str = "draft"

    def __post_init__(self) -> None:
        self.package_id = _non_empty(self.package_id, "package_id")
        self.workspace_id = _validate_workspace_id(self.workspace_id)
        self.title = _non_empty(self.title, "title")
        self.summary = _non_empty(self.summary, "summary")
        self.snapshot_type = _non_empty(self.snapshot_type, "snapshot_type")
        self.snapshot_version = _non_empty(self.snapshot_version, "snapshot_version")
        normalized_private_flags: list[dict[str, Any]] = []
        for item in self.private_dependency_flags:
            if isinstance(item, dict):
                normalized_private_flags.append(dict(item))
            else:
                normalized_private_flags.append({"private_node_id": str(item)})
        self.private_dependency_flags = normalized_private_flags
        normalized_gap_nodes: list[dict[str, Any]] = []
        for item in self.public_gap_nodes:
            if isinstance(item, dict):
                normalized_gap_nodes.append(dict(item))
            else:
                normalized_gap_nodes.append({"node_id": str(item)})
        self.public_gap_nodes = normalized_gap_nodes

    def to_dict(self) -> dict[str, Any]:
        return {
            "package_id": self.package_id,
            "workspace_id": self.workspace_id,
            "title": self.title,
            "summary": self.summary,
            "included_route_ids": self.included_route_ids,
            "included_node_ids": self.included_node_ids,
            "included_validation_ids": self.included_validation_ids,
            "private_dependency_flags": self.private_dependency_flags,
            "public_gap_nodes": self.public_gap_nodes,
            "snapshot_type": self.snapshot_type,
            "snapshot_version": self.snapshot_version,
            "boundary_notes": self.boundary_notes,
            "traceability_refs": self.traceability_refs,
            "replay_ready": self.replay_ready,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ResearchPackage":
        public_gap_nodes = payload.get("public_gap_nodes")
        if public_gap_nodes is None:
            public_gap_nodes = payload.get("public_gap_node_ids", [])
        return cls(
            package_id=payload["package_id"],
            workspace_id=payload["workspace_id"],
            title=payload["title"],
            summary=payload["summary"],
            included_route_ids=list(payload["included_route_ids"]),
            included_node_ids=list(payload["included_node_ids"]),
            included_validation_ids=list(payload["included_validation_ids"]),
            private_dependency_flags=list(payload["private_dependency_flags"]),
            public_gap_nodes=list(public_gap_nodes),
            snapshot_type=str(payload.get("snapshot_type", "research_package_snapshot")),
            snapshot_version=str(payload.get("snapshot_version", "slice11.v1")),
            boundary_notes=list(payload.get("boundary_notes", [])),
            traceability_refs=dict(payload.get("traceability_refs", {})),
            replay_ready=bool(payload.get("replay_ready", True)),
            status=str(payload.get("status", "draft")),
        )
