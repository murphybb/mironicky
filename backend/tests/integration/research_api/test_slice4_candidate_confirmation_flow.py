from __future__ import annotations

import sqlite3

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


def _import_extract_and_list(
    client: TestClient, *, workspace_id: str, content: str
) -> tuple[str, list[dict[str, object]]]:
    imported = client.post(
        "/api/v1/research/sources/import",
        json={
            "workspace_id": workspace_id,
            "source_type": "paper",
            "title": "slice4",
            "content": content,
        },
    )
    assert imported.status_code == 200
    source_id = imported.json()["source_id"]

    started = client.post(
        f"/api/v1/research/sources/{source_id}/extract",
        json={"workspace_id": workspace_id, "async_mode": True},
        headers={
            "x-research-llm-failure-mode": "timeout",
            "x-research-llm-allow-fallback": "true",
        },
    )
    assert started.status_code == 202
    extract_job = wait_for_job_terminal(client, job_id=str(started.json()["job_id"]))
    assert extract_job["status"] == "succeeded"

    listed = client.get(
        "/api/v1/research/candidates",
        params={"workspace_id": workspace_id, "source_id": source_id},
    )
    assert listed.status_code == 200
    return source_id, listed.json()["items"]


def test_slice4_dev_console_contains_candidate_confirmation_actions() -> None:
    client = _build_test_client()
    response = client.get("/api/v1/research/dev-console")
    assert response.status_code == 200
    assert "Candidate List" in response.text
    assert "Candidate Detail" in response.text
    assert "Confirm Candidate" in response.text
    assert "Reject Candidate" in response.text
    assert "/api/v1/research/candidates/confirm" in response.text
    assert "/api/v1/research/candidates/reject" in response.text


def test_confirm_flow_persists_formal_object_and_materializes_graph_version() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice4_confirm"
    source_id, items = _import_extract_and_list(
        client,
        workspace_id=workspace_id,
        content="Claim: confirmation should produce formal evidence.",
    )
    assert items
    candidate_id = items[0]["candidate_id"]

    extraction_result = client.get(
        f"/api/v1/research/sources/{source_id}/extraction-results/{items[0]['candidate_batch_id']}",
        params={"workspace_id": workspace_id},
    )
    assert extraction_result.status_code == 200
    assert extraction_result.json()["candidate_ids"]

    confirmed = client.post(
        "/api/v1/research/candidates/confirm",
        json={"workspace_id": workspace_id, "candidate_ids": [candidate_id]},
        headers={"x-request-id": "req_slice4_confirm"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"

    detail = client.get(
        f"/api/v1/research/candidates/{candidate_id}",
        params={"workspace_id": workspace_id},
    )
    assert detail.status_code == 200
    assert detail.json()["status"] == "confirmed"

    with sqlite3.connect(STORE.db_path) as conn:
        obj_count = conn.execute(
            "SELECT COUNT(*) FROM research_evidences WHERE candidate_id = ?",
            (candidate_id,),
        ).fetchone()[0]
        event_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM research_events
            WHERE event_name = 'candidate_confirmed'
              AND request_id = 'req_slice4_confirm'
              AND workspace_id = ?
            """,
            (workspace_id,),
        ).fetchone()[0]
    assert obj_count == 1
    assert event_count >= 1

    graph_after = client.get(f"/api/v1/research/graph/{workspace_id}")
    assert graph_after.status_code == 200
    assert graph_after.json()["nodes"]
    assert graph_after.json()["edges"] == [] or isinstance(
        graph_after.json()["edges"], list
    )

    versions = client.get(
        "/api/v1/research/versions", params={"workspace_id": workspace_id}
    )
    assert versions.status_code == 200
    assert versions.json()["items"]
    version_id = versions.json()["items"][-1]["version_id"]
    diff = client.get(f"/api/v1/research/versions/{version_id}/diff")
    assert diff.status_code == 200
    assert diff.json()["version_id"] == version_id
    assert "added" in diff.json()["diff_payload"]


def test_reject_flow_and_repeat_operations_use_explicit_error_semantics() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice4_reject"
    _, items = _import_extract_and_list(
        client,
        workspace_id=workspace_id,
        content="Assumption: reject path should remain explicit.",
    )
    candidate_id = items[0]["candidate_id"]

    rejected = client.post(
        "/api/v1/research/candidates/reject",
        json={
            "workspace_id": workspace_id,
            "candidate_ids": [candidate_id],
            "reason": "manual reject",
        },
        headers={"x-request-id": "req_slice4_reject"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"

    repeat_reject = client.post(
        "/api/v1/research/candidates/reject",
        json={
            "workspace_id": workspace_id,
            "candidate_ids": [candidate_id],
            "reason": "repeat reject",
        },
    )
    assert repeat_reject.status_code == 409
    assert repeat_reject.json()["detail"]["error_code"] == "research.invalid_state"

    repeat_confirm = client.post(
        "/api/v1/research/candidates/confirm",
        json={"workspace_id": workspace_id, "candidate_ids": [candidate_id]},
    )
    assert repeat_confirm.status_code == 409
    assert repeat_confirm.json()["detail"]["error_code"] == "research.invalid_state"


def test_confirm_duplicate_candidate_returns_conflict_signal() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice4_conflict"
    _, first_items = _import_extract_and_list(
        client,
        workspace_id=workspace_id,
        content="Claim: duplicate conflict should be signaled clearly.",
    )
    _, second_items = _import_extract_and_list(
        client,
        workspace_id=workspace_id,
        content="Claim: duplicate conflict should be signaled clearly.",
    )
    first_id = first_items[0]["candidate_id"]
    second_id = second_items[0]["candidate_id"]

    first_confirm = client.post(
        "/api/v1/research/candidates/confirm",
        json={"workspace_id": workspace_id, "candidate_ids": [first_id]},
    )
    assert first_confirm.status_code == 200

    second_confirm = client.post(
        "/api/v1/research/candidates/confirm",
        json={"workspace_id": workspace_id, "candidate_ids": [second_id]},
        headers={"x-request-id": "req_slice4_conflict"},
    )
    assert second_confirm.status_code == 409
    payload = second_confirm.json()["detail"]
    assert payload["error_code"] == "research.conflict"
    assert payload["details"]["reason"] == "duplicate_confirmed_object"


def test_invalid_json_fallback_confirms_multiple_types_without_cross_type_conflict() -> (
    None
):
    client = _build_test_client()
    workspace_id = "ws_slice4_fallback_cross_type"
    imported = client.post(
        "/api/v1/research/sources/import",
        json={
            "workspace_id": workspace_id,
            "source_type": "paper",
            "title": "slice4 fallback cross type",
            "content": (
                "Claim: rerank improves answer quality. "
                "Assumption: cache remains warm. "
                "Conflict: latency budget is inconsistent. "
                "Failure: queue timed out. "
                "Validation: run replay benchmark."
            ),
        },
    )
    assert imported.status_code == 200
    source_id = imported.json()["source_id"]

    started = client.post(
        f"/api/v1/research/sources/{source_id}/extract",
        json={"workspace_id": workspace_id, "async_mode": True},
        headers={
            "x-research-llm-failure-mode": "invalid_json",
            "x-research-llm-allow-fallback": "true",
        },
    )
    assert started.status_code == 202
    extract_job = wait_for_job_terminal(client, job_id=str(started.json()["job_id"]))
    assert extract_job["status"] == "succeeded"

    listed = client.get(
        "/api/v1/research/candidates",
        params={"workspace_id": workspace_id, "source_id": source_id},
    )
    assert listed.status_code == 200
    items = listed.json()["items"]
    candidates_by_type = {item["candidate_type"]: item for item in items}
    assert {"evidence", "assumption", "conflict", "failure", "validation"}.issubset(
        candidates_by_type
    )
    assert (
        len(
            {
                candidates_by_type[candidate_type]["text"]
                for candidate_type in (
                    "evidence",
                    "assumption",
                    "conflict",
                    "failure",
                    "validation",
                )
            }
        )
        == 5
    )

    for candidate_type in (
        "evidence",
        "assumption",
        "conflict",
        "failure",
        "validation",
    ):
        candidate_id = candidates_by_type[candidate_type]["candidate_id"]
        confirmed = client.post(
            "/api/v1/research/candidates/confirm",
            json={"workspace_id": workspace_id, "candidate_ids": [candidate_id]},
            headers={"x-request-id": f"req_slice4_fallback_{candidate_type}"},
        )
        assert confirmed.status_code == 200, confirmed.text


def test_slice4_no_bypass_chain_from_extract_result_ref_to_confirm_graph_version_events() -> (
    None
):
    client = _build_test_client()
    workspace_id = "ws_slice4_no_bypass"
    source_id, items = _import_extract_and_list(
        client,
        workspace_id=workspace_id,
        content=(
            "Claim: no bypass chain must rely on real extraction output. "
            "Assumption: graph and version are created by program logic."
        ),
    )
    assert items
    candidate_id = items[0]["candidate_id"]
    candidate_batch_id = items[0]["candidate_batch_id"]
    assert candidate_batch_id

    extraction_result = client.get(
        f"/api/v1/research/sources/{source_id}/extraction-results/{candidate_batch_id}",
        params={"workspace_id": workspace_id},
    )
    assert extraction_result.status_code == 200
    result_payload = extraction_result.json()
    assert candidate_id in result_payload["candidate_ids"]
    assert result_payload["job_id"]

    confirm = client.post(
        "/api/v1/research/candidates/confirm",
        json={"workspace_id": workspace_id, "candidate_ids": [candidate_id]},
        headers={"x-request-id": "req_slice4_no_bypass"},
    )
    assert confirm.status_code == 200

    versions = client.get(
        "/api/v1/research/versions", params={"workspace_id": workspace_id}
    )
    assert versions.status_code == 200
    version_items = versions.json()["items"]
    assert version_items
    latest_version_id = version_items[-1]["version_id"]
    diff = client.get(f"/api/v1/research/versions/{latest_version_id}/diff")
    assert diff.status_code == 200

    with sqlite3.connect(STORE.db_path) as conn:
        chain_events = conn.execute(
            """
            SELECT event_name
            FROM research_events
            WHERE workspace_id = ?
              AND request_id = 'req_slice4_no_bypass'
              AND event_name IN ('candidate_confirmed', 'graph_materialization_completed', 'graph_version_created')
            ORDER BY timestamp ASC, rowid ASC
            """,
            (workspace_id,),
        ).fetchall()
    assert [row[0] for row in chain_events] == [
        "candidate_confirmed",
        "graph_materialization_completed",
        "graph_version_created",
    ]


def test_confirm_persistence_failure_returns_explicit_error_and_leaves_no_residual_state(
    monkeypatch,
) -> None:
    client = _build_test_client()
    workspace_id = "ws_slice4_no_residual_failure"
    _, items = _import_extract_and_list(
        client,
        workspace_id=workspace_id,
        content="Claim: confirm failure should not leave partial durable state.",
    )
    candidate_id = items[0]["candidate_id"]

    def _raise(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("forced version persistence failure")

    monkeypatch.setattr(STORE, "create_graph_version", _raise)

    confirm = client.post(
        "/api/v1/research/candidates/confirm",
        json={"workspace_id": workspace_id, "candidate_ids": [candidate_id]},
        headers={"x-request-id": "req_slice4_no_residual_failure"},
    )
    assert confirm.status_code == 409
    payload = confirm.json()["detail"]
    assert payload["error_code"] == "research.version_diff_unavailable"

    detail = client.get(
        f"/api/v1/research/candidates/{candidate_id}",
        params={"workspace_id": workspace_id},
    )
    assert detail.status_code == 200
    assert detail.json()["status"] == "pending"

    with sqlite3.connect(STORE.db_path) as conn:
        confirmed_count = conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM research_evidences WHERE candidate_id = ?)
              + (SELECT COUNT(*) FROM research_assumptions WHERE candidate_id = ?)
              + (SELECT COUNT(*) FROM research_conflicts WHERE candidate_id = ?)
              + (SELECT COUNT(*) FROM research_failures WHERE candidate_id = ?)
              + (SELECT COUNT(*) FROM research_validations WHERE candidate_id = ?)
            """,
            (candidate_id, candidate_id, candidate_id, candidate_id, candidate_id),
        ).fetchone()[0]
        graph_node_count = conn.execute(
            "SELECT COUNT(*) FROM graph_nodes WHERE workspace_id = ?", (workspace_id,)
        ).fetchone()[0]
        graph_edge_count = conn.execute(
            "SELECT COUNT(*) FROM graph_edges WHERE workspace_id = ?", (workspace_id,)
        ).fetchone()[0]
        version_count = conn.execute(
            "SELECT COUNT(*) FROM graph_versions WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone()[0]
        workspace_count = conn.execute(
            "SELECT COUNT(*) FROM graph_workspaces WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone()[0]
        success_event_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM research_events
            WHERE request_id = 'req_slice4_no_residual_failure'
              AND workspace_id = ?
              AND event_name IN (
                'candidate_confirmed',
                'graph_materialization_completed',
                'graph_version_created'
              )
            """,
            (workspace_id,),
        ).fetchone()[0]
        failed_event_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM research_events
            WHERE request_id = 'req_slice4_no_residual_failure'
              AND workspace_id = ?
              AND event_name = 'candidate_confirmation_failed'
            """,
            (workspace_id,),
        ).fetchone()[0]

    assert confirmed_count == 0
    assert graph_node_count == 0
    assert graph_edge_count == 0
    assert version_count == 0
    assert workspace_count == 0
    assert success_event_count == 0
    assert failed_event_count == 1


def test_workspace_id_validation_and_traceability_fields_are_preserved() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice4_trace"
    _, items = _import_extract_and_list(
        client,
        workspace_id=workspace_id,
        content="Validation: ensure traceability survives confirmation.",
    )
    target = next(
        (item for item in items if item["candidate_type"] == "validation"), items[0]
    )
    candidate_id = target["candidate_id"]

    missing_workspace = client.post(
        "/api/v1/research/candidates/confirm", json={"candidate_ids": [candidate_id]}
    )
    assert missing_workspace.status_code == 400
    assert (
        missing_workspace.json()["detail"]["error_code"] == "research.invalid_request"
    )

    wrong_workspace = client.get(
        f"/api/v1/research/candidates/{candidate_id}",
        params={"workspace_id": "ws_other"},
    )
    assert wrong_workspace.status_code == 409
    assert wrong_workspace.json()["detail"]["error_code"] == "research.conflict"

    confirmed = client.post(
        "/api/v1/research/candidates/confirm",
        json={"workspace_id": workspace_id, "candidate_ids": [candidate_id]},
        headers={"x-request-id": "req_slice4_trace"},
    )
    assert confirmed.status_code == 200

    with sqlite3.connect(STORE.db_path) as conn:
        table_map = {
            "evidence": ("research_evidences", "evidence_id"),
            "assumption": ("research_assumptions", "assumption_id"),
            "conflict": ("research_conflicts", "conflict_id"),
            "failure": ("research_failures", "failure_id"),
            "validation": ("research_validations", "validation_id"),
        }
        table_name, _ = table_map[target["candidate_type"]]
        row = conn.execute(
            """
            SELECT source_id, candidate_batch_id, extraction_job_id
            FROM """
            + table_name
            + """
            WHERE candidate_id = ?
            """,
            (candidate_id,),
        ).fetchone()
    assert row is not None
    assert row[0]
    assert row[1]
    assert row[2]


def _assert_invalid_request_response(response, *, reason_fragment: str) -> None:
    assert response.status_code == 400
    payload = response.json()["detail"]
    assert payload["error_code"] == "research.invalid_request"
    assert payload["message"] == "request validation failed"
    assert "errors" in payload["details"]
    serialized = str(payload["details"]["errors"])
    assert reason_fragment in serialized


def test_slice4_confirmation_endpoints_convert_invalid_request_bodies_into_explicit_400() -> (
    None
):
    client = _build_test_client()
    workspace_id = "ws_slice4_invalid_bodies"
    _, items = _import_extract_and_list(
        client,
        workspace_id=workspace_id,
        content="Claim: invalid request bodies should not leak 500.",
    )
    candidate_id = items[0]["candidate_id"]

    endpoints = [
        (
            "confirm",
            "/api/v1/research/candidates/confirm",
            {"workspace_id": workspace_id, "candidate_ids": [candidate_id]},
        ),
        (
            "reject",
            "/api/v1/research/candidates/reject",
            {
                "workspace_id": workspace_id,
                "candidate_ids": [candidate_id],
                "reason": "invalid body regression",
            },
        ),
    ]

    for _, url, valid_payload in endpoints:
        empty_response = client.post(url)
        _assert_invalid_request_response(
            empty_response, reason_fragment="empty request body"
        )

        bad_json_response = client.post(
            url, data="{bad", headers={"Content-Type": "application/json"}
        )
        _assert_invalid_request_response(
            bad_json_response, reason_fragment="invalid json body"
        )

        for raw_payload in ["[]", '"abc"', "123", "true"]:
            non_object_response = client.post(
                url, data=raw_payload, headers={"Content-Type": "application/json"}
            )
            _assert_invalid_request_response(
                non_object_response, reason_fragment="JSON object"
            )

        missing_workspace_response = client.post(
            url,
            json={
                key: value
                for key, value in valid_payload.items()
                if key != "workspace_id"
            },
        )
        _assert_invalid_request_response(
            missing_workspace_response, reason_fragment="workspace_id"
        )
