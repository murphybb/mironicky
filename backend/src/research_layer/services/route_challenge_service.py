from __future__ import annotations

from research_layer.api.controllers._state_store import ResearchApiStateStore


class RouteChallengeService:
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
            return {
                "challenge_status": "clean",
                "conflict_count": 0,
                "conflict_ids": [],
            }

        active_conflicts: list[dict[str, object]] = []
        for conflict in conflicts:
            if str(conflict.get("workspace_id") or "") != workspace_id:
                continue
            status = str(conflict.get("status") or "")
            if status not in {"needs_review", "accepted"}:
                continue
            if (
                str(conflict.get("new_claim_id") or "") in claim_ids
                or str(conflict.get("existing_claim_id") or "") in claim_ids
            ):
                active_conflicts.append(conflict)

        conflict_ids = [str(conflict["conflict_id"]) for conflict in active_conflicts]
        if any(str(conflict.get("status")) == "needs_review" for conflict in active_conflicts):
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
