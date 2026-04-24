from __future__ import annotations

import pytest

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.graph.repository import GraphRepository
from research_layer.services.candidate_confirmation_service import (
    CandidateConfirmationService,
)
from research_layer.services.graph_build_service import GraphBuildService
from research_layer.services.graph_query_service import GraphQueryService


def _build_store(tmp_path) -> ResearchApiStateStore:
    db_path = tmp_path / "slice5_graph.sqlite3"
    return ResearchApiStateStore(db_path=str(db_path))


def _seed_confirmed_evidence_and_assumption(
    *, store: ResearchApiStateStore, workspace_id: str
) -> tuple[str, str]:
    source = store.create_source(
        workspace_id=workspace_id,
        source_type="paper",
        title="slice5 source",
        content="Claim: retrieval improves accuracy. Assumption: embeddings remain stable.",
        metadata={},
        import_request_id="req_slice5_seed",
    )
    job = store.create_job(
        job_type="source_extract",
        workspace_id=workspace_id,
        request_id="req_slice5_seed",
    )
    batch = store.create_candidate_batch(
        workspace_id=workspace_id,
        source_id=str(source["source_id"]),
        job_id=str(job["job_id"]),
        request_id="req_slice5_seed",
    )
    created = store.add_candidates_to_batch(
        candidate_batch_id=str(batch["candidate_batch_id"]),
        workspace_id=workspace_id,
        source_id=str(source["source_id"]),
        job_id=str(job["job_id"]),
        candidates=[
            {
                "candidate_type": "evidence",
                "semantic_type": "result",
                "text": "Claim: retrieval improves accuracy.",
                "source_span": {"start": 0, "end": 30},
                "quote": "Claim: retrieval improves accuracy.",
                "trace_refs": {
                    "source_artifact_id": "art_src_seed_p1-b0",
                    "source_anchor_id": "p1-b0",
                },
                "extractor_name": "evidence_extractor",
            },
            {
                "candidate_type": "assumption",
                "semantic_type": "hypothesis",
                "text": "Assumption: embeddings remain stable.",
                "source_span": {"start": 31, "end": 68},
                "quote": "Assumption: embeddings remain stable.",
                "trace_refs": {
                    "source_artifact_id": "art_src_seed_p1-b1",
                    "source_anchor_id": "p1-b1",
                },
                "extractor_name": "assumption_extractor",
            },
        ],
    )
    confirmation = CandidateConfirmationService(store)
    first = confirmation.confirm(
        workspace_id=workspace_id,
        candidate_id=str(created[0]["candidate_id"]),
        request_id="req_slice5_confirm_1",
    )
    second = confirmation.confirm(
        workspace_id=workspace_id,
        candidate_id=str(created[1]["candidate_id"]),
        request_id="req_slice5_confirm_2",
    )
    return first["formal_object_id"], second["formal_object_id"]


def test_build_graph_maps_confirmed_objects_with_traceable_backlinks(tmp_path) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_slice5_unit"
    _seed_confirmed_evidence_and_assumption(store=store, workspace_id=workspace_id)

    repo = GraphRepository(store)
    build_service = GraphBuildService(repo)
    version = build_service.build_workspace_graph(
        workspace_id=workspace_id, request_id="req_slice5_build"
    )

    nodes = repo.list_nodes(workspace_id=workspace_id)
    edges = repo.list_edges(workspace_id=workspace_id)
    active_nodes = [node for node in nodes if node["status"] == "active"]
    active_edges = [edge for edge in edges if edge["status"] == "active"]
    assert version["version_id"]
    assert len(nodes) >= 2
    assert len(edges) >= 1
    assert active_nodes
    assert active_edges
    assert {node["object_ref_type"] for node in nodes}.issuperset(
        {"evidence", "assumption"}
    )
    assert all(node["object_ref_id"] for node in nodes)
    assert all(node["claim_id"] for node in active_nodes)
    assert all(node["source_ref"]["source_id"] for node in active_nodes)
    assert {tuple(node["short_tags"]) for node in nodes}.issuperset(
        {("result",), ("hypothesis",)}
    )
    source_spans = [
        ref.get("source_span")
        for node in nodes
        for ref in node.get("source_refs", [])
    ]
    assert {"start": 0, "end": 30} in source_spans
    assert {"start": 31, "end": 68} in source_spans
    source_quotes = [
        ref.get("quote") for node in nodes for ref in node.get("source_refs", [])
    ]
    assert "Claim: retrieval improves accuracy." in source_quotes
    assert "Assumption: embeddings remain stable." in source_quotes
    artifact_ids = [
        ref.get("artifact_id")
        for node in nodes
        for ref in node.get("source_refs", [])
    ]
    assert "art_src_seed_p1-b0" in artifact_ids
    assert "art_src_seed_p1-b1" in artifact_ids
    assert all(edge["object_ref_type"] for edge in edges)
    assert all(edge["object_ref_id"] for edge in edges)
    assert all(edge["claim_id"] for edge in active_edges)
    assert all(edge["source_ref"]["source_id"] for edge in active_edges)


def test_query_returns_local_subgraph_and_update_changes_query_result(tmp_path) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_slice5_query"
    _seed_confirmed_evidence_and_assumption(store=store, workspace_id=workspace_id)
    repo = GraphRepository(store)
    build_service = GraphBuildService(repo)
    build_service.build_workspace_graph(
        workspace_id=workspace_id, request_id="req_slice5_build_query"
    )
    query_service = GraphQueryService(repo)
    all_nodes = [
        node
        for node in repo.list_nodes(workspace_id=workspace_id)
        if node["status"] != "superseded"
    ]
    assert all_nodes
    center_node_id = all_nodes[0]["node_id"]

    subgraph_before = query_service.query_subgraph(
        workspace_id=workspace_id, center_node_id=center_node_id, max_hops=1
    )
    assert subgraph_before["nodes"]
    assert subgraph_before["edges"]

    repo.update_node(
        node_id=center_node_id,
        short_label="Updated Label",
        full_description=None,
        status="weakened",
    )

    subgraph_after = query_service.query_subgraph(
        workspace_id=workspace_id, center_node_id=center_node_id, max_hops=1
    )
    updated_center = next(
        node for node in subgraph_after["nodes"] if node["node_id"] == center_node_id
    )
    assert updated_center["short_label"] == "Updated Label"
    assert updated_center["status"] == "weakened"


def test_query_hides_superseded_graph_objects_after_rebuild(tmp_path) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_slice5_hide_superseded"
    repo = GraphRepository(store)
    old_node = repo.create_node(
        workspace_id=workspace_id,
        node_type="evidence",
        object_ref_type="evidence",
        object_ref_id="evi_old",
        short_label="Old evidence",
        full_description="Old evidence",
    )
    repo.create_edge(
        workspace_id=workspace_id,
        source_node_id=str(old_node["node_id"]),
        target_node_id=str(old_node["node_id"]),
        edge_type="derives",
        object_ref_type="evidence",
        object_ref_id="evi_old",
        strength=0.5,
    )
    repo.reset_workspace_graph(workspace_id)
    active_node = repo.create_node(
        workspace_id=workspace_id,
        node_type="evidence",
        object_ref_type="evidence",
        object_ref_id="evi_new",
        short_label="New evidence",
        full_description="New evidence",
    )

    result = GraphQueryService(repo).query_subgraph(
        workspace_id=workspace_id, center_node_id=None, max_hops=1
    )

    assert [node["node_id"] for node in result["nodes"]] == [active_node["node_id"]]
    assert result["edges"] == []


def test_invalid_node_or_edge_updates_raise_explicit_errors(tmp_path) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_slice5_invalid"
    _seed_confirmed_evidence_and_assumption(store=store, workspace_id=workspace_id)
    repo = GraphRepository(store)
    build_service = GraphBuildService(repo)
    build_service.build_workspace_graph(
        workspace_id=workspace_id, request_id="req_slice5_build_invalid"
    )
    nodes = repo.list_nodes(workspace_id=workspace_id)
    edges = repo.list_edges(workspace_id=workspace_id)
    assert nodes and edges

    with pytest.raises(ValueError):
        repo.update_node(
            node_id=nodes[0]["node_id"],
            short_label=None,
            full_description=None,
            status="not_a_valid_status",
        )

    with pytest.raises(ValueError):
        repo.update_edge(
            edge_id=edges[0]["edge_id"], status="invalid_status", strength=None
        )


def test_rebuild_does_not_physically_delete_archived_graph_objects(tmp_path) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_slice5_archive_rebuild"
    _seed_confirmed_evidence_and_assumption(store=store, workspace_id=workspace_id)
    repo = GraphRepository(store)
    build_service = GraphBuildService(repo)
    build_service.build_workspace_graph(
        workspace_id=workspace_id, request_id="req_slice5_archive_rebuild_1"
    )

    node = repo.list_nodes(workspace_id=workspace_id)[0]
    edge = repo.list_edges(workspace_id=workspace_id)[0]
    archived_node = repo.update_node(
        node_id=node["node_id"],
        short_label=None,
        full_description=None,
        status="archived",
    )
    archived_edge = repo.update_edge(
        edge_id=edge["edge_id"], status="archived", strength=None
    )
    assert archived_node is not None and archived_node["status"] == "archived"
    assert archived_edge is not None and archived_edge["status"] == "archived"

    archived_node_ref = (
        str(archived_node["object_ref_type"]),
        str(archived_node["object_ref_id"]),
    )
    archived_edge_ref = (
        str(archived_edge["object_ref_type"]),
        str(archived_edge["object_ref_id"]),
    )

    build_service.build_workspace_graph(
        workspace_id=workspace_id, request_id="req_slice5_archive_rebuild_2"
    )
    nodes_after = repo.list_nodes(workspace_id=workspace_id)
    edges_after = repo.list_edges(workspace_id=workspace_id)
    matched_nodes = [
        item
        for item in nodes_after
        if (str(item["object_ref_type"]), str(item["object_ref_id"]))
        == archived_node_ref
    ]
    matched_edges = [
        item
        for item in edges_after
        if (str(item["object_ref_type"]), str(item["object_ref_id"]))
        == archived_edge_ref
    ]
    assert matched_nodes
    assert matched_edges
    assert any(item["status"] == "archived" for item in matched_nodes)
    assert any(item["status"] == "archived" for item in matched_edges)


def test_confirm_creates_version_diff_payload_query_back(tmp_path) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_slice5_confirm_version"
    _seed_confirmed_evidence_and_assumption(store=store, workspace_id=workspace_id)

    versions = store.list_graph_versions(workspace_id)
    assert len(versions) >= 2
    latest_version = store.get_graph_version(str(versions[-1]["version_id"]))
    assert latest_version is not None
    diff_payload = latest_version["diff_payload"]
    assert diff_payload["change_type"] == "candidate_confirm_materialization"
    assert "candidate_id" in diff_payload
    assert "added" in diff_payload


def test_build_graph_uses_resolved_relation_candidates_and_skips_unresolved(tmp_path) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_slice5_resolved_relation_build"
    source = store.create_source(
        workspace_id=workspace_id,
        source_type="paper",
        title="resolved relation build",
        content="Evidence supports conclusion. Unresolved link is ignored.",
        metadata={},
        import_request_id="req_slice5_rel_seed",
    )
    job = store.create_job(
        job_type="source_extract",
        workspace_id=workspace_id,
        request_id="req_slice5_rel_seed",
    )
    batch = store.create_candidate_batch(
        workspace_id=workspace_id,
        source_id=str(source["source_id"]),
        job_id=str(job["job_id"]),
        request_id="req_slice5_rel_seed",
    )
    candidates = store.add_candidates_to_batch(
        candidate_batch_id=str(batch["candidate_batch_id"]),
        workspace_id=workspace_id,
        source_id=str(source["source_id"]),
        job_id=str(job["job_id"]),
        candidates=[
            {
                "candidate_type": "evidence",
                "semantic_type": "evidence",
                "text": "Evidence sentence.",
                "source_span": {"page": 1, "block_id": "p1-b0"},
                "quote": "Evidence sentence.",
                "trace_refs": {"argument_unit_id": "u_evidence"},
                "extractor_name": "argument_unit_extractor",
            },
            {
                "candidate_type": "conclusion",
                "semantic_type": "claim",
                "text": "Conclusion sentence.",
                "source_span": {"page": 1, "block_id": "p1-b1"},
                "quote": "Conclusion sentence.",
                "trace_refs": {"argument_unit_id": "u_claim"},
                "extractor_name": "argument_unit_extractor",
            },
        ],
    )
    evidence_candidate_id = str(candidates[0]["candidate_id"])
    conclusion_candidate_id = str(candidates[1]["candidate_id"])
    store.add_relation_candidates_to_batch(
        candidate_batch_id=str(batch["candidate_batch_id"]),
        workspace_id=workspace_id,
        source_id=str(source["source_id"]),
        job_id=str(job["job_id"]),
        relations=[
            {
                "source_candidate_id": evidence_candidate_id,
                "target_candidate_id": conclusion_candidate_id,
                "semantic_relation_type": "supports",
                "relation_type": "supports",
                "relation_status": "resolved",
                "quote": "Evidence supports conclusion.",
                "trace_refs": {"block_id": "p1-b0"},
            },
            {
                "source_candidate_id": conclusion_candidate_id,
                "target_candidate_id": evidence_candidate_id,
                "semantic_relation_type": "unknown",
                "relation_type": "conflicts",
                "relation_status": "unresolved",
                "quote": "Unresolved link is ignored.",
                "trace_refs": {"block_id": "p1-b2"},
            },
        ],
    )
    confirmation = CandidateConfirmationService(store)
    confirmation.confirm(
        workspace_id=workspace_id,
        candidate_id=evidence_candidate_id,
        request_id="req_slice5_confirm_evidence",
    )
    confirmation.confirm(
        workspace_id=workspace_id,
        candidate_id=conclusion_candidate_id,
        request_id="req_slice5_confirm_conclusion",
    )

    repo = GraphRepository(store)
    GraphBuildService(repo).build_workspace_graph(
        workspace_id=workspace_id,
        request_id="req_slice5_build_resolved",
    )

    active_edges = [
        edge for edge in repo.list_edges(workspace_id=workspace_id) if edge["status"] == "active"
    ]
    assert [edge["edge_type"] for edge in active_edges] == ["supports"]
    assert active_edges[0]["object_ref_type"] == "relation_candidate"
    assert active_edges[0]["claim_id"]
    assert active_edges[0]["source_ref"]["source_id"] == str(source["source_id"])


def test_build_graph_skips_confirmed_objects_without_claim_traceability(tmp_path) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_slice5_gate"
    source = store.create_source(
        workspace_id=workspace_id,
        source_type="paper",
        title="gate source",
        content="Claim: legacy confirmed object lacks claim ledger.",
        metadata={},
        import_request_id="req_slice5_gate_seed",
    )
    job = store.create_job(
        job_type="source_extract",
        workspace_id=workspace_id,
        request_id="req_slice5_gate_seed",
    )
    batch = store.create_candidate_batch(
        workspace_id=workspace_id,
        source_id=str(source["source_id"]),
        job_id=str(job["job_id"]),
        request_id="req_slice5_gate_seed",
    )
    created = store.add_candidates_to_batch(
        candidate_batch_id=str(batch["candidate_batch_id"]),
        workspace_id=workspace_id,
        source_id=str(source["source_id"]),
        job_id=str(job["job_id"]),
        candidates=[
            {
                "candidate_type": "evidence",
                "semantic_type": "result",
                "text": "Claim: legacy confirmed object lacks claim ledger.",
                "source_span": {"start": 0, "end": 48},
                "quote": "Claim: legacy confirmed object lacks claim ledger.",
                "trace_refs": {"source_anchor_id": "p1-b0"},
                "extractor_name": "argument_unit_extractor",
            }
        ],
    )
    candidate = created[0]
    store.create_confirmed_object_from_candidate(
        candidate=candidate,
        normalized_text="claim: legacy confirmed object lacks claim ledger.",
        request_id="req_slice5_gate_confirmed",
    )
    store.update_candidate_status(
        candidate_id=str(candidate["candidate_id"]),
        status="confirmed",
    )

    repo = GraphRepository(store)
    version = GraphBuildService(repo).build_workspace_graph(
        workspace_id=workspace_id,
        request_id="req_slice5_gate_build",
    )
    latest_version = store.get_graph_version(str(version["version_id"]))
    skipped_event = store.find_latest_event(
        workspace_id=workspace_id,
        event_name="graph_projection_skipped",
        ref_key="reason",
        ref_value="missing_claim_or_source_ref",
    )

    assert version["node_count"] == 0
    assert version["edge_count"] == 0
    assert latest_version is not None
    assert (
        latest_version["diff_payload"]["skipped_missing_traceability_count"] == 1
    )
    assert skipped_event is not None
    assert skipped_event["status"] == "skipped"
