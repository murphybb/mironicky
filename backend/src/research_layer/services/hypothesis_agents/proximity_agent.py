from __future__ import annotations

from research_layer.services.hypothesis_agents.base import HypothesisAgentBase


class ProximityAgent(HypothesisAgentBase):
    role_name = "proximity"
    prompt_file = "proximity.txt"
    prompt_source = "reconstructed-from-paper"

    def build_edges(
        self,
        *,
        candidates: list[dict[str, object]],
        top_n: int = 12,
    ) -> dict[str, object]:
        rendered_prompt = self._render_prompt(
            {
                "candidate_count": len(candidates),
                "top_n": top_n,
            }
        )
        edges: list[dict[str, object]] = []
        for index, left in enumerate(candidates):
            for right in candidates[index + 1 :]:
                left_statement = str(left.get("statement", ""))
                right_statement = str(right.get("statement", ""))
                similarity = self._jaccard_similarity(left_statement, right_statement)
                distance = round(1.0 - similarity, 4)
                edges.append(
                    {
                        "left_candidate_id": str(left.get("candidate_id", "")),
                        "right_candidate_id": str(right.get("candidate_id", "")),
                        "distance": distance,
                        "reason": "statement token distance",
                    }
                )
        edges.sort(key=lambda item: float(item["distance"]))
        return {
            **self._base_output(rendered_prompt=rendered_prompt),
            "edges": edges[: max(1, top_n)],
        }
