from __future__ import annotations

import hashlib

from research_layer.api.controllers._state_store import ResearchApiStateStore


def test_state_store_list_sources_is_workspace_scoped(tmp_path) -> None:
    store = ResearchApiStateStore(db_path=str(tmp_path / "research_track1.sqlite3"))
    store.create_source(
        workspace_id="ws_track1_a",
        source_type="paper",
        title="A1",
        content="content-a1",
        metadata={},
        import_request_id="req_a1",
    )
    store.create_source(
        workspace_id="ws_track1_a",
        source_type="note",
        title="A2",
        content="content-a2",
        metadata={},
        import_request_id="req_a2",
    )
    store.create_source(
        workspace_id="ws_track1_b",
        source_type="paper",
        title="B1",
        content="content-b1",
        metadata={},
        import_request_id="req_b1",
    )

    items = store.list_sources(workspace_id="ws_track1_a")

    assert len(items) == 2
    assert all(item["workspace_id"] == "ws_track1_a" for item in items)


def test_state_store_list_workspaces_summarizes_non_empty_workspaces(tmp_path) -> None:
    store = ResearchApiStateStore(db_path=str(tmp_path / "research_workspaces.sqlite3"))
    store.create_source(
        workspace_id="ws_empty_default",
        source_type="paper",
        title="empty marker",
        content="source only",
        metadata={},
        import_request_id="req_empty",
    )
    source_a = store.create_source(
        workspace_id="ws_has_graph",
        source_type="paper",
        title="A",
        content="content-a",
        metadata={},
        import_request_id="req_a",
    )
    source_b = store.create_source(
        workspace_id="ws_has_source",
        source_type="note",
        title="B",
        content="content-b",
        metadata={},
        import_request_id="req_b",
    )
    first = store.create_graph_node(
        workspace_id="ws_has_graph",
        node_type="evidence",
        object_ref_type="source",
        object_ref_id=str(source_a["source_id"]),
        short_label="Evidence",
        full_description="Evidence node",
    )
    second = store.create_graph_node(
        workspace_id="ws_has_graph",
        node_type="conclusion",
        object_ref_type="source",
        object_ref_id=str(source_a["source_id"]),
        short_label="Conclusion",
        full_description="Conclusion node",
    )
    store.create_graph_edge(
        workspace_id="ws_has_graph",
        source_node_id=str(first["node_id"]),
        target_node_id=str(second["node_id"]),
        edge_type="supports",
        object_ref_type="manual_link",
        object_ref_id="edge-a",
        strength=0.9,
    )

    items = store.list_workspaces()

    by_id = {str(item["workspace_id"]): item for item in items}
    assert by_id["ws_has_graph"]["source_count"] == 1
    assert by_id["ws_has_graph"]["node_count"] == 2
    assert by_id["ws_has_graph"]["edge_count"] == 1
    assert by_id["ws_has_graph"]["updated_at"] is not None
    assert by_id["ws_has_source"]["source_count"] == 1
    assert str(source_b["workspace_id"]) in by_id


def test_state_store_persists_source_hashes_claims_and_memory_links(tmp_path) -> None:
    store = ResearchApiStateStore(db_path=str(tmp_path / "research_traceability.sqlite3"))
    source = store.create_source(
        workspace_id="ws_trace_store",
        source_type="paper",
        title="Trace Source",
        content="Claim: traceability is explicit.",
        metadata={},
        import_request_id="req_trace_store",
    )
    source_hash = store.create_source_hash(
        source_id=str(source["source_id"]),
        workspace_id="ws_trace_store",
        raw_sha256=hashlib.sha256(b"raw payload").hexdigest(),
        content_sha256=hashlib.sha256(
            b"Claim: traceability is explicit."
        ).hexdigest(),
        parser_name="manual_text",
        parser_version="v1",
    )
    claim = store.create_claim(
        workspace_id="ws_trace_store",
        source_id=str(source["source_id"]),
        candidate_id="cand_trace_store",
        claim_type="evidence",
        semantic_type="result",
        text="Claim: traceability is explicit.",
        normalized_text="claim: traceability is explicit.",
        quote="Claim: traceability is explicit.",
        source_span={"start": 0, "end": 31},
        trace_refs={"source_anchor_id": "p1-b0"},
        status="active",
    )
    memory_link = store.upsert_claim_memory_link(
        claim_id=str(claim["claim_id"]),
        workspace_id="ws_trace_store",
        memory_id=None,
        sync_mode="best_effort_record",
        status="skipped",
        reason="bridge_not_configured",
        last_error=None,
    )

    reloaded_source = store.get_source(str(source["source_id"]))
    reloaded_claim = store.get_claim(str(claim["claim_id"]))
    claim_lookup = store.get_claim_by_candidate_id(
        workspace_id="ws_trace_store",
        candidate_id="cand_trace_store",
    )

    assert reloaded_source is not None
    assert reloaded_source["source_hash"] == source_hash
    assert reloaded_claim is not None
    assert reloaded_claim["memory_link"] == memory_link
    assert claim_lookup is not None
    assert claim_lookup["claim_id"] == claim["claim_id"]
