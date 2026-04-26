from __future__ import annotations

from research_layer.services.hypothesis_agents.base import HypothesisAgentBase


class ProximityAgent(HypothesisAgentBase):
    """Deterministic candidate similarity service; not an LLM agent."""

    role_name = "similarity_service"
    prompt_file = "proximity.txt"
    prompt_source = "reconstructed-from-paper"

    def build_edges(
        self, *, candidates: list[dict[str, object]], top_n: int = 12
    ) -> dict[str, object]:
        rendered_prompt = self._render_prompt(
            {"candidate_count": len(candidates), "top_n": top_n}
        )
        edges: list[dict[str, object]] = []
        for index, left in enumerate(candidates):
            for right in candidates[index + 1 :]:
                edges.append(self.build_edge(left=left, right=right))
        edges.sort(
            key=lambda item: (
                float(item["source_overlap"]),
                float(item["validation_path_similarity"]),
                float(item["semantic_similarity"]),
                -float(item["distance"]),
            )
        )
        return {
            **self._base_output(rendered_prompt=rendered_prompt),
            "edges": edges[: max(1, top_n)],
        }

    def build_edge(
        self, *, left: dict[str, object], right: dict[str, object]
    ) -> dict[str, object]:
        left_statement = str(left.get("statement", ""))
        right_statement = str(right.get("statement", ""))
        semantic_similarity = round(
            self._jaccard_similarity(left_statement, right_statement), 4
        )
        source_overlap = round(
            self._jaccard_similarity(
                " ".join(self._source_ids(left)), " ".join(self._source_ids(right))
            ),
            4,
        )
        validation_path_similarity = round(
            self._jaccard_similarity(
                self._validation_path(left), self._validation_path(right)
            ),
            4,
        )
        mechanism_signature = self.mechanism_signature(left)
        right_mechanism_signature = self.mechanism_signature(right)
        same_mechanism = mechanism_signature == right_mechanism_signature
        same_validation = self._validation_path(left) == self._validation_path(right)
        frontier_exclusion_reason = ""
        if same_mechanism and source_overlap > 0.6 and same_validation:
            frontier_exclusion_reason = (
                "same mechanism signature, source overlap > 0.6, and same validation path"
            )
        distance = round(
            1.0
            - (
                0.5 * semantic_similarity
                + 0.3 * source_overlap
                + 0.2 * validation_path_similarity
            ),
            4,
        )
        return {
            "from_candidate_id": str(left.get("candidate_id", "")),
            "to_candidate_id": str(right.get("candidate_id", "")),
            "similarity_score": semantic_similarity,
            "shared_trigger_ratio": source_overlap,
            "shared_object_ratio": source_overlap,
            "shared_chain_overlap": max(semantic_similarity, validation_path_similarity),
            "reason": "low-overlap proximity service trace",
            "distance": distance,
            "service_name": "proximity",
            "mechanism_signature": mechanism_signature,
            "right_mechanism_signature": right_mechanism_signature,
            "source_overlap": source_overlap,
            "validation_path_similarity": validation_path_similarity,
            "semantic_similarity": semantic_similarity,
            "pairing_reason": (
                "prefer low source and validation overlap to maximize comparative signal"
            ),
            "frontier_exclusion_reason": frontier_exclusion_reason,
        }

    def mechanism_signature(self, candidate: dict[str, object]) -> str:
        chain = candidate.get("reasoning_chain")
        nested = chain.get("reasoning_chain") if isinstance(chain, dict) else {}
        text = " ".join(
            [
                str(candidate.get("statement") or ""),
                str((nested or {}).get("assumption") or ""),
                str((nested or {}).get("conclusion") or ""),
            ]
        ).lower()
        tokens = [
            token.strip(".,;:()[]{}")
            for token in text.split()
            if len(token.strip(".,;:()[]{}")) > 4
        ]
        return "-".join(sorted(set(tokens))[:6]) or "unspecified"

    def validation_path(self, candidate: dict[str, object]) -> str:
        return self._validation_path(candidate)

    def source_ids(self, candidate: dict[str, object]) -> list[str]:
        return self._source_ids(candidate)

    def _source_ids(self, candidate: dict[str, object]) -> list[str]:
        chain = candidate.get("reasoning_chain")
        refs = chain.get("source_refs") if isinstance(chain, dict) else []
        if not isinstance(refs, list):
            refs = []
        return sorted(
            {
                str(item.get("source_id") or "").strip()
                for item in refs
                if isinstance(item, dict) and str(item.get("source_id") or "").strip()
            }
        )

    def _validation_path(self, candidate: dict[str, object]) -> str:
        chain = candidate.get("reasoning_chain")
        nested = chain.get("reasoning_chain") if isinstance(chain, dict) else {}
        value = ""
        if isinstance(nested, dict):
            value = str(nested.get("validation_need") or "")
        if not value and isinstance(chain, dict):
            value = str(chain.get("required_validation") or "")
        return " ".join(value.lower().split())
