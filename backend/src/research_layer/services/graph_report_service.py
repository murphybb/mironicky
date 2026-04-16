from __future__ import annotations

from collections import Counter

from research_layer.api.controllers._state_store import ResearchApiStateStore


class GraphReportService:
    def __init__(self, store: ResearchApiStateStore) -> None:
        self._store = store

    def build_report(self, *, workspace_id: str) -> dict[str, object]:
        nodes = self._store.list_graph_nodes(workspace_id)
        edges = self._store.list_graph_edges(workspace_id)
        failures = self._store.list_failures(workspace_id=workspace_id)
        validations = self._store.list_validations(workspace_id=workspace_id)
        versions = self._store.list_graph_versions(workspace_id)
        workspace = self._store.get_graph_workspace(workspace_id)

        degree = Counter()
        for edge in edges:
            if edge.get("status") == "archived":
                continue
            degree[str(edge["source_node_id"])] += 1
            degree[str(edge["target_node_id"])] += 1

        failure_targets = self._failure_target_node_ids(failures)
        validation_targets = {
            str(item.get("target_object", ""))
            for item in validations
            if item.get("target_object")
        }
        risk_statuses = {"failed", "conflicted", "weakened"}
        active_nodes = [node for node in nodes if node.get("status") != "archived"]

        top_nodes = sorted(
            (self._node_ref(node, degree[str(node["node_id"])]) for node in active_nodes),
            key=lambda item: (-int(item["degree"]), item["node_id"]),
        )[:10]
        risk_nodes = [
            self._node_ref(node, degree[str(node["node_id"])])
            for node in active_nodes
            if str(node.get("node_id")) in failure_targets
            or str(node.get("status")) in risk_statuses
            or str(node.get("node_type")) in {"failure", "conflict"}
        ][:10]
        dangling_nodes = [
            self._node_ref(node, 0)
            for node in active_nodes
            if degree[str(node["node_id"])] == 0
        ][:20]
        unvalidated_assumptions = [
            self._node_ref(node, degree[str(node["node_id"])])
            for node in active_nodes
            if str(node.get("object_ref_type")) == "assumption"
            and str(node.get("object_ref_id")) not in validation_targets
        ][:20]

        latest_version_id = None
        if workspace and workspace.get("latest_version_id"):
            latest_version_id = str(workspace["latest_version_id"])
        elif versions:
            latest_version_id = str(versions[-1]["version_id"])

        return {
            "workspace_id": workspace_id,
            "summary": {
                "node_count": len(nodes),
                "edge_count": len(edges),
                "active_node_count": len(active_nodes),
                "failure_count": len(failures),
                "validation_count": len(validations),
                "version_count": len(versions),
            },
            "top_nodes": top_nodes,
            "risk_nodes": risk_nodes,
            "dangling_nodes": dangling_nodes,
            "unvalidated_assumptions": unvalidated_assumptions,
            "trace_refs": {
                "latest_version_id": latest_version_id,
                "version_ids": [str(item["version_id"]) for item in versions[-10:]],
            },
        }

    def _failure_target_node_ids(self, failures: list[dict[str, object]]) -> set[str]:
        node_ids: set[str] = set()
        for failure in failures:
            for target in failure.get("attached_targets", []):
                if not isinstance(target, dict):
                    continue
                if target.get("target_type") == "node" and target.get("target_id"):
                    node_ids.add(str(target["target_id"]))
        return node_ids

    def _node_ref(self, node: dict[str, object], degree: int) -> dict[str, object]:
        return {
            "node_id": str(node["node_id"]),
            "node_type": str(node.get("node_type", "")),
            "object_ref_type": str(node.get("object_ref_type", "")),
            "object_ref_id": str(node.get("object_ref_id", "")),
            "short_label": str(node.get("short_label", "")),
            "status": str(node.get("status", "")),
            "degree": int(degree),
        }
