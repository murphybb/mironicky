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
from research_layer.services.hypothesis_multi_agent_orchestrator import (
    HypothesisMultiAgentOrchestrator,
)
from research_layer.services.llm_trace import LLMCallResult
from research_layer.testing.job_helpers import wait_for_job_terminal


class _Gateway:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def invoke_json(self, **kwargs: object) -> LLMCallResult:
        prompt_name = str(kwargs["prompt_name"])
        agent_name = prompt_name.rsplit(".", 1)[-1]
        self.calls.append(agent_name)
        parsed = _payload(agent_name)
        return LLMCallResult(
            provider_backend="openai",
            provider_model="gpt-4.1-mini",
            request_id=str(kwargs["request_id"]),
            llm_response_id=f"resp_{agent_name}_{len(self.calls)}",
            usage={"prompt_tokens": 10, "completion_tokens": 6, "total_tokens": 16},
            raw_text="{}",
            parsed_json=parsed,
            fallback_used=False,
            degraded=False,
            degraded_reason=None,
        )


def _payload(agent_name: str) -> dict[str, object]:
    if agent_name == "supervisor":
        return {
            "decision": "continue",
            "strategy": "test",
            "next_actions": ["reflect", "rank", "evolve", "meta_review"],
        }
    if agent_name == "generation":
        return {
            "candidate": {
                "title": "LLM generated airflow hypothesis",
                "statement": "Fan airflow may mediate humidity-driven glass fogging recovery.",
                "hypothesis_level_conclusion": "Airflow is a plausible mediator of fogging recovery.",
                "summary": "Airflow mediation hypothesis.",
                "rationale": "Combines confirmed uploaded claims.",
                "testability_hint": "Compare fogging recovery with controlled airflow.",
                "novelty_hint": "Mechanism-level source recombination.",
                "confidence_hint": 0.63,
                "suggested_next_steps": ["run airflow comparison"],
                "source_refs": [
                    {
                        "source_id": "source_test",
                        "source_span": {"text": "fan airflow improves evaporation"},
                        "evidence_refs": ["claim_test"],
                    }
                ],
                "reasoning_chain": {
                    "evidence": ["fan airflow improves evaporation"],
                    "assumption": "Evaporation speed affects fogging recovery.",
                    "intermediate_reasoning": ["Airflow increases evaporation."],
                    "conclusion": "Airflow may reduce fogging persistence.",
                    "validation_need": "Controlled airflow test.",
                },
            }
        }
    if agent_name == "reflection":
        return {
            "verdict": "survive",
            "strengths": ["has provenance"],
            "weaknesses": ["needs controlled test"],
            "missing_evidence": [],
            "testability_issues": [],
            "weakest_step_ref": {},
            "recommended_actions": ["run experiment"],
            "score_delta": 0.05,
        }
    if agent_name == "ranking":
        return {
            "winner_candidate_id": "USE_LEFT",
            "match_reason": "left has stronger validation framing",
            "compare_vector": {"testability": 0.7},
        }
    if agent_name == "evolution":
        return {
            "children": [
                {
                    "title": "LLM evolved airflow hypothesis",
                    "statement": "Airflow and temperature drop jointly determine fogging recovery.",
                    "hypothesis_level_conclusion": "Airflow effect depends on temperature drop.",
                    "summary": "Evolved interaction hypothesis.",
                    "rationale": "Adds moderator from uploaded conflict.",
                    "testability_hint": "Test airflow x temperature interaction.",
                    "novelty_hint": "Interaction mechanism.",
                    "confidence_hint": 0.64,
                    "suggested_next_steps": ["fit interaction model"],
                    "source_refs": [
                        {
                            "source_id": "source_test",
                            "source_span": {"text": "temperature drop amplifies fog"},
                            "evidence_refs": ["claim_temp"],
                        }
                    ],
                    "reasoning_chain": {
                        "evidence": ["temperature drop amplifies fog"],
                        "assumption": "Temperature drop moderates evaporation.",
                        "intermediate_reasoning": ["Cooling can offset airflow."],
                        "conclusion": "Recovery depends on airflow x temperature.",
                        "validation_need": "Interaction test.",
                    },
                }
            ],
            "change_summary": "Added temperature moderator.",
        }
    if agent_name == "meta_review":
        return {
            "recurring_issues": ["needs experiment"],
            "strong_patterns": ["source grounded"],
            "weak_patterns": [],
            "continue_recommendation": "continue",
            "stop_recommendation": "",
            "diversity_assessment": "acceptable",
            "prune_recommendations": [],
        }
    raise AssertionError(agent_name)


def _build_test_client(gateway: _Gateway | None = None) -> TestClient:
    STORE.reset_all()
    if gateway is not None:
        STORE._hypothesis_multi_orchestrator = HypothesisMultiAgentOrchestrator(
            STORE, llm_gateway=gateway
        )
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


def _prepare_workspace_with_triggers(client: TestClient, workspace_id: str) -> None:
    del client
    conflict_node = STORE.create_graph_node(
        workspace_id=workspace_id,
        node_type="conflict",
        object_ref_type="conflict",
        object_ref_id="conflict_slice9_multi",
        short_label="Conflict Seed",
        full_description="Temperature drop amplifies fog while airflow improves evaporation.",
        status="active",
    )
    gap_node = STORE.create_graph_node(
        workspace_id=workspace_id,
        node_type="gap",
        object_ref_type="failure_gap",
        object_ref_id="gap_slice9_multi",
        short_label="Gap Seed",
        full_description="Need a causal explanation for airflow and fogging recovery.",
        status="active",
    )
    STORE.create_route(
        workspace_id=workspace_id,
        title="Weak Support Route",
        summary="route with weak support",
        status="weakened",
        support_score=41.5,
        risk_score=61.2,
        progressability_score=38.9,
        conclusion="Need new supporting evidence",
        key_supports=["support 1"],
        assumptions=["assumption 1"],
        risks=["risk 1"],
        next_validation_action="run targeted benchmark",
        route_node_ids=[str(conflict_node["node_id"]), str(gap_node["node_id"])],
        key_support_node_ids=[str(conflict_node["node_id"])],
        key_assumption_node_ids=[],
        risk_node_ids=[str(conflict_node["node_id"])],
        conclusion_node_id=str(conflict_node["node_id"]),
        version_id="ver_slice9_multi_seed",
    )
    STORE.create_failure(
        workspace_id=workspace_id,
        attached_targets=[
            {"target_type": "node", "target_id": str(gap_node["node_id"])}
        ],
        observed_outcome="seeded observed failure",
        expected_difference="seeded expected behavior",
        failure_reason="seeded reason",
        severity="high",
        reporter="slice9_integration",
    )


def test_slice9_multi_agent_pool_round_finalize_flow() -> None:
    gateway = _Gateway()
    client = _build_test_client(gateway)
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
    transcripts = client.get(f"/api/v1/research/hypotheses/pools/{pool_id}/transcripts")
    assert transcripts.status_code == 200, transcripts.text
    roles = {item["agent_name"] for item in transcripts.json()["items"]}
    assert {"generation", "reflection", "ranking", "evolution", "meta_review"} <= roles

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

    tree_node = client.get(
        f"/api/v1/research/hypotheses/search-tree/{root_tree_node_id}"
    )
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
        "/api/v1/research/hypotheses", params={"workspace_id": workspace_id}
    )
    assert hypotheses.status_code == 200, hypotheses.text
    items = hypotheses.json()["items"]
    assert len(items) >= 1
    assert any(str(item.get("source_pool_id")) == pool_id for item in items)
