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
            "x-request-id": f"req_slice9_multi_extract_{title}",
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

    for candidate_id in candidate_ids:
        confirmed = client.post(
            "/api/v1/research/candidates/confirm",
            json={"workspace_id": workspace_id, "candidate_ids": [candidate_id]},
            headers={"x-request-id": f"req_slice9_multi_confirm_{candidate_id}"},
        )
        assert confirmed.status_code in {200, 409}


def _prepare_workspace_with_triggers(client: TestClient, workspace_id: str) -> None:
    _import_extract_confirm_all(
        client,
        workspace_id=workspace_id,
        title="slice9 multi source 1",
        content="Claim: fan airflow improves evaporation rate. Validation: compare humidity trajectory.",
    )
    _import_extract_confirm_all(
        client,
        workspace_id=workspace_id,
        title="slice9 multi source 2",
        content="Failure: high humidity causes fogging risk. Conflict: temperature drop amplifies fog.",
    )
    built = client.post(
        f"/api/v1/research/graph/{workspace_id}/build",
        headers={"x-request-id": "req_slice9_multi_graph_build"},
    )
    assert built.status_code == 200


def test_slice9_multi_agent_pool_round_finalize_flow() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice9_multi_agent_flow"
    _prepare_workspace_with_triggers(client, workspace_id)

    triggers = client.get(
        "/api/v1/research/hypotheses/triggers/list",
        params={"workspace_id": workspace_id},
    )
    assert triggers.status_code == 200
    trigger_ids = [str(item["trigger_id"]) for item in triggers.json()["items"][:2]]
    assert trigger_ids

    generated = client.post(
        "/api/v1/research/hypotheses/generate",
        json={
            "workspace_id": workspace_id,
            "trigger_ids": trigger_ids,
            "mode": "multi_agent_pool",
            "top_k": 2,
            "max_rounds": 3,
            "candidate_count": 6,
            "research_goal": "推理风扇->蒸发->玻璃起雾链条",
            "async_mode": True,
        },
        headers={"x-request-id": "req_slice9_multi_generate"},
    )
    assert generated.status_code == 202, generated.text
    job = wait_for_job_terminal(client, job_id=str(generated.json()["job_id"]))
    assert job["status"] == "succeeded"
    assert job["result_ref"]["resource_type"] == "hypothesis_pool"
    pool_id = str(job["result_ref"]["resource_id"])

    pool = client.get(f"/api/v1/research/hypotheses/pools/{pool_id}")
    assert pool.status_code == 200, pool.text
    pool_payload = pool.json()
    assert pool_payload["pool_id"] == pool_id
    assert pool_payload["orchestration_mode"]
    root_tree_node_id = str(pool_payload["reasoning_subgraph"]["root_tree_node_id"])

    candidates = client.get(f"/api/v1/research/hypotheses/pools/{pool_id}/candidates")
    assert candidates.status_code == 200, candidates.text
    assert candidates.json()["total"] >= 2

    rounds = client.get(f"/api/v1/research/hypotheses/pools/{pool_id}/rounds")
    assert rounds.status_code == 200, rounds.text
    assert rounds.json()["total"] >= 1

    run_round = client.post(
        f"/api/v1/research/hypotheses/pools/{pool_id}/run-round",
        json={"workspace_id": workspace_id, "async_mode": True, "max_matches": 6},
        headers={"x-request-id": "req_slice9_multi_run_round"},
    )
    assert run_round.status_code == 202, run_round.text
    round_job = wait_for_job_terminal(client, job_id=str(run_round.json()["job_id"]))
    assert round_job["status"] == "succeeded"
    assert round_job["result_ref"]["resource_type"] == "hypothesis_round"

    tree_node = client.get(f"/api/v1/research/hypotheses/search-tree/{root_tree_node_id}")
    assert tree_node.status_code == 200, tree_node.text
    assert isinstance(tree_node.json().get("child_edges"), list)

    finalize = client.post(
        f"/api/v1/research/hypotheses/pools/{pool_id}/finalize",
        json={"workspace_id": workspace_id, "async_mode": True},
        headers={"x-request-id": "req_slice9_multi_finalize"},
    )
    assert finalize.status_code == 202, finalize.text
    finalize_job = wait_for_job_terminal(client, job_id=str(finalize.json()["job_id"]))
    assert finalize_job["status"] == "succeeded"
    assert finalize_job["result_ref"]["resource_type"] == "hypothesis"
    assert finalize_job["result_ref"]["resource_id"]

    hypotheses = client.get(
        "/api/v1/research/hypotheses",
        params={"workspace_id": workspace_id},
    )
    assert hypotheses.status_code == 200, hypotheses.text
    items = hypotheses.json()["items"]
    assert len(items) >= 1
    assert any(str(item.get("source_pool_id")) == pool_id for item in items)

