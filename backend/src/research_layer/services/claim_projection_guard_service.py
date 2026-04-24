from __future__ import annotations

from dataclasses import dataclass

from research_layer.api.controllers._state_store import ResearchApiStateStore


@dataclass(frozen=True)
class ClaimProjectionGuardError(Exception):
    status_code: int
    reason: str
    message: str
    details: dict[str, object]


class ClaimProjectionGuardService:
    def __init__(self, store: ResearchApiStateStore) -> None:
        self._store = store

    def require_claim(
        self,
        *,
        workspace_id: str,
        claim_id: str | None,
    ) -> dict[str, object]:
        normalized_claim_id = str(claim_id or "").strip()
        if not normalized_claim_id:
            raise ClaimProjectionGuardError(
                status_code=400,
                reason="missing_claim_id",
                message="graph projection requires claim_id",
                details={"workspace_id": workspace_id},
            )
        claim = self._store.get_claim(normalized_claim_id)
        if claim is None:
            raise ClaimProjectionGuardError(
                status_code=400,
                reason="claim_not_found",
                message="claim_id does not exist",
                details={"workspace_id": workspace_id, "claim_id": normalized_claim_id},
            )
        if str(claim["workspace_id"]) != workspace_id:
            raise ClaimProjectionGuardError(
                status_code=400,
                reason="claim_workspace_mismatch",
                message="claim_id belongs to a different workspace",
                details={
                    "workspace_id": workspace_id,
                    "claim_id": normalized_claim_id,
                    "claim_workspace_id": claim["workspace_id"],
                },
            )
        return claim
