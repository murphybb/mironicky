from __future__ import annotations

from research_layer.graph.repository import GraphRepository
from research_layer.services.graph_query_service import GraphQueryService
from research_layer.services.reasoning_chain_service import ReasoningChainService


class CausalChainRebuildService:
    def __init__(self, repository: GraphRepository) -> None:
        self._repository = repository
        self._query_service = GraphQueryService(repository)
        self._reasoning_chains = ReasoningChainService(repository)

    def rebuild(self, *, workspace_id: str, max_chains_per_conclusion: int = 4) -> dict[str, object]:
        active_chains = self._repository.list_reasoning_chains(
            workspace_id=workspace_id,
            status="active",
        )
        superseded_chain_count = 0
        for chain in active_chains:
            if str(chain.get("chain_type", "")) != "deep_reasoning_chain":
                continue
            updated = self._repository.update_reasoning_chain(
                reasoning_chain_id=str(chain["reasoning_chain_id"]),
                status="superseded",
            )
            if updated is not None:
                superseded_chain_count += 1

        nodes = self._repository.list_nodes(workspace_id=workspace_id)
        conclusion_node_ids = [
            str(node["node_id"])
            for node in nodes
            if str(node.get("status", "")) == "active"
            and str(node.get("graph_layer", "")) == "research"
            and str(node.get("node_type", "")) == "validation"
        ]
        if not conclusion_node_ids:
            conclusion_node_ids = [
                str(node["node_id"])
                for node in nodes
                if str(node.get("status", "")) == "active"
                and str(node.get("graph_layer", "")) == "research"
                and str(node.get("node_type", "")) == "assumption"
            ]

        created_chains: list[dict[str, object]] = []
        for conclusion_node_id in conclusion_node_ids:
            support_result = self._query_service.query_typed_metapath_paths(
                workspace_id=workspace_id,
                start_node_ids=[conclusion_node_id],
                edge_type_sequence=["supports"],
                max_paths=max_chains_per_conclusion,
            )
            support_chains = list(support_result.get("path_evidence", []))
            if not support_chains:
                continue
            created_chains.extend(
                self._reasoning_chains.build_and_persist_deep_chains(
                    workspace_id=workspace_id,
                    conclusion_node_id=conclusion_node_id,
                    support_chains=support_chains,
                    max_chains=max_chains_per_conclusion,
                )
            )
        return {
            "chain_count": len(created_chains),
            "superseded_chain_count": superseded_chain_count,
            "conclusion_node_ids": conclusion_node_ids,
        }
