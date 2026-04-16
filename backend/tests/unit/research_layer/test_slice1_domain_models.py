from __future__ import annotations

from datetime import datetime, timezone

import pytest

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
    PriorWorkRelation,
    ResearchSourceStatus,
    ResearchSourceType,
    RouteStatus,
    ValidationLevel,
    VisibilityLevel,
)
from research_layer.domain.models.research_domain import (
    FailureReport,
    GraphEdge,
    GraphNode,
    GraphVersion,
    ResearchAssumption,
    ResearchConflict,
    ResearchEvidence,
    ResearchPackage,
    ResearchSource,
    Route,
    ValidationAction,
)
from research_layer.domain.value_objects.research_value_objects import (
    ScoreMeta,
    TopFactor,
    WorkspaceId,
)


NOW = datetime(2026, 3, 30, 12, 0, 0, tzinfo=timezone.utc)


def test_workspace_id_accepts_valid_value():
    workspace_id = WorkspaceId.parse("ws_alpha-01")
    assert str(workspace_id) == "ws_alpha-01"


@pytest.mark.parametrize("raw", ["", "  ", "ab", "white space", "@bad"])
def test_workspace_id_rejects_invalid_values(raw: str):
    with pytest.raises(ValueError):
        WorkspaceId.parse(raw)


def test_enum_values_are_frozen():
    assert ResearchSourceType.PAPER.value == "paper"
    assert ResearchSourceStatus.EXTRACTED.value == "extracted"
    assert EvidenceType.OBSERVATION.value == "observation"
    assert PriorWorkRelation.RECOMBINATION.value == "recombination"
    assert AssumptionType.GENERATED.value == "generated"
    assert AssumptionStatus.INVALIDATED.value == "invalidated"
    assert ConflictSeverity.CRITICAL.value == "critical"
    assert FailureSeverity.HIGH.value == "high"
    assert RouteStatus.VALIDATED.value == "validated"
    assert GraphNodeType.PRIVATE_DEPENDENCY.value == "private_dependency"
    assert GraphNodeStatus.SUPERSEDED.value == "superseded"
    assert GraphEdgeType.BRANCHES_TO.value == "branches_to"
    assert GraphEdgeStatus.INVALIDATED.value == "invalidated"
    assert GraphTriggerType.RECOMPUTE.value == "recompute"
    assert ValidationLevel.MEDIUM.value == "medium"
    assert VisibilityLevel.PACKAGE_PUBLIC.value == "package_public"


def test_source_type_values_no_drift_with_slice2_api_contract():
    assert {member.value for member in ResearchSourceType} == {
        "paper",
        "note",
        "feedback",
        "failure_record",
        "dialogue",
    }


def test_research_source_valid_construction_and_state_flow():
    source = ResearchSource(
        source_id="src-1",
        workspace_id="ws_alpha-01",
        source_type=ResearchSourceType.PAPER,
        title="A paper",
        raw_content="raw",
        normalized_content="normalized",
        metadata={"lang": "en"},
        created_at=NOW,
        updated_at=NOW,
    )
    source.transition_to(ResearchSourceStatus.PARSED)
    source.transition_to(ResearchSourceStatus.INDEXED)
    source.transition_to(ResearchSourceStatus.EXTRACTED)
    assert source.status is ResearchSourceStatus.EXTRACTED


def test_research_source_rejects_illegal_status_jump():
    source = ResearchSource(
        source_id="src-1",
        workspace_id="ws_alpha-01",
        source_type=ResearchSourceType.NOTE,
        title="Note",
        raw_content="raw",
        normalized_content="normalized",
        metadata={},
        created_at=NOW,
        updated_at=NOW,
    )
    with pytest.raises(ValueError):
        source.transition_to(ResearchSourceStatus.INDEXED)


def test_research_evidence_constraints():
    evidence = ResearchEvidence(
        evidence_id="ev-1",
        workspace_id="ws_alpha-01",
        source_id="src-1",
        evidence_type=EvidenceType.CLAIM,
        span_text="span",
        normalized_text="normalized",
        citation_ref="[1]",
        relation_to_prior_work=PriorWorkRelation.DIRECT_SUPPORT,
        user_confirmed=True,
        confidence_hint=0.75,
    )
    assert evidence.confidence_hint == 0.75

    with pytest.raises(ValueError):
        ResearchEvidence(
            evidence_id="ev-2",
            workspace_id="ws_alpha-01",
            source_id="src-1",
            evidence_type=EvidenceType.RESULT,
            span_text="span",
            normalized_text="normalized",
            citation_ref="[2]",
            relation_to_prior_work=PriorWorkRelation.RECOMBINATION,
            user_confirmed=False,
            confidence_hint=1.5,
        )


def test_assumption_state_transitions():
    assumption = ResearchAssumption(
        assumption_id="as-1",
        workspace_id="ws_alpha-01",
        text="Assume X",
        assumption_type=AssumptionType.EXPLICIT,
        depends_on_evidence_ids=["ev-1"],
        burden_score=0.4,
    )
    assumption.transition_to(AssumptionStatus.CHALLENGED)
    assumption.transition_to(AssumptionStatus.INVALIDATED)
    assumption.transition_to(AssumptionStatus.ARCHIVED)
    assert assumption.status is AssumptionStatus.ARCHIVED

    with pytest.raises(ValueError):
        assumption.transition_to(AssumptionStatus.ACTIVE)


def test_conflict_requires_resolution_note_when_resolved():
    with pytest.raises(ValueError):
        ResearchConflict(
            conflict_id="cf-1",
            workspace_id="ws_alpha-01",
            involved_object_ids=["ev-1", "as-1"],
            reason="contradiction",
            severity=ConflictSeverity.MEDIUM,
            resolved=True,
            resolution_note="",
        )


def test_failure_report_boundary():
    failure = FailureReport(
        failure_id="fr-1",
        workspace_id="ws_alpha-01",
        attached_targets=["node-1"],
        observed_outcome="A",
        expected_difference="B",
        failure_reason="reason",
        severity=FailureSeverity.LOW,
        reporter="alice",
        timestamp=NOW,
    )
    assert failure.attached_targets == ["node-1"]


def test_validation_action_construction():
    action = ValidationAction(
        action_id="va-1",
        workspace_id="ws_alpha-01",
        target_object="as-1",
        method="ablation",
        success_signal="improves",
        weakening_signal="no_change",
        cost_level=ValidationLevel.MEDIUM,
        time_level=ValidationLevel.HIGH,
        domain_template="ml-experiment",
    )
    assert action.method == "ablation"


def test_route_state_transitions_and_boundaries():
    route = Route(
        route_id="rt-1",
        workspace_id="ws_alpha-01",
        title="Route 1",
        summary="summary",
        support_score=0.8,
        risk_score=0.3,
        progressability_score=0.7,
        novelty_level="incremental",
        relation_tags=["tag-1"],
        top_factors=[TopFactor(name="support", score=0.8)],
        conclusion_node_id="node-1",
        next_validation_action_id="va-1",
        version_id="gv-1",
    )
    route.transition_to(RouteStatus.ACTIVE)
    route.transition_to(RouteStatus.WEAKENED)
    route.transition_to(RouteStatus.FAILED)
    assert route.status is RouteStatus.FAILED

    with pytest.raises(ValueError):
        route.transition_to(RouteStatus.CANDIDATE)

    with pytest.raises(ValueError):
        Route(
            route_id="rt-2",
            workspace_id="ws_alpha-01",
            title="Route 2",
            summary="summary",
            support_score=1.1,
            risk_score=0.2,
            progressability_score=0.3,
            novelty_level="novel",
            relation_tags=[],
            top_factors=[],
            conclusion_node_id="node-1",
            next_validation_action_id="va-1",
            version_id="gv-1",
        )


def test_graph_node_state_transitions():
    node = GraphNode(
        node_id="node-1",
        workspace_id="ws_alpha-01",
        node_type=GraphNodeType.ASSUMPTION,
        object_ref_type="research_assumption",
        object_ref_id="as-1",
        short_label="A1",
        full_description="Assumption",
        short_tags=["assumption"],
        visibility=VisibilityLevel.WORKSPACE,
        score_meta=ScoreMeta(support=0.5, risk=0.4, progressability=0.6),
    )
    node.transition_to(GraphNodeStatus.WEAKENED)
    node.transition_to(GraphNodeStatus.CONFLICTED)
    node.transition_to(GraphNodeStatus.FAILED)
    node.transition_to(GraphNodeStatus.SUPERSEDED)
    node.transition_to(GraphNodeStatus.ARCHIVED)
    assert node.status is GraphNodeStatus.ARCHIVED

    with pytest.raises(ValueError):
        node.transition_to(GraphNodeStatus.ACTIVE)


def test_graph_edge_state_transitions_and_strength_boundary():
    edge = GraphEdge(
        edge_id="edge-1",
        workspace_id="ws_alpha-01",
        source_node_id="node-1",
        target_node_id="node-2",
        edge_type=GraphEdgeType.SUPPORTS,
        strength=1.0,
        attached_evidence_ids=["ev-1"],
        affected_by_failure_ids=[],
    )
    edge.transition_to(GraphEdgeStatus.WEAKENED)
    edge.transition_to(GraphEdgeStatus.INVALIDATED)
    edge.transition_to(GraphEdgeStatus.SUPERSEDED)
    assert edge.status is GraphEdgeStatus.SUPERSEDED

    with pytest.raises(ValueError):
        edge.transition_to(GraphEdgeStatus.ACTIVE)

    with pytest.raises(ValueError):
        GraphEdge(
            edge_id="edge-2",
            workspace_id="ws_alpha-01",
            source_node_id="node-1",
            target_node_id="node-2",
            edge_type=GraphEdgeType.REQUIRES,
            strength=-0.01,
            attached_evidence_ids=[],
            affected_by_failure_ids=[],
        )


def test_graph_version_and_research_package_construction():
    version = GraphVersion(
        version_id="gv-1",
        workspace_id="ws_alpha-01",
        trigger_type=GraphTriggerType.FAILURE,
        change_summary="summary",
        diff_payload={"added": ["node-1"]},
        created_at=NOW,
    )
    package = ResearchPackage(
        package_id="pkg-1",
        workspace_id="ws_alpha-01",
        title="P",
        summary="S",
        included_route_ids=["rt-1"],
        included_node_ids=["node-1"],
        included_validation_ids=["va-1"],
        private_dependency_flags=["node-9"],
        public_gap_nodes=["node-10"],
    )
    assert version.trigger_type is GraphTriggerType.FAILURE
    assert package.package_id == "pkg-1"


@pytest.mark.parametrize(
    "obj",
    [
        ResearchSource(
            source_id="src-1",
            workspace_id="ws_alpha-01",
            source_type=ResearchSourceType.DIALOGUE,
            title="T",
            raw_content="raw",
            normalized_content="normalized",
            metadata={"k": "v"},
            created_at=NOW,
            updated_at=NOW,
        ),
        ResearchEvidence(
            evidence_id="ev-1",
            workspace_id="ws_alpha-01",
            source_id="src-1",
            evidence_type=EvidenceType.RESULT,
            span_text="s",
            normalized_text="n",
            citation_ref="[1]",
            relation_to_prior_work=PriorWorkRelation.UPSTREAM_INSPIRATION,
            user_confirmed=False,
            confidence_hint=0.1,
        ),
        ResearchAssumption(
            assumption_id="as-1",
            workspace_id="ws_alpha-01",
            text="A",
            assumption_type=AssumptionType.IMPLICIT,
            depends_on_evidence_ids=[],
            burden_score=1.0,
        ),
        ResearchConflict(
            conflict_id="cf-1",
            workspace_id="ws_alpha-01",
            involved_object_ids=["a", "b"],
            reason="r",
            severity=ConflictSeverity.LOW,
            resolved=False,
            resolution_note="",
        ),
        FailureReport(
            failure_id="fr-1",
            workspace_id="ws_alpha-01",
            attached_targets=["node-1"],
            observed_outcome="obs",
            expected_difference="exp",
            failure_reason="reason",
            severity=FailureSeverity.CRITICAL,
            reporter="user",
            timestamp=NOW,
        ),
        ValidationAction(
            action_id="va-1",
            workspace_id="ws_alpha-01",
            target_object="as-1",
            method="m",
            success_signal="s",
            weakening_signal="w",
            cost_level=ValidationLevel.LOW,
            time_level=ValidationLevel.MEDIUM,
            domain_template="d",
        ),
        Route(
            route_id="rt-1",
            workspace_id="ws_alpha-01",
            title="t",
            summary="s",
            support_score=0.2,
            risk_score=0.3,
            progressability_score=0.4,
            novelty_level="conservative",
            relation_tags=[],
            top_factors=[TopFactor(name="f", score=0.4)],
            conclusion_node_id="n-1",
            next_validation_action_id="va-1",
            version_id="gv-1",
        ),
        GraphNode(
            node_id="n-1",
            workspace_id="ws_alpha-01",
            node_type=GraphNodeType.EVIDENCE,
            object_ref_type="research_evidence",
            object_ref_id="ev-1",
            short_label="n",
            full_description="desc",
            short_tags=[],
            visibility=VisibilityLevel.PRIVATE,
            score_meta=ScoreMeta(support=0.1, risk=0.2, progressability=0.3),
        ),
        GraphEdge(
            edge_id="e-1",
            workspace_id="ws_alpha-01",
            source_node_id="n-1",
            target_node_id="n-2",
            edge_type=GraphEdgeType.DERIVES,
            strength=0.3,
            attached_evidence_ids=[],
            affected_by_failure_ids=[],
        ),
        GraphVersion(
            version_id="gv-1",
            workspace_id="ws_alpha-01",
            trigger_type=GraphTriggerType.NEW_SOURCE,
            change_summary="new",
            diff_payload={"x": 1},
            created_at=NOW,
        ),
        ResearchPackage(
            package_id="pkg-1",
            workspace_id="ws_alpha-01",
            title="title",
            summary="summary",
            included_route_ids=["rt-1"],
            included_node_ids=["n-1"],
            included_validation_ids=["va-1"],
            private_dependency_flags=[],
            public_gap_nodes=[],
        ),
    ],
)
def test_serialization_roundtrip(obj):
    payload = obj.to_dict()
    restored = obj.__class__.from_dict(payload)
    assert restored == obj
