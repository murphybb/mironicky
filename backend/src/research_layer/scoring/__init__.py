"""Research scoring package."""

from research_layer.scoring.explainer import (
    build_factor_explanation,
    build_node_score_breakdown,
    select_top_factors,
)
from research_layer.scoring.heuristics import FactorInput, build_factor_inputs, clamp01
from research_layer.scoring.templates import (
    DEFAULT_TEMPLATE,
    FACTOR_ORDER_BY_DIMENSION,
    PROGRESSABILITY_DIMENSION,
    RISK_DIMENSION,
    ScoringTemplate,
    SUPPORT_DIMENSION,
    TOP_FACTOR_TIE_BREAK_ORDER,
    resolve_scoring_template,
    validate_template_contract,
)

__all__ = [
    "FactorInput",
    "ScoringTemplate",
    "DEFAULT_TEMPLATE",
    "SUPPORT_DIMENSION",
    "RISK_DIMENSION",
    "PROGRESSABILITY_DIMENSION",
    "FACTOR_ORDER_BY_DIMENSION",
    "TOP_FACTOR_TIE_BREAK_ORDER",
    "clamp01",
    "build_factor_inputs",
    "build_factor_explanation",
    "build_node_score_breakdown",
    "select_top_factors",
    "resolve_scoring_template",
    "validate_template_contract",
]
