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
        self._raise_llm_gateway_only()
