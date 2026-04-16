from __future__ import annotations

import json

from research_layer.services.hypothesis_agents.base import HypothesisAgentBase


class SupervisorAgent(HypothesisAgentBase):
    role_name = "supervisor"
    prompt_file = "supervisor.txt"
    prompt_source = "reconstructed-from-paper"

    def should_stop(
        self,
        *,
        round_number: int,
        max_rounds: int,
        alive_count: int,
        top_k: int,
    ) -> tuple[bool, str]:
        if round_number >= max_rounds:
            return True, "max_rounds_reached"
        if alive_count <= max(top_k, 1):
            return True, "alive_candidates_converged"
        return False, "continue"

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
        trigger_types = sorted(
            {
                str(item.get("trigger_type", "")).strip()
                for item in trigger_refs
                if isinstance(item, dict) and str(item.get("trigger_type", "")).strip()
            }
        )
        rendered_prompt = self._render_prompt(
            {
                "workspace_id": workspace_id,
                "research_goal": research_goal,
                "trigger_refs": trigger_refs,
                "trigger_types": trigger_types,
                "top_k": top_k,
                "max_rounds": max_rounds,
                "candidate_count": candidate_count,
                "constraints": constraints,
                "constraints_json": json.dumps(
                    constraints, ensure_ascii=False, default=str
                ),
                "preference_profile": preference_profile,
                "preference_profile_json": json.dumps(
                    preference_profile, ensure_ascii=False, default=str
                ),
            }
        )
        return {
            "strategy": "elo_tournament_plus_mcts",
            "round_budget": int(max_rounds),
            "candidate_budget": int(candidate_count),
            "top_k": int(top_k),
            "constraints": dict(constraints),
            "preference_profile": dict(preference_profile),
            "rendered_prompt": rendered_prompt,
        }

    def plan_pairs(
        self,
        *,
        alive_candidates: list[dict[str, object]],
        max_matches: int,
    ) -> list[tuple[str, str]]:
        ordered = sorted(
            alive_candidates,
            key=lambda item: (
                -float(item.get("elo_rating", 0.0)),
                str(item.get("candidate_id", "")),
            ),
        )
        pairs: list[tuple[str, str]] = []
        idx = 0
        while idx + 1 < len(ordered) and len(pairs) < max_matches:
            pairs.append(
                (
                    str(ordered[idx]["candidate_id"]),
                    str(ordered[idx + 1]["candidate_id"]),
                )
            )
            idx += 2
        return pairs
