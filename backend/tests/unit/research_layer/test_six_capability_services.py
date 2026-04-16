from __future__ import annotations

import pytest

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.graph.repository import GraphRepository
from research_layer.services.candidate_confirmation_service import (
    CandidateConfirmationService,
)
from research_layer.services.graph_build_service import GraphBuildService
from research_layer.services.graph_report_service import GraphReportService
from research_layer.services.raw_material_bootstrap_service import (
    RawMaterialBootstrapService,
)
from research_layer.services.research_export_service import ResearchExportService
from research_layer.services.research_llm_dependencies import (
    resolve_research_backend_and_model,
)
from research_layer.services.research_query_service import ResearchQueryService


def _build_store(tmp_path) -> ResearchApiStateStore:
    return ResearchApiStateStore(db_path=str(tmp_path / "six_capabilities.sqlite3"))


def _seed_graph(store: ResearchApiStateStore, workspace_id: str) -> dict[str, str]:
    source = store.create_source(
        workspace_id=workspace_id,
        source_type="paper",
        title="seed source",
        content="Evidence: retrieval improves. Assumption: cache is warm.",
        metadata={},
        import_request_id="req_seed",
    )
    job = store.create_job(
        job_type="source_extract", workspace_id=workspace_id, request_id="req_seed"
    )
    batch = store.create_candidate_batch(
        workspace_id=workspace_id,
        source_id=str(source["source_id"]),
        job_id=str(job["job_id"]),
        request_id="req_seed",
    )
    candidates = store.add_candidates_to_batch(
        candidate_batch_id=str(batch["candidate_batch_id"]),
        workspace_id=workspace_id,
        source_id=str(source["source_id"]),
        job_id=str(job["job_id"]),
        candidates=[
            {
                "candidate_type": "evidence",
                "text": "Evidence: retrieval improves.",
                "source_span": {"start": 0, "end": 28},
                "extractor_name": "seed",
            },
            {
                "candidate_type": "assumption",
                "text": "Assumption: cache is warm.",
                "source_span": {"start": 29, "end": 56},
                "extractor_name": "seed",
            },
        ],
    )
    confirmation = CandidateConfirmationService(store)
    evidence = confirmation.confirm(
        workspace_id=workspace_id,
        candidate_id=str(candidates[0]["candidate_id"]),
        request_id="req_confirm",
    )
    assumption = confirmation.confirm(
        workspace_id=workspace_id,
        candidate_id=str(candidates[1]["candidate_id"]),
        request_id="req_confirm",
    )
    GraphBuildService(GraphRepository(store)).build_workspace_graph(
        workspace_id=workspace_id, request_id="req_build"
    )
    return {
        "source_id": str(source["source_id"]),
        "evidence_object_id": str(evidence["formal_object_id"]),
        "assumption_object_id": str(assumption["formal_object_id"]),
    }


def test_graph_report_summarizes_read_only_risks_and_trace_refs(tmp_path) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_six_report"
    _seed_graph(store, workspace_id)
    node = store.list_graph_nodes(workspace_id)[0]
    store.create_failure(
        workspace_id=workspace_id,
        attached_targets=[{"target_type": "node", "target_id": str(node["node_id"])}],
        observed_outcome="latency spike",
        expected_difference="stable retrieval",
        failure_reason="queue timeout",
        severity="high",
        reporter="unit",
    )

    report = GraphReportService(store).build_report(workspace_id=workspace_id)

    assert report["summary"]["node_count"] >= 2
    assert report["summary"]["edge_count"] >= 1
    assert report["risk_nodes"]
    assert report["trace_refs"]["latest_version_id"]


def test_query_service_runs_whitelisted_read_tools_without_mutating_graph(tmp_path) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_six_query"
    _seed_graph(store, workspace_id)
    before_nodes = store.list_graph_nodes(workspace_id)

    result = ResearchQueryService(store).run_tool(
        workspace_id=workspace_id,
        tool_name="report",
        arguments={},
    )

    assert result["tool_name"] == "report"
    assert result["workspace_id"] == workspace_id
    assert result["result"]["summary"]["node_count"] == len(before_nodes)
    assert store.list_graph_nodes(workspace_id) == before_nodes


def test_raw_bootstrap_creates_raw_sources_and_pending_candidates_only(tmp_path) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_six_bootstrap"

    result = RawMaterialBootstrapService(store).bootstrap(
        workspace_id=workspace_id,
        materials=[
            {
                "source_type": "paper",
                "title": "paper one",
                "content": "Evidence: alpha. Assumption: beta.",
                "candidates": [
                    {"candidate_type": "evidence", "text": "Evidence: alpha."},
                    {"candidate_type": "assumption", "text": "Assumption: beta."},
                ],
            }
        ],
        request_id="req_bootstrap",
        run_extract=False,
    )

    assert result["imported_count"] == 1
    assert result["failed_count"] == 0
    candidates = store.list_candidates(
        workspace_id=workspace_id,
        source_id=None,
        candidate_type=None,
        status=None,
    )
    assert {item["status"] for item in candidates} == {"pending"}
    assert store.list_confirmed_objects(workspace_id=workspace_id) == []
    assert store.list_graph_nodes(workspace_id) == []


def test_export_service_omits_raw_source_content_from_public_payload(tmp_path) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_six_export"
    _seed_graph(store, workspace_id)

    graph_export = ResearchExportService(store).export_graph(
        workspace_id=workspace_id, export_format="json"
    )

    assert graph_export["format"] == "json"
    payload = graph_export["payload"]
    assert "nodes" in payload
    assert "Evidence: retrieval improves. Assumption: cache is warm." not in str(payload)


def test_export_service_filters_edges_connected_to_private_nodes(tmp_path) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_six_export_private_edge"
    _seed_graph(store, workspace_id)
    public_node = store.list_graph_nodes(workspace_id)[0]
    private_node = store.create_graph_node(
        workspace_id=workspace_id,
        node_type="fact",
        object_ref_type="evidence",
        object_ref_id="obj_private",
        short_label="private node",
        full_description="private detail",
        visibility="private",
        source_refs=[],
    )
    store.create_graph_edge(
        workspace_id=workspace_id,
        source_node_id=str(public_node["node_id"]),
        target_node_id=str(private_node["node_id"]),
        edge_type="supports",
        object_ref_type="graph_relation",
        object_ref_id="edge_private",
        strength=0.8,
    )

    exported = ResearchExportService(store).export_graph(
        workspace_id=workspace_id, export_format="json"
    )
    payload = exported["payload"]
    node_ids = {str(item["node_id"]) for item in payload["nodes"]}
    assert str(private_node["node_id"]) not in node_ids
    for edge in payload["edges"]:
        assert str(edge["source_node_id"]) in node_ids
        assert str(edge["target_node_id"]) in node_ids


def test_export_package_removes_private_traceability_refs(tmp_path) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_six_export_pkg"
    package = store.create_package(
        workspace_id=workspace_id,
        title="pkg",
        summary="summary",
        included_route_ids=["route_1"],
        included_node_ids=["node_public", "node_private"],
        included_validation_ids=["val_1"],
        traceability_refs={
            "routes": [{"route_id": "route_1", "node_ids": ["node_public"]}],
            "node_ids": ["node_public", "node_private"],
            "validation_ids": ["val_1"],
            "private_dependency_node_ids": ["node_private"],
            "replacement_map": {"node_private": "node_gap"},
            "prompt_response_ref": {"prompt": "raw"},
        },
    )

    exported = ResearchExportService(store).export_package(
        package_id=str(package["package_id"]), export_format="json"
    )
    refs = exported["payload"]["traceability_refs"]
    assert refs["node_ids"] == ["node_public"]
    assert "private_dependency_node_ids" not in refs
    assert "replacement_map" not in refs
    assert "prompt_response_ref" not in refs


def test_query_service_rejects_non_whitelisted_tools(tmp_path) -> None:
    store = _build_store(tmp_path)

    with pytest.raises(ValueError):
        ResearchQueryService(store).run_tool(
            workspace_id="ws_six_query_reject",
            tool_name="write_store",
            arguments={},
        )


def test_local_first_resolver_prefers_configured_local_backend(monkeypatch) -> None:
    monkeypatch.setenv("RESEARCH_FEATURE_LOCAL_FIRST_ENABLED", "1")
    monkeypatch.setenv("RESEARCH_LOCAL_LLM_BACKEND", "ollama")
    monkeypatch.setenv("RESEARCH_LOCAL_LLM_MODEL", "qwen2")

    backend, model = resolve_research_backend_and_model()

    assert backend == "ollama"
    assert model == "qwen2"


def test_bootstrap_emits_failed_event_when_all_materials_invalid(tmp_path) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_six_bootstrap_fail"

    result = RawMaterialBootstrapService(store).bootstrap(
        workspace_id=workspace_id,
        materials=[{"source_type": "unknown", "title": "", "content": ""}],
        request_id="req_bootstrap_fail",
        run_extract=False,
    )

    assert result["status"] == "failed"
    latest = store.find_latest_event(
        workspace_id=workspace_id, event_name="sources_bootstrap_completed"
    )
    assert latest is not None
    assert latest["status"] == "failed"
