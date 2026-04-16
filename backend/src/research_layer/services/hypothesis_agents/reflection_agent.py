from __future__ import annotations

from research_layer.services.hypothesis_agents.base import HypothesisAgentBase


class ReflectionAgent(HypothesisAgentBase):
    role_name = "reflection"
    prompt_file = "reflection.txt"
    prompt_source = "reconstructed-from-paper"

    def reflect_candidate(
        self,
        *,
        candidate: dict[str, object],
        round_number: int,
    ) -> dict[str, object]:
        title = str(candidate.get("title", "")).strip()
        statement = str(candidate.get("statement", "")).strip()
        next_steps = candidate.get("suggested_next_steps")
        steps = [str(item).strip() for item in next_steps or [] if str(item).strip()]
        confidence = float(candidate.get("confidence_hint") or 0.0)
        rendered_prompt = self._render_prompt(
            {
                "candidate_id": str(candidate.get("candidate_id", "")),
                "round_number": round_number,
                "candidate_json": str(candidate),
            }
        )
        weaknesses: list[str] = []
        if len(statement) < 120:
            weaknesses.append("statement is short and may hide causal assumptions")
        if not steps:
            weaknesses.append("no concrete next steps")
        strengths = [
            "candidate is linked to explicit trigger refs",
            "statement remains testable under constrained validation",
        ]
        if confidence >= 0.7:
            strengths.append("confidence estimate is internally consistent")
        action_items = [
            "name one confounder and mitigation",
            "bind hypothesis to measurable validation metric",
        ]
        score_delta = 0.05 if not weaknesses else -0.04 * len(weaknesses)
        return {
            **self._base_output(rendered_prompt=rendered_prompt),
            "candidate_id": str(candidate.get("candidate_id", "")),
            "reflection": {
                "strengths": strengths,
                "weaknesses": weaknesses,
                "action_items": action_items,
                "score_delta": round(score_delta, 3),
                "round_number": round_number,
                "title_snapshot": title,
            },
        }
