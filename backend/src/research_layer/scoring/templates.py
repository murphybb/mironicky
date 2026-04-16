from __future__ import annotations

from dataclasses import dataclass

SUPPORT_DIMENSION = "support_score"
RISK_DIMENSION = "risk_score"
PROGRESSABILITY_DIMENSION = "progressability_score"

FACTOR_ORDER_BY_DIMENSION: dict[str, tuple[str, ...]] = {
    SUPPORT_DIMENSION: (
        "confirmed_evidence_coverage",
        "evidence_quality",
        "cross_source_consistency",
        "validation_backing",
        "traceability_completeness",
    ),
    RISK_DIMENSION: (
        "unresolved_conflict_pressure",
        "failure_pressure",
        "assumption_burden",
        "private_dependency_pressure",
        "missing_validation_pressure",
    ),
    PROGRESSABILITY_DIMENSION: (
        "next_action_clarity",
        "execution_cost_feasibility",
        "execution_time_feasibility",
        "expected_signal_strength",
        "dependency_readiness",
    ),
}

TOP_FACTOR_TIE_BREAK_ORDER: tuple[str, ...] = (
    "confirmed_evidence_coverage",
    "unresolved_conflict_pressure",
    "failure_pressure",
    "next_action_clarity",
    "evidence_quality",
    "cross_source_consistency",
    "validation_backing",
    "assumption_burden",
    "private_dependency_pressure",
    "missing_validation_pressure",
    "execution_cost_feasibility",
    "execution_time_feasibility",
    "expected_signal_strength",
    "dependency_readiness",
    "traceability_completeness",
)


@dataclass(frozen=True, slots=True)
class ScoringTemplate:
    template_id: str
    weights: dict[str, dict[str, float]]


DEFAULT_TEMPLATE = ScoringTemplate(
    template_id="general_research_v1",
    weights={
        SUPPORT_DIMENSION: {
            "confirmed_evidence_coverage": 0.30,
            "evidence_quality": 0.25,
            "cross_source_consistency": 0.20,
            "validation_backing": 0.15,
            "traceability_completeness": 0.10,
        },
        RISK_DIMENSION: {
            "unresolved_conflict_pressure": 0.30,
            "failure_pressure": 0.25,
            "assumption_burden": 0.20,
            "private_dependency_pressure": 0.15,
            "missing_validation_pressure": 0.10,
        },
        PROGRESSABILITY_DIMENSION: {
            "next_action_clarity": 0.30,
            "execution_cost_feasibility": 0.20,
            "execution_time_feasibility": 0.15,
            "expected_signal_strength": 0.20,
            "dependency_readiness": 0.15,
        },
    },
)

VALIDATION_HEAVY_TEMPLATE = ScoringTemplate(
    template_id="validation_heavy_v1",
    weights={
        SUPPORT_DIMENSION: {
            "confirmed_evidence_coverage": 0.25,
            "evidence_quality": 0.20,
            "cross_source_consistency": 0.20,
            "validation_backing": 0.25,
            "traceability_completeness": 0.10,
        },
        RISK_DIMENSION: {
            "unresolved_conflict_pressure": 0.25,
            "failure_pressure": 0.20,
            "assumption_burden": 0.20,
            "private_dependency_pressure": 0.15,
            "missing_validation_pressure": 0.20,
        },
        PROGRESSABILITY_DIMENSION: {
            "next_action_clarity": 0.25,
            "execution_cost_feasibility": 0.20,
            "execution_time_feasibility": 0.15,
            "expected_signal_strength": 0.25,
            "dependency_readiness": 0.15,
        },
    },
)

TEMPLATES: dict[str, ScoringTemplate] = {
    DEFAULT_TEMPLATE.template_id: DEFAULT_TEMPLATE,
    VALIDATION_HEAVY_TEMPLATE.template_id: VALIDATION_HEAVY_TEMPLATE,
}


def resolve_scoring_template(
    *,
    template_id: str | None,
    relation_tags: list[str] | None,
) -> ScoringTemplate:
    if template_id:
        selected = TEMPLATES.get(template_id)
        if selected is None:
            raise ValueError(f"unknown scoring template: {template_id}")
        return selected

    tags = set(relation_tags or [])
    if "validation_heavy" in tags:
        return VALIDATION_HEAVY_TEMPLATE
    return DEFAULT_TEMPLATE


def validate_template_contract(template: ScoringTemplate) -> None:
    for dimension, ordered_factors in FACTOR_ORDER_BY_DIMENSION.items():
        weights = template.weights.get(dimension)
        if weights is None:
            raise ValueError(f"missing weights for dimension: {dimension}")
        unknown_factors = set(weights) - set(ordered_factors)
        if unknown_factors:
            factor_name = sorted(unknown_factors)[0]
            raise ValueError(f"unsupported factor in template: {factor_name}")
        total_weight = 0.0
        for factor_name in ordered_factors:
            weight = float(weights.get(factor_name, 0.0))
            if weight < 0.0:
                raise ValueError(f"negative weight for factor: {factor_name}")
            total_weight += weight
        if abs(total_weight - 1.0) > 1e-6:
            raise ValueError(f"weights must sum to 1.0 for dimension: {dimension}")
