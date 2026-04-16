from __future__ import annotations

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


def _seed_minimal_route_workspace(
    client: TestClient, workspace_id: str
) -> tuple[str, str]:
    imported = client.post(
        "/api/v1/research/sources/import",
        json={
            "workspace_id": workspace_id,
            "source_type": "paper",
            "title": "slice12 regression",
            "content": (
                "Claim: deterministic ranking should hold. "
                "Assumption: observable events remain complete. "
                "Validation: execute replay benchmark."
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
            headers={"x-request-id": f"req_slice12_confirm_{candidate_id}"},
        )
        if confirmed.status_code == 200:
            confirmed_count += 1
            continue
        assert confirmed.status_code == 409, confirmed.text
    assert confirmed_count > 0

    graph_built = client.post(f"/api/v1/research/graph/{workspace_id}/build")
    assert graph_built.status_code == 200

    generated = client.post(
        "/api/v1/research/routes/generate",
        json={
            "workspace_id": workspace_id,
            "reason": "regression seed",
            "max_candidates": 8,
        },
        headers={
            "x-request-id": "req_slice12_seed_generate",
            "x-research-llm-failure-mode": "invalid_json",
            "x-research-llm-allow-fallback": "1",
        },
    )
    assert generated.status_code == 200
    route_id = generated.json()["ranked_route_ids"][0]
    return source_id, route_id


def test_slice12_regression_explicit_errors_and_recovery_rerun() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice12_regression_errors"
    _, route_id = _seed_minimal_route_workspace(client, workspace_id)

    missing_failure = client.post(
        "/api/v1/research/routes/recompute",
        json={
            "workspace_id": workspace_id,
            "failure_id": "failure_not_exists",
            "reason": "expect explicit failure",
            "async_mode": True,
        },
    )
    assert missing_failure.status_code == 404
    assert missing_failure.json()["detail"]["error_code"] == "research.not_found"

    graph = client.get(f"/api/v1/research/graph/{workspace_id}")
    assert graph.status_code == 200
    graph_nodes = graph.json()["nodes"]
    attach_node = next(
        (
            item
            for item in graph_nodes
            if item["node_type"] in {"evidence", "assumption", "validation"}
            and item["status"] == "active"
        ),
        graph_nodes[0],
    )

    attached = client.post(
        "/api/v1/research/failures",
        json={
            "workspace_id": workspace_id,
            "attached_targets": [
                {"target_type": "node", "target_id": attach_node["node_id"]}
            ],
            "observed_outcome": "support became unstable",
            "expected_difference": "support should remain stable",
            "failure_reason": "regression run",
            "severity": "medium",
            "reporter": "slice12_regression",
        },
    )
    assert attached.status_code == 200
    failure_id = attached.json()["failure_id"]

    recompute = client.post(
        "/api/v1/research/routes/recompute",
        json={
            "workspace_id": workspace_id,
            "failure_id": failure_id,
            "reason": "regression recompute",
            "async_mode": True,
        },
        headers={
            "x-request-id": "req_slice12_recompute",
            "x-research-llm-failure-mode": "invalid_json",
            "x-research-llm-allow-fallback": "1",
        },
    )
    assert recompute.status_code == 202
    recompute_job = client.get(f"/api/v1/research/jobs/{recompute.json()['job_id']}")
    assert recompute_job.status_code == 200
    recompute_payload = wait_for_job_terminal(
        client, job_id=str(recompute.json()["job_id"])
    )
    assert recompute_payload["status"] == "succeeded"
    version_id = str(recompute_payload["result_ref"]["resource_id"])

    route_preview = client.get(
        f"/api/v1/research/routes/{route_id}/preview",
        params={"workspace_id": workspace_id},
    )
    assert route_preview.status_code == 200
    assert route_preview.json()["trace_refs"]["version_id"] == version_id

    rerun_generate = client.post(
        "/api/v1/research/routes/generate",
        json={
            "workspace_id": workspace_id,
            "reason": "rerun after failure",
            "max_candidates": 8,
        },
        headers={
            "x-request-id": "req_slice12_rerun_generate",
            "x-research-llm-failure-mode": "invalid_json",
            "x-research-llm-allow-fallback": "1",
        },
    )
    assert rerun_generate.status_code == 200
    assert rerun_generate.json()["generated_count"] >= 1


def test_slice12_regression_workspace_and_dependency_guardrails() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice12_regression_scope"
    source_id, route_id = _seed_minimal_route_workspace(client, workspace_id)

    cross_workspace_preview = client.get(
        f"/api/v1/research/routes/{route_id}/preview",
        params={"workspace_id": "ws_other_scope"},
    )
    assert cross_workspace_preview.status_code == 409
    assert cross_workspace_preview.json()["detail"]["error_code"] == "research.conflict"

    missing_dependency_hypothesis = client.post(
        "/api/v1/research/hypotheses/generate",
        json={
            "workspace_id": workspace_id,
            "trigger_ids": ["trigger_missing_dep"],
            "async_mode": False,
        },
    )
    assert missing_dependency_hypothesis.status_code == 400
    assert (
        missing_dependency_hypothesis.json()["detail"]["error_code"]
        == "research.invalid_request"
    )

    summary = client.get(
        "/api/v1/research/executions/summary", params={"workspace_id": workspace_id}
    )
    assert summary.status_code == 200
    payload = summary.json()
    assert source_id in payload["business_objects"]["source_ids"]
    assert route_id in payload["business_objects"]["route_ids"]


def test_slice12_regression_sources_list_contract_sync() -> None:
    client = _build_test_client()
    ws_primary = "ws_slice12_sources_primary"
    ws_other = "ws_slice12_sources_other"

    primary_ids: list[str] = []
    for idx in range(2):
        response = client.post(
            "/api/v1/research/sources/import",
            json={
                "workspace_id": ws_primary,
                "source_type": "paper",
                "title": f"slice12 source {idx}",
                "content": f"slice12 source content {idx}",
            },
        )
        assert response.status_code == 200
        primary_ids.append(response.json()["source_id"])

    other_response = client.post(
        "/api/v1/research/sources/import",
        json={
            "workspace_id": ws_other,
            "source_type": "note",
            "title": "slice12 other source",
            "content": "other workspace content",
        },
    )
    assert other_response.status_code == 200

    primary_list = client.get(
        "/api/v1/research/sources", params={"workspace_id": ws_primary}
    )
    assert primary_list.status_code == 200
    primary_payload = primary_list.json()
    assert primary_payload["total"] == 2
    assert {item["source_id"] for item in primary_payload["items"]} == set(primary_ids)
    assert all(item["workspace_id"] == ws_primary for item in primary_payload["items"])

    other_list = client.get("/api/v1/research/sources", params={"workspace_id": ws_other})
    assert other_list.status_code == 200
    other_payload = other_list.json()
    assert other_payload["total"] == 1
    assert other_payload["items"][0]["workspace_id"] == ws_other


def test_slice12_regression_graph_archive_delete_contract_sync() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice12_graph_archive"
    _seed_minimal_route_workspace(client, workspace_id)

    graph_before = client.get(f"/api/v1/research/graph/{workspace_id}")
    assert graph_before.status_code == 200
    graph_before_payload = graph_before.json()
    node_id = graph_before_payload["nodes"][0]["node_id"]
    edge_id = (
        graph_before_payload["edges"][0]["edge_id"]
        if graph_before_payload["edges"]
        else None
    )

    archive_node = client.request(
        "DELETE",
        f"/api/v1/research/graph/nodes/{node_id}",
        json={"workspace_id": workspace_id, "reason": "slice12 archive node"},
    )
    assert archive_node.status_code == 200
    archive_node_payload = archive_node.json()
    assert archive_node_payload["status"] == "archived"
    assert archive_node_payload["target_type"] == "node"
    assert node_id in archive_node_payload["diff_payload"]["archived"]["nodes"]

    if edge_id is not None:
        archive_edge = client.request(
            "DELETE",
            f"/api/v1/research/graph/edges/{edge_id}",
            json={"workspace_id": workspace_id, "reason": "slice12 archive edge"},
        )
        assert archive_edge.status_code == 200
        archive_edge_payload = archive_edge.json()
        assert archive_edge_payload["status"] == "archived"
        assert archive_edge_payload["target_type"] == "edge"
        assert edge_id in archive_edge_payload["diff_payload"]["archived"]["edges"]

    archived_graph = client.get(f"/api/v1/research/graph/{workspace_id}")
    assert archived_graph.status_code == 200
    archived_node = next(
        item for item in archived_graph.json()["nodes"] if item["node_id"] == node_id
    )
    assert archived_node["status"] == "archived"
    if edge_id is not None:
        archived_edge = next(
            item for item in archived_graph.json()["edges"] if item["edge_id"] == edge_id
        )
        assert archived_edge["status"] == "archived"

    duplicate_archive = client.request(
        "DELETE",
        (
            f"/api/v1/research/graph/edges/{edge_id}"
            if edge_id is not None
            else f"/api/v1/research/graph/nodes/{node_id}"
        ),
        json={"workspace_id": workspace_id},
    )
    assert duplicate_archive.status_code == 409
    assert duplicate_archive.json()["detail"]["error_code"] == "research.invalid_state"


def test_slice12_regression_hypothesis_inbox_defer_contract_sync() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice12_hypothesis_inbox"
    _seed_minimal_route_workspace(client, workspace_id)

    triggers_response = client.get(
        "/api/v1/research/hypotheses/triggers/list",
        params={"workspace_id": workspace_id},
    )
    assert triggers_response.status_code == 200
    trigger_items = triggers_response.json()["items"]
    assert trigger_items

    trigger = trigger_items[0]
    seeded_hypothesis = STORE.create_hypothesis(
        workspace_id=workspace_id,
        title="slice12 inbox hypothesis",
        summary="defer contract should remain queryable",
        premise="manual seed with full schema avoids llm nondeterminism",
        rationale="validate defer status transition and inbox visibility",
        trigger_refs=[
            {
                "trigger_id": str(trigger["trigger_id"]),
                "trigger_type": str(trigger["trigger_type"]),
                "workspace_id": str(trigger["workspace_id"]),
                "object_ref_type": str(trigger["object_ref_type"]),
                "object_ref_id": str(trigger["object_ref_id"]),
                "summary": str(trigger.get("summary") or "slice12 seeded trigger"),
                "trace_refs": dict(trigger.get("trace_refs") or {}),
                "related_object_ids": list(trigger.get("related_object_ids") or []),
                "metrics": dict(trigger.get("metrics") or {}),
            }
        ],
        related_object_ids=[],
        novelty_typing="workflow",
        minimum_validation_action={
            "validation_id": "validation_slice12_seed",
            "target_object": f"{trigger['object_ref_type']}:{trigger['object_ref_id']}",
            "method": "manual triage",
            "success_signal": "state remains deferred until explicit promote/reject",
            "weakening_signal": "state changes without explicit decision",
            "cost_level": "low",
            "time_level": "short",
        },
        weakening_signal={
            "signal_type": "state_transition",
            "signal_text": "hypothesis moved away from deferred without explicit action",
            "severity_hint": "medium",
            "trace_refs": {},
        },
        generation_job_id=None,
        provider_backend="seeded_test",
        provider_model="seeded_manual_hypothesis",
        llm_request_id="req_slice12_hypothesis_seed",
        llm_response_id="resp_slice12_hypothesis_seed",
        usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        fallback_used=True,
        degraded=False,
        degraded_reason=None,
    )
    assert seeded_hypothesis is not None
    hypothesis_id = str(seeded_hypothesis["hypothesis_id"])

    deferred = client.post(
        f"/api/v1/research/hypotheses/{hypothesis_id}/defer",
        json={
            "workspace_id": workspace_id,
            "note": "slice12 defer for contract sync",
            "decision_source_type": "manual",
            "decision_source_ref": "slice12_regression",
        },
    )
    assert deferred.status_code == 200
    assert deferred.json()["status"] == "deferred"

    inbox = client.get(
        "/api/v1/research/hypotheses",
        params={"workspace_id": workspace_id},
    )
    assert inbox.status_code == 200
    assert any(
        item["hypothesis_id"] == hypothesis_id and item["status"] == "deferred"
        for item in inbox.json()["items"]
    )

    duplicate_defer = client.post(
        f"/api/v1/research/hypotheses/{hypothesis_id}/defer",
        json={
            "workspace_id": workspace_id,
            "note": "duplicate defer",
            "decision_source_type": "manual",
            "decision_source_ref": "slice12_regression",
        },
    )
    assert duplicate_defer.status_code == 409
    assert duplicate_defer.json()["detail"]["error_code"] == "research.invalid_state"
