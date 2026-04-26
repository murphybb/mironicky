from __future__ import annotations

from research_layer.services.hypothesis_agents.base import HypothesisAgentBase


class GenerationAgent(HypothesisAgentBase):
    role_name = "generation"
    prompt_file = "generation.txt"
    prompt_source = "code-derived"

    def propose_candidate(
        self,
        *,
        workspace_id: str,
        research_goal: str,
        trigger_refs: list[dict[str, object]],
        seed_index: int,
        supervisor_plan: dict[str, object],
    ) -> dict[str, object]:
        self._raise_llm_gateway_only()
