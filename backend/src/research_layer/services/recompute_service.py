from __future__ import annotations

from dataclasses import dataclass

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.services.failure_impact_service import (
    FailureImpactError,
    FailureImpactService,
)
from research_layer.services.score_service import ScoreService, ScoreServiceError
from research_layer.services.version_diff_service import VersionDiffService


@dataclass(slots=True)
class RecomputeServiceError(Exception):
    status_code: int
    error_code: str
    message: str
    details: dict[str, object]

    def __str__(self) -> str:
        return self.message


class RecomputeService:
    def __init__(self, store: ResearchApiStateStore) -> None:
        self._store = store
        self._impact_service = FailureImpactService(store)
        self._score_service = ScoreService(store)
        self._diff_service = VersionDiffService()

    def _raise(
        self,
        *,
        status_code: int,
        error_code: str,
        message: str,
        details: dict[str, object] | None = None,
    ) -> None:
        raise RecomputeServiceError(
            status_code=status_code,
            error_code=error_code,
            message=message,
            details=details or {},
        )

    async def recompute_from_failure(
        self,
        *,
        workspace_id: str,
        failure_id: str,
        reason: str,
        request_id: str,
        job_id: str | None = None,
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
        graph_nodes = self._store.list_graph_nodes(workspace_id)
        if not graph_nodes:
            self._raise(
                status_code=409,
                error_code="research.invalid_state",
                message="graph is not ready for recompute",
                details={"workspace_id": workspace_id},
            )
        before_snapshot = self._snapshot(workspace_id)
        graph_workspace = self._store.get_graph_workspace(workspace_id)
        base_version_id = (
            str(graph_workspace["latest_version_id"])
            if graph_workspace and graph_workspace.get("latest_version_id")
            else None
        )
        self._store.emit_event(
            event_name="recompute_started",
            request_id=request_id,
            job_id=job_id,
            workspace_id=workspace_id,
            component="recompute_service",
            step="recompute",
            status="started",
            refs={
                "failure_id": failure_id,
                "base_version_id": base_version_id,
                "route_ids": [str(route["route_id"]) for route in before_snapshot["routes_meta"]],
            },
            metrics={
                "trigger": "failure_attach",
                "reason": reason,
                "affected_node_count": len(graph_nodes),
                "affected_edge_count": len(self._store.list_graph_edges(workspace_id)),
            },
        )

        try:
            routes = self._store.list_routes(workspace_id)
            if not routes:
                self._raise(
                    status_code=409,
                    error_code="research.invalid_state",
                    message="no persisted routes available for recompute",
                    details={"workspace_id": workspace_id},
                )

            impacted = self._impact_service.apply_failure(
                workspace_id=workspace_id,
                failure_id=failure_id,
                request_id=request_id,
            )

            for route in self._store.list_routes(workspace_id):
                route_id = str(route["route_id"])
                self._score_service.score_route(
                    workspace_id=workspace_id,
                    route_id=route_id,
                    request_id=request_id,
                    focus_node_ids=[
                        str(node_id) for node_id in route.get("route_node_ids", [])
                    ],
                )

            after_snapshot = self._snapshot(workspace_id)
            route_impacts = self._build_route_impacts(
                base_version_id=base_version_id,
                impacted=impacted,
                before_snapshot=before_snapshot,
                after_snapshot=after_snapshot,
            )
            diff_payload = self._diff_service.build_diff_payload(
                failure_id=failure_id,
                base_version_id=base_version_id,
                new_version_id=None,
                before_snapshot=before_snapshot,
                after_snapshot=after_snapshot,
                route_impacts=route_impacts,
            )
            self._merge_forced_diff_categories(
                diff_payload=diff_payload,
                impacted=impacted,
            )

            version = self._store.create_graph_version(
                workspace_id=workspace_id,
                trigger_type="recompute",
                change_summary=f"recompute after failure {failure_id}: {reason}",
                diff_payload=diff_payload,
                request_id=request_id,
            )
            version_id = str(version["version_id"])
            diff_payload["new_version_id"] = version_id
            for route_impact in diff_payload["route_impacts"]:
                if isinstance(route_impact, dict):
                    route_impact["version_id"] = version_id
            self._store.update_failure_impact(
                failure_id=failure_id,
                impact_summary={
                    **impacted,
                    "route_impacts": diff_payload["route_impacts"],
                    "version_id": version_id,
                },
                impact_updated_at=self._store.now(),
            )
            self._store.update_graph_version_diff_payload(
                version_id=version_id,
                diff_payload=diff_payload,
            )
            self._store.set_routes_version_for_workspace(
                workspace_id=workspace_id,
                version_id=version_id,
            )
            self._store.upsert_graph_workspace(
                workspace_id=workspace_id,
                latest_version_id=version_id,
                status="ready",
                node_count=len(after_snapshot["nodes"]),
                edge_count=len(after_snapshot["edges"]),
            )
            self._store.emit_event(
                event_name="diff_created",
                request_id=request_id,
                job_id=job_id,
                workspace_id=workspace_id,
                component="recompute_service",
                step="diff",
                status="completed",
                refs={
                    "failure_id": failure_id,
                    "version_id": version_id,
                    "route_ids": [str(route["route_id"]) for route in self._store.list_routes(workspace_id)],
                    "impacted_route_ids": [item["route_id"] for item in diff_payload["route_impacts"]],
                },
                metrics={
                    "added_node_count": len(diff_payload["added"]["nodes"]),
                    "weakened_node_count": len(diff_payload["weakened"]["nodes"]),
                    "invalidated_node_count": len(diff_payload["invalidated"]["nodes"]),
                    "branch_change_count": len(
                        diff_payload["branch_changes"]["created_branch_node_ids"]
                    ),
                },
            )
            self._store.emit_event(
                event_name="recompute_completed",
                request_id=request_id,
                job_id=job_id,
                workspace_id=workspace_id,
                component="recompute_service",
                step="recompute",
                status="completed",
                refs={
                    "failure_id": failure_id,
                    "version_id": version_id,
                    "route_ids": [str(route["route_id"]) for route in self._store.list_routes(workspace_id)],
                    "impacted_route_ids": [item["route_id"] for item in diff_payload["route_impacts"]],
                },
                metrics={
                    "new_version_id": version_id,
                    "route_count_after": len(after_snapshot["routes"]),
                    "weakened_node_count": len(diff_payload["weakened"]["nodes"]),
                    "weakened_edge_count": len(diff_payload["weakened"]["edges"]),
                },
            )
            return {
                "version_id": version_id,
                "diff_payload": diff_payload,
                "impact_summary": impacted,
            }
        except (
            RecomputeServiceError,
            ScoreServiceError,
            FailureImpactError,
        ) as exc:
            if isinstance(exc, RecomputeServiceError):
                payload_error = exc
            else:
                payload_error = RecomputeServiceError(
                    status_code=exc.status_code,
                    error_code=exc.error_code,
                    message=exc.message,
                    details=exc.details,
                )
            self._store.emit_event(
                event_name="recompute_completed",
                request_id=request_id,
                job_id=job_id,
                workspace_id=workspace_id,
                component="recompute_service",
                step="recompute",
                status="failed",
                refs={"failure_id": failure_id},
                error={
                    "error_code": payload_error.error_code,
                    "message": payload_error.message,
                    "details": payload_error.details,
                },
            )
            raise payload_error

    def _snapshot(self, workspace_id: str) -> dict[str, object]:
        nodes = {
            str(node["node_id"]): {
                "status": str(node.get("status", "")),
                "node_type": str(node.get("node_type", "")),
            }
            for node in self._store.list_graph_nodes(workspace_id)
        }
        edges = {
            str(edge["edge_id"]): {
                "status": str(edge.get("status", "")),
                "edge_type": str(edge.get("edge_type", "")),
            }
            for edge in self._store.list_graph_edges(workspace_id)
        }
        routes = {
            str(route["route_id"]): {
                "status": str(route.get("status", "")),
                "support_score": float(route.get("support_score", 0.0)),
                "risk_score": float(route.get("risk_score", 0.0)),
                "progressability_score": float(route.get("progressability_score", 0.0)),
                "route_node_ids": [str(node_id) for node_id in route.get("route_node_ids", [])],
                "route_edge_ids": [str(edge_id) for edge_id in route.get("route_edge_ids", [])],
                "route_edge_ids_canonical_present": bool(
                    route.get("route_edge_ids_canonical_present", False)
                ),
                "route_edge_ids_canonical_valid": bool(
                    route.get("route_edge_ids_canonical_valid", False)
                ),
                "route_edge_ids_canonical_error": route.get(
                    "route_edge_ids_canonical_error"
                ),
            }
            for route in self._store.list_routes(workspace_id)
        }
        routes_meta = [
            {"route_id": str(route["route_id"])}
            for route in self._store.list_routes(workspace_id)
        ]
        return {"nodes": nodes, "edges": edges, "routes": routes, "routes_meta": routes_meta}

    def _build_route_impacts(
        self,
        *,
        base_version_id: str | None,
        impacted: dict[str, object],
        before_snapshot: dict[str, object],
        after_snapshot: dict[str, object],
    ) -> list[dict[str, object]]:
        before_routes = before_snapshot["routes"]
        after_routes = after_snapshot["routes"]
        impacted_route_ids = {
            str(route_id) for route_id in impacted.get("affected_route_ids", [])
        }
        changed_route_ids = {
            route_id
            for route_id in set(before_routes) & set(after_routes)
            if before_routes[route_id] != after_routes[route_id]
        }
        all_route_ids = sorted(impacted_route_ids | changed_route_ids)
        impacted_node_ids = sorted(
            {
                str(node_id)
                for node_id in impacted.get("weakened_node_ids", [])
                + impacted.get("invalidated_node_ids", [])
            }
        )
        impacted_edge_ids = sorted(
            {
                str(edge_id)
                for edge_id in impacted.get("weakened_edge_ids", [])
                + impacted.get("invalidated_edge_ids", [])
            }
        )

        route_impacts: list[dict[str, object]] = []
        for route_id in all_route_ids:
            after_route = after_routes.get(route_id)
            if after_route is None:
                continue
            if not bool(after_route.get("route_edge_ids_canonical_present", False)):
                self._raise(
                    status_code=409,
                    error_code="research.version_diff_unavailable",
                    message="route impact unavailable due to missing canonical replay source",
                    details={"route_id": route_id, "reason": "missing"},
                )
            if not bool(after_route.get("route_edge_ids_canonical_valid", False)):
                self._raise(
                    status_code=409,
                    error_code="research.version_diff_unavailable",
                    message="route impact unavailable due to missing canonical replay source",
                    details={
                        "route_id": route_id,
                        "reason": str(after_route.get("route_edge_ids_canonical_error")),
                    },
                )
            before_route = before_routes.get(route_id, {})
            route_node_ids = [
                str(node_id) for node_id in after_route.get("route_node_ids", [])
            ]
            route_edge_ids = [
                str(edge_id) for edge_id in after_route.get("route_edge_ids", [])
            ]
            impacted_route_edge_ids = [
                edge_id for edge_id in route_edge_ids if edge_id in impacted_edge_ids
            ]
            if route_edge_ids and not impacted_route_edge_ids:
                continue
            route_impacts.append(
                {
                    "route_id": route_id,
                    "version_id": None,
                    "base_version_id": base_version_id,
                    "status_before": str(before_route.get("status", "missing")),
                    "status_after": str(after_route.get("status", "missing")),
                    "route_edge_ids": route_edge_ids,
                    "impacted_edge_ids": impacted_route_edge_ids,
                    "impacted_node_ids": [
                        node_id for node_id in route_node_ids if node_id in impacted_node_ids
                    ]
                    if not route_edge_ids
                    else [],
                    "reason": (
                        "route impact derived from persisted route_edge_ids_json "
                        "and persisted route/node status changes"
                    ),
                }
            )
        return route_impacts

    def _merge_forced_diff_categories(
        self,
        *,
        diff_payload: dict[str, object],
        impacted: dict[str, object],
    ) -> None:
        weakened = diff_payload["weakened"]
        invalidated = diff_payload["invalidated"]
        branch_changes = diff_payload["branch_changes"]

        weakened["nodes"] = sorted(
            set(weakened["nodes"]) | set(impacted.get("weakened_node_ids", []))
        )
        invalidated["nodes"] = sorted(
            set(invalidated["nodes"]) | set(impacted.get("invalidated_node_ids", []))
        )
        weakened["edges"] = sorted(
            set(weakened["edges"]) | set(impacted.get("weakened_edge_ids", []))
        )
        invalidated["edges"] = sorted(
            set(invalidated["edges"]) | set(impacted.get("invalidated_edge_ids", []))
        )
        weakened["routes"] = sorted(
            set(weakened["routes"]) | set(impacted.get("affected_route_ids", []))
        )
        branch_changes["created_branch_node_ids"] = sorted(
            set(branch_changes["created_branch_node_ids"])
            | set(impacted.get("created_branch_node_ids", []))
            | set(impacted.get("branch_node_ids", []))
        )
        branch_changes["created_branch_edge_ids"] = sorted(
            set(branch_changes["created_branch_edge_ids"])
            | set(impacted.get("created_branch_edge_ids", []))
            | set(impacted.get("branch_edge_ids", []))
        )
