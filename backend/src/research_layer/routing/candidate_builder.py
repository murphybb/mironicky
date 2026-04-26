from __future__ import annotations

from collections import defaultdict

_PRIMARY_ROUTE_NODE_TYPES = {"conclusion", "validation", "branch"}
_SUPPORT_NODE_TYPES = {"evidence", "validation"}
_RISK_NODE_TYPES = {"conflict", "failure"}
_OPEN_QUESTION_NODE_TYPES = {"gap"}
_INACTIVE_STATUSES = {"archived", "superseded"}
_NON_CLAIM_ASSUMPTION_TAGS = {"condition"}
_RESULT_EVIDENCE_TAGS = {
    "claim",
    "conclusion",
    "finding",
    "main_contribution",
    "outcome",
    "result",
}
_SOURCE_CONTEXT_SUPPORT_TAGS = {
    "dataset",
    "evidence",
    "experiment",
    "intervention",
    "method",
    "metric",
    "population",
    "result",
    "sample",
    "validation",
}


class RouteCandidateBuilder:
    def build_candidates(
        self,
        *,
        workspace_id: str,
        graph_nodes: list[dict[str, object]],
        graph_edges: list[dict[str, object]],
        version_id: str | None,
        max_candidates: int = 8,
    ) -> list[dict[str, object]]:
        if max_candidates <= 0:
            return []

        graph_nodes = [
            node
            for node in graph_nodes
            if str(node.get("status", "")) not in _INACTIVE_STATUSES
        ]
        active_node_ids = {str(node.get("node_id", "")) for node in graph_nodes}
        graph_edges = [
            edge
            for edge in graph_edges
            if str(edge.get("status", "")) not in _INACTIVE_STATUSES
            and str(edge.get("source_node_id", "")) in active_node_ids
            and str(edge.get("target_node_id", "")) in active_node_ids
        ]

        node_map = {str(node["node_id"]): node for node in graph_nodes}
        adjacency = self._build_adjacency(graph_edges)
        edge_ids_by_node_pair: dict[tuple[str, str], list[str]] = defaultdict(list)
        for edge in graph_edges:
            source = str(edge["source_node_id"])
            target = str(edge["target_node_id"])
            edge_id = str(edge["edge_id"])
            edge_ids_by_node_pair[(source, target)].append(edge_id)
            edge_ids_by_node_pair[(target, source)].append(edge_id)

        conclusion_nodes = [
            node for node in graph_nodes if self._is_primary_route_seed(node)
        ]
        if not conclusion_nodes:
            conclusion_nodes = [
                node
                for node in graph_nodes
                if str(node.get("node_type", "")) in _RISK_NODE_TYPES
                and str(node.get("status", "")) not in _INACTIVE_STATUSES
            ]

        seen_signatures: set[tuple[str, ...]] = set()
        candidates: list[dict[str, object]] = []
        for conclusion_node in sorted(
            conclusion_nodes,
            key=lambda item: (
                self._route_priority(item),
                str(item.get("node_id", "")),
            ),
        ):
            conclusion_node_id = str(conclusion_node["node_id"])
            route_node_ids = self._collect_route_node_ids(
                conclusion_node_id=conclusion_node_id, adjacency=adjacency
            )
            route_node_ids = self._add_source_context_node_ids(
                conclusion_node=conclusion_node,
                graph_nodes=graph_nodes,
                route_node_ids=route_node_ids,
            )
            signature = tuple(route_node_ids)
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)

            route_nodes = [
                node_map[node_id] for node_id in route_node_ids if node_id in node_map
            ]
            key_support_node_ids = [
                str(node["node_id"])
                for node in route_nodes
                if self._is_support_node(node)
                and str(node.get("status", "")) != "failed"
                and str(node["node_id"]) != conclusion_node_id
            ][:3]
            key_assumption_node_ids = [
                str(node["node_id"])
                for node in route_nodes
                if str(node.get("node_type")) == "assumption"
            ][:3]
            risk_node_ids = [
                str(node["node_id"])
                for node in route_nodes
                if str(node.get("node_type"))
                in _RISK_NODE_TYPES | _OPEN_QUESTION_NODE_TYPES
                or str(node.get("status", "")) == "failed"
            ][:3]
            if not self._is_route_supported(
                conclusion_node=conclusion_node,
                key_support_node_ids=key_support_node_ids,
            ):
                continue
            next_validation_node_ids = [
                str(node["node_id"])
                for node in route_nodes
                if str(node.get("node_type")) == "validation"
                and str(node.get("status", "")) not in _INACTIVE_STATUSES
            ]
            next_validation_node_id = (
                next_validation_node_ids[0] if next_validation_node_ids else None
            )
            next_validation_action = self._build_next_validation_action(
                conclusion_node=conclusion_node,
                next_validation_node=(
                    node_map.get(next_validation_node_id)
                    if next_validation_node_id
                    else None
                ),
            )

            route_edge_ids: set[str] = set()
            for source_node_id in route_node_ids:
                for target_node_id in route_node_ids:
                    for edge_id in edge_ids_by_node_pair.get(
                        (source_node_id, target_node_id), []
                    ):
                        route_edge_ids.add(edge_id)

            candidates.append(
                {
                    "workspace_id": workspace_id,
                    "conclusion_node_id": conclusion_node_id,
                    "route_node_ids": route_node_ids,
                    "key_support_node_ids": key_support_node_ids,
                    "key_assumption_node_ids": key_assumption_node_ids,
                    "risk_node_ids": risk_node_ids,
                    "next_validation_node_id": next_validation_node_id,
                    "next_validation_action": next_validation_action,
                    "trace_refs": {
                        "version_id": version_id,
                        "conclusion_node_id": conclusion_node_id,
                        "route_node_ids": route_node_ids,
                        "route_edge_ids": sorted(route_edge_ids),
                    },
                }
            )
            if len(candidates) >= max_candidates:
                break

        return candidates

    def _route_priority(self, node: dict[str, object]) -> int:
        node_type = str(node.get("node_type", ""))
        tags = self._tags(node)
        if node_type == "conclusion":
            return 0
        if node_type == "assumption" and "hypothesis" in tags:
            return 1
        if node_type == "evidence" and tags & _RESULT_EVIDENCE_TAGS:
            return 2
        if node_type == "validation":
            return 3
        if node_type == "assumption":
            return 4
        return 5

    def _is_primary_route_seed(self, node: dict[str, object]) -> bool:
        if str(node.get("status", "")) in _INACTIVE_STATUSES:
            return False
        node_type = str(node.get("node_type", ""))
        tags = self._tags(node)
        if node_type in _PRIMARY_ROUTE_NODE_TYPES:
            return True
        if node_type == "assumption":
            return not tags or not tags <= _NON_CLAIM_ASSUMPTION_TAGS
        if node_type == "evidence":
            return bool(tags & _RESULT_EVIDENCE_TAGS)
        return False

    def _is_support_node(self, node: dict[str, object]) -> bool:
        node_type = str(node.get("node_type", ""))
        return node_type in _SUPPORT_NODE_TYPES

    def _is_route_supported(
        self,
        *,
        conclusion_node: dict[str, object],
        key_support_node_ids: list[str],
    ) -> bool:
        node_type = str(conclusion_node.get("node_type", ""))
        if node_type in _RISK_NODE_TYPES:
            return True
        if node_type in _OPEN_QUESTION_NODE_TYPES:
            return False
        return bool(key_support_node_ids)

    def _collect_route_node_ids(
        self, *, conclusion_node_id: str, adjacency: dict[str, set[str]]
    ) -> list[str]:
        neighbor_ids = sorted(adjacency.get(conclusion_node_id, set()))
        route_node_ids = sorted({conclusion_node_id, *neighbor_ids})
        return route_node_ids

    def _add_source_context_node_ids(
        self,
        *,
        conclusion_node: dict[str, object],
        graph_nodes: list[dict[str, object]],
        route_node_ids: list[str],
    ) -> list[str]:
        conclusion_anchors = self._source_anchor_ids(conclusion_node)
        if not conclusion_anchors:
            return route_node_ids

        source_context_ids = [
            str(node["node_id"])
            for node in graph_nodes
            if str(node.get("node_id", "")) != str(conclusion_node.get("node_id", ""))
            and self._source_anchor_ids(node) & conclusion_anchors
            and self._is_source_context_support(node)
        ][:6]
        return sorted({*route_node_ids, *source_context_ids})

    def _is_source_context_support(self, node: dict[str, object]) -> bool:
        return bool(self._tags(node) & _SOURCE_CONTEXT_SUPPORT_TAGS) and self._is_support_node(
            node
        )

    def _source_anchor_ids(self, node: dict[str, object]) -> set[str]:
        anchors: set[str] = set()
        source_ref = node.get("source_ref")
        if isinstance(source_ref, dict):
            anchor_id = str(source_ref.get("anchor_id", "")).strip()
            if anchor_id:
                anchors.add(anchor_id)
        source_refs = node.get("source_refs")
        if isinstance(source_refs, list):
            for item in source_refs:
                if not isinstance(item, dict):
                    continue
                anchor_id = str(item.get("anchor_id", "")).strip()
                if anchor_id:
                    anchors.add(anchor_id)
        return anchors

    def _tags(self, node: dict[str, object]) -> set[str]:
        return {str(tag) for tag in node.get("short_tags", []) if str(tag).strip()}

    def _build_adjacency(
        self, graph_edges: list[dict[str, object]]
    ) -> dict[str, set[str]]:
        adjacency: dict[str, set[str]] = defaultdict(set)
        for edge in graph_edges:
            source = str(edge["source_node_id"])
            target = str(edge["target_node_id"])
            adjacency[source].add(target)
            adjacency[target].add(source)
        return adjacency

    def _build_next_validation_action(
        self,
        *,
        conclusion_node: dict[str, object],
        next_validation_node: dict[str, object] | None,
    ) -> str:
        if next_validation_node is not None:
            label = str(next_validation_node.get("short_label", "")).strip()
            if label:
                return f"Execute validation: {label}"
        conclusion_label = str(conclusion_node.get("short_label", "")).strip() or str(
            conclusion_node.get("node_id", "")
        )
        return f"Validate conclusion node {conclusion_label} with an ablation or controlled experiment"
