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
                "text": "Claim: retrieval improves accuracy.",
                "source_span": {"start": 0, "end": 30},
                "extractor_name": "evidence_extractor",
            },
            {
                "candidate_type": "assumption",
                "text": "Assumption: embeddings remain stable.",
                "source_span": {"start": 31, "end": 68},
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
    assert version["version_id"]
    assert len(nodes) >= 2
    assert len(edges) >= 1
    assert {node["object_ref_type"] for node in nodes}.issuperset(
        {"evidence", "assumption"}
    )
    assert all(node["object_ref_id"] for node in nodes)
    assert all(edge["object_ref_type"] for edge in edges)
    assert all(edge["object_ref_id"] for edge in edges)


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
    all_nodes = repo.list_nodes(workspace_id=workspace_id)
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
