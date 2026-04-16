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
from research_layer.api.controllers.research_retrieval_controller import (
    ResearchRetrievalController,
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
        ResearchRetrievalController(),
        ResearchPackageController(),
        ResearchJobController(),
    ]
    for controller in controllers:
        controller.register_to_app(app)
    return TestClient(app)


def _seed_track6_workspace(client: TestClient, workspace_id: str) -> dict[str, str]:
    imported = client.post(
        "/api/v1/research/sources/import",
        json={
            "workspace_id": workspace_id,
            "source_type": "paper",
            "title": "track6 memory source",
            "content": (
                "Evidence: retrieval precision improved on benchmark replay. "
                "Assumption: cache warmness is stable across shards. "
                "Conflict: baseline mismatch appears under low-memory condition. "
                "Failure: timeout pattern repeats when queue is saturated. "
                "Validation: run replay benchmark with shard isolation."
            ),
        },
    )
    assert imported.status_code == 200
    source_id = imported.json()["source_id"]

    extracted = client.post(
        f"/api/v1/research/sources/{source_id}/extract",
        json={"workspace_id": workspace_id, "async_mode": True},
        headers={
            "x-research-llm-failure-mode": "invalid_json",
            "x-research-llm-allow-fallback": "1",
        },
    )
    assert extracted.status_code == 202
    extract_job = wait_for_job_terminal(
        client, job_id=str(extracted.json()["job_id"])
    )
    assert extract_job["status"] == "succeeded"

    candidates = client.get(
        "/api/v1/research/candidates",
        params={"workspace_id": workspace_id, "source_id": source_id},
    )
    assert candidates.status_code == 200
    candidate_ids = [item["candidate_id"] for item in candidates.json()["items"]]
    assert candidate_ids

    confirmed_count = 0
    for candidate_id in candidate_ids:
        confirmed = client.post(
            "/api/v1/research/candidates/confirm",
            json={"workspace_id": workspace_id, "candidate_ids": [candidate_id]},
            headers={"x-request-id": f"req_track6_confirm_{candidate_id}"},
        )
        if confirmed.status_code == 200:
            confirmed_count += 1
            continue
        assert confirmed.status_code == 409, confirmed.text
    assert confirmed_count > 0

    graph_build = client.post(
        f"/api/v1/research/graph/{workspace_id}/build",
        headers={"x-request-id": "req_track6_graph_build"},
    )
    assert graph_build.status_code == 200

    routes = client.post(
        "/api/v1/research/routes/generate",
        json={
            "workspace_id": workspace_id,
            "reason": "track6 memory binding seed",
            "max_candidates": 8,
        },
        headers={
            "x-request-id": "req_track6_generate_routes",
            "x-research-llm-failure-mode": "invalid_json",
            "x-research-llm-allow-fallback": "1",
        },
    )
    assert routes.status_code == 200
    route_ids = routes.json()["ranked_route_ids"]
    assert route_ids

    return {"source_id": source_id, "route_id": route_ids[0]}


def _first_memory_item(client: TestClient, workspace_id: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/research/memory/list",
        json={
            "workspace_id": workspace_id,
            "view_types": ["evidence", "contradiction", "failure_pattern"],
            "query": "retrieval benchmark timeout conflict",
            "retrieve_method": "hybrid",
            "top_k_per_view": 20,
        },
        headers={"x-request-id": "req_track6_memory_list_for_item"},
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert items
    return items[0]


def test_track6_dev_console_exposes_memory_vault_controlled_action_controls() -> None:
    client = _build_test_client()
    response = client.get("/api/v1/research/dev-console")
    assert response.status_code == 200
    assert "Load Memory Vault" in response.text
    assert "Bind Memory To Current Route" in response.text
    assert "Memory -> Hypothesis Candidate" in response.text


def test_track6_memory_list_is_retrieval_backed_read_model() -> None:
    client = _build_test_client()
    workspace_id = "ws_track6_memory_list"
    seeded = _seed_track6_workspace(client, workspace_id)

    response = client.post(
        "/api/v1/research/memory/list",
        json={
            "workspace_id": workspace_id,
            "view_types": ["evidence", "validation_history"],
            "query": "retrieval precision benchmark",
            "retrieve_method": "hybrid",
            "top_k_per_view": 20,
            "metadata_filters_by_view": {
                "evidence": {"source_id": [seeded["source_id"]]},
                "validation_history": {},
            },
        },
        headers={"x-request-id": "req_track6_memory_list"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["read_model_kind"] == "retrieval_backed_read_model"
    assert payload["workspace_id"] == workspace_id
    assert payload["total"] >= 1
    assert payload["controlled_action_semantics"]["open_in_workbench"] == "navigation_only"
    assert payload["controlled_action_semantics"]["bind_to_current_route"] == "backend_controlled_action"
    assert (
        payload["controlled_action_semantics"]["memory_to_hypothesis_candidate"]
        == "backend_controlled_action"
    )
    assert payload["tool_capability_refs"]["scenario"] == "memory_assisted_reasoning"
    assert payload["tool_capability_refs"]["chain_length"] >= 2
    assert payload["tool_capability_refs"]["selected_chain"][0]["tool_id"] == "retrieval_views"
    first = payload["items"][0]
    assert first["read_model_kind"] == "retrieval_backed"
    assert first["memory_id"]
    assert first["memory_view_type"] in {"evidence", "validation_history"}
    assert "trace_refs" in first
    assert "retrieval_context" in first


def test_track6_bind_to_current_route_is_persisted_and_traceable() -> None:
    client = _build_test_client()
    workspace_id = "ws_track6_bind_route"
    seeded = _seed_track6_workspace(client, workspace_id)
    memory = _first_memory_item(client, workspace_id)

    bind_response = client.post(
        "/api/v1/research/memory/actions/bind-to-current-route",
        json={
            "workspace_id": workspace_id,
            "route_id": seeded["route_id"],
            "memory_id": memory["memory_id"],
            "memory_view_type": memory["memory_view_type"],
            "note": "bind memory into current route context",
        },
        headers={"x-request-id": "req_track6_bind_route"},
    )
    assert bind_response.status_code == 200
    bind_payload = bind_response.json()
    assert bind_payload["action_type"] == "bind_to_current_route"
    assert bind_payload["workspace_id"] == workspace_id
    assert bind_payload["route_id"] == seeded["route_id"]
    assert bind_payload["memory_id"] == memory["memory_id"]
    assert bind_payload["memory_view_type"] == memory["memory_view_type"]
    assert bind_payload["binding_status"] == "bound"
    assert bind_payload["validation_action"]["target_object"] == f"route:{seeded['route_id']}"

    duplicate = client.post(
        "/api/v1/research/memory/actions/bind-to-current-route",
        json={
            "workspace_id": workspace_id,
            "route_id": seeded["route_id"],
            "memory_id": memory["memory_id"],
            "memory_view_type": memory["memory_view_type"],
            "note": "duplicate bind should fail",
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["error_code"] == "research.invalid_state"

    with sqlite3.connect(STORE.db_path) as conn:
        conn.row_factory = sqlite3.Row
        action_row = conn.execute(
            """
            SELECT action_type, route_id, memory_result_id, memory_view_type, validation_id
            FROM memory_actions
            WHERE action_id = ?
            """,
            (bind_payload["action_id"],),
        ).fetchone()
        assert action_row is not None
        assert action_row["action_type"] == "bind_to_current_route"
        assert action_row["route_id"] == seeded["route_id"]
        assert action_row["memory_result_id"] == memory["memory_id"]
        assert action_row["memory_view_type"] == memory["memory_view_type"]
        assert action_row["validation_id"] == bind_payload["validation_action"]["validation_id"]


def test_track6_memory_to_hypothesis_candidate_uses_formal_hypothesis_flow() -> None:
    client = _build_test_client()
    workspace_id = "ws_track6_memory_hypothesis"
    _seed_track6_workspace(client, workspace_id)
    memory = _first_memory_item(client, workspace_id)

    action = client.post(
        "/api/v1/research/memory/actions/memory-to-hypothesis-candidate",
        json={
            "workspace_id": workspace_id,
            "memory_id": memory["memory_id"],
            "memory_view_type": memory["memory_view_type"],
            "note": "spawn hypothesis candidate from memory",
        },
        headers={"x-request-id": "req_track6_memory_to_hypothesis"},
    )
    assert action.status_code == 200
    payload = action.json()
    assert payload["action_type"] == "memory_to_hypothesis_candidate"
    assert payload["workspace_id"] == workspace_id
    assert payload["memory_id"] == memory["memory_id"]
    assert payload["memory_view_type"] == memory["memory_view_type"]
    assert payload["hypothesis"]["status"] == "candidate"
    hypothesis_id = payload["hypothesis"]["hypothesis_id"]

    hypothesis = client.get(f"/api/v1/research/hypotheses/{hypothesis_id}")
    assert hypothesis.status_code == 200
    hypothesis_payload = hypothesis.json()
    assert hypothesis_payload["status"] == "candidate"
    first_trigger = hypothesis_payload["trigger_refs"][0]
    assert first_trigger["trace_refs"]["memory_result_id"] == memory["memory_id"]
    assert first_trigger["trace_refs"]["memory_view_type"] == memory["memory_view_type"]

    with sqlite3.connect(STORE.db_path) as conn:
        conn.row_factory = sqlite3.Row
        action_row = conn.execute(
            """
            SELECT action_type, hypothesis_id, memory_result_id, memory_view_type
            FROM memory_actions
            WHERE action_id = ?
            """,
            (payload["action_id"],),
        ).fetchone()
        assert action_row is not None
        assert action_row["action_type"] == "memory_to_hypothesis_candidate"
        assert action_row["hypothesis_id"] == hypothesis_id
        assert action_row["memory_result_id"] == memory["memory_id"]
        assert action_row["memory_view_type"] == memory["memory_view_type"]


def test_track6_memory_actions_validate_workspace_route_and_view_contract() -> None:
    client = _build_test_client()
    workspace_id = "ws_track6_action_errors"
    seeded = _seed_track6_workspace(client, workspace_id)
    memory = _first_memory_item(client, workspace_id)

    missing_route = client.post(
        "/api/v1/research/memory/actions/bind-to-current-route",
        json={
            "workspace_id": workspace_id,
            "route_id": "route_not_found",
            "memory_id": memory["memory_id"],
            "memory_view_type": memory["memory_view_type"],
            "note": "route missing",
        },
    )
    assert missing_route.status_code == 404
    assert missing_route.json()["detail"]["error_code"] == "research.not_found"

    conflict_workspace = client.post(
        "/api/v1/research/memory/actions/bind-to-current-route",
        json={
            "workspace_id": "ws_other_workspace",
            "route_id": seeded["route_id"],
            "memory_id": memory["memory_id"],
            "memory_view_type": memory["memory_view_type"],
            "note": "workspace mismatch",
        },
    )
    assert conflict_workspace.status_code == 409
    assert conflict_workspace.json()["detail"]["error_code"] == "research.conflict"

    invalid_view = client.post(
        "/api/v1/research/memory/actions/memory-to-hypothesis-candidate",
        json={
            "workspace_id": workspace_id,
            "memory_id": memory["memory_id"],
            "memory_view_type": "unsupported_view",
            "note": "invalid view type",
        },
    )
    assert invalid_view.status_code == 400
    assert invalid_view.json()["detail"]["error_code"] == "research.invalid_request"
