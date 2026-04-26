from __future__ import annotations

from research_layer.services.hypothesis_agents.base import HypothesisAgentBase


class ReflectionAgent(HypothesisAgentBase):
    role_name = "reflection"
    prompt_file = "reflection.txt"
    prompt_source = "reconstructed-from-paper"

    def reflect_candidate(
        self, *, candidate: dict[str, object], round_number: int
    ) -> dict[str, object]:
        self._raise_llm_gateway_only()
