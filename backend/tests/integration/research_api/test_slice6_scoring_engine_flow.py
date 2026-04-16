from __future__ import annotations

import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient

from research_layer.api.controllers._state_store import STORE
from research_layer.api.controllers.research_failure_controller import (
    ResearchFailureController,
)
from research_layer.api.controllers.research_graph_controller import ResearchGraphController
from research_layer.api.controllers.research_hypothesis_controller import (
    ResearchHypothesisController,
)
from research_layer.api.controllers.research_job_controller import ResearchJobController
from research_layer.api.controllers.research_package_controller import (
    ResearchPackageController,
)
from research_layer.api.controllers.research_route_controller import ResearchRouteController
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


def _prepare_scoring_ready_route(client: TestClient, *, workspace_id: str) -> tuple[str, str]:
    imported = client.post(
        "/api/v1/research/sources/import",
        json={
            "workspace_id": workspace_id,
            "source_type": "paper",
            "title": "slice6 scoring",
            "content": "Claim: support is strong. Assumption: infra stable. Conflict: external drift. Failure: queue timeout. Validation: run ablation.",
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

    listed = client.get(
        "/api/v1/research/candidates",
        params={"workspace_id": workspace_id, "source_id": source_id},
    )
    assert listed.status_code == 200
    candidate_ids = [item["candidate_id"] for item in listed.json()["items"]]
    assert candidate_ids

    confirmed_count = 0
    for candidate_id in candidate_ids:
        confirmed = client.post(
            "/api/v1/research/candidates/confirm",
            json={"workspace_id": workspace_id, "candidate_ids": [candidate_id]},
            headers={"x-request-id": f"req_slice6_confirm_{candidate_id}"},
        )
        if confirmed.status_code == 200:
            confirmed_count += 1
            continue
        assert confirmed.status_code == 409, confirmed.text
    assert confirmed_count > 0

    built = client.post(
        f"/api/v1/research/graph/{workspace_id}/build",
        headers={"x-request-id": "req_slice6_build"},
    )
    assert built.status_code == 200

    recompute = client.post(
        "/api/v1/research/routes/recompute",
        json={
            "workspace_id": workspace_id,
            "reason": "score baseline route",
            "async_mode": True,
        },
        headers={
            "x-request-id": "req_slice6_recompute",
            "x-research-llm-failure-mode": "invalid_json",
            "x-research-llm-allow-fallback": "1",
        },
    )
    assert recompute.status_code == 202
    job_id = recompute.json()["job_id"]
    route_job = wait_for_job_terminal(client, job_id=str(job_id))
    assert route_job["status"] == "succeeded"
    route_id = str(route_job["result_ref"]["resource_id"])
    assert route_id
    return source_id, route_id


def test_slice6_dev_console_exposes_scoring_controls() -> None:
    client = _build_test_client()
    response = client.get("/api/v1/research/dev-console")
    assert response.status_code == 200
    assert "Route Scoring" in response.text
    assert "Score Route" in response.text
    assert "Recompute Route" in response.text
    assert "/api/v1/research/routes/" in response.text


def test_slice6_scoring_api_returns_scores_breakdown_and_top_factors() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice6_api"
    _, route_id = _prepare_scoring_ready_route(client, workspace_id=workspace_id)

    score = client.post(
        f"/api/v1/research/routes/{route_id}/score",
        json={"workspace_id": workspace_id},
        headers={"x-request-id": "req_slice6_score"},
    )
    assert score.status_code == 200
    payload = score.json()
    assert payload["route_id"] == route_id
    assert payload["workspace_id"] == workspace_id
    assert 0.0 <= payload["support_score"] <= 100.0
    assert 0.0 <= payload["risk_score"] <= 100.0
    assert 0.0 <= payload["progressability_score"] <= 100.0
    assert payload["score_breakdown"]["support_score"]["factors"]
    assert payload["node_score_breakdown"]
    assert len(payload["top_factors"]) == 3

    route_detail = client.get(
        f"/api/v1/research/routes/{route_id}",
        params={"workspace_id": workspace_id},
    )
    assert route_detail.status_code == 200
    detail_payload = route_detail.json()
    assert detail_payload["score_breakdown"]
    assert detail_payload["top_factors"]

    with sqlite3.connect(STORE.db_path) as conn:
        event_row = conn.execute(
            """
            SELECT COUNT(*)
            FROM research_events
            WHERE event_name = 'score_recalculated'
              AND request_id = 'req_slice6_score'
              AND workspace_id = ?
            """,
            (workspace_id,),
        ).fetchone()
    assert event_row is not None and event_row[0] >= 1


def test_slice6_scoring_changes_after_input_update_and_reports_explicit_errors() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice6_change"
    _, route_id = _prepare_scoring_ready_route(client, workspace_id=workspace_id)

    graph = client.get(f"/api/v1/research/graph/{workspace_id}")
    assert graph.status_code == 200
    node_id = graph.json()["nodes"][0]["node_id"]

    first = client.post(
        f"/api/v1/research/routes/{route_id}/score",
        json={"workspace_id": workspace_id, "focus_node_ids": [node_id]},
        headers={"x-request-id": "req_slice6_first"},
    )
    assert first.status_code == 200

    updated = client.patch(
        f"/api/v1/research/graph/nodes/{node_id}",
        json={"workspace_id": workspace_id, "status": "failed"},
        headers={"x-request-id": "req_slice6_node_fail"},
    )
    assert updated.status_code == 200

    second = client.post(
        f"/api/v1/research/routes/{route_id}/score",
        json={"workspace_id": workspace_id, "focus_node_ids": [node_id]},
        headers={"x-request-id": "req_slice6_second"},
    )
    assert second.status_code == 200
    assert first.json()["risk_score"] != second.json()["risk_score"]

    wrong_workspace = client.post(
        f"/api/v1/research/routes/{route_id}/score",
        json={"workspace_id": "ws_other"},
    )
    assert wrong_workspace.status_code == 409
    assert wrong_workspace.json()["detail"]["error_code"] == "research.conflict"

    bad_node = client.post(
        f"/api/v1/research/routes/{route_id}/score",
        json={"workspace_id": workspace_id, "focus_node_ids": ["node_missing"]},
    )
    assert bad_node.status_code == 400
    assert bad_node.json()["detail"]["error_code"] == "research.invalid_request"

    missing_route = client.post(
        "/api/v1/research/routes/route_missing/score",
        json={"workspace_id": workspace_id},
    )
    assert missing_route.status_code == 404
    assert missing_route.json()["detail"]["error_code"] == "research.not_found"
