from __future__ import annotations

import json
import sqlite3
import pytest

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.graph.repository import GraphRepository
from research_layer.services.candidate_confirmation_service import normalize_candidate_text
from research_layer.services.graph_query_service import GraphQueryService
from research_layer.services.retrieval_views_service import (
    ResearchRetrievalService,
    RetrievalServiceError,
)


def _build_store(tmp_path) -> ResearchApiStateStore:
    return ResearchApiStateStore(db_path=str(tmp_path / "slice10_retrieval.sqlite3"))


def _seed_confirmed_objects(store: ResearchApiStateStore, workspace_id: str) -> dict[str, str]:
    source_a = store.create_source(
        workspace_id=workspace_id,
        source_type="paper",
        title="Retrieval Precision Study",
        content="retrieval precision improves with grounded evidence",
        metadata={"dataset": "A"},
        import_request_id="req_slice10_seed_source_a",
    )
    source_b = store.create_source(
        workspace_id=workspace_id,
        source_type="paper",
        title="Latency Incident Study",
        content="latency spikes and timeout patterns under shard imbalance",
        metadata={"dataset": "B"},
        import_request_id="req_slice10_seed_source_b",
    )

    batch = store.create_candidate_batch(
        workspace_id=workspace_id,
        source_id=str(source_a["source_id"]),
        job_id="job_slice10_seed_batch",
        request_id="req_slice10_seed_batch",
    )
    created = store.add_candidates_to_batch(
        candidate_batch_id=str(batch["candidate_batch_id"]),
        workspace_id=workspace_id,
        source_id=str(source_a["source_id"]),
        job_id="job_slice10_seed_batch",
        candidates=[
            {
                "candidate_type": "evidence",
                "text": "retrieval precision improved by 12 percent in benchmark",
                "source_span": {"start": 0, "end": 45},
                "extractor_name": "deterministic_seed",
            },
            {
                "candidate_type": "conflict",
                "text": "contradiction found between baseline and online run",
                "source_span": {"start": 46, "end": 97},
                "extractor_name": "deterministic_seed",
            },
            {
                "candidate_type": "validation",
                "text": "validation benchmark repeated with consistent outcomes",
                "source_span": {"start": 98, "end": 150},
                "extractor_name": "deterministic_seed",
            },
        ],
    )
    batch_b = store.create_candidate_batch(
        workspace_id=workspace_id,
        source_id=str(source_b["source_id"]),
        job_id="job_slice10_seed_batch_b",
        request_id="req_slice10_seed_batch_b",
    )
    created.extend(
        store.add_candidates_to_batch(
            candidate_batch_id=str(batch_b["candidate_batch_id"]),
            workspace_id=workspace_id,
            source_id=str(source_b["source_id"]),
            job_id="job_slice10_seed_batch_b",
            candidates=[
                {
                    "candidate_type": "evidence",
                    "text": "timeout latency increased in retrieval queue on shard imbalance",
                    "source_span": {"start": 0, "end": 60},
                    "extractor_name": "deterministic_seed",
                }
            ],
        )
    )
    confirmed_map: dict[str, dict[str, str]] = {}
    for candidate in created:
        object_ref = store.create_confirmed_object_from_candidate(
            candidate=candidate,
            normalized_text=normalize_candidate_text(str(candidate["text"])),
            request_id="req_slice10_confirm",
        )
        store.update_candidate_status(
            candidate_id=str(candidate["candidate_id"]), status="confirmed"
        )
        confirmed_map[str(candidate["candidate_type"])] = object_ref

    evidence_node = store.create_graph_node(
        workspace_id=workspace_id,
        node_type="evidence",
        object_ref_type="evidence",
        object_ref_id=confirmed_map["evidence"]["object_id"],
        short_label="Evidence Node",
        full_description="Graph node for evidence retrieval",
        status="active",
    )
    conflict_node = store.create_graph_node(
        workspace_id=workspace_id,
        node_type="conflict",
        object_ref_type="conflict",
        object_ref_id=confirmed_map["conflict"]["object_id"],
        short_label="Conflict Node",
        full_description="Graph node for contradiction retrieval",
        status="active",
    )
    validation_node = store.create_graph_node(
        workspace_id=workspace_id,
        node_type="validation",
        object_ref_type="validation",
        object_ref_id=confirmed_map["validation"]["object_id"],
        short_label="Validation Node",
        full_description="Graph node for validation history retrieval",
        status="active",
    )
    conflict_edge = store.create_graph_edge(
        workspace_id=workspace_id,
        source_node_id=str(evidence_node["node_id"]),
        target_node_id=str(conflict_node["node_id"]),
        edge_type="conflicts",
        object_ref_type="conflict_link",
        object_ref_id=f"link_{confirmed_map['conflict']['object_id']}",
        strength=0.7,
        status="active",
    )
    evidence_ref = store.create_evidence_ref(
        workspace_id=workspace_id,
        source_id=str(source_b["source_id"]),
        object_type="evidence",
        object_id=confirmed_map["evidence"]["object_id"],
        ref_type="literature",
        layer="fragment",
        title=str(source_b["title"]),
        doi=None,
        url=None,
        venue=None,
        publication_year=None,
        authors=[],
        excerpt="timeout latency increased in retrieval queue on shard imbalance",
        locator={
            "start": 0,
            "end": 60,
            "char_start": 0,
            "char_end": 60,
            "text": "timeout latency increased in retrieval queue on shard imbalance",
        },
        authority_score=0.9,
        authority_tier="tier_b_preprint_or_official_report",
        metadata={"seeded_by": "slice10"},
        confirmed_at=store.now(),
    )

    failure = store.create_failure(
        workspace_id=workspace_id,
        attached_targets=[{"target_type": "node", "target_id": str(evidence_node["node_id"])}],
        observed_outcome="timeout pattern detected on retrieval pipeline",
        expected_difference="latency should remain stable",
        failure_reason="timeout pattern from queue saturation",
        severity="high",
        reporter="slice10_unit",
    )
    validation_action = store.create_validation(
        workspace_id=workspace_id,
        target_object=f"evidence:{confirmed_map['evidence']['object_id']}",
        method="run benchmark replay",
        success_signal="support score remains above threshold",
        weakening_signal="timeout keeps appearing",
    )

    hypothesis = store.create_hypothesis(
        workspace_id=workspace_id,
        title="Timeout mitigation hypothesis",
        summary="retry policy can reduce queue timeout spikes",
        premise="failure and conflict both point to queue pressure",
        rationale="hypothesis stays exploratory until validation",
        trigger_refs=[
            {
                "trigger_id": "trigger_failure_seed",
                "trigger_type": "failure",
                "workspace_id": workspace_id,
                "object_ref_type": "failure",
                "object_ref_id": str(failure["failure_id"]),
                "summary": "timeout failure trigger",
                "trace_refs": {
                    "failure_id": str(failure["failure_id"]),
                    "graph_node_id": str(evidence_node["node_id"]),
                },
            }
        ],
        related_object_ids=[
            {"object_type": "failure", "object_id": str(failure["failure_id"])},
            {"object_type": "graph_node", "object_id": str(evidence_node["node_id"])},
        ],
        novelty_typing="incremental",
        minimum_validation_action={
            "validation_id": str(validation_action["validation_id"]),
            "target_object": f"evidence:{confirmed_map['evidence']['object_id']}",
            "method": "run benchmark replay",
            "success_signal": "support improves",
            "weakening_signal": "timeouts persist",
            "cost_level": "low",
            "time_level": "medium",
        },
        weakening_signal={
            "signal_type": "failure",
            "signal_text": "timeouts still occur in replay",
            "severity_hint": "high",
            "trace_refs": {"failure_id": str(failure["failure_id"])},
        },
        generation_job_id="job_slice10_hypothesis",
    )
    return {
        "source_a_id": str(source_a["source_id"]),
        "source_b_id": str(source_b["source_id"]),
        "evidence_object_id": confirmed_map["evidence"]["object_id"],
        "conflict_object_id": confirmed_map["conflict"]["object_id"],
        "validation_object_id": confirmed_map["validation"]["object_id"],
        "evidence_node_id": str(evidence_node["node_id"]),
        "conflict_node_id": str(conflict_node["node_id"]),
        "validation_node_id": str(validation_node["node_id"]),
        "conflict_edge_id": str(conflict_edge["edge_id"]),
        "failure_id": str(failure["failure_id"]),
        "validation_id": str(validation_action["validation_id"]),
        "hypothesis_id": str(hypothesis["hypothesis_id"]),
        "evidence_ref_id": str(evidence_ref["ref_id"]),
    }


def test_slice10_each_retrieval_view_returns_traceable_research_items(tmp_path) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_slice10_view_coverage"
    _seed_confirmed_objects(store, workspace_id)
    service = ResearchRetrievalService(store)

    view_queries = {
        "evidence": "retrieval precision",
        "contradiction": "contradiction baseline",
        "failure_pattern": "timeout pattern",
        "validation_history": "benchmark replay",
        "hypothesis_support": "retry policy hypothesis",
    }
    for view_type, query in view_queries.items():
        response = service.retrieve(
            workspace_id=workspace_id,
            view_type=view_type,
            query=query,
            retrieve_method="hybrid",
            top_k=10,
            metadata_filters={},
            request_id=f"req_slice10_{view_type}",
        )
        assert response["view_type"] == view_type
        assert response["workspace_id"] == workspace_id
        assert response["retrieve_method"] == "hybrid"
        assert response["total"] >= 1
        item = response["items"][0]
        assert "source_ref" in item
        assert "graph_refs" in item
        assert "formal_refs" in item
        assert "trace_refs" in item
        assert isinstance(item.get("evidence_highlight_spans", []), list)
        assert isinstance(item.get("mechanism_relation_highlights", []), list)


def test_slice10_retrieval_item_contains_evidence_highlight_span_trace(tmp_path) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_slice10_evidence_span_highlight"
    seeded = _seed_confirmed_objects(store, workspace_id)
    service = ResearchRetrievalService(store)

    response = service.retrieve(
        workspace_id=workspace_id,
        view_type="evidence",
        query="timeout latency increased",
        retrieve_method="hybrid",
        top_k=10,
        metadata_filters={},
        request_id="req_slice10_evidence_highlight",
    )
    assert response["total"] >= 1
    item = response["items"][0]
    highlights = item.get("evidence_highlight_spans", [])
    assert highlights
    first = highlights[0]
    assert first["trace_ref"]["evidence_ref_id"] == seeded["evidence_ref_id"]
    assert first["span"]["char_start"] == 0
    assert first["span"]["char_end"] == 60
    assert item["trace_refs"]["evidence_highlight_spans"] == highlights


def test_slice10_metadata_filter_and_hybrid_scoring_changes_results(tmp_path) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_slice10_filter_hybrid"
    seeded = _seed_confirmed_objects(store, workspace_id)
    service = ResearchRetrievalService(store)

    filtered = service.retrieve(
        workspace_id=workspace_id,
        view_type="evidence",
        query="retrieval precision benchmark",
        retrieve_method="hybrid",
        top_k=10,
        metadata_filters={"source_id": [seeded["source_a_id"]]},
        request_id="req_slice10_filter",
    )
    assert filtered["total"] >= 1
    assert all(
        item["source_ref"].get("source_id") == seeded["source_a_id"]
        for item in filtered["items"]
    )
    assert filtered["items"][0]["score"] >= filtered["items"][-1]["score"]

    changed = service.retrieve(
        workspace_id=workspace_id,
        view_type="evidence",
        query="timeout latency",
        retrieve_method="hybrid",
        top_k=10,
        metadata_filters={},
        request_id="req_slice10_filter_changed",
    )
    assert changed["total"] >= 1
    assert filtered["items"][0]["result_id"] != changed["items"][0]["result_id"]


def test_slice10_workspace_scope_empty_result_and_invalid_request_semantics(tmp_path) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_slice10_scope"
    _seed_confirmed_objects(store, workspace_id)
    service = ResearchRetrievalService(store)

    empty = service.retrieve(
        workspace_id=workspace_id,
        view_type="failure_pattern",
        query="nonexistent keyword for empty result",
        retrieve_method="hybrid",
        top_k=10,
        metadata_filters={"severity": ["low"]},
        request_id="req_slice10_empty",
    )
    assert empty["total"] == 0
    assert empty["items"] == []

    other_workspace = service.retrieve(
        workspace_id="ws_slice10_other",
        view_type="evidence",
        query="retrieval precision",
        retrieve_method="hybrid",
        top_k=10,
        metadata_filters={},
        request_id="req_slice10_other_workspace",
    )
    assert other_workspace["total"] == 0
    assert other_workspace["items"] == []

    with pytest.raises(RetrievalServiceError) as invalid_view_exc:
        service.retrieve(
            workspace_id=workspace_id,
            view_type="invalid_view",
            query="anything",
            retrieve_method="hybrid",
            top_k=10,
            metadata_filters={},
            request_id="req_slice10_invalid_view",
        )
    assert invalid_view_exc.value.status_code == 400
    assert invalid_view_exc.value.error_code == "research.invalid_request"

    with pytest.raises(RetrievalServiceError) as invalid_filter_exc:
        service.retrieve(
            workspace_id=workspace_id,
            view_type="evidence",
            query="retrieval",
            retrieve_method="hybrid",
            top_k=10,
            metadata_filters={"severity": ["high"]},
            request_id="req_slice10_invalid_filter",
        )
    assert invalid_filter_exc.value.status_code == 400
    assert invalid_filter_exc.value.error_code == "research.invalid_request"

    with sqlite3.connect(store.db_path) as conn:
        row = conn.execute(
            """
            SELECT status, error_json
            FROM research_events
            WHERE request_id = ?
              AND event_name = 'retrieval_view_completed'
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            ("req_slice10_invalid_filter",),
        ).fetchone()
    assert row is not None
    assert row[0] == "failed"
    assert row[1] is not None
    error_payload = json.loads(str(row[1]))
    assert error_payload["error_code"] == "research.invalid_request"


def test_slice10_validation_history_target_node_keeps_source_and_graph_traceability(
    tmp_path,
) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_slice10_validation_traceability"
    seeded = _seed_confirmed_objects(store, workspace_id)
    evidence_node_id = seeded["evidence_node_id"]

    # Add a validation action that explicitly targets a graph node, matching dev-console flow.
    store.create_validation(
        workspace_id=workspace_id,
        target_object=f"node:{evidence_node_id}",
        method="node targeted replay",
        success_signal="evidence still supported",
        weakening_signal="node support weakens",
    )

    service = ResearchRetrievalService(store)
    response = service.retrieve(
        workspace_id=workspace_id,
        view_type="validation_history",
        query="node targeted replay",
        retrieve_method="hybrid",
        top_k=10,
        metadata_filters={"method": ["node targeted replay"]},
        request_id="req_slice10_validation_node_target",
    )
    assert response["total"] >= 1
    action_item = next(
        (
            item
            for item in response["items"]
            if str(item["result_id"]).startswith("validation_action:")
        ),
        None,
    )
    assert action_item is not None
    assert action_item["source_ref"].get("source_id")
    assert evidence_node_id in action_item["graph_refs"].get("node_ids", [])


def test_slice10_logical_retrieval_method_returns_logical_query_ref_and_mutual_index(
    tmp_path,
) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_slice10_logical_method"
    seeded = _seed_confirmed_objects(store, workspace_id)
    service = ResearchRetrievalService(store)

    response = service.retrieve(
        workspace_id=workspace_id,
        view_type="evidence",
        query="under shard imbalance, conflicts mechanism reduces timeout outcomes",
        retrieve_method="logical",
        top_k=10,
        metadata_filters={},
        request_id="req_slice10_logical_method",
    )

    assert response["retrieve_method"] == "logical"
    assert response["query_ref"]["logical_subgoal_count"] >= 1
    roles = {
        str(item.get("role", ""))
        for item in response["query_ref"].get("logical_subgoals", [])
        if isinstance(item, dict)
    }
    assert {"condition", "mechanism", "outcome"} & roles
    assert response["total"] >= 1
    trace_refs = response["items"][0]["trace_refs"]
    mutual_index = trace_refs.get("mutual_index", {})
    assert "graph_to_text" in mutual_index
    assert "text_to_graph" in mutual_index
    assert "formal_ref_keys" in mutual_index["graph_to_text"]
    assert "graph_node_ids" in mutual_index["text_to_graph"]
    mechanism_highlights = response["items"][0]["mechanism_relation_highlights"]
    assert mechanism_highlights
    edge_ids = {item["edge_ref"]["edge_id"] for item in mechanism_highlights}
    assert seeded["conflict_edge_id"] in edge_ids
    assert response["items"][0]["trace_refs"]["mechanism_relation_highlights"] == mechanism_highlights


def test_slice10_graph_query_service_supports_logical_subgraph_entrypoint(tmp_path) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_slice10_logical_subgraph"
    seeded = _seed_confirmed_objects(store, workspace_id)
    repository = GraphRepository(store)
    query_service = GraphQueryService(repository)

    result = query_service.query_logical_subgraph(
        workspace_id=workspace_id,
        formal_refs=[
            {
                "object_type": "evidence",
                "object_id": seeded["evidence_object_id"],
            }
        ],
    )

    node_ids = {str(node["node_id"]) for node in result["nodes"]}
    assert seeded["evidence_node_id"] in node_ids
    assert "trace_refs" in result
    assert "matched_object_refs" in result["trace_refs"]
    assert "path_evidence" in result
    assert result["path_evidence"] == []

    metapath_result = query_service.query_logical_subgraph(
        workspace_id=workspace_id,
        formal_refs=[
            {
                "object_type": "evidence",
                "object_id": seeded["evidence_object_id"],
            }
        ],
        edge_type_sequence=["conflicts"],
        path_limit=8,
    )
    assert metapath_result["path_evidence"]
    path = metapath_result["path_evidence"][0]
    assert path["edge_type_sequence"] == ["conflicts"]
    assert "trace_refs" in path
    assert metapath_result["trace_refs"]["metapath_path_count"] >= 1


def test_slice10_retrieval_attaches_top_level_memory_recall_with_formal_ref_scope(
    monkeypatch, tmp_path
) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_slice10_memory_recall"
    _seed_confirmed_objects(store, workspace_id)
    service = ResearchRetrievalService(store)
    captured: dict[str, object] = {}

    def _fake_recall(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "status": "completed",
            "requested_method": str(kwargs["requested_method"]),
            "applied_method": str(kwargs["requested_method"]),
            "reason": None,
            "query_text": str(kwargs["query_text"]),
            "total": 1,
            "items": [
                {
                    "memory_type": "event_log",
                    "memory_id": "mem_retrieval_01",
                    "score": 0.88,
                    "title": "retrieval memory",
                    "snippet": "retrieval memory snippet",
                    "timestamp": "2026-04-24T00:00:00Z",
                    "linked_claim_refs": [],
                    "trace_refs": {},
                }
            ],
            "trace_refs": {},
        }

    monkeypatch.setattr(service._memory_recall_service, "recall", _fake_recall)

    response = service.retrieve(
        workspace_id=workspace_id,
        view_type="evidence",
        query="retrieval precision",
        retrieve_method="hybrid",
        top_k=10,
        metadata_filters={},
        request_id="req_slice10_memory_recall",
    )

    claim_by_formal_ref = {
        (str(item["object_type"]), str(item["object_id"])): str(item["claim_id"])
        for item in store.list_confirmed_objects(workspace_id)
        if item.get("claim_id")
    }
    expected_scope: list[str] = []
    for item in response["items"]:
        for formal_ref in item["formal_refs"]:
            key = (str(formal_ref["object_type"]), str(formal_ref["object_id"]))
            claim_id = claim_by_formal_ref.get(key)
            if claim_id and claim_id not in expected_scope:
                expected_scope.append(claim_id)

    assert response["memory_recall"]["status"] == "completed"
    assert captured["workspace_id"] == workspace_id
    assert captured["query_text"] == "retrieval precision"
    assert captured["requested_method"] == "hybrid"
    assert captured["scope_mode"] == "prefer"
    assert captured["scope_claim_ids"] == expected_scope
