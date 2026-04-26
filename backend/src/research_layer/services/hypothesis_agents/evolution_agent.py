from __future__ import annotations

from research_layer.services.hypothesis_agents.base import HypothesisAgentBase


class EvolutionAgent(HypothesisAgentBase):
    role_name = "evolution"
    prompt_file = "evolution.txt"
    prompt_source = "code-derived"

    def evolve_candidates(
        self,
        *,
        pool_id: str,
        round_number: int,
        parent_candidates: list[dict[str, object]],
        target_children: int,
    ) -> dict[str, object]:
        self._raise_llm_gateway_only()
