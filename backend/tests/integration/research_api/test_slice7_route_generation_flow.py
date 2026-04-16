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
            "x-request-id": f"req_slice7_extract_{title}",
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
            headers={"x-request-id": f"req_slice7_confirm_{title}_{candidate_id}"},
        )
        if confirmed.status_code == 200:
            confirmed_count += 1
            continue
        assert confirmed.status_code == 409, confirmed.text
    assert confirmed_count > 0
    return source_id


def _prepare_graph_ready_workspace(client: TestClient, workspace_id: str) -> None:
    _import_extract_confirm_all(
        client,
        workspace_id=workspace_id,
        title="slice7 source 1",
        content="Claim: retrieval improves precision. Assumption: embeddings stay stable. Validation: run ablation.",
    )
    _import_extract_confirm_all(
        client,
        workspace_id=workspace_id,
        title="slice7 source 2",
        content="Claim: retrieval harms latency. Assumption: queue saturation. Conflict: baseline mismatch. Failure: timeout spikes.",
    )
    built = client.post(
        f"/api/v1/research/graph/{workspace_id}/build",
        headers={"x-request-id": "req_slice7_graph_build"},
    )
    assert built.status_code == 200


def _private_dependency_pressure(route: dict[str, object]) -> float:
    factors = route.get("score_breakdown", {}).get("risk_score", {}).get("factors", [])
    for factor in factors:
        if factor.get("factor_name") == "private_dependency_pressure":
            return float(factor.get("normalized_value", 1.0))
    return 1.0


def _rank_tuple(route: dict[str, object]) -> tuple[float, float, float, float, str]:
    confidence_score = route.get("confidence_score")
    if confidence_score is None:
        confidence_score = (
            float(route["support_score"])
            + (100.0 - float(route["risk_score"]))
            + float(route["progressability_score"])
        ) / 3.0
    return (
        -float(confidence_score),
        -float(route["support_score"]),
        float(route["risk_score"]),
        -float(route["progressability_score"]),
        _private_dependency_pressure(route),
        str(route["route_id"]),
    )


def test_slice7_dev_console_exposes_route_generation_preview_controls() -> None:
    client = _build_test_client()
    response = client.get("/api/v1/research/dev-console")
    assert response.status_code == 200
    assert "Route Generation + Ranking + Preview" in response.text
    assert "Generate Routes" in response.text
    assert "Load Route Preview" in response.text
    assert "Top 3 Factors" in response.text


def test_slice7_generate_routes_then_list_and_preview_with_traceability() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice7_api"
    _prepare_graph_ready_workspace(client, workspace_id)

    generated = client.post(
        "/api/v1/research/routes/generate",
        json={
            "workspace_id": workspace_id,
            "reason": "generate candidate routes for ranking",
            "max_candidates": 8,
        },
        headers={
            "x-request-id": "req_slice7_generate",
            "x-research-llm-failure-mode": "invalid_json",
            "x-research-llm-allow-fallback": "1",
        },
    )
    assert generated.status_code == 200
    generated_payload = generated.json()
    assert generated_payload["generated_count"] >= 2
    assert generated_payload["ranked_route_ids"]

    listed = client.get(
        "/api/v1/research/routes", params={"workspace_id": workspace_id}
    )
    assert listed.status_code == 200
    list_payload = listed.json()
    assert list_payload["total"] >= 2
    assert list_payload["items"] == sorted(list_payload["items"], key=_rank_tuple)
    semantic_tags = {"direct_support", "recombination", "upstream_inspiration"}
    for item in list_payload["items"]:
        assert isinstance(item.get("confidence_score"), float)
        assert item.get("confidence_grade") in {"low", "medium", "high"}
        relation_tags = item.get("relation_tags") or []
        assert relation_tags
        assert set(relation_tags).issubset(semantic_tags)

    top_route = list_payload["items"][0]
    preview = client.get(
        f"/api/v1/research/routes/{top_route['route_id']}/preview",
        params={"workspace_id": workspace_id},
    )
    assert preview.status_code == 200
    preview_payload = preview.json()
    assert preview_payload["conclusion_node"]["node_id"]
    assert preview_payload["key_support_evidence"] is not None
    assert preview_payload["key_assumptions"] is not None
    assert preview_payload["conflict_failure_hints"] is not None
    assert preview_payload["next_validation_action"]
    assert len(preview_payload["top_factors"]) == 3
    assert preview_payload["trace_refs"]["route_node_ids"]
    assert isinstance(preview_payload["trace_refs"]["route_edge_ids"], list)
    assert preview_payload["summary"]
    assert preview_payload["summary_generation_mode"] in {"llm", "degraded_fallback"}
    if preview_payload["summary_generation_mode"] == "degraded_fallback":
        assert preview_payload["degraded"] is True
        assert preview_payload["fallback_used"] is True
        assert preview_payload["degraded_reason"]
    else:
        assert preview_payload["provider_backend"]
        assert preview_payload["provider_model"]
        assert preview_payload["request_id"] == "req_slice7_generate"
        assert preview_payload["llm_response_id"]
        usage = preview_payload.get("usage") or {}
        assert "prompt_tokens" in usage
        assert "completion_tokens" in usage
        assert "total_tokens" in usage

    with sqlite3.connect(STORE.db_path) as conn:
        route_row = conn.execute(
            """
            SELECT route_edge_ids_json, summary_generation_mode, degraded, fallback_used
            FROM routes
            WHERE route_id = ?
            """,
            (top_route["route_id"],),
        ).fetchone()
    assert route_row is not None
    assert route_row[0] is not None

    with sqlite3.connect(STORE.db_path) as conn:
        event_row = conn.execute(
            """
            SELECT COUNT(*)
            FROM research_events
            WHERE event_name = 'route_generation_completed'
              AND request_id = 'req_slice7_generate'
              AND workspace_id = ?
              AND status = 'completed'
            """,
            (workspace_id,),
        ).fetchone()
    assert event_row is not None and event_row[0] >= 1


def test_slice7_ranking_changes_after_input_change_and_errors_are_explicit() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice7_change"
    _prepare_graph_ready_workspace(client, workspace_id)

    first_generate = client.post(
        "/api/v1/research/routes/generate",
        json={"workspace_id": workspace_id, "reason": "baseline", "max_candidates": 8},
        headers={
            "x-request-id": "req_slice7_first_generate",
            "x-research-llm-failure-mode": "invalid_json",
            "x-research-llm-allow-fallback": "1",
        },
    )
    assert first_generate.status_code == 200
    first_routes = client.get(
        "/api/v1/research/routes", params={"workspace_id": workspace_id}
    ).json()["items"]
    first_order = [item["route_id"] for item in first_routes]
    assert first_order

    node_to_fail = first_routes[0]["conclusion_node_id"]
    updated = client.patch(
        f"/api/v1/research/graph/nodes/{node_to_fail}",
        json={"workspace_id": workspace_id, "status": "failed"},
        headers={"x-request-id": "req_slice7_node_fail"},
    )
    assert updated.status_code == 200

    second_generate = client.post(
        "/api/v1/research/routes/generate",
        json={
            "workspace_id": workspace_id,
            "reason": "after node status change",
            "max_candidates": 8,
        },
        headers={
            "x-request-id": "req_slice7_second_generate",
            "x-research-llm-failure-mode": "invalid_json",
            "x-research-llm-allow-fallback": "1",
        },
    )
    assert second_generate.status_code == 200
    second_routes = client.get(
        "/api/v1/research/routes", params={"workspace_id": workspace_id}
    ).json()["items"]
    second_order = [item["route_id"] for item in second_routes]
    assert first_order != second_order

    bad_generate = client.post(
        "/api/v1/research/routes/generate",
        json={"workspace_id": "bad ws", "reason": "invalid workspace"},
    )
    assert bad_generate.status_code == 400
    assert bad_generate.json()["detail"]["error_code"] == "research.invalid_request"

    missing_preview = client.get(
        "/api/v1/research/routes/route_missing/preview",
        params={"workspace_id": workspace_id},
    )
    assert missing_preview.status_code == 404
    assert missing_preview.json()["detail"]["error_code"] == "research.not_found"
