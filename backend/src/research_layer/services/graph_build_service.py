from __future__ import annotations

from collections import defaultdict
import re

from research_layer.graph.repository import GraphRepository

OBJECT_TO_NODE_TYPE = {
    "evidence": "evidence",
    "assumption": "assumption",
    "conclusion": "conclusion",
    "gap": "gap",
    "conflict": "conflict",
    "failure": "failure",
    "validation": "validation",
}


class GraphBuildService:
    def __init__(self, repository: GraphRepository) -> None:
        self._repository = repository

    def build_workspace_graph(
        self, *, workspace_id: str, request_id: str
    ) -> dict[str, object]:
        self._repository.emit_event(
            event_name="graph_build_started",
            request_id=request_id,
            workspace_id=workspace_id,
            step="build",
            status="started",
        )
        confirmed_objects = self._repository.list_confirmed_objects(workspace_id)
        self._repository.reset_workspace_graph(workspace_id)
        archived_object_refs = {
            (str(node["object_ref_type"]), str(node["object_ref_id"]))
            for node in self._repository.list_nodes(workspace_id=workspace_id)
            if str(node.get("status")) == "archived"
        }
        source_nodes: dict[str, list[dict[str, object]]] = defaultdict(list)
        candidate_nodes: dict[str, dict[str, object]] = {}
        created_nodes: list[dict[str, object]] = []
        created_edges: list[dict[str, object]] = []
        skipped_archived_count = 0

        for obj in confirmed_objects:
            object_type = str(obj["object_type"])
            object_ref_id = str(obj["object_id"])
            if (object_type, object_ref_id) in archived_object_refs:
                skipped_archived_count += 1
                continue
            short_label = self._build_short_label(str(obj["text"]))
            node = self._repository.create_node(
                workspace_id=workspace_id,
                node_type=OBJECT_TO_NODE_TYPE.get(object_type, "evidence"),
                object_ref_type=object_type,
                object_ref_id=object_ref_id,
                short_label=short_label,
                full_description=str(obj["text"]),
                source_refs=[
                    {
                        "source_id": str(obj["source_id"]),
                        "object_id": str(obj["object_id"]),
                        "object_type": object_type,
                        "source_span": {},
                    }
                ],
            )
            created_nodes.append(node)
            source_nodes[str(obj["source_id"])].append(node)
            candidate_id = str(obj.get("candidate_id") or "")
            if candidate_id:
                candidate_nodes[candidate_id] = node

        relation_candidates = self._repository.list_relation_candidates(
            workspace_id=workspace_id
        )
        sources_with_relation_candidates = {
            str(item["source_id"]) for item in relation_candidates
        }
        for relation in relation_candidates:
            if str(relation.get("relation_status")) != "resolved":
                continue
            relation_type = str(relation.get("relation_type") or "").strip()
            if not relation_type:
                continue
            source_node = candidate_nodes.get(str(relation.get("source_candidate_id") or ""))
            target_node = candidate_nodes.get(str(relation.get("target_candidate_id") or ""))
            if source_node is None or target_node is None:
                continue
            edge = self._repository.create_edge(
                workspace_id=workspace_id,
                source_node_id=str(source_node["node_id"]),
                target_node_id=str(target_node["node_id"]),
                edge_type=relation_type,
                object_ref_type="relation_candidate",
                object_ref_id=str(relation["relation_candidate_id"]),
                strength=0.9,
            )
            created_edges.append(edge)

        for source_id, nodes in source_nodes.items():
            if source_id in sources_with_relation_candidates:
                continue
            evidence_nodes = [node for node in nodes if node["node_type"] == "evidence"]
            anchor = evidence_nodes[0] if evidence_nodes else nodes[0]
            for node in nodes:
                if node["node_id"] == anchor["node_id"]:
                    continue
                edge_type = "derives"
                if node["node_type"] == "assumption":
                    edge_type = "requires"
                elif node["node_type"] == "conflict":
                    edge_type = "conflicts"
                elif node["node_type"] == "failure":
                    edge_type = "weakens"
                elif node["node_type"] == "validation":
                    edge_type = "validates"
                edge = self._repository.create_edge(
                    workspace_id=workspace_id,
                    source_node_id=anchor["node_id"],
                    target_node_id=node["node_id"],
                    edge_type=edge_type,
                    object_ref_type=node["object_ref_type"],
                    object_ref_id=node["object_ref_id"],
                    strength=0.8,
                )
                created_edges.append(edge)

        version = self._repository.create_version(
            workspace_id=workspace_id,
            trigger_type="confirm_candidate",
            change_summary=f"build graph from {len(confirmed_objects)} confirmed objects",
            diff_payload={
                "node_count": len(created_nodes),
                "edge_count": len(created_edges),
                "source_ids": sorted(source_nodes.keys()),
                "skipped_archived_count": skipped_archived_count,
            },
            request_id=request_id,
        )
        self._repository.upsert_workspace(
            workspace_id=workspace_id,
            latest_version_id=version["version_id"],
            status="ready",
            node_count=len(created_nodes),
            edge_count=len(created_edges),
        )
        self._repository.emit_event(
            event_name="graph_build_completed",
            request_id=request_id,
            workspace_id=workspace_id,
            step="build",
            status="completed",
            refs={"version_id": version["version_id"]},
            metrics={
                "node_count": len(created_nodes),
                "edge_count": len(created_edges),
            },
        )
        return {
            "workspace_id": workspace_id,
            "version_id": version["version_id"],
            "node_count": len(created_nodes),
            "edge_count": len(created_edges),
        }

    def _build_short_label(self, raw_text: str) -> str:
        collapsed = re.sub(r"\s+", " ", str(raw_text or "").strip())
        if not collapsed:
            return "未命名节点"
        sentence_parts = re.split(r"[。！？!?;；]\s*", collapsed)
        first_sentence = next((part.strip() for part in sentence_parts if part.strip()), "")
        preferred = first_sentence or collapsed
        normalized_first_sentence = re.split(r"[。！？!?;；]\s*", collapsed)
        if normalized_first_sentence:
            preferred = normalized_first_sentence[0].strip() or preferred
        max_len = 36
        if len(preferred) <= max_len:
            return preferred
        return f"{preferred[:max_len].rstrip()}..."
