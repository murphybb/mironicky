from __future__ import annotations

from research_layer.services.hypothesis_agents.base import HypothesisAgentBase


class RankingAgent(HypothesisAgentBase):
    role_name = "ranking"
    prompt_file = "ranking.txt"
    prompt_source = "published"

    def compare_pair(
        self,
        *,
        left_candidate: dict[str, object],
        right_candidate: dict[str, object],
    ) -> dict[str, object]:
        rendered_prompt = self._render_prompt(
            {
                "left_candidate_json": str(left_candidate),
                "right_candidate_json": str(right_candidate),
            }
        )

        left_score = self._score_candidate(left_candidate)
        right_score = self._score_candidate(right_candidate)
        if left_score >= right_score:
            winner_id = str(left_candidate.get("candidate_id", ""))
            loser_id = str(right_candidate.get("candidate_id", ""))
        else:
            winner_id = str(right_candidate.get("candidate_id", ""))
            loser_id = str(left_candidate.get("candidate_id", ""))

        return {
            **self._base_output(rendered_prompt=rendered_prompt),
            "left_candidate_id": str(left_candidate.get("candidate_id", "")),
            "right_candidate_id": str(right_candidate.get("candidate_id", "")),
            "winner_candidate_id": winner_id,
            "loser_candidate_id": loser_id,
            "match_reason": "higher aggregate score on novelty/testability/clarity",
            "compare_vector": {
                "left_score": round(left_score, 4),
                "right_score": round(right_score, 4),
                "left_novelty_overlap": round(
                    self._jaccard_similarity(
                        str(left_candidate.get("novelty_hint", "")),
                        str(left_candidate.get("statement", "")),
                    ),
                    4,
                ),
                "right_novelty_overlap": round(
                    self._jaccard_similarity(
                        str(right_candidate.get("novelty_hint", "")),
                        str(right_candidate.get("statement", "")),
                    ),
                    4,
                ),
            },
        }

    def _score_candidate(self, candidate: dict[str, object]) -> float:
        confidence = float(candidate.get("confidence_hint") or 0.0)
        elo = float(candidate.get("elo_rating") or 1200.0)
        next_steps_raw = candidate.get("suggested_next_steps")
        next_steps = [
            str(item).strip()
            for item in (next_steps_raw if isinstance(next_steps_raw, list) else [])
            if str(item).strip()
        ]
        reflection = candidate.get("last_reflection", {})
        score_delta = 0.0
        if isinstance(reflection, dict):
            score_delta = float(reflection.get("score_delta") or 0.0)
        clarity = min(1.0, len(str(candidate.get("statement", ""))) / 260.0)
        return (
            confidence * 0.45
            + (elo / 1500.0) * 0.25
            + min(1.0, len(next_steps) / 4.0) * 0.2
            + clarity * 0.1
            + score_delta
        )
