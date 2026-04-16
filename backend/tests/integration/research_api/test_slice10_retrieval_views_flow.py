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


def _import_extract_confirm_all(
    client: TestClient,
    *,
    workspace_id: str,
    title: str,
    content: str,
    source_type: str = "paper",
    preferred_candidate_type: str | None = None,
) -> str:
    imported = client.post(
        "/api/v1/research/sources/import",
        json={
            "workspace_id": workspace_id,
            "source_type": source_type,
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
    candidate_items = listed.json()["items"]
    assert candidate_items
    ordered_candidates = list(candidate_items)
    forced_candidate_id: str | None = None
    if preferred_candidate_type:
        preferred = [
            item
            for item in candidate_items
            if str(item.get("candidate_type")) == preferred_candidate_type
        ]
        assert preferred, f"missing preferred candidate_type={preferred_candidate_type}"
        forced_candidate_id = str(preferred[0]["candidate_id"])
        forced_confirm = client.post(
            "/api/v1/research/candidates/confirm",
            json={"workspace_id": workspace_id, "candidate_ids": [forced_candidate_id]},
            headers={"x-request-id": f"req_slice10_force_confirm_{title}_{forced_candidate_id}"},
        )
        assert forced_confirm.status_code == 200, forced_confirm.text
        rest = [
            item
            for item in candidate_items
            if str(item.get("candidate_id")) != forced_candidate_id
        ]
        ordered_candidates = rest

    confirmed_count = 1 if forced_candidate_id is not None else 0
    for item in ordered_candidates:
        candidate_id = str(item["candidate_id"])
        confirmed = client.post(
            "/api/v1/research/candidates/confirm",
            json={"workspace_id": workspace_id, "candidate_ids": [candidate_id]},
            headers={"x-request-id": f"req_slice10_confirm_{title}_{candidate_id}"},
        )
        if confirmed.status_code == 200:
            confirmed_count += 1
            continue
        assert confirmed.status_code == 409, confirmed.text
    assert confirmed_count > 0
    return source_id


def _seed_workspace_for_slice10(client: TestClient, workspace_id: str) -> dict[str, str]:
    source_a = _import_extract_confirm_all(
        client,
        workspace_id=workspace_id,
        title="slice10 source A",
        content=(
            "Claim: retrieval precision improved. "
            "Validation: benchmark replay succeeded."
        ),
        preferred_candidate_type="evidence",
    )
    source_b = _import_extract_confirm_all(
        client,
        workspace_id=workspace_id,
        source_type="note",
        title="slice10 source B",
        content=(
            "Claim: timeout latency worsened in retrieval pipeline. "
            "Conflict: baseline mismatch appears. "
            "Failure: timeout pattern repeats under shard imbalance."
        ),
        preferred_candidate_type="conflict",
    )
    source_c = _import_extract_confirm_all(
        client,
        workspace_id=workspace_id,
        title="slice10 source C",
        content=(
            "Claim: timeout latency degraded after shard rebalance. "
            "Validation: replay benchmark confirms instability."
        ),
    )

    graph_build = client.post(
        f"/api/v1/research/graph/{workspace_id}/build",
        headers={"x-request-id": "req_slice10_graph_build"},
    )
    assert graph_build.status_code == 200

    generated = client.post(
        "/api/v1/research/routes/generate",
        json={
            "workspace_id": workspace_id,
            "reason": "slice10 seed routes for weak-support trigger",
            "max_candidates": 8,
        },
        headers={
            "x-request-id": "req_slice10_route_generate",
            "x-research-llm-failure-mode": "invalid_json",
            "x-research-llm-allow-fallback": "1",
        },
    )
    assert generated.status_code == 200

    graph = client.get(f"/api/v1/research/graph/{workspace_id}")
    assert graph.status_code == 200
    graph_payload = graph.json()
    evidence_node = next(
        (
            node
            for node in graph_payload["nodes"]
            if node["node_type"] == "evidence"
        ),
        graph_payload["nodes"][0],
    )

    failure = client.post(
        "/api/v1/research/failures",
        json={
            "workspace_id": workspace_id,
            "attached_targets": [{"target_type": "node", "target_id": evidence_node["node_id"]}],
            "observed_outcome": "timeout pattern persists",
            "expected_difference": "latency should be stable",
            "failure_reason": "queue saturation",
            "severity": "high",
            "reporter": "slice10_integration",
        },
        headers={"x-request-id": "req_slice10_failure_create"},
    )
    assert failure.status_code == 200
    failure_id = failure.json()["failure_id"]

    validation = client.post(
        "/api/v1/research/validations",
        json={
            "workspace_id": workspace_id,
            "target_object": f"node:{evidence_node['node_id']}",
            "method": "run replay benchmark",
            "success_signal": "support remains high",
            "weakening_signal": "timeout repeats",
        },
    )
    assert validation.status_code == 200
    validation_id = validation.json()["validation_id"]

    trigger_list = client.get(
        "/api/v1/research/hypotheses/triggers/list",
        params={"workspace_id": workspace_id},
    )
    assert trigger_list.status_code == 200
    trigger_items = trigger_list.json()["items"][:2]
    assert trigger_items
    hypothesis = STORE.create_hypothesis(
        workspace_id=workspace_id,
        title="slice10 seeded hypothesis",
        summary="retrieval reliability can be improved via targeted replay validation",
        premise="current contradiction and failure signals are local and diagnosable",
        rationale="combine evidence support with failure-aware validation loop",
        trigger_refs=[
            {
                "trigger_id": str(item["trigger_id"]),
                "trigger_type": str(item["trigger_type"]),
                "object_ref_type": str(item["object_ref_type"]),
                "object_ref_id": str(item["object_ref_id"]),
            }
            for item in trigger_items
        ],
        related_object_ids=[
            {"object_ref_type": "failure", "object_ref_id": failure_id},
            {"object_ref_type": "validation", "object_ref_id": validation_id},
        ],
        novelty_typing="recombination",
        minimum_validation_action={
            "target_object": f"validation:{validation_id}",
            "method": "run replay benchmark",
            "success_signal": "support remains high",
        },
        weakening_signal={"signal": "timeout repeats"},
        generation_job_id=None,
        provider_backend="seeded_test",
        provider_model="seeded_manual_hypothesis",
        llm_request_id="req_slice10_hypothesis_seed",
        llm_response_id="resp_slice10_hypothesis_seed",
        usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        fallback_used=True,
        degraded=False,
        degraded_reason=None,
    )
    assert hypothesis is not None
    hypothesis_id = str(hypothesis["hypothesis_id"])

    return {
        "source_a_id": source_a,
        "source_b_id": source_b,
        "source_c_id": source_c,
        "failure_id": failure_id,
        "validation_id": validation_id,
        "hypothesis_id": hypothesis_id,
    }


def test_slice10_dev_console_exposes_retrieval_controls() -> None:
    client = _build_test_client()
    response = client.get("/api/v1/research/dev-console")
    assert response.status_code == 200
    assert "Research Retrieval Views" in response.text
    assert "Retrieve Evidence View" in response.text
    assert "Retrieve Contradiction View" in response.text
    assert "Retrieve Failure Pattern View" in response.text
    assert "Retrieve Validation History View" in response.text
    assert "Retrieve Hypothesis Support View" in response.text


def test_slice10_retrieval_views_hybrid_filter_traceability_and_observability() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice10_flow"
    seeded = _seed_workspace_for_slice10(client, workspace_id)

    payloads = {
        "evidence": {
            "query": "retrieval precision benchmark",
            "retrieve_method": "hybrid",
            "metadata_filters": {"source_id": [seeded["source_a_id"]]},
            "top_k": 20,
        },
        "contradiction": {
            "query": "baseline mismatch contradiction",
            "retrieve_method": "hybrid",
            "metadata_filters": {},
            "top_k": 20,
        },
        "failure_pattern": {
            "query": "timeout pattern",
            "retrieve_method": "hybrid",
            "metadata_filters": {"severity": ["high"]},
            "top_k": 20,
        },
        "validation_history": {
            "query": "replay benchmark validation",
            "retrieve_method": "hybrid",
            "metadata_filters": {"method": ["run replay benchmark"]},
            "top_k": 20,
        },
        "hypothesis_support": {
            "query": "hypothesis trigger support",
            "retrieve_method": "hybrid",
            "metadata_filters": {},
            "top_k": 20,
        },
    }

    for view_type, body in payloads.items():
        response = client.post(
            f"/api/v1/research/retrieval/views/{view_type}",
            json={"workspace_id": workspace_id, **body},
            headers={"x-request-id": f"req_slice10_{view_type}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["view_type"] == view_type
        assert data["workspace_id"] == workspace_id
        assert data["retrieve_method"] == "hybrid"
        assert data["total"] >= 1
        item = data["items"][0]
        assert "source_ref" in item
        assert "graph_refs" in item
        assert "formal_refs" in item
        assert "trace_refs" in item
        if view_type == "validation_history":
            assert item["source_ref"].get("source_id")
            assert item["graph_refs"].get("node_ids")

    first_query = client.post(
        "/api/v1/research/retrieval/views/evidence",
        json={
            "workspace_id": workspace_id,
            "query": "retrieval precision",
            "retrieve_method": "hybrid",
            "metadata_filters": {},
            "top_k": 10,
        },
        headers={"x-request-id": "req_slice10_query_a"},
    )
    second_query = client.post(
        "/api/v1/research/retrieval/views/evidence",
        json={
            "workspace_id": workspace_id,
            "query": "timeout latency",
            "retrieve_method": "hybrid",
            "metadata_filters": {},
            "top_k": 10,
        },
        headers={"x-request-id": "req_slice10_query_b"},
    )
    assert first_query.status_code == 200
    assert second_query.status_code == 200
    first_top = first_query.json()["items"][0]["result_id"]
    second_top = second_query.json()["items"][0]["result_id"]
    assert first_top != second_top

    with sqlite3.connect(STORE.db_path) as conn:
        events = conn.execute(
            """
            SELECT event_name, status, COUNT(*)
            FROM research_events
            WHERE workspace_id = ?
              AND event_name IN ('retrieval_view_started', 'retrieval_view_completed')
            GROUP BY event_name, status
            """,
            (workspace_id,),
        ).fetchall()
    event_counter = {(row[0], row[1]): row[2] for row in events}
    assert event_counter.get(("retrieval_view_started", "started"), 0) >= 1
    assert event_counter.get(("retrieval_view_completed", "completed"), 0) >= 1


def test_slice10_retrieval_invalid_view_filter_and_missing_workspace_errors() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice10_error"
    _seed_workspace_for_slice10(client, workspace_id)

    invalid_view = client.post(
        "/api/v1/research/retrieval/views/not_a_view",
        json={
            "workspace_id": workspace_id,
            "query": "anything",
            "retrieve_method": "hybrid",
            "metadata_filters": {},
        },
    )
    assert invalid_view.status_code == 400
    assert invalid_view.json()["detail"]["error_code"] == "research.invalid_request"

    invalid_filter = client.post(
        "/api/v1/research/retrieval/views/evidence",
        json={
            "workspace_id": workspace_id,
            "query": "retrieval",
            "retrieve_method": "hybrid",
            "metadata_filters": {"severity": ["high"]},
        },
        headers={"x-request-id": "req_slice10_invalid_filter_event"},
    )
    assert invalid_filter.status_code == 400
    assert invalid_filter.json()["detail"]["error_code"] == "research.invalid_request"

    with sqlite3.connect(STORE.db_path) as conn:
        failed_event = conn.execute(
            """
            SELECT status, error_json
            FROM research_events
            WHERE request_id = ?
              AND event_name = 'retrieval_view_completed'
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            ("req_slice10_invalid_filter_event",),
        ).fetchone()
    assert failed_event is not None
    assert failed_event[0] == "failed"
    assert failed_event[1] is not None

    missing_workspace = client.post(
        "/api/v1/research/retrieval/views/evidence",
        json={
            "query": "retrieval",
            "retrieve_method": "hybrid",
            "metadata_filters": {},
        },
    )
    assert missing_workspace.status_code == 400
    assert missing_workspace.json()["detail"]["error_code"] == "research.invalid_request"
