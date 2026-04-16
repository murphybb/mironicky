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
        rendered_prompt = self._render_prompt(
            {
                "pool_id": pool_id,
                "round_number": round_number,
                "parent_candidates_json": str(parent_candidates),
                "target_children": target_children,
            }
        )
        if not parent_candidates:
            return {
                **self._base_output(rendered_prompt=rendered_prompt),
                "children": [],
                "notes": ["no parent candidates available for evolution"],
            }
        children: list[dict[str, object]] = []
        max_children = max(1, target_children)
        for index in range(max_children):
            left = parent_candidates[index % len(parent_candidates)]
            right = parent_candidates[(index + 1) % len(parent_candidates)]
            left_statement = str(left.get("statement", "")).strip()
            right_statement = str(right.get("statement", "")).strip()
            child_statement = (
                f"{left_statement} Additionally, cross-check against: {right_statement}"
            )
            children.append(
                {
                    "title": f"Evolved hypothesis {round_number}.{index + 1}",
                    "statement": child_statement[:900],
                    "summary": "Mutation + crossover from high-Elo parents.",
                    "rationale": (
                        "Evolution combines top-ranked assumptions to preserve strong "
                        "signals while introducing broader causal coverage."
                    ),
                    "testability_hint": (
                        "A/B validate against at least one parent baseline and one "
                        "combined outcome metric."
                    ),
                    "novelty_hint": "lineage-derived crossover with targeted mutation",
                    "confidence_hint": round(
                        min(
                            0.88,
                            (
                                float(left.get("confidence_hint") or 0.5)
                                + float(right.get("confidence_hint") or 0.5)
                            )
                            / 2.0
                            + 0.03,
                        ),
                        2,
                    ),
                    "suggested_next_steps": [
                        "run validation on parent and child in parallel",
                        "capture divergence and explanatory gain",
                    ],
                    "lineage": {
                        "parents": [
                            str(left.get("candidate_id", "")),
                            str(right.get("candidate_id", "")),
                        ],
                        "mode": "crossover+mutation",
                    },
                }
            )
        return {
            **self._base_output(rendered_prompt=rendered_prompt),
            "children": children,
            "notes": ["kept evolution deterministic for stable orchestration tests"],
        }
