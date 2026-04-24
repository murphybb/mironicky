from __future__ import annotations

from research_layer.api.controllers._state_store import ResearchApiStateStore


class RouteChallengeService:
    _ACTIVE_CONFLICT_STATUSES = {"needs_review", "accepted"}

    def __init__(self, store: ResearchApiStateStore) -> None:
        self._store = store

    def evaluate_route(
        self, *, workspace_id: str, route: dict[str, object]
    ) -> dict[str, object]:
        return self.evaluate_route_with_conflicts(
            workspace_id=workspace_id,
            route=route,
            conflicts=self._store.list_claim_conflicts(workspace_id=workspace_id),
        )

    def build_conflict_index(
        self,
        *,
        workspace_id: str,
        conflicts: list[dict[str, object]],
    ) -> dict[str, list[dict[str, object]]]:
        conflict_index: dict[str, list[dict[str, object]]] = {}
        for conflict in conflicts:
            if str(conflict.get("workspace_id") or "") != workspace_id:
                continue
            status = str(conflict.get("status") or "")
            if status not in self._ACTIVE_CONFLICT_STATUSES:
                continue
            for field in ("new_claim_id", "existing_claim_id"):
                claim_id = str(conflict.get(field) or "").strip()
                if claim_id:
                    conflict_index.setdefault(claim_id, []).append(conflict)
        return conflict_index

    def evaluate_route_with_conflict_index(
        self,
        *,
        route: dict[str, object],
        conflict_index: dict[str, list[dict[str, object]]],
    ) -> dict[str, object]:
        claim_ids: list[str] = []
        seen_claim_ids: set[str] = set()
        for claim_id in route.get("claim_ids", []):
            clean = str(claim_id).strip()
            if clean and clean not in seen_claim_ids:
                seen_claim_ids.add(clean)
                claim_ids.append(clean)
        if not claim_ids:
            return self._clean_result()

        active_conflicts: list[dict[str, object]] = []
        seen_conflict_ids: set[str] = set()
        for claim_id in claim_ids:
            for conflict in conflict_index.get(claim_id, []):
                conflict_id = str(conflict.get("conflict_id") or "")
                if conflict_id in seen_conflict_ids:
                    continue
                seen_conflict_ids.add(conflict_id)
                active_conflicts.append(conflict)
        return self._evaluate_active_conflicts(active_conflicts)

    def evaluate_route_with_conflicts(
        self,
        *,
        workspace_id: str,
        route: dict[str, object],
        conflicts: list[dict[str, object]],
    ) -> dict[str, object]:
        claim_ids = {
            str(claim_id).strip()
            for claim_id in route.get("claim_ids", [])
            if str(claim_id).strip()
        }
        if not claim_ids:
            return self._clean_result()

        active_conflicts: list[dict[str, object]] = []
        for conflict in conflicts:
            if str(conflict.get("workspace_id") or "") != workspace_id:
                continue
            status = str(conflict.get("status") or "")
            if status not in self._ACTIVE_CONFLICT_STATUSES:
                continue
            if (
                str(conflict.get("new_claim_id") or "") in claim_ids
                or str(conflict.get("existing_claim_id") or "") in claim_ids
            ):
                active_conflicts.append(conflict)
        return self._evaluate_active_conflicts(active_conflicts)

    def _evaluate_active_conflicts(
        self, active_conflicts: list[dict[str, object]]
    ) -> dict[str, object]:
        conflict_ids = [str(conflict["conflict_id"]) for conflict in active_conflicts]
        if any(
            str(conflict.get("status")) == "needs_review"
            for conflict in active_conflicts
        ):
            challenge_status = "needs_review"
        elif active_conflicts:
            challenge_status = "weakened"
        else:
            challenge_status = "clean"

        return {
            "challenge_status": challenge_status,
            "conflict_count": len(conflict_ids),
            "conflict_ids": conflict_ids,
        }

    def _clean_result(self) -> dict[str, object]:
        return {
            "challenge_status": "clean",
            "conflict_count": 0,
            "conflict_ids": [],
        }
