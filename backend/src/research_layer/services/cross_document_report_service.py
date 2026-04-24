from __future__ import annotations

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.services.route_challenge_service import RouteChallengeService

SECTION_LIMITS = {
    "claims": 50,
    "conflicts": 50,
    "historical_recall": 20,
    "routes": 50,
    "challenged_routes": 50,
    "unresolved_gaps": 50,
}
ITEM_SAMPLE_LIMIT = 3
ID_SAMPLE_LIMIT = 5


class CrossDocumentReportService:
    def __init__(self, store: ResearchApiStateStore) -> None:
        self._store = store
        self._route_challenge_service = RouteChallengeService(store)

    def build(self, *, workspace_id: str, request_id: str) -> dict[str, object]:
        claims = self._store.list_claims(workspace_id)
        conflicts = self._store.list_claim_conflicts(workspace_id=workspace_id)
        recalls = self._store.list_source_memory_recall_results(
            workspace_id=workspace_id
        )
        routes = self._store.list_routes(workspace_id)
        node_map = {
            str(node["node_id"]): node
            for node in self._store.list_graph_nodes(workspace_id)
        }
        challenged_routes = self._challenged_routes(
            workspace_id=workspace_id,
            routes=routes,
            conflicts=conflicts,
            node_map=node_map,
        )
        unresolved_gaps = self._unresolved_gaps(
            conflicts=conflicts,
            recalls=recalls,
            challenged_routes=challenged_routes,
        )

        return {
            "workspace_id": workspace_id,
            "summary": {
                "claim_count": len(claims),
                "conflict_count": len(conflicts),
                "source_recall_count": len(recalls),
                "route_count": len(routes),
                "challenged_route_count": len(challenged_routes),
                "unresolved_gap_count": len(unresolved_gaps),
                "section_limits": SECTION_LIMITS,
            },
            "sections": {
                "claims": [
                    self._claim_ref(claim)
                    for claim in self._limit_section("claims", claims)
                ],
                "conflicts": [
                    self._conflict_ref(conflict)
                    for conflict in self._limit_section("conflicts", conflicts)
                ],
                "historical_recall": [
                    self._source_recall_ref(recall)
                    for recall in self._limit_section("historical_recall", recalls)
                ],
                "unresolved_gaps": self._limit_section(
                    "unresolved_gaps", unresolved_gaps
                ),
                "routes": [
                    self._route_ref(route, node_map=node_map)
                    for route in self._limit_section("routes", routes)
                ],
                "challenged_routes": self._limit_section(
                    "challenged_routes", challenged_routes
                ),
            },
            "trace_refs": {
                "request_id": request_id,
                "claim_ids": self._id_sample(claim["claim_id"] for claim in claims),
                "conflict_ids": self._id_sample(
                    conflict["conflict_id"] for conflict in conflicts
                ),
                "source_recall_ids": self._id_sample(
                    recall["recall_id"] for recall in recalls
                ),
                "route_ids": self._id_sample(route["route_id"] for route in routes),
            },
        }

    def _limit_section(
        self, section_name: str, items: list[dict[str, object]]
    ) -> list[dict[str, object]]:
        return items[: SECTION_LIMITS[section_name]]

    def _claim_ref(self, claim: dict[str, object]) -> dict[str, object]:
        return {
            "claim_id": str(claim["claim_id"]),
            "source_id": str(claim["source_id"]),
            "candidate_id": str(claim["candidate_id"]),
            "claim_type": str(claim["claim_type"]),
            "semantic_type": claim.get("semantic_type"),
            "text": str(claim["text"]),
            "normalized_text": str(claim["normalized_text"]),
            "status": str(claim["status"]),
            "source_span": claim.get("source_span", {}),
            "trace_summary": self._compact_mapping(claim.get("trace_refs")),
            "memory_summary": self._compact_mapping(claim.get("memory_link")),
        }

    def _conflict_ref(self, conflict: dict[str, object]) -> dict[str, object]:
        return {
            "conflict_id": str(conflict["conflict_id"]),
            "new_claim_id": str(conflict["new_claim_id"]),
            "existing_claim_id": str(conflict["existing_claim_id"]),
            "conflict_type": str(conflict["conflict_type"]),
            "status": str(conflict["status"]),
            "evidence": conflict.get("evidence", {}),
            "source_ref": conflict.get("source_ref", {}),
            "decision_note": conflict.get("decision_note"),
            "created_request_id": conflict.get("created_request_id"),
            "resolved_request_id": conflict.get("resolved_request_id"),
        }

    def _source_recall_ref(self, recall: dict[str, object]) -> dict[str, object]:
        return {
            "recall_id": str(recall["recall_id"]),
            "source_id": str(recall["source_id"]),
            "status": str(recall["status"]),
            "reason": recall.get("reason"),
            "requested_method": recall.get("requested_method"),
            "applied_method": recall.get("applied_method"),
            "query_text": str(recall.get("query_text") or ""),
            "total": int(recall.get("total") or 0),
            "item_total": len(self._as_dict_list(recall.get("items"))),
            "items": [
                self._source_recall_item_ref(item)
                for item in self._as_dict_list(recall.get("items"))[:ITEM_SAMPLE_LIMIT]
            ],
            "items_truncated": len(self._as_dict_list(recall.get("items")))
            > ITEM_SAMPLE_LIMIT,
            "trace_refs": self._compact_mapping(recall.get("trace_refs")),
            "error": recall.get("error"),
            "request_id": recall.get("request_id"),
        }

    def _source_recall_item_ref(self, item: dict[str, object]) -> dict[str, object]:
        return {
            "memory_type": item.get("memory_type"),
            "memory_id": item.get("memory_id"),
            "score": item.get("score"),
            "title": item.get("title"),
            "snippet": item.get("snippet"),
            "source_ref": item.get("source_ref", {}),
            "linked_claim_refs": self._limit_claim_refs(item.get("linked_claim_refs")),
        }

    def _route_ref(
        self,
        route: dict[str, object],
        *,
        node_map: dict[str, dict[str, object]],
    ) -> dict[str, object]:
        return {
            "route_id": str(route["route_id"]),
            "title": str(route["title"]),
            "summary": str(route["summary"]),
            "status": str(route["status"]),
            "conclusion": str(route.get("conclusion") or ""),
            "claim_ids": self._route_claim_ids(route=route, node_map=node_map),
            "route_node_ids": self._id_sample(route.get("route_node_ids", [])),
            "route_edge_ids": self._id_sample(route.get("route_edge_ids", [])),
            "version_id": route.get("version_id"),
            "request_id": route.get("request_id"),
        }

    def _challenged_routes(
        self,
        *,
        workspace_id: str,
        routes: list[dict[str, object]],
        conflicts: list[dict[str, object]],
        node_map: dict[str, dict[str, object]],
    ) -> list[dict[str, object]]:
        conflict_index = self._route_challenge_service.build_conflict_index(
            workspace_id=workspace_id,
            conflicts=conflicts,
        )
        challenged: list[dict[str, object]] = []
        for route in routes:
            claim_ids = self._route_claim_ids(route=route, node_map=node_map)
            challenge = self._route_challenge_service.evaluate_route_with_conflict_index(
                route={**route, "claim_ids": claim_ids},
                conflict_index=conflict_index,
            )
            if challenge["challenge_status"] == "clean":
                continue
            challenged.append(
                {
                    "route_id": str(route["route_id"]),
                    "title": str(route["title"]),
                    "summary": str(route["summary"]),
                    "status": str(route["status"]),
                    "claim_ids": claim_ids,
                    "route_node_ids": self._id_sample(route.get("route_node_ids", [])),
                    "route_edge_ids": self._id_sample(route.get("route_edge_ids", [])),
                    "challenge_status": challenge["challenge_status"],
                    "challenge_refs": {
                        "conflict_count": challenge["conflict_count"],
                        "conflict_ids": self._id_sample(challenge["conflict_ids"]),
                    },
                }
            )
        return challenged

    def _route_claim_ids(
        self,
        *,
        route: dict[str, object],
        node_map: dict[str, dict[str, object]],
    ) -> list[str]:
        claim_ids: list[str] = []
        seen: set[str] = set()
        for node_id in route.get("route_node_ids", []):
            node = node_map.get(str(node_id))
            if node is None:
                continue
            claim_id = str(node.get("claim_id") or "").strip()
            if not claim_id or claim_id in seen:
                continue
            seen.add(claim_id)
            claim_ids.append(claim_id)
        return claim_ids

    def _unresolved_gaps(
        self,
        *,
        conflicts: list[dict[str, object]],
        recalls: list[dict[str, object]],
        challenged_routes: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        gaps: list[dict[str, object]] = []
        for conflict in conflicts:
            if str(conflict.get("status") or "") != "needs_review":
                continue
            gaps.append(
                {
                    "gap_type": "claim_conflict",
                    "status": "needs_review",
                    "conflict_id": str(conflict["conflict_id"]),
                    "claim_ids": [
                        str(conflict["new_claim_id"]),
                        str(conflict["existing_claim_id"]),
                    ],
                }
            )
        for recall in recalls:
            if str(recall.get("status") or "") == "completed":
                continue
            gaps.append(
                {
                    "gap_type": "source_memory_recall",
                    "status": str(recall.get("status") or "unknown"),
                    "recall_id": str(recall["recall_id"]),
                    "source_id": str(recall["source_id"]),
                    "reason": recall.get("reason"),
                }
            )
        for route in challenged_routes:
            gaps.append(
                {
                    "gap_type": "challenged_route",
                    "status": str(route["challenge_status"]),
                    "route_id": str(route["route_id"]),
                    "conflict_ids": route["challenge_refs"]["conflict_ids"],
                }
            )
        return gaps

    def _id_sample(self, values: object) -> dict[str, object]:
        items = [str(value) for value in values] if values is not None else []
        return {
            "total": len(items),
            "items": items[:ID_SAMPLE_LIMIT],
            "truncated": len(items) > ID_SAMPLE_LIMIT,
        }

    def _compact_mapping(self, value: object) -> dict[str, object]:
        if not isinstance(value, dict):
            return {"keys": [], "total_keys": 0, "truncated": False}
        keys = [str(key) for key in value.keys()]
        return {
            "keys": keys[:ID_SAMPLE_LIMIT],
            "total_keys": len(keys),
            "truncated": len(keys) > ID_SAMPLE_LIMIT,
        }

    def _as_dict_list(self, value: object) -> list[dict[str, object]]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    def _limit_claim_refs(self, value: object) -> list[dict[str, object]]:
        return self._as_dict_list(value)[:ITEM_SAMPLE_LIMIT]
