from __future__ import annotations

from research_layer.services.hypothesis_agents.base import HypothesisAgentBase


class MetaReviewAgent(HypothesisAgentBase):
    role_name = "meta_review"
    prompt_file = "meta_review.txt"
    prompt_source = "local-design"

    def review_round(
        self,
        *,
        pool_id: str,
        round_number: int,
        candidates: list[dict[str, object]],
        matches: list[dict[str, object]],
        evolution_count: int,
    ) -> dict[str, object]:
        rendered_prompt = self._render_prompt(
            {
                "pool_id": pool_id,
                "round_number": round_number,
                "candidate_count": len(candidates),
                "match_count": len(matches),
                "evolution_count": evolution_count,
            }
        )
        sorted_candidates = sorted(
            candidates,
            key=lambda item: float(item.get("elo_rating") or 0.0),
            reverse=True,
        )
        top_ids = [str(item.get("candidate_id", "")) for item in sorted_candidates[:3]]
        prune_ids = [str(item.get("candidate_id", "")) for item in sorted_candidates[-2:]]
        return {
            **self._base_output(rendered_prompt=rendered_prompt),
            "round_number": round_number,
            "summary": (
                f"Round {round_number} processed {len(candidates)} candidates, "
                f"{len(matches)} matches and {evolution_count} evolved children."
            ),
            "strengths": [
                "Elo dynamics provided stable ranking signal",
                "single-pass reflection surfaced weak assumptions before ranking",
            ],
            "risks": [
                "candidate diversity may collapse if same trigger dominates",
                "few matches can overfit Elo to early pairings",
            ],
            "prune_recommendations": prune_ids,
            "next_focus": [
                "expand validation-oriented descendants from top nodes",
                "increase cross-trigger pairing in next round",
            ],
            "top_candidate_ids": top_ids,
        }
