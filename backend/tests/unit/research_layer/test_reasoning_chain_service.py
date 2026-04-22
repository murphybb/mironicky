from __future__ import annotations

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.graph.repository import GraphRepository
from research_layer.services.reasoning_chain_service import ReasoningChainService


def test_reasoning_chain_persists_and_invalidates_intersecting_paths(tmp_path) -> None:
    store = ResearchApiStateStore(db_path=str(tmp_path / "reasoning_chains.sqlite3"))
    repo = GraphRepository(store)
    service = ReasoningChainService(repo)
    workspace_id = "ws_reasoning"
    evidence = repo.create_node(
        workspace_id=workspace_id,
        node_type="evidence",
        object_ref_type="evidence",
        object_ref_id="ev_1",
        short_label="Evidence",
        full_description="Evidence supports the conclusion.",
    )
    conclusion = repo.create_node(
        workspace_id=workspace_id,
        node_type="conclusion",
        object_ref_type="conclusion",
        object_ref_id="co_1",
        short_label="Conclusion",
        full_description="Conclusion to test.",
    )
    edge = repo.create_edge(
        workspace_id=workspace_id,
        source_node_id=str(evidence["node_id"]),
        target_node_id=str(conclusion["node_id"]),
        edge_type="supports",
        object_ref_type="relation_candidate",
        object_ref_id="rel_1",
        strength=0.9,
    )

    chains = service.build_and_persist_deep_chains(
        workspace_id=workspace_id,
        conclusion_node_id=str(conclusion["node_id"]),
        support_chains=[
            {
                "chain_id": "support_1",
                "path_node_ids": [evidence["node_id"], conclusion["node_id"]],
                "path_edge_ids": [edge["edge_id"]],
                "weakest_step": {"edge_id": edge["edge_id"], "summary": "Check edge."},
            }
        ],
        max_chains=3,
    )
    invalidated = service.invalidate_intersecting_deep_chains(
        workspace_id=workspace_id,
        touched_node_ids={str(evidence["node_id"])},
        touched_edge_ids=set(),
    )

    assert len(chains) == 1
    assert chains[0]["path_node_ids"] == [evidence["node_id"], conclusion["node_id"]]
    assert invalidated["invalidated_chain_ids"] == [chains[0]["chain_id"]]
