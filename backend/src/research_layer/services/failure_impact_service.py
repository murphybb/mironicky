from __future__ import annotations

from dataclasses import dataclass

from research_layer.api.controllers._state_store import ResearchApiStateStore

_FAILURE_SEVERITY_TO_NODE_STATUS = {
    "low": "weakened",
    "medium": "weakened",
    "high": "failed",
    "critical": "failed",
}
_FAILURE_SEVERITY_TO_EDGE_STATUS = {
    "low": "weakened",
    "medium": "weakened",
    "high": "invalidated",
    "critical": "invalidated",
}
_TERMINAL_NODE_STATUSES = {"archived", "superseded"}
_TERMINAL_EDGE_STATUSES = {"archived", "superseded"}
_ROUTE_TERMINAL_STATUSES = {"failed", "superseded"}


@dataclass(slots=True)
class FailureImpactError(Exception):
    status_code: int
    error_code: str
    message: str
    details: dict[str, object]

    def __str__(self) -> str:
        return self.message


class FailureImpactService:
    def __init__(self, store: ResearchApiStateStore) -> None:
        self._store = store

    def _raise(
        self,
        *,
        status_code: int,
        error_code: str,
        message: str,
        details: dict[str, object] | None = None,
    ) -> None:
        raise FailureImpactError(
            status_code=status_code,
            error_code=error_code,
            message=message,
            details=details or {},
        )

    def validate_targets_for_create(
        self,
        *,
        workspace_id: str,
        attached_targets: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        if not attached_targets:
            self._raise(
                status_code=400,
                error_code="research.invalid_request",
                message="attached_targets must not be empty",
            )
        normalized = self._normalize_targets(attached_targets)
        for target in normalized:
            self._ensure_target_exists_and_owned(
                workspace_id=workspace_id,
                target_type=target["target_type"],
                target_id=target["target_id"],
            )
        return normalized

    def apply_failure(
        self,
        *,
        workspace_id: str,
        failure_id: str,
        request_id: str,
    ) -> dict[str, object]:
        failure = self._store.get_failure(failure_id)
        if failure is None:
            self._raise(
                status_code=404,
                error_code="research.not_found",
                message="failure not found",
                details={"failure_id": failure_id},
            )
        if str(failure["workspace_id"]) != workspace_id:
            self._raise(
                status_code=409,
                error_code="research.conflict",
                message="workspace_id does not match failure ownership",
                details={"failure_id": failure_id},
            )
        existing_event = self._store.find_latest_event(
            workspace_id=workspace_id,
            event_name="failure_attached",
            ref_key="failure_id",
            ref_value=failure_id,
        )
        if existing_event is not None:
            existing_summary = existing_event.get("refs", {}).get("impact_summary")
            if isinstance(existing_summary, dict):
                return existing_summary

        targets = self._normalize_targets(
            [
                {
                    "target_type": str(item.get("target_type", "")),
                    "target_id": str(item.get("target_id", "")),
                }
                for item in failure.get("attached_targets", [])
                if isinstance(item, dict)
            ]
        )
        severity = str(failure.get("severity", "medium")).lower()

        weakened_node_ids: list[str] = []
        invalidated_node_ids: list[str] = []
        weakened_edge_ids: list[str] = []
        invalidated_edge_ids: list[str] = []
        affected_edge_ids: set[str] = set()
        anchor_node_ids: set[str] = set()

        for target in targets:
            target_type = target["target_type"]
            target_id = target["target_id"]
            if target_type == "node":
                node = self._ensure_target_exists_and_owned(
                    workspace_id=workspace_id,
                    target_type="node",
                    target_id=target_id,
                )
                node_status = str(node["status"])
                if node_status in _TERMINAL_NODE_STATUSES:
                    self._raise(
                        status_code=409,
                        error_code="research.invalid_state",
                        message="cannot attach failure to terminal node",
                        details={"node_id": target_id, "status": node_status},
                    )
                next_status = _FAILURE_SEVERITY_TO_NODE_STATUS.get(severity, "weakened")
                if node_status != next_status and not (
                    node_status == "failed" and next_status == "weakened"
                ):
                    self._store.update_graph_node(
                        node_id=target_id,
                        short_label=None,
                        full_description=None,
                        status=next_status,
                    )
                if next_status == "failed":
                    invalidated_node_ids.append(target_id)
                else:
                    weakened_node_ids.append(target_id)
                anchor_node_ids.add(target_id)
            else:
                edge = self._ensure_target_exists_and_owned(
                    workspace_id=workspace_id,
                    target_type="edge",
                    target_id=target_id,
                )
                edge_status = str(edge["status"])
                if edge_status in _TERMINAL_EDGE_STATUSES:
                    self._raise(
                        status_code=409,
                        error_code="research.invalid_state",
                        message="cannot attach failure to terminal edge",
                        details={"edge_id": target_id, "status": edge_status},
                    )
                next_status = _FAILURE_SEVERITY_TO_EDGE_STATUS.get(severity, "weakened")
                current_strength = float(edge["strength"])
                penalty = 0.5 if next_status == "invalidated" else 0.3
                next_strength = max(0.0, round(current_strength - penalty, 4))
                self._store.update_graph_edge(
                    edge_id=target_id,
                    status=next_status,
                    strength=next_strength,
                )
                if next_status == "invalidated":
                    invalidated_edge_ids.append(target_id)
                else:
                    weakened_edge_ids.append(target_id)
                affected_edge_ids.add(target_id)
                source_node_id = str(edge["source_node_id"])
                target_node_id = str(edge["target_node_id"])
                anchor_node_ids.add(source_node_id)
                anchor_node_ids.add(target_node_id)

        affected_route_ids = self._mark_affected_routes(
            workspace_id=workspace_id,
            affected_node_ids=set(weakened_node_ids + invalidated_node_ids),
            affected_edge_ids=affected_edge_ids,
        )

        marker_summary = self._ensure_gap_and_branch_markers(
            workspace_id=workspace_id,
            failure_id=failure_id,
            anchor_node_ids=sorted(anchor_node_ids),
        )

        summary = {
            "failure_id": failure_id,
            "weakened_node_ids": sorted(set(weakened_node_ids)),
            "invalidated_node_ids": sorted(set(invalidated_node_ids)),
            "weakened_edge_ids": sorted(set(weakened_edge_ids)),
            "invalidated_edge_ids": sorted(set(invalidated_edge_ids)),
            "affected_route_ids": sorted(set(affected_route_ids)),
            **marker_summary,
        }
        self._store.update_failure_impact(
            failure_id=failure_id,
            impact_summary=summary,
            impact_updated_at=self._store.now(),
        )
        self._store.emit_event(
            event_name="failure_attached",
            request_id=request_id,
            job_id=None,
            workspace_id=workspace_id,
            component="failure_impact_service",
            step="attach",
            status="completed",
            refs={
                "failure_id": failure_id,
                "targets": targets,
                "impact_summary": summary,
            },
            metrics={
                "affected_node_count": len(summary["weakened_node_ids"])
                + len(summary["invalidated_node_ids"]),
                "affected_edge_count": len(summary["weakened_edge_ids"])
                + len(summary["invalidated_edge_ids"]),
                "affected_route_count": len(summary["affected_route_ids"]),
                "gap_count": len(summary["created_gap_node_ids"]),
                "branch_count": len(summary["created_branch_node_ids"]),
            },
        )
        return summary

    def _normalize_targets(
        self, attached_targets: list[dict[str, str]]
    ) -> list[dict[str, str]]:
        normalized: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for target in attached_targets:
            target_type = str(target.get("target_type", "")).strip()
            target_id = str(target.get("target_id", "")).strip()
            if target_type not in {"node", "edge"}:
                self._raise(
                    status_code=400,
                    error_code="research.invalid_request",
                    message="unsupported failure attached target_type",
                    details={"target_type": target_type},
                )
            if not target_id:
                self._raise(
                    status_code=400,
                    error_code="research.invalid_request",
                    message="attached target_id must not be empty",
                    details={"target_type": target_type},
                )
            signature = (target_type, target_id)
            if signature in seen:
                self._raise(
                    status_code=409,
                    error_code="research.invalid_state",
                    message="duplicate failure attach target",
                    details={"target_type": target_type, "target_id": target_id},
                )
            seen.add(signature)
            normalized.append({"target_type": target_type, "target_id": target_id})
        return normalized

    def _ensure_target_exists_and_owned(
        self, *, workspace_id: str, target_type: str, target_id: str
    ) -> dict[str, object]:
        if target_type == "node":
            target = self._store.get_graph_node(target_id)
            object_name = "node"
        else:
            target = self._store.get_graph_edge(target_id)
            object_name = "edge"
        if target is None:
            self._raise(
                status_code=404,
                error_code="research.not_found",
                message=f"failure attached {object_name} not found",
                details={"target_type": target_type, "target_id": target_id},
            )
        if str(target["workspace_id"]) != workspace_id:
            self._raise(
                status_code=409,
                error_code="research.conflict",
                message=f"failure attached {object_name} belongs to a different workspace",
                details={"target_type": target_type, "target_id": target_id},
            )
        return target

    def _mark_affected_routes(
        self,
        *,
        workspace_id: str,
        affected_node_ids: set[str],
        affected_edge_ids: set[str],
    ) -> list[str]:
        affected_routes: list[str] = []
        for route in self._store.list_routes(workspace_id):
            route_id = str(route["route_id"])
            route_edge_ids = {
                str(edge_id) for edge_id in route.get("route_edge_ids", [])
            }
            route_node_ids = {
                str(node_id) for node_id in route.get("route_node_ids", [])
            }
            has_edge_chain = bool(route_edge_ids)
            touches_edge = bool(route_edge_ids & affected_edge_ids)
            touches_atomic_node = (not has_edge_chain) and bool(
                route_node_ids & affected_node_ids
            )
            if not touches_edge and not touches_atomic_node:
                continue
            status = str(route.get("status", "candidate"))
            if status not in _ROUTE_TERMINAL_STATUSES and status != "weakened":
                self._store.update_route_status(route_id=route_id, status="weakened")
            affected_routes.append(route_id)
        return affected_routes

    def _ensure_gap_and_branch_markers(
        self, *, workspace_id: str, failure_id: str, anchor_node_ids: list[str]
    ) -> dict[str, list[str]]:
        created_gap_node_ids: list[str] = []
        created_branch_node_ids: list[str] = []
        created_branch_edge_ids: list[str] = []
        gap_node_ids: list[str] = []
        branch_node_ids: list[str] = []
        branch_edge_ids: list[str] = []
        for anchor_node_id in anchor_node_ids:
            gap_object_ref_id = f"{failure_id}:{anchor_node_id}:gap"
            gap_node = self._store.find_graph_node_by_object_ref(
                workspace_id=workspace_id,
                object_ref_type="failure_gap",
                object_ref_id=gap_object_ref_id,
            )
            if gap_node is None:
                gap_node = self._store.create_graph_node(
                    workspace_id=workspace_id,
                    node_type="gap",
                    object_ref_type="failure_gap",
                    object_ref_id=gap_object_ref_id,
                    short_label=f"Gap after failure {failure_id[:8]}",
                    full_description=(
                        f"Gap generated from failure {failure_id} on node {anchor_node_id}"
                    ),
                    status="active",
                )
                created_gap_node_ids.append(str(gap_node["node_id"]))
            gap_node_ids.append(str(gap_node["node_id"]))

            branch_object_ref_id = f"{failure_id}:{anchor_node_id}:branch"
            branch_node = self._store.find_graph_node_by_object_ref(
                workspace_id=workspace_id,
                object_ref_type="failure_branch",
                object_ref_id=branch_object_ref_id,
            )
            if branch_node is None:
                branch_node = self._store.create_graph_node(
                    workspace_id=workspace_id,
                    node_type="branch",
                    object_ref_type="failure_branch",
                    object_ref_id=branch_object_ref_id,
                    short_label=f"Branch after failure {failure_id[:8]}",
                    full_description=(
                        f"Branch generated from failure {failure_id} on node {anchor_node_id}"
                    ),
                    status="active",
                )
                created_branch_node_ids.append(str(branch_node["node_id"]))
            branch_node_ids.append(str(branch_node["node_id"]))

            gap_edge_ref = f"{failure_id}:{anchor_node_id}:gap_edge"
            existing_gap_edge = self._store.find_graph_edge_by_ref(
                workspace_id=workspace_id,
                source_node_id=anchor_node_id,
                target_node_id=str(gap_node["node_id"]),
                edge_type="weakens",
                object_ref_type="failure_gap_link",
                object_ref_id=gap_edge_ref,
            )
            if existing_gap_edge is None:
                self._store.create_graph_edge(
                    workspace_id=workspace_id,
                    source_node_id=anchor_node_id,
                    target_node_id=str(gap_node["node_id"]),
                    edge_type="weakens",
                    object_ref_type="failure_gap_link",
                    object_ref_id=gap_edge_ref,
                    strength=0.7,
                    status="active",
                )

            branch_edge_ref = f"{failure_id}:{anchor_node_id}:branch_edge"
            existing_branch_edge = self._store.find_graph_edge_by_ref(
                workspace_id=workspace_id,
                source_node_id=anchor_node_id,
                target_node_id=str(branch_node["node_id"]),
                edge_type="branches_to",
                object_ref_type="failure_branch_link",
                object_ref_id=branch_edge_ref,
            )
            if existing_branch_edge is None:
                created_edge = self._store.create_graph_edge(
                    workspace_id=workspace_id,
                    source_node_id=anchor_node_id,
                    target_node_id=str(branch_node["node_id"]),
                    edge_type="branches_to",
                    object_ref_type="failure_branch_link",
                    object_ref_id=branch_edge_ref,
                    strength=0.7,
                    status="active",
                )
                created_branch_edge_ids.append(str(created_edge["edge_id"]))
                branch_edge_ids.append(str(created_edge["edge_id"]))
            else:
                branch_edge_ids.append(str(existing_branch_edge["edge_id"]))

        return {
            "created_gap_node_ids": created_gap_node_ids,
            "created_branch_node_ids": created_branch_node_ids,
            "created_branch_edge_ids": created_branch_edge_ids,
            "gap_node_ids": sorted(set(gap_node_ids)),
            "branch_node_ids": sorted(set(branch_node_ids)),
            "branch_edge_ids": sorted(set(branch_edge_ids)),
        }
