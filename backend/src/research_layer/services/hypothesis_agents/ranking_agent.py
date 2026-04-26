from __future__ import annotations

from research_layer.services.hypothesis_agents.base import HypothesisAgentBase


class RankingAgent(HypothesisAgentBase):
    role_name = "ranking"
    prompt_file = "ranking.txt"
    prompt_source = "published"

    def compare_pair(
        self, *, left_candidate: dict[str, object], right_candidate: dict[str, object]
    ) -> dict[str, object]:
        self._raise_llm_gateway_only()

    def _score_candidate(self, candidate: dict[str, object]) -> float:
        self._raise_llm_gateway_only()
