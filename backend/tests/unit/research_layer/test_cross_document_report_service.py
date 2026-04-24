from __future__ import annotations

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.services.cross_document_report_service import (
    CrossDocumentReportService,
)


def _seed_claim(
    store: ResearchApiStateStore, workspace_id: str, text: str
) -> dict[str, object]:
    source = store.create_source(
        workspace_id=workspace_id,
        source_type="paper",
        title=text[:40],
        content=text,
        metadata={},
        import_request_id="req_report_seed",
    )
    batch = store.create_candidate_batch(
        workspace_id=workspace_id,
        source_id=str(source["source_id"]),
        job_id="job_report_seed",
        request_id="req_report_seed",
    )
    candidate = store.add_candidates_to_batch(
        candidate_batch_id=str(batch["candidate_batch_id"]),
        workspace_id=workspace_id,
        source_id=str(source["source_id"]),
        job_id="job_report_seed",
        candidates=[
            {
                "candidate_type": "evidence",
                "text": text,
                "source_span": {"start": 0, "end": len(text)},
                "trace_refs": {"source_id": source["source_id"]},
                "extractor_name": "test_cross_document_report",
            }
        ],
    )[0]
    return store.create_claim_from_candidate(
        candidate=candidate,
        normalized_text=text.lower(),
    )


def test_cross_document_report_summarizes_workspace_state(tmp_path) -> None:
    store = ResearchApiStateStore(db_path=str(tmp_path / "cross_doc.sqlite3"))
    workspace_id = "ws_cross_doc_report"
    old_claim = _seed_claim(store, workspace_id, "Method A improves recall.")
    new_claim = _seed_claim(store, workspace_id, "Method A does not improve recall.")
    conflict = store.create_claim_conflict(
        workspace_id=workspace_id,
        new_claim_id=str(new_claim["claim_id"]),
        existing_claim_id=str(old_claim["claim_id"]),
        conflict_type="possible_contradiction",
        status="needs_review",
        evidence={"detector": "test"},
        source_ref={"new_claim_id": new_claim["claim_id"]},
        created_request_id="req_report_conflict",
    )
    store.create_source_memory_recall_result(
        workspace_id=workspace_id,
        source_id=str(new_claim["source_id"]),
        status="completed",
        reason=None,
        requested_method="logical",
        applied_method="hybrid",
        query_text=str(new_claim["text"]),
        total=1,
        items=[
            {
                "memory_type": "episodic_memory",
                "memory_id": "mem_report_1",
                "score": 0.87,
                "title": "Prior method A result",
                "snippet": "Prior work questioned recall improvement.",
                "linked_claim_refs": [{"claim_id": old_claim["claim_id"]}],
                "trace_refs": {},
            }
        ],
        trace_refs={"request_id": "req_report_recall"},
        error=None,
        request_id="req_report_recall",
    )
    node = store.create_graph_node(
        workspace_id=workspace_id,
        node_type="evidence",
        object_ref_type="claim",
        object_ref_id=str(new_claim["claim_id"]),
        short_label="Method A recall",
        full_description=str(new_claim["text"]),
        claim_id=str(new_claim["claim_id"]),
        source_ref={"source_id": new_claim["source_id"]},
    )
    route = store.create_route(
        workspace_id=workspace_id,
        title="Evaluate Method A",
        summary="Check whether Method A improves recall.",
        status="active",
        support_score=0.5,
        risk_score=0.7,
        progressability_score=0.6,
        conclusion="Method A recall claim is contested.",
        key_supports=[str(new_claim["text"])],
        assumptions=[],
        risks=["conflicting claim"],
        next_validation_action="review contradiction",
        route_node_ids=[str(node["node_id"])],
    )

    report = CrossDocumentReportService(store).build(
        workspace_id=workspace_id,
        request_id="req_report",
    )

    assert report["workspace_id"] == workspace_id
    assert report["summary"]["claim_count"] == 2
    assert report["summary"]["conflict_count"] == 1
    assert report["summary"]["source_recall_count"] == 1
    assert report["summary"]["route_count"] == 1
    assert [item["claim_id"] for item in report["sections"]["claims"]] == [
        old_claim["claim_id"],
        new_claim["claim_id"],
    ]
    assert report["sections"]["conflicts"][0]["conflict_id"] == conflict["conflict_id"]
    assert report["sections"]["historical_recall"][0]["items"][0]["memory_id"] == "mem_report_1"
    assert report["sections"]["routes"][0]["route_id"] == route["route_id"]
    assert report["sections"]["routes"][0]["route_node_ids"] == {
        "total": 1,
        "items": [node["node_id"]],
        "truncated": False,
    }
    assert report["sections"]["challenged_routes"][0]["challenge_status"] == "needs_review"
    assert report["sections"]["unresolved_gaps"][0]["gap_type"] == "claim_conflict"
    assert report["trace_refs"]["request_id"] == "req_report"
    assert report["trace_refs"]["claim_ids"]["items"] == [
        old_claim["claim_id"],
        new_claim["claim_id"],
    ]


def test_cross_document_report_truncates_large_nested_payloads(tmp_path) -> None:
    store = ResearchApiStateStore(db_path=str(tmp_path / "cross_doc_large.sqlite3"))
    workspace_id = "ws_cross_doc_large"
    claim = _seed_claim(store, workspace_id, "Large payload claim.")
    recall_items = [
        {
            "memory_type": "episodic_memory",
            "memory_id": f"mem_large_{index}",
            "score": 1.0 - index / 100,
            "title": f"Memory {index}",
            "snippet": "historical context",
            "linked_claim_refs": [{"claim_id": claim["claim_id"]}],
            "trace_refs": {"oversized": ["x"] * 100},
        }
        for index in range(10)
    ]
    store.create_source_memory_recall_result(
        workspace_id=workspace_id,
        source_id=str(claim["source_id"]),
        status="completed",
        reason=None,
        requested_method="logical",
        applied_method="hybrid",
        query_text=str(claim["text"]),
        total=len(recall_items),
        items=recall_items,
        trace_refs={"request_id": "req_large", "large": ["x"] * 100},
        error=None,
        request_id="req_large",
    )
    node = store.create_graph_node(
        workspace_id=workspace_id,
        node_type="evidence",
        object_ref_type="claim",
        object_ref_id=str(claim["claim_id"]),
        short_label="Large route",
        full_description=str(claim["text"]),
        claim_id=str(claim["claim_id"]),
        source_ref={"source_id": claim["source_id"]},
    )
    route_node_ids = [str(node["node_id"])] + [
        f"node_extra_{index}" for index in range(20)
    ]
    route_edge_ids = [f"edge_extra_{index}" for index in range(20)]
    store.create_route(
        workspace_id=workspace_id,
        title="Large route arrays",
        summary="Route with large arrays.",
        status="active",
        support_score=0.5,
        risk_score=0.1,
        progressability_score=0.6,
        conclusion="Large route conclusion.",
        key_supports=[],
        assumptions=[],
        risks=[],
        next_validation_action="review samples",
        route_node_ids=route_node_ids,
        route_edge_ids=route_edge_ids,
    )

    report = CrossDocumentReportService(store).build(
        workspace_id=workspace_id,
        request_id="req_large_report",
    )

    historical_recall = report["sections"]["historical_recall"][0]
    assert historical_recall["item_total"] == 10
    assert len(historical_recall["items"]) == 3
    assert historical_recall["items_truncated"] is True
    assert "trace_refs" not in historical_recall["items"][0]
    route_ref = report["sections"]["routes"][0]
    assert route_ref["route_node_ids"] == {
        "total": 21,
        "items": route_node_ids[:5],
        "truncated": True,
    }
    assert route_ref["route_edge_ids"] == {
        "total": 20,
        "items": route_edge_ids[:5],
        "truncated": True,
    }
