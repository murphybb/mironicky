from __future__ import annotations


def _as_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class RouteRanker:
    def rank_routes(self, routes: list[dict[str, object]]) -> list[dict[str, object]]:
        return sorted(routes, key=self._sort_key)

    def _sort_key(
        self, route: dict[str, object]
    ) -> tuple[float, float, float, float, float, str]:
        confidence_score = route.get("confidence_score")
        if confidence_score is None:
            support_score = _as_float(route.get("support_score"), 0.0)
            risk_score = _as_float(route.get("risk_score"), 100.0)
            progressability_score = _as_float(route.get("progressability_score"), 0.0)
            confidence_score = round(
                (support_score + (100.0 - risk_score) + progressability_score) / 3.0,
                1,
            )
        return (
            -_as_float(confidence_score, 0.0),
            -_as_float(route.get("support_score"), 0.0),
            _as_float(route.get("risk_score"), 100.0),
            -_as_float(route.get("progressability_score"), 0.0),
            self._private_dependency_pressure(route),
            str(route.get("route_id", "")),
        )

    def _private_dependency_pressure(self, route: dict[str, object]) -> float:
        score_breakdown = route.get("score_breakdown")
        breakdown_dict = score_breakdown if isinstance(score_breakdown, dict) else {}
        risk_dimension = breakdown_dict.get("risk_score")
        risk_dict = risk_dimension if isinstance(risk_dimension, dict) else {}
        factors_raw = risk_dict.get("factors")
        factors = factors_raw if isinstance(factors_raw, list) else []
        for factor in factors:
            if not isinstance(factor, dict):
                continue
            if str(factor.get("factor_name", "")) == "private_dependency_pressure":
                return _as_float(factor.get("normalized_value"), 1.0)
        return 1.0
