from __future__ import annotations

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.services.failure_impact_service import FailureImpactService
from research_layer.services.version_diff_service import VersionDiffService


def _build_store(tmp_path) -> ResearchApiStateStore:
    return ResearchApiStateStore(
        db_path=str(tmp_path / "slice8_failure_loop_services.sqlite3")
    )


def _seed_graph_with_route(
    store: ResearchApiStateStore, workspace_id: str
) -> tuple[str, str, str]:
    node_a = store.create_graph_node(
        workspace_id=workspace_id,
        node_type="evidence",
        object_ref_type="evidence",
        object_ref_id="evidence_1",
        short_label="Evidence A",
        full_description="Evidence A desc",
        status="active",
    )
    node_b = store.create_graph_node(
        workspace_id=workspace_id,
        node_type="assumption",
        object_ref_type="assumption",
        object_ref_id="assumption_1",
        short_label="Assumption B",
        full_description="Assumption B desc",
        status="active",
    )
    edge_ab = store.create_graph_edge(
        workspace_id=workspace_id,
        source_node_id=str(node_a["node_id"]),
        target_node_id=str(node_b["node_id"]),
        edge_type="supports",
        object_ref_type="relation",
        object_ref_id="rel_1",
        strength=0.8,
        status="active",
    )
    route = store.create_route(
        workspace_id=workspace_id,
        title="Seed Route",
        summary="seed",
        status="active",
        support_score=71.0,
        risk_score=24.0,
        progressability_score=62.0,
        conclusion="seed",
        key_supports=["Evidence A"],
        assumptions=["Assumption B"],
        risks=[],
        next_validation_action="run ablation",
        conclusion_node_id=str(node_a["node_id"]),
        route_node_ids=[str(node_a["node_id"]), str(node_b["node_id"])],
        key_support_node_ids=[str(node_a["node_id"])],
        key_assumption_node_ids=[str(node_b["node_id"])],
        risk_node_ids=[],
        next_validation_node_id=None,
        version_id="ver_seed",
    )
    return str(node_a["node_id"]), str(edge_ab["edge_id"]), str(route["route_id"])


def test_slice8_failure_impact_service_marks_targets_routes_and_gap_branch(tmp_path) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_slice8_unit_impact"
    node_id, edge_id, route_id = _seed_graph_with_route(store, workspace_id)

    failure = store.create_failure(
        workspace_id=workspace_id,
        attached_targets=[
            {"target_type": "node", "target_id": node_id},
            {"target_type": "edge", "target_id": edge_id},
        ],
        observed_outcome="pipeline degraded",
        expected_difference="stable throughput",
        failure_reason="queue timeout",
        severity="high",
        reporter="tester",
    )

    service = FailureImpactService(store)
    impact = service.apply_failure(
        workspace_id=workspace_id,
        failure_id=str(failure["failure_id"]),
        request_id="req_slice8_unit_impact",
    )

    updated_node = store.get_graph_node(node_id)
    updated_edge = store.get_graph_edge(edge_id)
    updated_route = store.get_route(route_id)
    assert updated_node is not None and updated_node["status"] in {"weakened", "failed"}
    assert updated_edge is not None and updated_edge["status"] in {
        "weakened",
        "invalidated",
    }
    assert updated_route is not None and updated_route["status"] == "weakened"

    current_nodes = store.list_graph_nodes(workspace_id)
    assert any(node["node_type"] == "gap" for node in current_nodes)
    assert any(node["node_type"] == "branch" for node in current_nodes)

    assert node_id in impact["weakened_node_ids"] or node_id in impact["invalidated_node_ids"]
    assert edge_id in impact["weakened_edge_ids"] or edge_id in impact["invalidated_edge_ids"]


def test_slice8_failure_impact_service_is_idempotent_for_same_failure(tmp_path) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_slice8_unit_idempotent"
    node_id, edge_id, route_id = _seed_graph_with_route(store, workspace_id)

    failure = store.create_failure(
        workspace_id=workspace_id,
        attached_targets=[
            {"target_type": "node", "target_id": node_id},
            {"target_type": "edge", "target_id": edge_id},
        ],
        observed_outcome="pipeline degraded",
        expected_difference="stable throughput",
        failure_reason="queue timeout",
        severity="high",
        reporter="tester",
    )

    service = FailureImpactService(store)
    first = service.apply_failure(
        workspace_id=workspace_id,
        failure_id=str(failure["failure_id"]),
        request_id="req_slice8_unit_idempotent_first",
    )
    edge_after_first = store.get_graph_edge(edge_id)
    assert edge_after_first is not None

    second = service.apply_failure(
        workspace_id=workspace_id,
        failure_id=str(failure["failure_id"]),
        request_id="req_slice8_unit_idempotent_second",
    )
    edge_after_second = store.get_graph_edge(edge_id)
    assert edge_after_second is not None

    assert edge_after_second["strength"] == edge_after_first["strength"]
    assert first == second

    routes = store.list_routes(workspace_id)
    assert len(routes) == 1
    assert routes[0]["route_id"] == route_id


def test_slice8_failure_impact_service_marks_routes_by_actual_edge_id_not_node_pair(
    tmp_path,
) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_slice8_unit_edge_exact"
    node_a = store.create_graph_node(
        workspace_id=workspace_id,
        node_type="evidence",
        object_ref_type="evidence",
        object_ref_id="evidence_a",
        short_label="Evidence A",
        full_description="Evidence A desc",
        status="active",
    )
    node_b = store.create_graph_node(
        workspace_id=workspace_id,
        node_type="evidence",
        object_ref_type="evidence",
        object_ref_id="evidence_b",
        short_label="Evidence B",
        full_description="Evidence B desc",
        status="active",
    )
    edge_1 = store.create_graph_edge(
        workspace_id=workspace_id,
        source_node_id=str(node_a["node_id"]),
        target_node_id=str(node_b["node_id"]),
        edge_type="supports",
        object_ref_type="relation",
        object_ref_id="rel_1",
        strength=0.8,
        status="active",
    )
    edge_2 = store.create_graph_edge(
        workspace_id=workspace_id,
        source_node_id=str(node_a["node_id"]),
        target_node_id=str(node_b["node_id"]),
        edge_type="supports",
        object_ref_type="relation",
        object_ref_id="rel_2",
        strength=0.8,
        status="active",
    )
    route_1 = store.create_route(
        workspace_id=workspace_id,
        title="Route 1",
        summary="route 1",
        status="active",
        support_score=70.0,
        risk_score=20.0,
        progressability_score=60.0,
        conclusion="route 1",
        key_supports=["Evidence A"],
        assumptions=[],
        risks=[],
        next_validation_action="validate route 1",
        conclusion_node_id=str(node_a["node_id"]),
        route_node_ids=[str(node_a["node_id"]), str(node_b["node_id"])],
        route_edge_ids=[str(edge_1["edge_id"])],
        key_support_node_ids=[str(node_a["node_id"])],
        key_assumption_node_ids=[],
        risk_node_ids=[],
        next_validation_node_id=None,
        version_id="ver_seed",
    )
    route_2 = store.create_route(
        workspace_id=workspace_id,
        title="Route 2",
        summary="route 2",
        status="active",
        support_score=69.0,
        risk_score=21.0,
        progressability_score=61.0,
        conclusion="route 2",
        key_supports=["Evidence B"],
        assumptions=[],
        risks=[],
        next_validation_action="validate route 2",
        conclusion_node_id=str(node_b["node_id"]),
        route_node_ids=[str(node_a["node_id"]), str(node_b["node_id"])],
        route_edge_ids=[str(edge_2["edge_id"])],
        key_support_node_ids=[str(node_b["node_id"])],
        key_assumption_node_ids=[],
        risk_node_ids=[],
        next_validation_node_id=None,
        version_id="ver_seed",
    )
    failure = store.create_failure(
        workspace_id=workspace_id,
        attached_targets=[{"target_type": "edge", "target_id": str(edge_1["edge_id"])}],
        observed_outcome="first edge degraded",
        expected_difference="second route should remain untouched",
        failure_reason="single relation failure",
        severity="medium",
        reporter="tester",
    )

    service = FailureImpactService(store)
    impact = service.apply_failure(
        workspace_id=workspace_id,
        failure_id=str(failure["failure_id"]),
        request_id="req_slice8_unit_edge_exact",
    )

    assert impact["affected_route_ids"] == [str(route_1["route_id"])]
    refreshed_route_1 = store.get_route(str(route_1["route_id"]))
    refreshed_route_2 = store.get_route(str(route_2["route_id"]))
    assert refreshed_route_1 is not None and refreshed_route_1["status"] == "weakened"
    assert refreshed_route_2 is not None and refreshed_route_2["status"] == "active"


def test_slice8_version_diff_service_outputs_required_categories() -> None:
    service = VersionDiffService()
    before = {
        "nodes": {
            "node_a": {"status": "active", "node_type": "evidence"},
            "node_b": {"status": "active", "node_type": "assumption"},
        },
        "edges": {
            "edge_ab": {"status": "active", "edge_type": "supports"},
        },
        "routes": {
            "route_1": {
                "status": "active",
                "support_score": 72.0,
                "risk_score": 21.0,
                "progressability_score": 66.0,
            }
        },
    }
    after = {
        "nodes": {
            "node_a": {"status": "weakened", "node_type": "evidence"},
            "node_b": {"status": "failed", "node_type": "assumption"},
            "node_gap_1": {"status": "active", "node_type": "gap"},
            "node_branch_1": {"status": "active", "node_type": "branch"},
        },
        "edges": {
            "edge_ab": {"status": "invalidated", "edge_type": "supports"},
            "edge_branch_1": {"status": "active", "edge_type": "branches_to"},
        },
        "routes": {
            "route_1": {
                "status": "weakened",
                "support_score": 58.0,
                "risk_score": 44.0,
                "progressability_score": 51.0,
            }
        },
    }

    diff_payload = service.build_diff_payload(
        failure_id="failure_x",
        base_version_id="ver_before",
        new_version_id="ver_after",
        before_snapshot=before,
        after_snapshot=after,
        route_impacts=[
            {
                "route_id": "route_1",
                "version_id": "ver_after",
                "base_version_id": "ver_before",
                "status_before": "active",
                "status_after": "weakened",
                "route_edge_ids": ["edge_ab"],
                "impacted_edge_ids": ["edge_ab"],
                "impacted_node_ids": ["node_a", "node_b"],
                "reason": "failure failure_x touched canonical route edges",
            }
        ],
    )

    assert set(diff_payload.keys()) >= {
        "failure_id",
        "base_version_id",
        "new_version_id",
        "added",
        "weakened",
        "invalidated",
        "branch_changes",
        "route_score_changes",
        "route_impacts",
    }
    assert "node_gap_1" in diff_payload["added"]["nodes"]
    assert "node_a" in diff_payload["weakened"]["nodes"]
    assert "node_b" in diff_payload["invalidated"]["nodes"]
    assert "edge_ab" in diff_payload["invalidated"]["edges"]
    assert "node_branch_1" in diff_payload["branch_changes"]["created_branch_node_ids"]
    assert diff_payload["route_score_changes"][0]["route_id"] == "route_1"
    assert diff_payload["route_impacts"][0]["route_id"] == "route_1"
    assert diff_payload["route_impacts"][0]["route_edge_ids"] == ["edge_ab"]
