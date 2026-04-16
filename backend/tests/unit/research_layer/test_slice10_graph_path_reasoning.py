from __future__ import annotations

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.graph.repository import GraphRepository
from research_layer.services.graph_query_service import GraphQueryService


def _build_store(tmp_path) -> ResearchApiStateStore:
    return ResearchApiStateStore(
        db_path=str(tmp_path / "slice10_graph_path_reasoning.sqlite3")
    )


def _seed_graph_for_metapath(
    store: ResearchApiStateStore, workspace_id: str
) -> dict[str, str]:
    n1 = store.create_graph_node(
        workspace_id=workspace_id,
        node_type="evidence",
        object_ref_type="research_evidence",
        object_ref_id="obj_evidence_1",
        short_label="Evidence A",
        full_description="seed evidence A",
        status="active",
    )
    n2 = store.create_graph_node(
        workspace_id=workspace_id,
        node_type="assumption",
        object_ref_type="research_assumption",
        object_ref_id="obj_assumption_1",
        short_label="Assumption B",
        full_description="seed assumption B",
        status="active",
    )
    n3 = store.create_graph_node(
        workspace_id=workspace_id,
        node_type="validation",
        object_ref_type="research_validation",
        object_ref_id="obj_validation_1",
        short_label="Validation C",
        full_description="seed validation C",
        status="active",
    )
    n4 = store.create_graph_node(
        workspace_id=workspace_id,
        node_type="evidence",
        object_ref_type="research_evidence",
        object_ref_id="obj_evidence_2",
        short_label="Evidence D",
        full_description="seed evidence D",
        status="active",
    )

    store.create_graph_edge(
        workspace_id=workspace_id,
        source_node_id=str(n1["node_id"]),
        target_node_id=str(n2["node_id"]),
        edge_type="supports",
        object_ref_type="research_link",
        object_ref_id="edge_support_1",
        strength=0.8,
        status="active",
    )
    store.create_graph_edge(
        workspace_id=workspace_id,
        source_node_id=str(n2["node_id"]),
        target_node_id=str(n3["node_id"]),
        edge_type="enables",
        object_ref_type="research_link",
        object_ref_id="edge_enable_1",
        strength=0.7,
        status="active",
    )
    store.create_graph_edge(
        workspace_id=workspace_id,
        source_node_id=str(n1["node_id"]),
        target_node_id=str(n4["node_id"]),
        edge_type="supports",
        object_ref_type="research_link",
        object_ref_id="edge_support_2",
        strength=0.6,
        status="active",
    )
    store.create_graph_edge(
        workspace_id=workspace_id,
        source_node_id=str(n4["node_id"]),
        target_node_id=str(n3["node_id"]),
        edge_type="enables",
        object_ref_type="research_link",
        object_ref_id="edge_enable_2",
        strength=0.9,
        status="active",
    )
    return {
        "node_a": str(n1["node_id"]),
        "node_c": str(n3["node_id"]),
    }


def test_slice10_typed_metapath_traversal_returns_path_evidence_and_trace_refs(
    tmp_path,
) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_slice10_metapath"
    seeded = _seed_graph_for_metapath(store, workspace_id)
    query_service = GraphQueryService(GraphRepository(store))

    result = query_service.query_typed_metapath_paths(
        workspace_id=workspace_id,
        start_node_ids=[seeded["node_a"]],
        edge_type_sequence=["supports", "enables"],
        max_paths=10,
    )

    assert result["path_evidence"]
    assert len(result["path_evidence"]) == 2
    first = result["path_evidence"][0]
    assert first["start_node_id"] == seeded["node_a"]
    assert first["end_node_id"] == seeded["node_c"]
    assert first["edge_type_sequence"] == ["supports", "enables"]
    assert first["hop_count"] == 2
    assert len(first["path_node_ids"]) == 3
    assert len(first["path_edge_ids"]) == 2
    assert "trace_refs" in first
    assert result["trace_refs"]["edge_type_sequence"] == ["supports", "enables"]
    assert result["trace_refs"]["returned_path_count"] == 2


def test_slice10_missing_edge_prediction_uses_metapath_evidence(tmp_path) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_slice10_missing_edge"
    seeded = _seed_graph_for_metapath(store, workspace_id)
    query_service = GraphQueryService(GraphRepository(store))

    predicted = query_service.predict_missing_edges(
        workspace_id=workspace_id,
        start_node_ids=[seeded["node_a"]],
        edge_type_sequence=["supports", "enables"],
        predicted_edge_type="implies",
        top_k=10,
        max_paths=20,
    )
    assert predicted["predictions"]
    candidate = predicted["predictions"][0]
    assert candidate["source_node_id"] == seeded["node_a"]
    assert candidate["target_node_id"] == seeded["node_c"]
    assert candidate["predicted_edge_type"] == "implies"
    assert candidate["path_count"] == 2
    assert candidate["path_evidence"]
    assert candidate["trace_refs"]["supporting_path_ids"]
    assert predicted["path_evidence"]
    assert predicted["trace_refs"]["returned_prediction_count"] >= 1

    store.create_graph_edge(
        workspace_id=workspace_id,
        source_node_id=seeded["node_a"],
        target_node_id=seeded["node_c"],
        edge_type="implies",
        object_ref_type="research_link",
        object_ref_id="edge_implies_existing",
        strength=0.5,
        status="active",
    )
    skipped = query_service.predict_missing_edges(
        workspace_id=workspace_id,
        start_node_ids=[seeded["node_a"]],
        edge_type_sequence=["supports", "enables"],
        predicted_edge_type="implies",
        top_k=10,
        max_paths=20,
    )
    assert skipped["predictions"] == []
    assert f"{seeded['node_a']}->{seeded['node_c']}" in set(
        skipped["trace_refs"]["existing_edge_pairs_skipped"]
    )
