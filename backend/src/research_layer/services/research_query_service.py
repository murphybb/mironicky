from __future__ import annotations

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.services.graph_report_service import GraphReportService


QUERY_TOOLS: tuple[dict[str, object], ...] = (
    {"name": "graph", "description": "Read workspace graph nodes and edges."},
    {"name": "query", "description": "Read a graph node neighborhood."},
    {"name": "route", "description": "Read routes by workspace or route_id."},
    {"name": "hypothesis", "description": "Read hypotheses by workspace or hypothesis_id."},
    {"name": "package", "description": "Read packages by workspace or package_id."},
    {"name": "version-diff", "description": "Read a graph version diff."},
    {"name": "report", "description": "Read a graph report summary."},
)


class ResearchQueryService:
    def __init__(self, store: ResearchApiStateStore) -> None:
        self._store = store
        self._report_service = GraphReportService(store)

    def list_tools(self) -> list[dict[str, object]]:
        return [dict(item) for item in QUERY_TOOLS]

    def run_tool(
        self, *, workspace_id: str, tool_name: str, arguments: dict[str, object]
    ) -> dict[str, object]:
        normalized_tool = tool_name.strip()
        if normalized_tool not in {str(item["name"]) for item in QUERY_TOOLS}:
            raise ValueError("unsupported research query tool")

        result = self._run_whitelisted_tool(
            workspace_id=workspace_id,
            tool_name=normalized_tool,
            arguments=dict(arguments),
        )
        return {
            "workspace_id": workspace_id,
            "tool_name": normalized_tool,
            "result": result,
        }

    def _run_whitelisted_tool(
        self, *, workspace_id: str, tool_name: str, arguments: dict[str, object]
    ) -> dict[str, object]:
        if tool_name == "graph":
            return {
                "nodes": self._store.list_graph_nodes(workspace_id),
                "edges": self._store.list_graph_edges(workspace_id),
            }
        if tool_name == "query":
            node_id = str(arguments.get("node_id", "")).strip()
            nodes = self._store.list_graph_nodes(workspace_id)
            edges = self._store.list_graph_edges(workspace_id)
            if not node_id:
                return {"nodes": nodes, "edges": edges}
            related_edges = [
                edge
                for edge in edges
                if node_id
                in {str(edge.get("source_node_id")), str(edge.get("target_node_id"))}
            ]
            related_node_ids = {node_id}
            for edge in related_edges:
                related_node_ids.add(str(edge.get("source_node_id")))
                related_node_ids.add(str(edge.get("target_node_id")))
            return {
                "nodes": [
                    node
                    for node in nodes
                    if str(node.get("node_id")) in related_node_ids
                ],
                "edges": related_edges,
            }
        if tool_name == "route":
            route_id = str(arguments.get("route_id", "")).strip()
            if route_id:
                route = self._store.get_route(route_id)
                return {"item": route if self._owns(route, workspace_id) else None}
            return {"items": self._store.list_routes(workspace_id)}
        if tool_name == "hypothesis":
            hypothesis_id = str(arguments.get("hypothesis_id", "")).strip()
            if hypothesis_id:
                hypothesis = self._store.get_hypothesis(hypothesis_id)
                return {
                    "item": hypothesis if self._owns(hypothesis, workspace_id) else None
                }
            return {"items": self._store.list_hypotheses(workspace_id=workspace_id)}
        if tool_name == "package":
            package_id = str(arguments.get("package_id", "")).strip()
            if package_id:
                package = self._store.get_package(package_id)
                return {"item": package if self._owns(package, workspace_id) else None}
            return {"items": self._store.list_packages(workspace_id=workspace_id)}
        if tool_name == "version-diff":
            version_id = str(arguments.get("version_id", "")).strip()
            if not version_id:
                return {"item": None}
            version = self._store.get_graph_version(version_id)
            if not self._owns(version, workspace_id):
                return {"item": None}
            return {
                "item": {
                    "version_id": version_id,
                    "workspace_id": workspace_id,
                    "diff_payload": version.get("diff_payload", {}),
                }
            }
        if tool_name == "report":
            return self._report_service.build_report(workspace_id=workspace_id)
        raise ValueError("unsupported research query tool")

    def _owns(self, record: dict[str, object] | None, workspace_id: str) -> bool:
        return record is not None and str(record.get("workspace_id")) == workspace_id
