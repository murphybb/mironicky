from __future__ import annotations


class VersionDiffService:
    def build_diff_payload(
        self,
        *,
        failure_id: str,
        base_version_id: str | None,
        new_version_id: str | None,
        before_snapshot: dict[str, object],
        after_snapshot: dict[str, object],
        route_impacts: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        before_nodes = self._as_mapping(before_snapshot.get("nodes"))
        after_nodes = self._as_mapping(after_snapshot.get("nodes"))
        before_edges = self._as_mapping(before_snapshot.get("edges"))
        after_edges = self._as_mapping(after_snapshot.get("edges"))
        before_routes = self._as_mapping(before_snapshot.get("routes"))
        after_routes = self._as_mapping(after_snapshot.get("routes"))

        added_node_ids = sorted(set(after_nodes) - set(before_nodes))
        added_edge_ids = sorted(set(after_edges) - set(before_edges))

        weakened_node_ids = sorted(
            self._status_changed_to(
                before_nodes,
                after_nodes,
                weakened_statuses={"weakened"},
            )
        )
        weakened_edge_ids = sorted(
            self._status_changed_to(
                before_edges,
                after_edges,
                weakened_statuses={"weakened"},
            )
        )
        weakened_route_ids = sorted(
            self._status_changed_to(
                before_routes,
                after_routes,
                weakened_statuses={"weakened"},
            )
        )

        invalidated_node_ids = sorted(
            self._status_changed_to(
                before_nodes,
                after_nodes,
                weakened_statuses={"failed"},
            )
        )
        invalidated_edge_ids = sorted(
            self._status_changed_to(
                before_edges,
                after_edges,
                weakened_statuses={"invalidated"},
            )
        )
        invalidated_route_ids = sorted(
            self._status_changed_to(
                before_routes,
                after_routes,
                weakened_statuses={"failed"},
            )
        )

        created_branch_node_ids = sorted(
            node_id
            for node_id in added_node_ids
            if str(after_nodes[node_id].get("node_type", "")) == "branch"
        )
        created_branch_edge_ids = sorted(
            edge_id
            for edge_id in added_edge_ids
            if str(after_edges[edge_id].get("edge_type", "")) == "branches_to"
        )

        route_score_changes: list[dict[str, object]] = []
        for route_id in sorted(set(before_routes) & set(after_routes)):
            before_route = before_routes[route_id]
            after_route = after_routes[route_id]
            before_support = float(before_route.get("support_score", 0.0))
            after_support = float(after_route.get("support_score", 0.0))
            before_risk = float(before_route.get("risk_score", 0.0))
            after_risk = float(after_route.get("risk_score", 0.0))
            before_progress = float(before_route.get("progressability_score", 0.0))
            after_progress = float(after_route.get("progressability_score", 0.0))
            if (
                before_support == after_support
                and before_risk == after_risk
                and before_progress == after_progress
            ):
                continue
            route_score_changes.append(
                {
                    "route_id": route_id,
                    "support_score_before": before_support,
                    "support_score_after": after_support,
                    "risk_score_before": before_risk,
                    "risk_score_after": after_risk,
                    "progressability_score_before": before_progress,
                    "progressability_score_after": after_progress,
                }
            )

        return {
            "failure_id": failure_id,
            "base_version_id": base_version_id,
            "new_version_id": new_version_id,
            "added": {
                "nodes": added_node_ids,
                "edges": added_edge_ids,
            },
            "weakened": {
                "nodes": weakened_node_ids,
                "edges": weakened_edge_ids,
                "routes": weakened_route_ids,
            },
            "invalidated": {
                "nodes": invalidated_node_ids,
                "edges": invalidated_edge_ids,
                "routes": invalidated_route_ids,
            },
            "branch_changes": {
                "created_branch_node_ids": created_branch_node_ids,
                "created_branch_edge_ids": created_branch_edge_ids,
            },
            "route_score_changes": route_score_changes,
            "route_impacts": route_impacts or [],
        }

    def _as_mapping(self, raw: object) -> dict[str, dict[str, object]]:
        if not isinstance(raw, dict):
            return {}
        normalized: dict[str, dict[str, object]] = {}
        for key, value in raw.items():
            if not isinstance(value, dict):
                continue
            normalized[str(key)] = value
        return normalized

    def _status_changed_to(
        self,
        before: dict[str, dict[str, object]],
        after: dict[str, dict[str, object]],
        *,
        weakened_statuses: set[str],
    ) -> set[str]:
        changed: set[str] = set()
        for object_id, after_value in after.items():
            if object_id not in before:
                continue
            after_status = str(after_value.get("status", ""))
            if after_status not in weakened_statuses:
                continue
            before_status = str(before[object_id].get("status", ""))
            if before_status != after_status:
                changed.add(object_id)
        return changed
