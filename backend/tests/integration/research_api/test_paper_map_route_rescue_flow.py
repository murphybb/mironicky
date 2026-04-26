from __future__ import annotations

import json
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
from research_layer.services.llm_trace import LLMCallResult
from research_layer.testing.job_helpers import wait_for_job_terminal


class _RecordingGateway:
    def __init__(self) -> None:
        self.prompt_names: list[str] = []

    async def invoke_text(self, **kwargs: object) -> LLMCallResult:
        prompt_name = str(kwargs["prompt_name"])
        self.prompt_names.append(prompt_name)
        raw_text = self._text_payload(prompt_name)
        return LLMCallResult(
            provider_backend="integration_fake",
            provider_model="paper_map_route_rescue",
            request_id=str(kwargs["request_id"]),
            llm_response_id=f"resp_{prompt_name}",
            usage={"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
            raw_text=raw_text,
            parsed_json=None,
            fallback_used=False,
            degraded=False,
            degraded_reason=None,
        )

    async def invoke_json(self, **kwargs: object) -> LLMCallResult:
        prompt_name = str(kwargs["prompt_name"])
        self.prompt_names.append(prompt_name)
        return LLMCallResult(
            provider_backend="integration_fake",
            provider_model="paper_map_route_rescue",
            request_id=str(kwargs["request_id"]),
            llm_response_id=f"resp_{prompt_name}",
            usage={"prompt_tokens": 10, "completion_tokens": 6, "total_tokens": 16},
            raw_text="{}",
            parsed_json={
                "summary": "The validated result supports the paper's main conclusion.",
                "key_strengths": [
                    {"text": "The result evidence directly supports the conclusion.", "node_refs": []}
                ],
                "key_risks": [
                    {"text": "The limitation remains a next-work item, not the route conclusion.", "node_refs": []}
                ],
                "open_questions": [],
            },
            fallback_used=False,
            degraded=False,
            degraded_reason=None,
        )

    def _text_payload(self, prompt_name: str) -> str:
        if prompt_name == "extraction_document_reader":
            return json.dumps(
                {
                    "document_summary": "A paper evaluates AIFS using method, validation, and result evidence.",
                    "document_type": "academic_paper",
                    "domain_profile": ["computer_science", "weather_forecasting"],
                    "research_questions": [
                        {"quote": "Can AIFS produce skilled forecasts?", "reason": "central question"}
                    ],
                    "main_contributions": [
                        {"quote": "AIFS produces skilled forecasts.", "reason": "main contribution"}
                    ],
                    "hypotheses_or_claims": [
                        {"quote": "AIFS produces skilled forecasts.", "reason": "central claim"}
                    ],
                    "method_chain": [
                        {"quote": "AIFS uses ERA5 training data.", "reason": "method evidence"}
                    ],
                    "data_or_corpus": [
                        {"quote": "AIFS uses ERA5 training data.", "reason": "dataset"}
                    ],
                    "experiments_or_validation": [
                        {"quote": "Weak scaling validation was run.", "reason": "validation"}
                    ],
                    "results_or_findings": [
                        {"quote": "AIFS improves forecast skill.", "reason": "result"}
                    ],
                    "limitations_or_open_questions": [
                        {"quote": "Future work should test more variables.", "reason": "limitation"}
                    ],
                    "artifact_index": [],
                    "route_seed_candidates": [
                        {"quote": "AIFS produces skilled forecasts.", "reason": "candidate conclusion"}
                    ],
                    "coverage_warnings": [],
                },
                ensure_ascii=False,
            )
        if prompt_name == "argument_unit_extraction":
            return json.dumps(
                {
                    "domain_profile": ["computer_science", "weather_forecasting"],
                    "units": [
                        {
                            "unit_id": "u_claim",
                            "semantic_type": "claim",
                            "domain_tags": ["main_contribution"],
                            "text": "AIFS produces skilled forecasts.",
                            "normalized_label": "AIFS skilled forecasts",
                            "quote": "AIFS produces skilled forecasts.",
                            "confidence_score": 0.95,
                        },
                        {
                            "unit_id": "u_method",
                            "semantic_type": "method",
                            "domain_tags": ["method", "dataset"],
                            "text": "AIFS uses ERA5 training data.",
                            "normalized_label": "ERA5 training data",
                            "quote": "AIFS uses ERA5 training data.",
                            "confidence_score": 0.92,
                        },
                        {
                            "unit_id": "u_result",
                            "semantic_type": "result",
                            "domain_tags": ["result"],
                            "text": "AIFS improves forecast skill.",
                            "normalized_label": "AIFS improves forecast skill",
                            "quote": "AIFS improves forecast skill.",
                            "confidence_score": 0.93,
                        },
                        {
                            "unit_id": "u_gap",
                            "semantic_type": "limitation",
                            "domain_tags": ["future_work"],
                            "text": "Future work should test more variables.",
                            "normalized_label": "test more variables",
                            "quote": "Future work should test more variables.",
                            "confidence_score": 0.8,
                        },
                    ],
                },
                ensure_ascii=False,
            )
        if prompt_name == "argument_relation_rebuild":
            return json.dumps(
                {
                    "relations": [
                        {
                            "source_unit_id": "u_result",
                            "target_unit_id": "u_claim",
                            "semantic_relation_type": "supports",
                            "confidence_label": "EXTRACTED",
                            "confidence_score": 0.94,
                            "quote": "AIFS improves forecast skill.",
                            "relation_status": "resolved",
                        },
                        {
                            "source_unit_id": "u_method",
                            "target_unit_id": "u_claim",
                            "semantic_relation_type": "supports",
                            "confidence_label": "EXTRACTED",
                            "confidence_score": 0.88,
                            "quote": "AIFS uses ERA5 training data.",
                            "relation_status": "resolved",
                        },
                    ]
                },
                ensure_ascii=False,
            )
        raise AssertionError(f"unexpected prompt_name: {prompt_name}")


def _build_test_client(monkeypatch, gateway: _RecordingGateway) -> TestClient:
    import research_layer.services.research_llm_dependencies as llm_dependencies
    import research_layer.workers.extraction_worker as extraction_worker_module

    monkeypatch.setattr(llm_dependencies, "build_research_llm_gateway", lambda: gateway)
    monkeypatch.setattr(
        extraction_worker_module, "build_research_llm_gateway", lambda: gateway
    )
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


def test_paper_map_route_rescue_flow_uses_llm_prompts_and_blocks_gap_routes(monkeypatch):
    gateway = _RecordingGateway()
    client = _build_test_client(monkeypatch, gateway)
    workspace_id = "ws_paper_map_route_rescue"
    content = (
        "Can AIFS produce skilled forecasts? "
        "AIFS produces skilled forecasts. "
        "AIFS uses ERA5 training data. "
        "AIFS improves forecast skill. "
        "Future work should test more variables."
    )

    imported = client.post(
        "/api/v1/research/sources/import",
        json={
            "workspace_id": workspace_id,
            "source_type": "paper",
            "title": "PaperMap route rescue",
            "content": content,
        },
    )
    assert imported.status_code == 200
    source_id = imported.json()["source_id"]

    started = client.post(
        f"/api/v1/research/sources/{source_id}/extract",
        json={"workspace_id": workspace_id, "async_mode": True},
        headers={"x-request-id": "req_paper_map_extract"},
    )
    assert started.status_code == 202
    extract_job = wait_for_job_terminal(client, job_id=str(started.json()["job_id"]))
    assert extract_job["status"] == "succeeded"

    batch_id = extract_job["result_ref"]["resource_id"]
    extracted = client.get(
        f"/api/v1/research/sources/{source_id}/extraction-results/{batch_id}",
        params={"workspace_id": workspace_id},
    )
    assert extracted.status_code == 200
    extracted_payload = extracted.json()
    assert extracted_payload["fallback_used"] is False
    assert extracted_payload["degraded"] is False

    candidates = client.get(
        "/api/v1/research/candidates",
        params={"workspace_id": workspace_id, "source_id": source_id},
    )
    assert candidates.status_code == 200
    candidate_items = candidates.json()["items"]
    candidate_types = {item["candidate_type"] for item in candidate_items}
    assert "conclusion" in candidate_types
    assert "evidence" in candidate_types
    assert "gap" in candidate_types
    assert all(
        item.get("extractor_name") != "deterministic_explicit_paper_claim_extractor"
        for item in candidate_items
    )

    for candidate in candidate_items:
        confirmed = client.post(
            "/api/v1/research/candidates/confirm",
            json={"workspace_id": workspace_id, "candidate_ids": [candidate["candidate_id"]]},
            headers={"x-request-id": f"req_paper_map_confirm_{candidate['candidate_id']}"},
        )
        assert confirmed.status_code == 200, confirmed.text

    built = client.post(f"/api/v1/research/graph/{workspace_id}/build")
    assert built.status_code == 200
    graph = client.get(f"/api/v1/research/graph/{workspace_id}")
    assert graph.status_code == 200
    graph_payload = graph.json()
    node_types = {node["node_type"] for node in graph_payload["nodes"]}
    assert "conclusion" in node_types
    assert "evidence" in node_types
    assert "gap" in node_types
    assert graph_payload["edges"]

    generated = client.post(
        "/api/v1/research/routes/generate",
        json={
            "workspace_id": workspace_id,
            "reason": "paper map route rescue regression",
            "max_candidates": 8,
        },
        headers={"x-request-id": "req_paper_map_routes"},
    )
    assert generated.status_code == 200
    generated_payload = generated.json()
    assert generated_payload["generated_count"] >= 1

    routes = client.get("/api/v1/research/routes", params={"workspace_id": workspace_id})
    assert routes.status_code == 200
    route_items = routes.json()["items"]
    assert route_items
    node_by_id = {node["node_id"]: node for node in graph_payload["nodes"]}
    for route in route_items:
        conclusion_node = node_by_id[str(route["conclusion_node_id"])]
        assert conclusion_node["node_type"] != "gap"
        assert route["key_supports"]
        assert route["summary_generation_mode"] == "llm"
        assert route["fallback_used"] is False
        assert route["degraded"] is False

    assert {
        "extraction_document_reader",
        "argument_unit_extraction",
        "argument_relation_rebuild",
        "route_summary",
    }.issubset(set(gateway.prompt_names))

    missing_workspace_artifacts = client.get(
        f"/api/v1/research/sources/{source_id}/artifacts"
    )
    assert missing_workspace_artifacts.status_code == 422

    wrong_workspace_artifacts = client.get(
        f"/api/v1/research/sources/{source_id}/artifacts",
        params={"workspace_id": "ws_paper_map_route_rescue_other"},
    )
    assert wrong_workspace_artifacts.status_code == 404

    artifacts_response = client.get(
        f"/api/v1/research/sources/{source_id}/artifacts",
        params={"workspace_id": workspace_id},
    )
    assert artifacts_response.status_code == 200
    artifacts = artifacts_response.json()["items"]
    paper_map_artifacts = [
        artifact for artifact in artifacts if artifact["artifact_type"] == "paper_map"
    ]
    assert len(paper_map_artifacts) == 1

    with sqlite3.connect(STORE.db_path) as conn:
        stale_cache_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM source_chunk_cache
            WHERE workspace_id = ?
              AND cache_key NOT LIKE '%v10_paper_map_units:%'
            """,
            (workspace_id,),
        ).fetchone()[0]
    assert stale_cache_count == 0
