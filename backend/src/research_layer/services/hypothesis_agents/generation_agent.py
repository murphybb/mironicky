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
        primary = trigger_refs[seed_index % len(trigger_refs)] if trigger_refs else {}
        trigger_type = str(primary.get("trigger_type", "gap")) or "gap"
        object_ref = str(primary.get("object_ref_id", "unknown")) or "unknown"
        trigger_ids = [
            str(item.get("trigger_id", "")).strip()
            for item in trigger_refs
            if isinstance(item, dict) and str(item.get("trigger_id", "")).strip()
        ]
        rotated_ids = (
            trigger_ids[seed_index % len(trigger_ids) :] + trigger_ids[: seed_index % len(trigger_ids)]
            if trigger_ids
            else []
        )
        statement = (
            f"If trigger cluster ({', '.join(rotated_ids[:3]) or 'n/a'}) drives "
            f"{trigger_type} behavior on {object_ref}, then a targeted intervention "
            "should shift downstream validation outcomes."
        )
        rendered_prompt = self._render_prompt(
            {
                "workspace_id": workspace_id,
                "research_goal": research_goal or "(unspecified)",
                "seed_index": seed_index,
                "trigger_context_json": str(trigger_refs),
                "supervisor_plan_json": str(supervisor_plan),
            }
        )
        return {
            **self._base_output(rendered_prompt=rendered_prompt),
            "candidate": {
                "title": f"{trigger_type.title()} pathway hypothesis #{seed_index + 1}",
                "statement": statement,
                "summary": f"Probe causal pathway around {trigger_type}:{object_ref}.",
                "rationale": (
                    f"Generated from trigger mix anchored on {trigger_type}:{object_ref} "
                    f"for goal '{research_goal or 'improve hypothesis quality'}'."
                ),
                "testability_hint": (
                    f"Design one low-cost validation around object {object_ref} and compare "
                    "pre/post state transitions."
                ),
                "novelty_hint": (
                    "Cross-trigger composition with rotated anchor order to keep candidate "
                    "pool diverse."
                ),
                "confidence_hint": round(min(0.9, 0.42 + 0.06 * (seed_index % 7)), 2),
                "suggested_next_steps": [
                    "select one measurable outcome variable",
                    "run controlled validation on affected route",
                    "record uncertainty and confounders",
                ],
            },
            "reasoning": {
                "seed_index": seed_index,
                "trigger_anchor": {
                    "trigger_id": primary.get("trigger_id"),
                    "trigger_type": trigger_type,
                    "object_ref_id": object_ref,
                },
            },
        }
