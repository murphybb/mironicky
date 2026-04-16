from __future__ import annotations

from dataclasses import dataclass

from research_layer.api.controllers._state_store import ResearchApiStateStore


@dataclass(slots=True)
class PackageBuildServiceError(Exception):
    status_code: int
    error_code: str
    message: str
    details: dict[str, object]

    def __str__(self) -> str:
        return self.message


class PackageBuildService:
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
        raise PackageBuildServiceError(
            status_code=status_code,
            error_code=error_code,
            message=message,
            details=details or {},
        )

    def build_snapshot(
        self,
        *,
        workspace_id: str,
        title: str,
        summary: str,
        included_route_ids: list[str],
        included_node_ids: list[str],
        included_validation_ids: list[str],
        request_id: str,
    ) -> dict[str, object]:
        if not (
            included_route_ids
            or included_node_ids
            or included_validation_ids
        ):
            self._raise(
                status_code=400,
                error_code="research.invalid_request",
                message="package build requires at least one route/node/validation reference",
            )

        requested_route_ids = self._dedupe_ids(included_route_ids)
        requested_node_ids = self._dedupe_ids(included_node_ids)
        requested_validation_ids = self._dedupe_ids(included_validation_ids)

        package_id = self._store.gen_id("pkg")
        self._store.emit_event(
            event_name="package_build_started",
            request_id=request_id,
            job_id=None,
            workspace_id=workspace_id,
            component="package_build_service",
            step="build",
            status="started",
            refs={
                "package_id": package_id,
                "included_route_ids": requested_route_ids,
                "included_node_ids": requested_node_ids,
                "included_validation_ids": requested_validation_ids,
            },
            metrics={
                "request_route_count": len(requested_route_ids),
                "request_node_count": len(requested_node_ids),
                "request_validation_count": len(requested_validation_ids),
            },
        )

        try:
            routes = self._resolve_routes(
                workspace_id=workspace_id, route_ids=requested_route_ids
            )

            route_traceability: dict[str, dict[str, object]] = {}
            route_derived_node_ids: list[str] = []
            route_derived_validation_ids: list[str] = []
            for route in routes:
                route_id = str(route["route_id"])
                route_node_ids = self._collect_route_node_ids(route)
                route_derived_node_ids.extend(route_node_ids)
                route_traceability[route_id] = {
                    "node_ids": route_node_ids,
                    "version_id": route.get("version_id"),
                    "next_validation_node_id": route.get("next_validation_node_id"),
                }
                next_validation_node_id = route.get("next_validation_node_id")
                if next_validation_node_id:
                    node = self._store.get_graph_node(str(next_validation_node_id))
                    if (
                        node is not None
                        and str(node.get("workspace_id")) == workspace_id
                        and str(node.get("object_ref_type"))
                        in {"validation_action", "research_validation", "validation"}
                    ):
                        route_derived_validation_ids.append(
                            str(node.get("object_ref_id"))
                        )

            nodes = self._resolve_nodes(
                workspace_id=workspace_id,
                node_ids=self._dedupe_ids(requested_node_ids + route_derived_node_ids),
            )
            validation_map = {
                str(item["validation_id"]): item
                for item in self._store.list_validations(workspace_id=workspace_id)
            }
            resolved_validations: list[dict[str, object]] = []
            for validation_id in requested_validation_ids:
                validation = validation_map.get(validation_id)
                if validation is None:
                    self._raise(
                        status_code=404,
                        error_code="research.not_found",
                        message="validation not found",
                        details={"validation_id": validation_id},
                    )
                resolved_validations.append(validation)

            missing_route_validation_ids: list[str] = []
            for validation_id in self._dedupe_ids(route_derived_validation_ids):
                validation = validation_map.get(validation_id)
                if validation is None:
                    missing_route_validation_ids.append(validation_id)
                    continue
                resolved_validations.append(validation)

            validations = list(
                {
                    str(item["validation_id"]): item
                    for item in resolved_validations
                }.values()
            )

            private_nodes = [
                node
                for node in nodes
                if str(node.get("node_type")) == "private_dependency"
            ]
            public_nodes = [
                node
                for node in nodes
                if str(node.get("node_type")) != "private_dependency"
            ]
            route_refs_by_node = self._build_route_refs_by_node(route_traceability)

            public_gap_nodes: list[dict[str, object]] = []
            private_dependency_flags: list[dict[str, object]] = []
            for private_node in private_nodes:
                private_node_id = str(private_node["node_id"])
                replacement_gap_node_id = self._store.gen_id("pkg_gap")
                route_ids = route_refs_by_node.get(private_node_id, [])
                gap_node = {
                    "node_id": replacement_gap_node_id,
                    "workspace_id": workspace_id,
                    "node_type": "gap",
                    "object_ref_type": "public_gap",
                    "object_ref_id": f"{package_id}:{private_node_id}",
                    "short_label": f"Public gap for private dependency {private_node_id}",
                    "full_description": (
                        "Private dependency excluded from package snapshot; "
                        "this public gap marks required follow-up validation."
                    ),
                    "status": "active",
                    "trace_refs": {
                        "private_node_id": private_node_id,
                        "route_ids": route_ids,
                        "private_object_ref": {
                            "object_ref_type": str(private_node.get("object_ref_type")),
                            "object_ref_id": str(private_node.get("object_ref_id")),
                        },
                    },
                }
                public_gap_nodes.append(gap_node)
                private_dependency_flags.append(
                    {
                        "private_node_id": private_node_id,
                        "private_object_ref": {
                            "object_ref_type": str(private_node.get("object_ref_type")),
                            "object_ref_id": str(private_node.get("object_ref_id")),
                        },
                        "reason": "private_dependency_requires_public_gap",
                        "referenced_by_route_ids": route_ids,
                        "replacement_gap_node_id": replacement_gap_node_id,
                    }
                )

            public_nodes.extend(public_gap_nodes)
            replacement_map = {
                str(flag["private_node_id"]): str(flag["replacement_gap_node_id"])
                for flag in private_dependency_flags
            }
            normalized_routes = [
                self._normalize_route(route, replacement_map=replacement_map)
                for route in routes
            ]
            normalized_validations = [
                self._normalize_validation(item) for item in validations
            ]
            normalized_nodes = [self._normalize_node(item) for item in public_nodes]

            boundary_notes = [
                "This package is a snapshot and does not live-sync with workspace state.",
                "Private dependencies are converted into public gap nodes for transparent boundaries.",
            ]
            if not private_dependency_flags:
                boundary_notes.append(
                    "No private dependency conversion was required for this snapshot."
                )
            if missing_route_validation_ids:
                boundary_notes.append(
                    "Some route-derived validation references could not be resolved "
                    "to formal validation actions and were excluded from snapshot validations."
                )

            pre_publish_review = self._build_pre_publish_review(
                workspace_id=workspace_id,
                routes=routes,
                normalized_nodes=normalized_nodes,
                normalized_validations=normalized_validations,
                private_dependency_flags=private_dependency_flags,
                missing_route_validation_ids=missing_route_validation_ids,
            )
            pre_publish_review_refs = {
                "readiness": pre_publish_review["readiness"],
                "blocking_issue_refs": [
                    item.get("refs", {})
                    for item in pre_publish_review.get("blocking_issues", [])
                    if isinstance(item, dict)
                ],
                "warning_refs": [
                    item.get("refs", {})
                    for item in pre_publish_review.get("warnings", [])
                    if isinstance(item, dict)
                ],
            }

            traceability_refs = {
                "routes": route_traceability,
                "node_ids": [str(item["node_id"]) for item in normalized_nodes],
                "validation_ids": [
                    str(item["validation_id"]) for item in normalized_validations
                ],
                "missing_route_validation_ids": missing_route_validation_ids,
                "private_dependency_node_ids": [
                    str(item["private_node_id"]) for item in private_dependency_flags
                ],
                "public_gap_node_ids": [
                    str(item["node_id"]) for item in public_gap_nodes
                ],
                "replacement_map": replacement_map,
                "pre_publish_review_refs": pre_publish_review_refs,
            }

            snapshot_payload = {
                "package_id": package_id,
                "workspace_id": workspace_id,
                "snapshot_type": "research_package_snapshot",
                "snapshot_version": "slice11.v1",
                "title": title,
                "summary": summary,
                "routes": normalized_routes,
                "nodes": normalized_nodes,
                "validations": normalized_validations,
                "private_dependency_flags": private_dependency_flags,
                "public_gap_nodes": public_gap_nodes,
                "boundary_notes": boundary_notes,
                "pre_publish_review": pre_publish_review,
                "traceability_refs": traceability_refs,
            }

            package = self._store.create_package(
                package_id=package_id,
                workspace_id=workspace_id,
                title=title,
                summary=summary,
                included_route_ids=[
                    str(route["route_id"]) for route in normalized_routes
                ],
                included_node_ids=[str(node["node_id"]) for node in normalized_nodes],
                included_validation_ids=[
                    str(item["validation_id"]) for item in normalized_validations
                ],
                status="draft",
                snapshot_type="research_package_snapshot",
                snapshot_version="slice11.v1",
                private_dependency_flags=private_dependency_flags,
                public_gap_nodes=public_gap_nodes,
                boundary_notes=boundary_notes,
                traceability_refs=traceability_refs,
                snapshot_payload=snapshot_payload,
                replay_ready=True,
                build_request_id=request_id,
            )

            self._store.emit_event(
                event_name="package_build_completed",
                request_id=request_id,
                job_id=None,
                workspace_id=workspace_id,
                component="package_build_service",
                step="build",
                status="completed",
                refs={"package_id": package_id},
                metrics={
                    "included_route_count": len(normalized_routes),
                    "included_node_count": len(normalized_nodes),
                    "included_validation_count": len(normalized_validations),
                    "private_dependency_count": len(private_dependency_flags),
                    "public_gap_count": len(public_gap_nodes),
                    "replay_ready": True,
                },
            )
            return package
        except PackageBuildServiceError as exc:
            self._store.emit_event(
                event_name="package_build_completed",
                request_id=request_id,
                job_id=None,
                workspace_id=workspace_id,
                component="package_build_service",
                step="build",
                status="failed",
                refs={"package_id": package_id},
                error={
                    "error_code": exc.error_code,
                    "message": exc.message,
                    "details": exc.details,
                },
            )
            raise

    def _build_pre_publish_review(
        self,
        *,
        workspace_id: str,
        routes: list[dict[str, object]],
        normalized_nodes: list[dict[str, object]],
        normalized_validations: list[dict[str, object]],
        private_dependency_flags: list[dict[str, object]],
        missing_route_validation_ids: list[str],
    ) -> dict[str, object]:
        blocking_issues: list[dict[str, object]] = []
        warnings: list[dict[str, object]] = []
        suggestions: list[str] = []

        if not routes:
            blocking_issues.append(
                {
                    "issue_code": "no_routes_in_snapshot",
                    "severity": "blocking",
                    "message": "Snapshot must include at least one route.",
                    "refs": {"workspace_id": workspace_id},
                }
            )
            suggestions.append("Include at least one validated route before publishing.")

        for route in routes:
            route_id = str(route.get("route_id", ""))
            risk_score = float(route.get("risk_score", 0.0))
            if risk_score >= 70.0:
                blocking_issues.append(
                    {
                        "issue_code": f"route_high_risk:{route_id}",
                        "severity": "blocking",
                        "message": "Route risk score is above publish threshold.",
                        "refs": {"route_id": route_id, "risk_score": risk_score},
                    }
                )
                suggestions.append(
                    "Reduce high-risk routes or add stronger mitigation evidence."
                )
            elif risk_score >= 55.0:
                warnings.append(
                    {
                        "issue_code": f"route_elevated_risk:{route_id}",
                        "severity": "warning",
                        "message": "Route risk score is elevated for publication.",
                        "refs": {"route_id": route_id, "risk_score": risk_score},
                    }
                )

            if not list(route.get("top_factors", [])):
                warnings.append(
                    {
                        "issue_code": f"route_missing_top_factors:{route_id}",
                        "severity": "warning",
                        "message": "Route lacks top factor traceability for reviewer context.",
                        "refs": {"route_id": route_id},
                    }
                )
                suggestions.append(
                    "Re-score routes to persist top factors before package publication."
                )

        if not normalized_validations:
            warnings.append(
                {
                    "issue_code": "snapshot_without_validation",
                    "severity": "warning",
                    "message": "Snapshot includes no validation actions.",
                    "refs": {"workspace_id": workspace_id},
                }
            )
            suggestions.append(
                "Include at least one validation action to improve publication readiness."
            )

        if missing_route_validation_ids:
            blocking_issues.append(
                {
                    "issue_code": "missing_route_validations",
                    "severity": "blocking",
                    "message": (
                        "Some route-derived validation references cannot be resolved."
                    ),
                    "refs": {
                        "workspace_id": workspace_id,
                        "validation_ids": list(missing_route_validation_ids),
                    },
                }
            )
            suggestions.append(
                "Resolve route validation references or remove stale route links."
            )

        if private_dependency_flags:
            warnings.append(
                {
                    "issue_code": "private_dependency_public_gap_present",
                    "severity": "warning",
                    "message": (
                        "Private dependencies were converted to public gaps; review completeness."
                    ),
                    "refs": {
                        "private_node_ids": [
                            str(item.get("private_node_id", ""))
                            for item in private_dependency_flags
                        ],
                    },
                }
            )
            suggestions.append(
                "Verify each public gap has a follow-up validation owner and timeline."
            )

        if not normalized_nodes:
            blocking_issues.append(
                {
                    "issue_code": "snapshot_without_nodes",
                    "severity": "blocking",
                    "message": "Snapshot contains no graph nodes after normalization.",
                    "refs": {"workspace_id": workspace_id},
                }
            )

        readiness = "ready"
        if blocking_issues:
            readiness = "blocked"
        elif warnings:
            readiness = "review_required"

        normalized_suggestions = [
            text for text in sorted(set(suggestions)) if str(text).strip()
        ]
        if not normalized_suggestions:
            normalized_suggestions = [
                "No blocking concerns detected; proceed with standard publication checks."
            ]

        return {
            "generated_by": "package_build_service.pre_publish_review.v1",
            "readiness": readiness,
            "blocking_issues": blocking_issues,
            "warnings": warnings,
            "suggestions": normalized_suggestions,
        }

    def publish_snapshot(
        self,
        *,
        workspace_id: str,
        package_id: str,
        request_id: str,
        job_id: str | None,
        async_mode: bool,
    ) -> dict[str, object]:
        package = self._store.get_package(package_id)
        if package is None:
            self._raise(
                status_code=404,
                error_code="research.not_found",
                message="package not found",
                details={"package_id": package_id},
            )
        if str(package["workspace_id"]) != workspace_id:
            self._raise(
                status_code=409,
                error_code="research.conflict",
                message="workspace_id does not match package ownership",
                details={"package_id": package_id},
            )
        if str(package["status"]) == "published":
            self._raise(
                status_code=409,
                error_code="research.invalid_state",
                message="package is already published",
                details={"package_id": package_id},
            )
        if not bool(package.get("replay_ready")):
            self._raise(
                status_code=409,
                error_code="research.invalid_state",
                message="package snapshot is not replay-ready",
                details={"package_id": package_id},
            )

        self._store.emit_event(
            event_name="package_publish_started",
            request_id=request_id,
            job_id=job_id,
            workspace_id=workspace_id,
            component="package_build_service",
            step="publish",
            status="started",
            refs={"package_id": package_id, "async_mode": async_mode},
        )

        try:
            publish_result = self._store.create_package_publish_result(
                package_id=package_id,
                workspace_id=workspace_id,
                snapshot_type=str(package["snapshot_type"]),
                snapshot_version=str(package["snapshot_version"]),
                boundary_notes=list(package.get("boundary_notes", [])),
                published_snapshot=dict(package.get("snapshot_payload", {})),
                request_id=request_id,
            )
            self._store.update_package_status(
                package_id=package_id,
                status="published",
                published_at=publish_result["published_at"].isoformat(),
            )
            self._store.emit_event(
                event_name="package_publish_completed",
                request_id=request_id,
                job_id=job_id,
                workspace_id=workspace_id,
                component="package_build_service",
                step="publish",
                status="completed",
                refs={
                    "package_id": package_id,
                    "publish_result_id": publish_result["publish_result_id"],
                },
                metrics={
                    "snapshot_version": str(package["snapshot_version"]),
                    "boundary_note_count": len(list(package.get("boundary_notes", []))),
                },
            )
            return publish_result
        except PackageBuildServiceError as exc:
            self._store.emit_event(
                event_name="package_publish_completed",
                request_id=request_id,
                job_id=job_id,
                workspace_id=workspace_id,
                component="package_build_service",
                step="publish",
                status="failed",
                refs={"package_id": package_id},
                error={
                    "error_code": exc.error_code,
                    "message": exc.message,
                    "details": exc.details,
                },
            )
            raise

    def _resolve_routes(
        self, *, workspace_id: str, route_ids: list[str]
    ) -> list[dict[str, object]]:
        resolved: list[dict[str, object]] = []
        for route_id in route_ids:
            route = self._store.get_route(route_id)
            if route is None:
                self._raise(
                    status_code=404,
                    error_code="research.not_found",
                    message="route not found",
                    details={"route_id": route_id},
                )
            if str(route["workspace_id"]) != workspace_id:
                self._raise(
                    status_code=409,
                    error_code="research.conflict",
                    message="workspace_id does not match route ownership",
                    details={"route_id": route_id},
                )
            resolved.append(route)
        return resolved

    def _resolve_nodes(
        self, *, workspace_id: str, node_ids: list[str]
    ) -> list[dict[str, object]]:
        resolved: list[dict[str, object]] = []
        for node_id in node_ids:
            node = self._store.get_graph_node(node_id)
            if node is None:
                self._raise(
                    status_code=404,
                    error_code="research.not_found",
                    message="graph node not found",
                    details={"node_id": node_id},
                )
            if str(node["workspace_id"]) != workspace_id:
                self._raise(
                    status_code=409,
                    error_code="research.conflict",
                    message="workspace_id does not match node ownership",
                    details={"node_id": node_id},
                )
            resolved.append(node)
        return resolved

    def _resolve_validations(
        self, *, workspace_id: str, validation_ids: list[str]
    ) -> list[dict[str, object]]:
        validation_map = {
            str(item["validation_id"]): item
            for item in self._store.list_validations(workspace_id=workspace_id)
        }
        resolved: list[dict[str, object]] = []
        for validation_id in validation_ids:
            validation = validation_map.get(validation_id)
            if validation is None:
                self._raise(
                    status_code=404,
                    error_code="research.not_found",
                    message="validation not found",
                    details={"validation_id": validation_id},
                )
            resolved.append(validation)
        return resolved

    def _build_route_refs_by_node(
        self, route_traceability: dict[str, dict[str, object]]
    ) -> dict[str, list[str]]:
        refs_by_node: dict[str, list[str]] = {}
        for route_id, trace in route_traceability.items():
            for node_id in trace.get("node_ids", []):
                refs_by_node.setdefault(str(node_id), []).append(route_id)
        return {
            node_id: sorted(set(route_ids))
            for node_id, route_ids in refs_by_node.items()
        }

    def _collect_route_node_ids(self, route: dict[str, object]) -> list[str]:
        collected = list(route.get("route_node_ids", []))
        conclusion_node_id = route.get("conclusion_node_id")
        next_validation_node_id = route.get("next_validation_node_id")
        if conclusion_node_id:
            collected.append(str(conclusion_node_id))
        if next_validation_node_id:
            collected.append(str(next_validation_node_id))
        return self._dedupe_ids([str(item) for item in collected if item])

    def _dedupe_ids(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for value in values:
            normalized = str(value).strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)
        return deduped

    def _normalize_route(
        self,
        route: dict[str, object],
        *,
        replacement_map: dict[str, str],
    ) -> dict[str, object]:
        rewritten_route_node_ids = [
            str(replacement_map.get(str(node_id), str(node_id)))
            for node_id in route.get("route_node_ids", [])
        ]
        rewritten_conclusion_node_id = route.get("conclusion_node_id")
        if rewritten_conclusion_node_id is not None:
            rewritten_conclusion_node_id = replacement_map.get(
                str(rewritten_conclusion_node_id),
                str(rewritten_conclusion_node_id),
            )
        rewritten_next_validation_node_id = route.get("next_validation_node_id")
        if rewritten_next_validation_node_id is not None:
            rewritten_next_validation_node_id = replacement_map.get(
                str(rewritten_next_validation_node_id),
                str(rewritten_next_validation_node_id),
            )
        return {
            "route_id": str(route["route_id"]),
            "workspace_id": str(route["workspace_id"]),
            "status": str(route["status"]),
            "title": str(route["title"]),
            "summary": str(route["summary"]),
            "version_id": route.get("version_id"),
            "route_node_ids": self._dedupe_ids(rewritten_route_node_ids),
            "conclusion_node_id": rewritten_conclusion_node_id,
            "next_validation_node_id": rewritten_next_validation_node_id,
            "top_factors": list(route.get("top_factors", [])),
        }

    def _normalize_node(self, node: dict[str, object]) -> dict[str, object]:
        return {
            "node_id": str(node["node_id"]),
            "workspace_id": str(node["workspace_id"]),
            "node_type": str(node["node_type"]),
            "object_ref_type": str(node["object_ref_type"]),
            "object_ref_id": str(node["object_ref_id"]),
            "short_label": str(node.get("short_label", "")),
            "full_description": str(node.get("full_description", "")),
            "status": str(node.get("status", "active")),
            "trace_refs": dict(node.get("trace_refs", {})),
        }

    def _normalize_validation(self, validation: dict[str, object]) -> dict[str, object]:
        return {
            "validation_id": str(validation["validation_id"]),
            "workspace_id": str(validation["workspace_id"]),
            "target_object": str(validation["target_object"]),
            "method": str(validation["method"]),
            "success_signal": str(validation["success_signal"]),
            "weakening_signal": str(validation["weakening_signal"]),
        }
