from __future__ import annotations

import sqlite3

import pytest
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
from research_layer.services.hypothesis_service import HypothesisService
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
) -> None:
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
            "x-request-id": f"req_slice9_extract_{title}",
            "x-research-llm-failure-mode": "invalid_json",
            "x-research-llm-allow-fallback": "1",
        },
    )
    assert extracted.status_code == 202
    extract_job = wait_for_job_terminal(client, job_id=str(extracted.json()["job_id"]))
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
            headers={"x-request-id": f"req_slice9_confirm_{title}_{candidate_id}"},
        )
        if confirmed.status_code == 200:
            confirmed_count += 1
            continue
        assert confirmed.status_code == 409, confirmed.text
    assert confirmed_count > 0


def _prepare_workspace_with_hypothesis_triggers(
    client: TestClient, workspace_id: str
) -> str:
    _import_extract_confirm_all(
        client,
        workspace_id=workspace_id,
        title="slice9 source 1",
        content="Claim: retrieval boosts recall. Assumption: cache is warm. Validation: run targeted benchmark.",
    )
    _import_extract_confirm_all(
        client,
        workspace_id=workspace_id,
        title="slice9 source 2",
        content="Conflict: latency regresses under load. Failure: timeout spikes on shard imbalance.",
    )
    built = client.post(
        f"/api/v1/research/graph/{workspace_id}/build",
        headers={"x-request-id": "req_slice9_graph_build"},
    )
    assert built.status_code == 200

    graph = client.get(f"/api/v1/research/graph/{workspace_id}")
    assert graph.status_code == 200
    target_node = next(
        node for node in graph.json()["nodes"] if node["node_type"] == "evidence"
    )
    graph_workspace = STORE.get_graph_workspace(workspace_id)
    assert graph_workspace is not None
    route = STORE.create_route(
        workspace_id=workspace_id,
        title="slice9 weak support seed route",
        summary="seeded route to expose weak_support trigger contract",
        status="weakened",
        support_score=39.0,
        risk_score=62.0,
        progressability_score=41.0,
        conclusion="need stronger support evidence",
        key_supports=["seed support"],
        assumptions=["seed assumption"],
        risks=["seed risk"],
        next_validation_action="run focused support benchmark",
        route_node_ids=[str(target_node["node_id"])],
        key_support_node_ids=[str(target_node["node_id"])],
        key_assumption_node_ids=[],
        risk_node_ids=[str(target_node["node_id"])],
        conclusion_node_id=str(target_node["node_id"]),
        version_id=str(graph_workspace.get("latest_version_id") or ""),
    )
    return str(route["route_id"])


def test_slice9_dev_console_exposes_hypothesis_controls() -> None:
    client = _build_test_client()
    response = client.get("/api/v1/research/dev-console")
    assert response.status_code == 200
    assert "Hypothesis Engine" in response.text
    assert "Load Hypothesis Triggers" in response.text
    assert "Generate Hypothesis" in response.text
    assert "Load Hypothesis Inbox" in response.text
    assert "Promote Hypothesis" in response.text
    assert "Reject Hypothesis" in response.text
    assert "Defer Hypothesis" in response.text


def test_slice9_hypothesis_invalid_json_fallback_marks_degraded() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice9_hypothesis_invalid_json_fallback"
    request_id = "req_slice9_hypothesis_invalid_json_fallback"
    _prepare_workspace_with_hypothesis_triggers(client, workspace_id)

    trigger_list = client.get(
        "/api/v1/research/hypotheses/triggers/list",
        params={"workspace_id": workspace_id},
    )
    assert trigger_list.status_code == 200
    selected_trigger_id = str(trigger_list.json()["items"][0]["trigger_id"])

    generated = client.post(
        "/api/v1/research/hypotheses/generate",
        json={
            "workspace_id": workspace_id,
            "trigger_ids": [selected_trigger_id],
            "async_mode": True,
        },
        headers={
            "x-request-id": request_id,
            "x-research-llm-failure-mode": "invalid_json",
            "x-research-llm-allow-fallback": "1",
        },
    )
    assert generated.status_code == 202, generated.text
    job_payload = wait_for_job_terminal(client, job_id=str(generated.json()["job_id"]))
    assert job_payload["status"] == "succeeded"
    assert job_payload["result_ref"]["resource_type"] == "hypothesis"

    hypothesis_id = str(job_payload["result_ref"]["resource_id"])
    hypothesis = client.get(f"/api/v1/research/hypotheses/{hypothesis_id}")
    assert hypothesis.status_code == 200, hypothesis.text
    hypothesis_payload = hypothesis.json()
    assert hypothesis_payload["status"] == "candidate"
    assert hypothesis_payload["title"]
    assert hypothesis_payload["statement"]
    assert hypothesis_payload["rationale"]
    assert hypothesis_payload["trigger_refs"][0]["trigger_id"] == selected_trigger_id
    assert hypothesis_payload["fallback_used"] is True
    assert hypothesis_payload["degraded"] is True
    assert hypothesis_payload["degraded_reason"] == "research.llm_invalid_output"

    with sqlite3.connect(STORE.db_path) as conn:
        row = conn.execute(
            """
            SELECT metrics_json
            FROM research_events
            WHERE workspace_id = ?
              AND request_id = ?
              AND event_name = 'hypothesis_generation_completed'
              AND status = 'completed'
            ORDER BY timestamp DESC, event_id DESC
            LIMIT 1
            """,
            (workspace_id, request_id),
        ).fetchone()
    assert row is not None
    assert '"fallback_used": true' in row[0]
    assert '"degraded": true' in row[0]
    assert "research.llm_invalid_output" in row[0]


def test_slice9_hypothesis_generate_promote_reject_defer_flow_and_traceability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_generate_with_llm(
        self: HypothesisService,
        *,
        workspace_id: str,
        request_id: str,
        resolved_triggers: list[dict[str, object]],
        failure_mode: str | None,
    ) -> tuple[dict[str, str], dict[str, object], dict[str, object]]:
        del self, workspace_id, failure_mode
        trigger_ref_ids = [str(item["trigger_id"]) for item in resolved_triggers]
        return (
            {
                "title": "Queue backpressure drives observed latency tail",
                "statement": (
                    "If queue pressure is isolated before retrieval fan-out, "
                    "latency regression should shrink while recall gain remains."
                ),
                "rationale": (
                    "Selected triggers share failure/conflict pressure around the same "
                    "workspace graph/version neighborhood."
                ),
                "testability_hint": "run queue-only pressure test with fixed retrieval depth",
                "novelty_hint": "targets queue bottleneck over embedding quality",
                "confidence_hint": 0.68,
                "suggested_next_steps": [
                    "collect queue metrics",
                    "run controlled replay",
                ],
                "trigger_refs": trigger_ref_ids,
            },
            {
                "provider_backend": "openai",
                "provider_model": "gpt-4.1-mini",
                "request_id": request_id,
                "llm_response_id": "resp_slice9_integration",
            },
            {
                "prompt_tokens": 98,
                "completion_tokens": 51,
                "total_tokens": 149,
                "degraded": False,
                "degraded_reason": None,
            },
        )

    monkeypatch.setattr(
        HypothesisService, "_generate_with_llm", _fake_generate_with_llm
    )
    client = _build_test_client()
    workspace_id = "ws_slice9_flow"
    _prepare_workspace_with_hypothesis_triggers(client, workspace_id)

    routes_before = client.get(
        "/api/v1/research/routes", params={"workspace_id": workspace_id}
    )
    assert routes_before.status_code == 200
    route_items_before = routes_before.json()["items"]
    assert route_items_before
    top_route_before = route_items_before[0]

    trigger_list = client.get(
        "/api/v1/research/hypotheses/triggers/list",
        params={"workspace_id": workspace_id},
    )
    assert trigger_list.status_code == 200
    trigger_payload = trigger_list.json()
    trigger_types = {item["trigger_type"] for item in trigger_payload["items"]}
    assert "weak_support" in trigger_types

    selected_trigger_ids = [item["trigger_id"] for item in trigger_payload["items"][:2]]
    generated = client.post(
        "/api/v1/research/hypotheses/generate",
        json={
            "workspace_id": workspace_id,
            "trigger_ids": selected_trigger_ids,
            "async_mode": True,
        },
        headers={"x-request-id": "req_slice9_generate"},
    )
    assert generated.status_code == 202
    job_id = generated.json()["job_id"]

    job_payload = wait_for_job_terminal(client, job_id=str(job_id))
    assert job_payload["status"] == "succeeded"
    assert job_payload["result_ref"]["resource_type"] == "hypothesis"
    hypothesis_id = job_payload["result_ref"]["resource_id"]

    hypothesis = client.get(f"/api/v1/research/hypotheses/{hypothesis_id}")
    assert hypothesis.status_code == 200
    hypothesis_payload = hypothesis.json()
    assert hypothesis_payload["status"] == "candidate"
    assert hypothesis_payload["stage"] == "exploratory"
    assert hypothesis_payload["title"]
    assert hypothesis_payload["summary"]
    assert hypothesis_payload["premise"]
    assert hypothesis_payload["rationale"]
    assert hypothesis_payload["novelty_typing"] in {
        "conservative",
        "incremental",
        "novel",
        "breakthrough",
    }
    assert hypothesis_payload["trigger_refs"]
    assert hypothesis_payload["related_object_ids"]
    assert hypothesis_payload["minimum_validation_action"]["validation_id"]
    assert hypothesis_payload["weakening_signal"]["signal_type"]
    assert hypothesis_payload["provider_backend"] == "openai"
    assert hypothesis_payload["provider_model"] == "gpt-4.1-mini"
    assert hypothesis_payload["request_id"] == "req_slice9_generate"
    assert hypothesis_payload["llm_response_id"] == "resp_slice9_integration"
    usage = hypothesis_payload.get("usage") or {}
    assert usage.get("prompt_tokens") == 98
    assert usage.get("completion_tokens") == 51
    assert usage.get("total_tokens") == 149
    assert hypothesis_payload.get("fallback_used") is False
    assert hypothesis_payload.get("degraded") is False
    assert hypothesis_payload["testability_hint"]
    assert hypothesis_payload["novelty_hint"]
    assert isinstance(hypothesis_payload["suggested_next_steps"], list)
    assert hypothesis_payload["suggested_next_steps"]

    deferred = client.post(
        f"/api/v1/research/hypotheses/{hypothesis_id}/defer",
        json={
            "workspace_id": workspace_id,
            "note": "defer while collecting more evidence",
            "decision_source_type": "manual",
            "decision_source_ref": "integration_test",
        },
        headers={"x-request-id": "req_slice9_defer"},
    )
    assert deferred.status_code == 200
    deferred_payload = deferred.json()
    assert deferred_payload["status"] == "deferred"
    assert deferred_payload["decision_source_type"] == "manual"

    inbox_after_defer = client.get(
        "/api/v1/research/hypotheses", params={"workspace_id": workspace_id}
    )
    assert inbox_after_defer.status_code == 200
    inbox_items = inbox_after_defer.json()["items"]
    assert any(
        item["hypothesis_id"] == hypothesis_id and item["status"] == "deferred"
        for item in inbox_items
    )

    duplicate_defer = client.post(
        f"/api/v1/research/hypotheses/{hypothesis_id}/defer",
        json={
            "workspace_id": workspace_id,
            "note": "duplicate defer",
            "decision_source_type": "manual",
            "decision_source_ref": "integration_test",
        },
    )
    assert duplicate_defer.status_code == 409
    assert duplicate_defer.json()["detail"]["error_code"] == "research.invalid_state"

    promoted = client.post(
        f"/api/v1/research/hypotheses/{hypothesis_id}/promote",
        json={
            "workspace_id": workspace_id,
            "note": "promote for exploratory validation",
            "decision_source_type": "manual",
            "decision_source_ref": "integration_test",
        },
        headers={"x-request-id": "req_slice9_promote"},
    )
    assert promoted.status_code == 200
    promoted_payload = promoted.json()
    assert promoted_payload["status"] == "promoted_for_validation"
    assert promoted_payload["decision_source_type"] == "manual"
    assert promoted_payload["decision_source_ref"] == "integration_test"

    duplicate_promote = client.post(
        f"/api/v1/research/hypotheses/{hypothesis_id}/promote",
        json={
            "workspace_id": workspace_id,
            "note": "duplicate promote",
            "decision_source_type": "manual",
            "decision_source_ref": "integration_test",
        },
    )
    assert duplicate_promote.status_code == 409
    assert duplicate_promote.json()["detail"]["error_code"] == "research.invalid_state"

    duplicate_generate = client.post(
        "/api/v1/research/hypotheses/generate",
        json={
            "workspace_id": workspace_id,
            "trigger_ids": selected_trigger_ids,
            "async_mode": True,
        },
        headers={"x-request-id": "req_slice9_generate_duplicate"},
    )
    assert duplicate_generate.status_code == 202
    duplicate_job = wait_for_job_terminal(
        client, job_id=str(duplicate_generate.json()["job_id"])
    )
    assert duplicate_job["status"] == "failed"
    assert (
        duplicate_job["error"]["error_code"]
        == "research.duplicate_hypothesis_candidate"
    )
    assert duplicate_job["error"]["details"]["existing_hypothesis_id"] == hypothesis_id

    async def _fake_generate_with_llm_second(
        self: HypothesisService,
        *,
        workspace_id: str,
        request_id: str,
        resolved_triggers: list[dict[str, object]],
        failure_mode: str | None,
    ) -> tuple[dict[str, str], dict[str, object], dict[str, object]]:
        del self, workspace_id, failure_mode
        trigger_ref_ids = [str(item["trigger_id"]) for item in resolved_triggers]
        return (
            {
                "title": "Alternative latency hypothesis branch",
                "statement": (
                    "If shard balancing is introduced before queue build-up, "
                    "latency regression should reduce in peak windows."
                ),
                "rationale": "same trigger set but distinct causal branch hypothesis",
                "testability_hint": "run shard-balance A/B test",
                "novelty_hint": "focuses on shard balancing path",
                "confidence_hint": 0.63,
                "suggested_next_steps": ["enable balancing", "replay traffic"],
                "trigger_refs": trigger_ref_ids,
            },
            {
                "provider_backend": "openai",
                "provider_model": "gpt-4.1-mini",
                "request_id": request_id,
                "llm_response_id": "resp_slice9_integration_second",
            },
            {
                "prompt_tokens": 87,
                "completion_tokens": 44,
                "total_tokens": 131,
                "degraded": False,
                "degraded_reason": None,
            },
        )

    monkeypatch.setattr(
        HypothesisService, "_generate_with_llm", _fake_generate_with_llm_second
    )
    reject_workspace_mismatch = client.post(
        f"/api/v1/research/hypotheses/{hypothesis_id}/reject",
        json={
            "workspace_id": "ws_other",
            "note": "workspace mismatch",
            "decision_source_type": "manual",
            "decision_source_ref": "integration_test",
        },
    )
    assert reject_workspace_mismatch.status_code == 409
    assert (
        reject_workspace_mismatch.json()["detail"]["error_code"] == "research.conflict"
    )

    second_generated = client.post(
        "/api/v1/research/hypotheses/generate",
        json={
            "workspace_id": workspace_id,
            "trigger_ids": [selected_trigger_ids[0]],
            "async_mode": True,
        },
        headers={"x-request-id": "req_slice9_generate_reject"},
    )
    assert second_generated.status_code == 202
    second_job = wait_for_job_terminal(
        client, job_id=str(second_generated.json()["job_id"])
    )
    second_hypothesis_id = str(second_job["result_ref"]["resource_id"])

    rejected = client.post(
        f"/api/v1/research/hypotheses/{second_hypothesis_id}/reject",
        json={
            "workspace_id": workspace_id,
            "note": "reject exploratory candidate",
            "decision_source_type": "manual",
            "decision_source_ref": "integration_test",
        },
        headers={"x-request-id": "req_slice9_reject"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"

    duplicate_reject = client.post(
        f"/api/v1/research/hypotheses/{second_hypothesis_id}/reject",
        json={
            "workspace_id": workspace_id,
            "note": "duplicate reject",
            "decision_source_type": "manual",
            "decision_source_ref": "integration_test",
        },
    )
    assert duplicate_reject.status_code == 409
    assert duplicate_reject.json()["detail"]["error_code"] == "research.invalid_state"

    invalid_trigger = client.post(
        "/api/v1/research/hypotheses/generate",
        json={
            "workspace_id": workspace_id,
            "trigger_ids": ["trigger_not_exist"],
            "async_mode": False,
        },
    )
    assert invalid_trigger.status_code == 400
    assert invalid_trigger.json()["detail"]["error_code"] == "research.invalid_request"

    routes_after = client.get(
        "/api/v1/research/routes", params={"workspace_id": workspace_id}
    )
    assert routes_after.status_code == 200
    assert routes_after.json()["items"][0]["route_id"] == top_route_before["route_id"]
    assert (
        routes_after.json()["items"][0]["conclusion"] == top_route_before["conclusion"]
    )

    with sqlite3.connect(STORE.db_path) as conn:
        event_rows = conn.execute(
            """
            SELECT event_name, COUNT(*)
            FROM research_events
            WHERE workspace_id = ?
              AND event_name IN (
                'hypothesis_generation_started',
                'hypothesis_generation_completed',
                'hypothesis_deferred',
                'hypothesis_promoted',
                'hypothesis_rejected'
              )
            GROUP BY event_name
            """,
            (workspace_id,),
        ).fetchall()
    event_map = {row[0]: row[1] for row in event_rows}
    assert event_map.get("hypothesis_generation_started", 0) >= 2
    assert event_map.get("hypothesis_generation_completed", 0) >= 2
    assert event_map.get("hypothesis_deferred", 0) >= 1
    assert event_map.get("hypothesis_promoted", 0) >= 1
    assert event_map.get("hypothesis_rejected", 0) >= 1
