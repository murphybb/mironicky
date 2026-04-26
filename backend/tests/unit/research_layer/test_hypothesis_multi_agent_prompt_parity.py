from __future__ import annotations

from pathlib import Path

import pytest


PROMPT_DIR = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "research_layer"
    / "prompts"
    / "hypothesis_multi_agent"
)


REQUIRED_PROMPT_PHRASES = {
    "generation": [
        "source_id",
        "source_span",
        "evidence_refs",
        "evidence_packets",
        "reasoning chain",
        "what would falsify",
        "insufficient evidence",
        "conservative",
        "adjacent",
        "speculative",
    ],
    "reflection": [
        "initial_review",
        "literature_grounding_review",
        "deep_assumption_verification",
        "simulation_or_counterexample_review",
        "evidence_packets",
        "fatal",
        "fixable",
        "non-fundamental",
    ],
    "supervisor": [
        "top-level decision",
        "evidence_packets",
        "continue",
        "retrieve",
        "evolve",
        "pause",
        "stop",
        "finalize",
        "decision_rationale",
        "retrieval_intent",
        "user_control_state",
    ],
    "ranking": [
        "debate_transcript",
        "criterion_scores",
        "loser_failure_modes",
        "match_scheduling_reason",
        "confidence_in_judgment",
        "elo_delta",
    ],
    "evolution": [
        "grounding",
        "feasibility",
        "combination",
        "simplification",
        "out_of_box",
        "lineage",
    ],
    "meta_review": [
        "generation_feedback",
        "reflection_feedback",
        "ranking_feedback",
        "research_overview",
        "stop_or_continue_rationale",
    ],
}


def _prompt_text(prompt_name: str) -> str:
    return (PROMPT_DIR / f"{prompt_name}.txt").read_text(encoding="utf-8").lower()


@pytest.mark.parametrize("prompt_name", REQUIRED_PROMPT_PHRASES)
def test_hypothesis_multi_agent_prompt_matches_reference_baseline(
    prompt_name: str,
) -> None:
    text = _prompt_text(prompt_name)
    missing = [
        phrase
        for phrase in REQUIRED_PROMPT_PHRASES[prompt_name]
        if phrase.lower() not in text
    ]

    assert not missing, (
        f"{prompt_name}.txt is missing required reference-baseline phrases: "
        f"{', '.join(missing)}"
    )


def test_ranking_prompt_matches_debate_grade_contract() -> None:
    text = _prompt_text("ranking")

    for field in [
        "winner_candidate_id",
        "match_reason",
        "debate_transcript",
        "loser_failure_modes",
        "criterion_scores",
        "confidence_in_judgment",
        "match_scheduling_reason",
        "elo_delta",
    ]:
        assert field in text
    for field in [
        "evidence_strength",
        "novelty",
        "testability",
        "mechanism_specificity",
        "validation_cost",
        "contradiction_risk",
    ]:
        assert field in text
    assert "put debate_transcript" not in text
    assert "inside compare_vector" not in text
    assert "less unsafe" not in text
    assert "do not output an unsupported no_decision token" not in text


def test_reflection_prompt_requires_staged_sections_as_output_schema() -> None:
    text = _prompt_text("reflection")

    assert "overall_verdict" in text
    assert "top-level staged sections" in text
    assert "matching output_schema" in text
    assert "current output_schema exposes flat fields" not in text
    assert "compress their findings into the current flat fields" not in text
    assert "do not output top-level initial_review" not in text
    for field in [
        "initial_review",
        "literature_grounding_review",
        "deep_assumption_verification",
        "simulation_or_counterexample_review",
        "targeted_node_refs",
    ]:
        assert field in text


def test_supervisor_prompt_advertises_runtime_decision_branches() -> None:
    text = _prompt_text("supervisor")

    assert "continue | retrieve | evolve | pause | stop | finalize" in text
    assert "retrieve, evolve, and pause are control intents" not in text
    assert "current output_schema supports top-level decision values continue | stop | finalize only" not in text
    assert "do not put retrieve in decision or next_actions" not in text


def test_evolution_prompt_requires_task7_lineage_contract() -> None:
    text = _prompt_text("evolution")

    assert "grounding | feasibility | combination | simplification | out_of_box" in text
    assert "parent_weaknesses" in text
    assert "parent ids" in text
    assert "re-enter reflection and ranking" in text
    assert "llm_evolution" not in text
    assert '"mode"' not in text
    assert "lineage mode" not in text
