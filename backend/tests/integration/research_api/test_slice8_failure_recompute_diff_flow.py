from __future__ import annotations

import json
import sqlite3
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from research_layer.api.controllers._state_store import STORE
from research_layer.api.controllers.research_failure_controller import (
    ResearchFailureController,
)
from research_layer.api.controllers.research_graph_controller import (
    ResearchGraphController,
)
from research_layer.api.controllers.research_hypothesis_controller import (
    ResearchHypothesisController,
)
from research_layer.api.controllers.research_job_controller import ResearchJobController
from research_layer.api.controllers.research_package_controller import (
    ResearchPackageController,
)
from research_layer.api.controllers.research_route_controller import (
    ResearchRouteController,
)
from research_layer.api.controllers.research_source_controller import (
    ResearchSourceController,
)
from research_layer.testing.job_helpers import wait_for_job_terminal


def _build_test_client() -> TestClient:
    STORE.reset_all()
    app = FastAPI()
    controllers = [
        ResearchSourceController(),
        ResearchRouteController(),
        ResearchGraphController(),
        ResearchFailureController(),
        ResearchHypothesisController(),
        ResearchPackageController(),
        ResearchJobController(),
    ]
    for controller in controllers:
        controller.register_to_app(app)
    return TestClient(app)


def _import_extract_confirm_all(
    client: TestClient, *, workspace_id: str, title: str, content: str
) -> str:
    imported = client.post(
        "/api/v1/research/sources/import",
        json={
            "workspace_id": workspace_id,
            "source_type": "paper",
            "title": title,
            "content": content,
        },
    )
    assert imported.status_code == 200
    source_id = imported.json()["source_id"]

    extracted = client.post(
        f"/api/v1/research/sources/{source_id}/extract",
        json={"workspace_id": workspace_id, "async_mode": True},
        headers={
            "x-request-id": f"req_slice8_extract_{title}",
            "x-research-llm-failure-mode": "timeout",
            "x-research-llm-allow-fallback": "true",
        },
    )
    assert extracted.status_code == 202
    extract_job = wait_for_job_terminal(
        client, job_id=str(extracted.json()["job_id"])
    )
    assert extract_job["status"] == "succeeded"

    listed = client.get(
        "/api/v1/research/candidates",
        params={"workspace_id": workspace_id, "source_id": source_id},
    )
    assert listed.status_code == 200
    items = listed.json()["items"]
    candidate_ids = [items[0]["candidate_id"]]
    assert candidate_ids
    confirmed = client.post(
        "/api/v1/research/candidates/confirm",
        json={"workspace_id": workspace_id, "candidate_ids": candidate_ids},
        headers={"x-request-id": f"req_slice8_confirm_{title}"},
    )
    assert confirmed.status_code == 200
    return source_id


def _prepare_workspace_with_graph_and_routes(client: TestClient, workspace_id: str) -> None:
    _import_extract_confirm_all(
        client,
        workspace_id=workspace_id,
        title="slice8 source 1",
        content="Claim: retrieval improves precision. Assumption: warm cache. Validation: run ablation.",
    )
    _import_extract_confirm_all(
        client,
        workspace_id=workspace_id,
        title="slice8 source 2",
        content="Claim: retrieval harms latency. Assumption: queue saturation. Conflict: baseline mismatch. Failure: timeout spikes.",
    )
    built = client.post(
        f"/api/v1/research/graph/{workspace_id}/build",
        headers={"x-request-id": "req_slice8_graph_build"},
    )
    assert built.status_code == 200
    generated = client.post(
        "/api/v1/research/routes/generate",
        json={
            "workspace_id": workspace_id,
            "reason": "slice8 baseline route generation",
            "max_candidates": 8,
        },
        headers={
            "x-request-id": "req_slice8_generate_baseline",
            "x-research-llm-failure-mode": "timeout",
            "x-research-llm-allow-fallback": "true",
        },
    )
    assert generated.status_code == 200
    assert generated.json()["generated_count"] > 0


def _ensure_route_edge_baseline(client: TestClient, workspace_id: str) -> None:
    graph = client.get(f"/api/v1/research/graph/{workspace_id}")
    assert graph.status_code == 200
    graph_payload = graph.json()
    active_nodes = [node for node in graph_payload["nodes"] if node["status"] == "active"]
    assert len(active_nodes) >= 2
    created = client.post(
        "/api/v1/research/graph/edges",
        json={
            "workspace_id": workspace_id,
            "source_node_id": active_nodes[0]["node_id"],
            "target_node_id": active_nodes[1]["node_id"],
            "edge_type": "supports",
            "object_ref_type": "relation",
            "object_ref_id": f"rel_{workspace_id}",
            "strength": 0.8,
        },
        headers={"x-request-id": f"req_slice8_edge_baseline_{workspace_id}"},
    )
    assert created.status_code == 200
    regenerated = client.post(
        "/api/v1/research/routes/generate",
        json={
            "workspace_id": workspace_id,
            "reason": "slice8 baseline route regeneration with edge",
            "max_candidates": 8,
        },
        headers={
            "x-request-id": f"req_slice8_regenerate_{workspace_id}",
            "x-research-llm-failure-mode": "timeout",
            "x-research-llm-allow-fallback": "true",
        },
    )
    assert regenerated.status_code == 200


def _null_route_edge_ids_for_workspace(workspace_id: str) -> None:
    with sqlite3.connect(STORE.db_path) as conn:
        conn.execute(
            "UPDATE routes SET route_edge_ids_json = NULL WHERE workspace_id = ?",
            (workspace_id,),
        )
        conn.commit()


def _set_route_edge_ids_raw_for_workspace(workspace_id: str, raw: str) -> None:
    with sqlite3.connect(STORE.db_path) as conn:
        conn.execute(
            "UPDATE routes SET route_edge_ids_json = ? WHERE workspace_id = ?",
            (raw, workspace_id),
        )
        conn.commit()


def _active_evidence_node_id(client: TestClient, workspace_id: str) -> str:
    graph = client.get(f"/api/v1/research/graph/{workspace_id}")
    assert graph.status_code == 200
    nodes = graph.json()["nodes"]
    active_evidence = next(
        node
        for node in nodes
        if node["node_type"] == "evidence" and node["status"] == "active"
    )
    return active_evidence["node_id"]


def _first_route_id(client: TestClient, workspace_id: str) -> str:
    listed = client.get("/api/v1/research/routes", params={"workspace_id": workspace_id})
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert items
    return str(items[0]["route_id"])


def test_slice8_dev_console_exposes_failure_recompute_diff_controls() -> None:
    client = _build_test_client()
    response = client.get("/api/v1/research/dev-console")
    assert response.status_code == 200
    assert "Failure Loop + Recompute + Version Diff" in response.text
    assert "Attach Failure" in response.text
    assert "Recompute From Failure" in response.text
    assert "Load Job Status" in response.text
    assert "Load Version Diff" in response.text


def test_slice8_validation_result_validated_is_persisted_without_recompute() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice8_validation_validated"
    _prepare_workspace_with_graph_and_routes(client, workspace_id)
    route_id = _first_route_id(client, workspace_id)

    created_validation = client.post(
        "/api/v1/research/validations",
        json={
            "workspace_id": workspace_id,
            "target_object": f"route:{route_id}",
            "method": "run deterministic benchmark",
            "success_signal": "support score improves",
            "weakening_signal": "support score drops",
        },
        headers={"x-request-id": "req_slice8_validation_create"},
    )
    assert created_validation.status_code == 200
    validation_id = created_validation.json()["validation_id"]

    submitted = client.post(
        f"/api/v1/research/validations/{validation_id}/results",
        json={
            "workspace_id": workspace_id,
            "outcome": "validated",
            "note": "benchmark passed",
        },
        headers={"x-request-id": "req_slice8_validation_submit_validated"},
    )
    assert submitted.status_code == 200
    payload = submitted.json()
    assert payload["validation_id"] == validation_id
    assert payload["outcome"] == "validated"
    assert payload["triggered_failure_id"] is None
    assert payload["recompute_job_id"] is None

    validation = STORE.get_validation(validation_id)
    assert validation is not None
    assert validation["status"] == "validated"
    assert validation["latest_outcome"] == "validated"
    assert validation["latest_result_id"] == payload["result_id"]


def test_slice8_recompute_rejects_async_mode_false() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice8_recompute_async_false"
    _prepare_workspace_with_graph_and_routes(client, workspace_id)
    node_id = _active_evidence_node_id(client, workspace_id)

    created = client.post(
        "/api/v1/research/failures",
        json={
            "workspace_id": workspace_id,
            "attached_targets": [{"target_type": "node", "target_id": node_id}],
            "observed_outcome": "async false contract check",
            "expected_difference": "must reject synchronous recompute",
            "failure_reason": "contract enforcement",
            "severity": "high",
            "reporter": "slice8_tester",
        },
        headers={"x-request-id": "req_slice8_recompute_async_false_attach"},
    )
    assert created.status_code == 200
    created_payload = created.json()
    assert created_payload["impact_summary"] == {}
    assert created_payload["impact_updated_at"] is None
    assert created_payload["derived_from_validation_id"] is None
    assert created_payload["derived_from_validation_result_id"] is None

    response = client.post(
        "/api/v1/research/routes/recompute",
        json={
            "workspace_id": workspace_id,
            "failure_id": created_payload["failure_id"],
            "reason": "contract check",
            "async_mode": False,
        },
        headers={"x-request-id": "req_slice8_recompute_async_false"},
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["error_code"] == "research.invalid_request"
    assert "async_mode must be true" in detail["message"]


def test_slice8_validation_result_weakened_triggers_failure_and_recompute() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice8_validation_weakened"
    _prepare_workspace_with_graph_and_routes(client, workspace_id)
    route_id = _first_route_id(client, workspace_id)

    created_validation = client.post(
        "/api/v1/research/validations",
        json={
            "workspace_id": workspace_id,
            "target_object": f"route:{route_id}",
            "method": "run deterministic benchmark",
            "success_signal": "support score improves",
            "weakening_signal": "support score drops",
        },
        headers={"x-request-id": "req_slice8_validation_create_weakened"},
    )
    assert created_validation.status_code == 200
    validation_id = created_validation.json()["validation_id"]

    submitted = client.post(
        f"/api/v1/research/validations/{validation_id}/results",
        json={
            "workspace_id": workspace_id,
            "outcome": "weakened",
            "note": "benchmark regressed",
        },
        headers={"x-request-id": "req_slice8_validation_submit_weakened"},
    )
    assert submitted.status_code == 200
    payload = submitted.json()
    assert payload["validation_id"] == validation_id
    assert payload["outcome"] == "weakened"
    assert payload["triggered_failure_id"]
    assert payload["recompute_job_id"]
    assert payload["triggered_failure"]["failure_id"] == payload["triggered_failure_id"]
    assert (
        payload["triggered_failure"]["impact_summary"]["failure_id"]
        == payload["triggered_failure_id"]
    )
    assert payload["triggered_failure"]["impact_updated_at"] is not None
    assert (
        payload["triggered_failure"]["derived_from_validation_id"] == validation_id
    )
    assert (
        payload["triggered_failure"]["derived_from_validation_result_id"]
        == payload["result_id"]
    )

    job_payload = wait_for_job_terminal(
        client, job_id=str(payload["recompute_job_id"])
    )
    assert job_payload["status"] == "succeeded"
    assert job_payload["result_ref"]["resource_type"] == "graph_version"

    failure = STORE.get_failure(str(payload["triggered_failure_id"]))
    assert failure is not None
    assert failure["impact_summary"]["failure_id"] == str(payload["triggered_failure_id"])
    assert failure["impact_updated_at"] is not None
    assert failure["derived_from_validation_id"] == validation_id
    assert failure["derived_from_validation_result_id"] == payload["result_id"]
    validation = STORE.get_validation(validation_id)
    assert validation is not None
    assert validation["status"] == "weakened"
    assert validation["latest_result_id"] == payload["result_id"]


def test_slice8_validation_result_failed_triggers_failure_and_recompute() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice8_validation_failed"
    _prepare_workspace_with_graph_and_routes(client, workspace_id)
    route_id = _first_route_id(client, workspace_id)

    created_validation = client.post(
        "/api/v1/research/validations",
        json={
            "workspace_id": workspace_id,
            "target_object": f"route:{route_id}",
            "method": "run deterministic benchmark",
            "success_signal": "support score improves",
            "weakening_signal": "support score drops",
        },
        headers={"x-request-id": "req_slice8_validation_create_failed"},
    )
    assert created_validation.status_code == 200
    validation_id = created_validation.json()["validation_id"]

    submitted = client.post(
        f"/api/v1/research/validations/{validation_id}/results",
        json={
            "workspace_id": workspace_id,
            "outcome": "failed",
            "note": "benchmark collapsed",
        },
        headers={"x-request-id": "req_slice8_validation_submit_failed"},
    )
    assert submitted.status_code == 200
    payload = submitted.json()
    assert payload["validation_id"] == validation_id
    assert payload["outcome"] == "failed"
    assert payload["triggered_failure_id"]
    assert payload["recompute_job_id"]
    assert payload["triggered_failure"]["failure_id"] == payload["triggered_failure_id"]
    assert (
        payload["triggered_failure"]["derived_from_validation_id"] == validation_id
    )
    assert (
        payload["triggered_failure"]["derived_from_validation_result_id"]
        == payload["result_id"]
    )
    assert payload["triggered_failure"]["severity"] == "high"

    job_payload = wait_for_job_terminal(
        client, job_id=str(payload["recompute_job_id"])
    )
    assert job_payload["status"] == "succeeded"

    failure = STORE.get_failure(str(payload["triggered_failure_id"]))
    assert failure is not None
    assert failure["derived_from_validation_id"] == validation_id
    assert failure["derived_from_validation_result_id"] == payload["result_id"]

    validation = STORE.get_validation(validation_id)
    assert validation is not None
    assert validation["status"] == "failed"
    assert validation["latest_result_id"] == payload["result_id"]


def test_slice8_validation_result_is_persisted_even_when_recompute_fails() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice8_validation_recompute_fail_persist"
    _prepare_workspace_with_graph_and_routes(client, workspace_id)
    route_id = _first_route_id(client, workspace_id)

    created_validation = client.post(
        "/api/v1/research/validations",
        json={
            "workspace_id": workspace_id,
            "target_object": f"route:{route_id}",
            "method": "run deterministic benchmark",
            "success_signal": "support score improves",
            "weakening_signal": "support score drops",
        },
        headers={"x-request-id": "req_slice8_validation_create_persist"},
    )
    assert created_validation.status_code == 200
    validation_id = created_validation.json()["validation_id"]

    graph_payload = client.get(f"/api/v1/research/graph/{workspace_id}").json()
    for node in graph_payload["nodes"]:
        client.patch(
            f"/api/v1/research/graph/nodes/{node['node_id']}",
            json={"workspace_id": workspace_id, "status": "archived"},
        )

    submitted = client.post(
        f"/api/v1/research/validations/{validation_id}/results",
        json={
            "workspace_id": workspace_id,
            "outcome": "weakened",
            "note": "force recompute failure after result persistence",
        },
        headers={"x-request-id": "req_slice8_validation_submit_persist_fail"},
    )
    assert submitted.status_code == 409
    detail = submitted.json()["detail"]
    assert detail["error_code"] == "research.invalid_state"
    assert detail["details"]["validation_id"] == validation_id
    assert detail["details"]["result_id"]
    assert detail["details"]["recompute_job_id"]
    assert detail["details"]["triggered_failure_id"]

    validation = STORE.get_validation(validation_id)
    assert validation is not None
    assert validation["status"] == "weakened"
    assert validation["latest_result_id"] == detail["details"]["result_id"]

    with sqlite3.connect(STORE.db_path) as conn:
        row = conn.execute(
            """
            SELECT result_id, triggered_failure_id, recompute_job_id
            FROM validation_results
            WHERE result_id = ?
            """,
            (detail["details"]["result_id"],),
        ).fetchone()
    assert row is not None
    assert row[0] == detail["details"]["result_id"]
    assert row[1] == detail["details"]["triggered_failure_id"]
    assert row[2] == detail["details"]["recompute_job_id"]

    recompute_job = STORE.get_job(str(detail["details"]["recompute_job_id"]))
    assert recompute_job is not None
    assert recompute_job["status"] == "failed"

    failure = STORE.get_failure(str(detail["details"]["triggered_failure_id"]))
    assert failure is not None
    assert failure["impact_summary"] == {}
    assert failure["impact_updated_at"] is None
    assert failure["derived_from_validation_id"] == validation_id
    assert (
        failure["derived_from_validation_result_id"]
        == detail["details"]["result_id"]
    )


def test_slice8_failure_attach_node_then_recompute_diff_and_traceability() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice8_node_flow"
    _prepare_workspace_with_graph_and_routes(client, workspace_id)

    graph = client.get(f"/api/v1/research/graph/{workspace_id}")
    assert graph.status_code == 200
    graph_payload = graph.json()
    target_node = next(
        node
        for node in graph_payload["nodes"]
        if node["node_type"] == "evidence" and node["status"] == "active"
    )

    attach = client.post(
        "/api/v1/research/failures",
        json={
            "workspace_id": workspace_id,
            "attached_targets": [{"target_type": "node", "target_id": target_node["node_id"]}],
            "observed_outcome": "retrieval precision regressed",
            "expected_difference": "precision should stay high",
            "failure_reason": "new index skew",
            "severity": "high",
            "reporter": "slice8_tester",
        },
        headers={"x-request-id": "req_slice8_attach_node"},
    )
    assert attach.status_code == 200
    failure_id = attach.json()["failure_id"]

    recompute = client.post(
        "/api/v1/research/routes/recompute",
        json={
            "workspace_id": workspace_id,
            "failure_id": failure_id,
            "reason": "recompute after attached node failure",
            "async_mode": True,
        },
        headers={"x-request-id": "req_slice8_recompute_node"},
    )
    assert recompute.status_code == 202
    job_id = recompute.json()["job_id"]

    job_payload = wait_for_job_terminal(client, job_id=str(job_id))
    assert job_payload["status"] == "succeeded"
    assert job_payload["result_ref"]["resource_type"] == "graph_version"
    version_id = job_payload["result_ref"]["resource_id"]

    failure_detail = client.get(f"/api/v1/research/failures/{failure_id}")
    assert failure_detail.status_code == 200
    failure_payload = failure_detail.json()
    assert failure_payload["failure_id"] == failure_id
    assert failure_payload["impact_summary"]["failure_id"] == failure_id
    assert target_node["node_id"] in (
        failure_payload["impact_summary"]["weakened_node_ids"]
        + failure_payload["impact_summary"]["invalidated_node_ids"]
    )
    assert failure_payload["impact_updated_at"] is not None
    assert failure_payload["derived_from_validation_id"] is None
    assert failure_payload["derived_from_validation_result_id"] is None

    with sqlite3.connect(STORE.db_path) as conn:
        conn.execute(
            """
            UPDATE failures
            SET impact_summary_json = ?, impact_updated_at = NULL
            WHERE failure_id = ?
            """,
            ("{}", failure_id),
        )
        conn.commit()

    backfilled = client.get(f"/api/v1/research/failures/{failure_id}")
    assert backfilled.status_code == 200
    backfilled_payload = backfilled.json()
    assert backfilled_payload["impact_summary"]["failure_id"] == failure_id
    assert backfilled_payload["impact_updated_at"] is not None

    with sqlite3.connect(STORE.db_path) as conn:
        stored_row = conn.execute(
            """
            SELECT impact_summary_json, impact_updated_at
            FROM failures
            WHERE failure_id = ?
            """,
            (failure_id,),
        ).fetchone()
    assert stored_row is not None
    assert "weakened_node_ids" in (stored_row[0] or "")
    assert stored_row[1] is not None

    diff = client.get(f"/api/v1/research/versions/{version_id}/diff")
    assert diff.status_code == 200
    diff_payload = diff.json()["diff_payload"]
    assert set(diff_payload.keys()) >= {
        "added",
        "weakened",
        "invalidated",
        "branch_changes",
        "route_impacts",
    }
    assert target_node["node_id"] in (
        diff_payload["weakened"]["nodes"] + diff_payload["invalidated"]["nodes"]
    )
    assert diff_payload["route_impacts"]
    assert all(item["version_id"] == version_id for item in diff_payload["route_impacts"])
    assert any(target_node["node_id"] in item["impacted_node_ids"] for item in diff_payload["route_impacts"])

    routes = client.get("/api/v1/research/routes", params={"workspace_id": workspace_id})
    assert routes.status_code == 200
    route_items = routes.json()["items"]
    assert route_items
    assert any(item["status"] in {"weakened", "failed"} for item in route_items)
    assert any(item.get("version_id") == version_id for item in route_items)

    refreshed_graph = client.get(f"/api/v1/research/graph/{workspace_id}")
    assert refreshed_graph.status_code == 200
    nodes = refreshed_graph.json()["nodes"]
    node_map = {node["node_id"]: node for node in nodes}
    assert node_map[target_node["node_id"]]["status"] in {"weakened", "failed"}
    assert any(node["node_type"] in {"gap", "branch"} for node in nodes)

    with sqlite3.connect(STORE.db_path) as conn:
        recompute_events = conn.execute(
            """
            SELECT event_name, job_id, refs_json
            FROM research_events
            WHERE workspace_id = ?
              AND request_id = 'req_slice8_recompute_node'
              AND event_name IN ('recompute_started', 'recompute_completed', 'diff_created')
            ORDER BY timestamp ASC, rowid ASC
            """,
            (workspace_id,),
        ).fetchall()
        failure_recorded_events = conn.execute(
            """
            SELECT COUNT(*)
            FROM research_events
            WHERE workspace_id = ?
              AND request_id = 'req_slice8_attach_node'
              AND event_name = 'failure_recorded'
            """,
            (workspace_id,),
        ).fetchone()
        failure_attached_event = conn.execute(
            """
            SELECT refs_json
            FROM research_events
            WHERE workspace_id = ?
              AND request_id = 'req_slice8_recompute_node'
              AND event_name = 'failure_attached'
            ORDER BY timestamp DESC, rowid DESC
            LIMIT 1
            """,
            (workspace_id,),
        ).fetchone()
    assert recompute_events is not None and len(recompute_events) >= 3
    for event_name, job_ref, refs_json in recompute_events:
        assert job_ref == job_id
        assert "route_ids" in refs_json
        if event_name != "recompute_started":
            assert version_id in refs_json
    assert failure_recorded_events is not None and failure_recorded_events[0] == 1
    assert failure_attached_event is not None
    failure_attached_refs = json.loads(str(failure_attached_event[0]))
    assert failure_attached_refs["failure_id"] == failure_id
    assert failure_attached_refs["impact_summary"]["failure_id"] == failure_id


def test_slice8_failure_attach_edge_changes_edge_and_scores_and_diff() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice8_edge_flow"
    _prepare_workspace_with_graph_and_routes(client, workspace_id)
    _ensure_route_edge_baseline(client, workspace_id)

    graph = client.get(f"/api/v1/research/graph/{workspace_id}")
    assert graph.status_code == 200
    target_edge = graph.json()["edges"][0]

    attach = client.post(
        "/api/v1/research/failures",
        json={
            "workspace_id": workspace_id,
            "attached_targets": [{"target_type": "edge", "target_id": target_edge["edge_id"]}],
            "observed_outcome": "support relation broke",
            "expected_difference": "edge should stay active",
            "failure_reason": "dependency broken",
            "severity": "medium",
            "reporter": "slice8_tester",
        },
        headers={"x-request-id": "req_slice8_attach_edge"},
    )
    assert attach.status_code == 200
    failure_id = attach.json()["failure_id"]

    recompute = client.post(
        "/api/v1/research/routes/recompute",
        json={
            "workspace_id": workspace_id,
            "failure_id": failure_id,
            "reason": "recompute after edge failure",
            "async_mode": True,
        },
        headers={"x-request-id": "req_slice8_recompute_edge"},
    )
    assert recompute.status_code == 202
    job = wait_for_job_terminal(client, job_id=str(recompute.json()["job_id"]))
    assert job["status"] == "succeeded"
    version_id = str(job["result_ref"]["resource_id"])

    diff = client.get(f"/api/v1/research/versions/{version_id}/diff")
    assert diff.status_code == 200
    diff_payload = diff.json()["diff_payload"]
    assert target_edge["edge_id"] in (
        diff_payload["weakened"]["edges"] + diff_payload["invalidated"]["edges"]
    )
    assert diff_payload["route_score_changes"]
    assert diff_payload["route_impacts"]
    assert any(
        target_edge["edge_id"] in item["impacted_edge_ids"]
        for item in diff_payload["route_impacts"]
    )
    changed_edge_ids = set(
        diff_payload["weakened"]["edges"] + diff_payload["invalidated"]["edges"]
    )
    for item in diff_payload["route_impacts"]:
        route_edge_ids = set(item.get("route_edge_ids") or [])
        impacted_edge_ids = set(item.get("impacted_edge_ids") or [])
        assert impacted_edge_ids.issubset(route_edge_ids)
        assert impacted_edge_ids.issubset(changed_edge_ids)

    score_changes = diff_payload["route_score_changes"]
    assert any(
        change["support_score_before"] != change["support_score_after"]
        or change["risk_score_before"] != change["risk_score_after"]
        or change["progressability_score_before"]
        != change["progressability_score_after"]
        for change in score_changes
    )

    refreshed_graph = client.get(f"/api/v1/research/graph/{workspace_id}")
    edge_map = {edge["edge_id"]: edge for edge in refreshed_graph.json()["edges"]}
    assert edge_map[target_edge["edge_id"]]["status"] in {"weakened", "invalidated"}


def test_slice8_attach_validation_errors_duplicate_and_async_failure_terminal_state() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice8_error_flow"
    _prepare_workspace_with_graph_and_routes(client, workspace_id)
    node_id = _active_evidence_node_id(client, workspace_id)

    duplicated_attach = client.post(
        "/api/v1/research/failures",
        json={
            "workspace_id": workspace_id,
            "attached_targets": [
                {"target_type": "node", "target_id": node_id},
                {"target_type": "node", "target_id": node_id},
            ],
            "observed_outcome": "dup",
            "expected_difference": "dup",
            "failure_reason": "dup",
            "severity": "low",
            "reporter": "slice8_tester",
        },
    )
    assert duplicated_attach.status_code == 409
    assert duplicated_attach.json()["detail"]["error_code"] == "research.invalid_state"

    missing_target = client.post(
        "/api/v1/research/failures",
        json={
            "workspace_id": workspace_id,
            "attached_targets": [{"target_type": "node", "target_id": "node_missing"}],
            "observed_outcome": "missing",
            "expected_difference": "missing",
            "failure_reason": "missing",
            "severity": "low",
            "reporter": "slice8_tester",
        },
    )
    assert missing_target.status_code == 404
    assert missing_target.json()["detail"]["error_code"] == "research.not_found"

    created = client.post(
        "/api/v1/research/failures",
        json={
            "workspace_id": workspace_id,
            "attached_targets": [{"target_type": "node", "target_id": node_id}],
            "observed_outcome": "force recompute failure",
            "expected_difference": "should still rank",
            "failure_reason": "manual outage",
            "severity": "critical",
            "reporter": "slice8_tester",
        },
        headers={"x-request-id": "req_slice8_attach_for_failed_job"},
    )
    assert created.status_code == 200
    failure_id = created.json()["failure_id"]
    baseline_routes = client.get(
        "/api/v1/research/routes",
        params={"workspace_id": workspace_id},
    )
    assert baseline_routes.status_code == 200
    baseline_route_ids = sorted(
        str(item["route_id"]) for item in baseline_routes.json()["items"]
    )
    assert baseline_route_ids

    graph_after_attach = client.get(f"/api/v1/research/graph/{workspace_id}").json()
    for node in graph_after_attach["nodes"]:
        client.patch(
            f"/api/v1/research/graph/nodes/{node['node_id']}",
            json={"workspace_id": workspace_id, "status": "archived"},
        )

    recompute = client.post(
        "/api/v1/research/routes/recompute",
        json={
            "workspace_id": workspace_id,
            "failure_id": failure_id,
            "reason": "expect recompute failure because graph unavailable",
            "async_mode": True,
        },
        headers={"x-request-id": "req_slice8_recompute_failed"},
    )
    assert recompute.status_code == 202
    failed_job_id = recompute.json()["job_id"]
    failed_payload = wait_for_job_terminal(client, job_id=str(failed_job_id))
    assert failed_payload["status"] == "failed"
    assert failed_payload["error"]["error_code"] == "research.invalid_state"
    routes_after_failure = client.get(
        "/api/v1/research/routes",
        params={"workspace_id": workspace_id},
    )
    assert routes_after_failure.status_code == 200
    route_ids_after_failure = sorted(
        str(item["route_id"]) for item in routes_after_failure.json()["items"]
    )
    assert route_ids_after_failure == baseline_route_ids

    failed_event = None
    for _ in range(20):
        with sqlite3.connect(STORE.db_path) as conn:
            failed_event = conn.execute(
                """
                SELECT COUNT(*)
                FROM research_events
                WHERE workspace_id = ?
                  AND request_id = 'req_slice8_recompute_failed'
                  AND event_name = 'job_failed'
                """,
                (workspace_id,),
            ).fetchone()
        if failed_event is not None and failed_event[0] >= 1:
            break
        time.sleep(0.05)
    assert failed_event is not None and failed_event[0] >= 1


def test_slice8_failure_invalid_severity_returns_explicit_validation_error() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice8_invalid_severity"
    _prepare_workspace_with_graph_and_routes(client, workspace_id)
    node_id = _active_evidence_node_id(client, workspace_id)

    invalid = client.post(
        "/api/v1/research/failures",
        json={
            "workspace_id": workspace_id,
            "attached_targets": [{"target_type": "node", "target_id": node_id}],
            "observed_outcome": "bad severity",
            "expected_difference": "should validate",
            "failure_reason": "bad payload",
            "severity": "urgent",
            "reporter": "slice8_tester",
        },
    )

    assert invalid.status_code == 400
    assert invalid.json()["detail"]["error_code"] == "research.invalid_request"


def test_slice8_recompute_requires_persisted_routes_and_never_generates_them() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice8_no_routes"
    _prepare_workspace_with_graph_and_routes(client, workspace_id)
    node_id = _active_evidence_node_id(client, workspace_id)

    with sqlite3.connect(STORE.db_path) as conn:
        conn.execute("DELETE FROM routes WHERE workspace_id = ?", (workspace_id,))
        conn.commit()

    created = client.post(
        "/api/v1/research/failures",
        json={
            "workspace_id": workspace_id,
            "attached_targets": [{"target_type": "node", "target_id": node_id}],
            "observed_outcome": "no routes",
            "expected_difference": "recompute should fail explicitly",
            "failure_reason": "route baseline missing",
            "severity": "high",
            "reporter": "slice8_tester",
        },
        headers={"x-request-id": "req_slice8_no_routes_attach"},
    )
    assert created.status_code == 200

    recompute = client.post(
        "/api/v1/research/routes/recompute",
        json={
            "workspace_id": workspace_id,
            "failure_id": created.json()["failure_id"],
            "reason": "route baseline must exist before recompute",
            "async_mode": True,
        },
        headers={"x-request-id": "req_slice8_no_routes_recompute"},
    )

    assert recompute.status_code == 202
    failed_job = wait_for_job_terminal(client, job_id=str(recompute.json()["job_id"]))
    assert failed_job["status"] == "failed"
    assert failed_job["error"]["error_code"] == "research.invalid_state"

    with sqlite3.connect(STORE.db_path) as conn:
        route_generation_events = conn.execute(
            """
            SELECT COUNT(*)
            FROM research_events
            WHERE workspace_id = ?
              AND request_id = 'req_slice8_no_routes_recompute'
              AND event_name = 'route_generation_started'
            """,
            (workspace_id,),
        ).fetchone()
    assert route_generation_events is not None and route_generation_events[0] == 0


def test_slice8_recompute_fails_when_canonical_route_edge_source_is_missing() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice8_missing_route_edges"
    _prepare_workspace_with_graph_and_routes(client, workspace_id)
    node_id = _active_evidence_node_id(client, workspace_id)
    _null_route_edge_ids_for_workspace(workspace_id)

    created = client.post(
        "/api/v1/research/failures",
        json={
            "workspace_id": workspace_id,
            "attached_targets": [{"target_type": "node", "target_id": node_id}],
            "observed_outcome": "canonical route replay source missing",
            "expected_difference": "explicit diff failure",
            "failure_reason": "legacy route row",
            "severity": "high",
            "reporter": "slice8_tester",
        },
        headers={"x-request-id": "req_slice8_missing_edges_attach"},
    )
    assert created.status_code == 200

    recompute = client.post(
        "/api/v1/research/routes/recompute",
        json={
            "workspace_id": workspace_id,
            "failure_id": created.json()["failure_id"],
            "reason": "missing canonical route replay source must fail",
            "async_mode": True,
        },
        headers={"x-request-id": "req_slice8_missing_edges_recompute"},
    )

    assert recompute.status_code == 202
    failed_job = wait_for_job_terminal(client, job_id=str(recompute.json()["job_id"]))
    assert failed_job["status"] == "failed"
    assert failed_job["error"]["error_code"] == "research.version_diff_unavailable"


def test_slice8_recompute_fails_when_canonical_route_edge_source_is_malformed() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice8_malformed_route_edges"
    _prepare_workspace_with_graph_and_routes(client, workspace_id)
    node_id = _active_evidence_node_id(client, workspace_id)
    _set_route_edge_ids_raw_for_workspace(workspace_id, "{bad-json")

    created = client.post(
        "/api/v1/research/failures",
        json={
            "workspace_id": workspace_id,
            "attached_targets": [{"target_type": "node", "target_id": node_id}],
            "observed_outcome": "canonical route replay source malformed",
            "expected_difference": "explicit diff failure",
            "failure_reason": "legacy route row",
            "severity": "high",
            "reporter": "slice8_tester",
        },
        headers={"x-request-id": "req_slice8_malformed_edges_attach"},
    )
    assert created.status_code == 200

    recompute = client.post(
        "/api/v1/research/routes/recompute",
        json={
            "workspace_id": workspace_id,
            "failure_id": created.json()["failure_id"],
            "reason": "malformed canonical route replay source must fail",
            "async_mode": True,
        },
        headers={"x-request-id": "req_slice8_malformed_edges_recompute"},
    )

    assert recompute.status_code == 202
    failed_job = wait_for_job_terminal(client, job_id=str(recompute.json()["job_id"]))
    assert failed_job["status"] == "failed"
    assert failed_job["error"]["error_code"] == "research.version_diff_unavailable"


def test_slice8_recompute_fails_when_canonical_route_edge_source_is_non_array() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice8_nonarray_route_edges"
    _prepare_workspace_with_graph_and_routes(client, workspace_id)
    node_id = _active_evidence_node_id(client, workspace_id)
    _set_route_edge_ids_raw_for_workspace(workspace_id, '"not-an-array"')

    created = client.post(
        "/api/v1/research/failures",
        json={
            "workspace_id": workspace_id,
            "attached_targets": [{"target_type": "node", "target_id": node_id}],
            "observed_outcome": "canonical route replay source non-array",
            "expected_difference": "explicit diff failure",
            "failure_reason": "legacy route row",
            "severity": "high",
            "reporter": "slice8_tester",
        },
        headers={"x-request-id": "req_slice8_nonarray_edges_attach"},
    )
    assert created.status_code == 200

    recompute = client.post(
        "/api/v1/research/routes/recompute",
        json={
            "workspace_id": workspace_id,
            "failure_id": created.json()["failure_id"],
            "reason": "non-array canonical route replay source must fail",
            "async_mode": True,
        },
        headers={"x-request-id": "req_slice8_nonarray_edges_recompute"},
    )

    assert recompute.status_code == 202
    failed_job = wait_for_job_terminal(client, job_id=str(recompute.json()["job_id"]))
    assert failed_job["status"] == "failed"
    assert failed_job["error"]["error_code"] == "research.version_diff_unavailable"


def test_slice8_recompute_fails_when_canonical_route_edge_source_has_non_string_member() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice8_nonstr_route_edges"
    _prepare_workspace_with_graph_and_routes(client, workspace_id)
    node_id = _active_evidence_node_id(client, workspace_id)
    _set_route_edge_ids_raw_for_workspace(workspace_id, '[1, \"edge_ok\"]')

    created = client.post(
        "/api/v1/research/failures",
        json={
            "workspace_id": workspace_id,
            "attached_targets": [{"target_type": "node", "target_id": node_id}],
            "observed_outcome": "canonical route replay source non-string member",
            "expected_difference": "explicit diff failure",
            "failure_reason": "legacy route row",
            "severity": "high",
            "reporter": "slice8_tester",
        },
        headers={"x-request-id": "req_slice8_nonstr_edges_attach"},
    )
    assert created.status_code == 200

    recompute = client.post(
        "/api/v1/research/routes/recompute",
        json={
            "workspace_id": workspace_id,
            "failure_id": created.json()["failure_id"],
            "reason": "non-string member canonical route replay source must fail",
            "async_mode": True,
        },
        headers={"x-request-id": "req_slice8_nonstr_edges_recompute"},
    )

    assert recompute.status_code == 202
    failed_job = wait_for_job_terminal(client, job_id=str(recompute.json()["job_id"]))
    assert failed_job["status"] == "failed"
    assert failed_job["error"]["error_code"] == "research.version_diff_unavailable"


def test_slice8_recompute_failure_not_found_returns_404() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice8_failure_not_found"
    _prepare_workspace_with_graph_and_routes(client, workspace_id)

    recompute = client.post(
        "/api/v1/research/routes/recompute",
        json={
            "workspace_id": workspace_id,
            "failure_id": "failure_missing",
            "reason": "missing failure should fail",
            "async_mode": True,
        },
        headers={"x-request-id": "req_slice8_failure_not_found"},
    )

    assert recompute.status_code == 404
    assert recompute.json()["detail"]["error_code"] == "research.not_found"


def test_slice8_recompute_workspace_mismatch_returns_409() -> None:
    client = _build_test_client()
    source_workspace = "ws_slice8_workspace_mismatch_src"
    target_workspace = "ws_slice8_workspace_mismatch_dst"
    _prepare_workspace_with_graph_and_routes(client, source_workspace)
    _prepare_workspace_with_graph_and_routes(client, target_workspace)
    node_id = _active_evidence_node_id(client, source_workspace)

    created = client.post(
        "/api/v1/research/failures",
        json={
            "workspace_id": source_workspace,
            "attached_targets": [{"target_type": "node", "target_id": node_id}],
            "observed_outcome": "workspace mismatch",
            "expected_difference": "explicit conflict",
            "failure_reason": "ownership mismatch",
            "severity": "high",
            "reporter": "slice8_tester",
        },
        headers={"x-request-id": "req_slice8_workspace_mismatch_attach"},
    )
    assert created.status_code == 200

    recompute = client.post(
        "/api/v1/research/routes/recompute",
        json={
            "workspace_id": target_workspace,
            "failure_id": created.json()["failure_id"],
            "reason": "workspace mismatch should fail",
            "async_mode": True,
        },
        headers={"x-request-id": "req_slice8_workspace_mismatch_recompute"},
    )

    assert recompute.status_code == 409
    assert recompute.json()["detail"]["error_code"] == "research.conflict"


def test_slice8_get_missing_version_diff_returns_404() -> None:
    client = _build_test_client()
    response = client.get("/api/v1/research/versions/ver_missing/diff")
    assert response.status_code == 404
    assert response.json()["detail"]["error_code"] == "research.not_found"
