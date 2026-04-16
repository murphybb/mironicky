from __future__ import annotations

from research_layer.api.controllers._state_store import ResearchApiStateStore


class ResearchExportService:
    def __init__(self, store: ResearchApiStateStore) -> None:
        self._store = store

    def export_graph(self, *, workspace_id: str, export_format: str) -> dict[str, object]:
        export_format = self._normalize_format(export_format)
        safe_nodes = [
            self._safe_node(node)
            for node in self._store.list_graph_nodes(workspace_id)
            if node.get("visibility") != "private"
        ]
        safe_node_ids = {str(item["node_id"]) for item in safe_nodes}
        payload = {
            "workspace_id": workspace_id,
            "nodes": safe_nodes,
            "edges": [
                self._safe_edge(edge)
                for edge in self._store.list_graph_edges(workspace_id)
                if str(edge.get("source_node_id")) in safe_node_ids
                and str(edge.get("target_node_id")) in safe_node_ids
            ],
            "versions": [
                {
                    "version_id": str(item["version_id"]),
                    "trigger_type": str(item.get("trigger_type", "")),
                    "change_summary": str(item.get("change_summary", "")),
                    "created_at": item.get("created_at"),
                }
                for item in self._store.list_graph_versions(workspace_id)
            ],
        }
        return self._format_payload(
            export_type="graph",
            export_format=export_format,
            payload=payload,
        )

    def export_package(self, *, package_id: str, export_format: str) -> dict[str, object]:
        export_format = self._normalize_format(export_format)
        package = self._store.get_package(package_id)
        if package is None:
            raise KeyError("package not found")
        payload = {
            "package_id": str(package["package_id"]),
            "workspace_id": str(package["workspace_id"]),
            "title": str(package["title"]),
            "summary": str(package["summary"]),
            "status": str(package["status"]),
            "snapshot_type": str(package["snapshot_type"]),
            "snapshot_version": str(package["snapshot_version"]),
            "included_route_ids": list(package.get("included_route_ids", [])),
            "included_node_ids": list(package.get("included_node_ids", [])),
            "included_validation_ids": list(
                package.get("included_validation_ids", [])
            ),
            "boundary_notes": list(package.get("boundary_notes", [])),
            "traceability_refs": self._safe_traceability_refs(package),
        }
        return self._format_payload(
            export_type="package",
            export_format=export_format,
            payload=payload,
        )

    def _normalize_format(self, export_format: str) -> str:
        normalized = export_format.strip().lower()
        if normalized not in {"json", "markdown"}:
            raise ValueError("unsupported export format")
        return normalized

    def _format_payload(
        self, *, export_type: str, export_format: str, payload: dict[str, object]
    ) -> dict[str, object]:
        if export_format == "json":
            rendered: object = payload
        else:
            rendered = self._to_markdown(export_type=export_type, payload=payload)
        return {
            "export_type": export_type,
            "format": export_format,
            "payload": rendered,
        }

    def _safe_node(self, node: dict[str, object]) -> dict[str, object]:
        return {
            "node_id": str(node["node_id"]),
            "workspace_id": str(node["workspace_id"]),
            "node_type": str(node.get("node_type", "")),
            "object_ref_type": str(node.get("object_ref_type", "")),
            "object_ref_id": str(node.get("object_ref_id", "")),
            "short_label": str(node.get("short_label", "")),
            "full_description": str(node.get("full_description", "")),
            "short_tags": list(node.get("short_tags", [])),
            "visibility": str(node.get("visibility", "workspace")),
            "status": str(node.get("status", "")),
        }

    def _safe_edge(self, edge: dict[str, object]) -> dict[str, object]:
        return {
            "edge_id": str(edge["edge_id"]),
            "workspace_id": str(edge["workspace_id"]),
            "source_node_id": str(edge["source_node_id"]),
            "target_node_id": str(edge["target_node_id"]),
            "edge_type": str(edge.get("edge_type", "")),
            "strength": float(edge.get("strength", 0.0)),
            "status": str(edge.get("status", "")),
        }

    def _to_markdown(self, *, export_type: str, payload: dict[str, object]) -> str:
        title = f"# Research {export_type.title()} Export"
        lines = [title, "", f"Workspace: {payload.get('workspace_id', '')}", ""]
        if export_type == "graph":
            nodes = payload.get("nodes", [])
            edges = payload.get("edges", [])
            lines.extend([f"Nodes: {len(nodes)}", f"Edges: {len(edges)}", ""])
            for node in nodes if isinstance(nodes, list) else []:
                if isinstance(node, dict):
                    lines.append(
                        f"- {node.get('node_id')}: {node.get('short_label')} [{node.get('status')}]"
                    )
        else:
            lines.extend(
                [
                    f"Package: {payload.get('package_id', '')}",
                    f"Title: {payload.get('title', '')}",
                    "",
                    str(payload.get("summary", "")),
                ]
            )
        return "\n".join(lines)

    def _safe_traceability_refs(self, package: dict[str, object]) -> dict[str, object]:
        traceability = package.get("traceability_refs")
        if not isinstance(traceability, dict):
            return {}
        private_node_ids = {
            str(item)
            for item in traceability.get("private_dependency_node_ids", [])
            if isinstance(item, (str, int))
        }
        allowed_keys = {
            "routes",
            "node_ids",
            "validation_ids",
            "missing_route_validation_ids",
            "public_gap_node_ids",
            "pre_publish_review_refs",
        }
        sanitized: dict[str, object] = {}
        for key in allowed_keys:
            if key not in traceability:
                continue
            sanitized[key] = self._sanitize_public_payload(traceability[key])
        if "node_ids" in sanitized and isinstance(sanitized["node_ids"], list):
            sanitized["node_ids"] = [
                str(node_id)
                for node_id in sanitized["node_ids"]
                if str(node_id) not in private_node_ids
            ]
        return sanitized

    def _sanitize_public_payload(self, value: object) -> object:
        blocked_tokens = ("private", "raw", "prompt", "unconfirmed", "replacement")
        if isinstance(value, dict):
            output: dict[str, object] = {}
            for raw_key, raw_value in value.items():
                key = str(raw_key)
                if any(token in key.lower() for token in blocked_tokens):
                    continue
                output[key] = self._sanitize_public_payload(raw_value)
            return output
        if isinstance(value, list):
            return [self._sanitize_public_payload(item) for item in value]
        return value
