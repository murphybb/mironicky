from __future__ import annotations

from research_layer.services.hypothesis_agents.base import HypothesisAgentBase


class SupervisorAgent(HypothesisAgentBase):
    role_name = "supervisor"
    prompt_file = "supervisor.txt"
    prompt_source = "reconstructed-from-paper"

    def should_stop(
        self, *, round_number: int, max_rounds: int, alive_count: int, top_k: int
    ) -> tuple[bool, str]:
        self._raise_llm_gateway_only()

    def build_pool_plan(
        self,
        *,
        workspace_id: str,
        research_goal: str,
        trigger_refs: list[dict[str, object]],
        top_k: int,
        max_rounds: int,
        candidate_count: int,
        constraints: dict[str, object],
        preference_profile: dict[str, object],
    ) -> dict[str, object]:
        self._raise_llm_gateway_only()

    def plan_pairs(
        self, *, alive_candidates: list[dict[str, object]], max_matches: int
    ) -> list[tuple[str, str]]:
        self._raise_llm_gateway_only()
