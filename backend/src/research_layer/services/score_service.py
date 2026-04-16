from __future__ import annotations

from dataclasses import dataclass

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.scoring import (
    FACTOR_ORDER_BY_DIMENSION,
    build_factor_explanation,
    build_factor_inputs,
    build_node_score_breakdown,
    clamp01,
    resolve_scoring_template,
    select_top_factors,
    validate_template_contract,
)


@dataclass(slots=True)
class ScoreServiceError(Exception):
    status_code: int
    error_code: str
    message: str
    details: dict[str, object]

    def __str__(self) -> str:
        return self.message


class ScoreService:
    def __init__(self, store: ResearchApiStateStore) -> None:
        self._store = store

    def _raise(
        self,
        *,
        status_code: int,
        error_code: str,
        message: str,
        details: dict[str, object] | None = None,
    ) -> None:
        raise ScoreServiceError(
            status_code=status_code,
            error_code=error_code,
            message=message,
            details=details or {},
        )

    def _emit_failure_event(
        self,
        *,
        request_id: str,
        workspace_id: str,
        route_id: str,
        focus_node_ids: list[str] | None,
        error: ScoreServiceError,
    ) -> None:
        self._store.emit_event(
            event_name="score_recalculated",
            request_id=request_id,
            job_id=None,
            workspace_id=workspace_id,
            component="score_service",
            step="score_route",
            status="failed",
            refs={"route_id": route_id, "node_ids": focus_node_ids or []},
            error={
                "error_code": error.error_code,
                "message": error.message,
                "details": error.details,
            },
        )

    def _build_reviewer_like_critique(
        self,
        *,
        route: dict[str, object],
        main_scores: dict[str, float],
        factor_records: list[dict[str, object]],
        top_factors: list[dict[str, object]],
    ) -> tuple[dict[str, object], dict[str, str]]:
        route_id = str(route.get("route_id", ""))
        blocking_issues: list[dict[str, object]] = []
        warnings: list[dict[str, object]] = []
        suggestions: list[str] = []
        factor_notes: dict[str, str] = {}

        support_score = float(main_scores.get("support_score", 0.0))
        risk_score = float(main_scores.get("risk_score", 0.0))
        progressability_score = float(main_scores.get("progressability_score", 0.0))

        if risk_score >= 70.0:
            blocking_issues.append(
                {
                    "issue_code": "risk_score_high",
                    "severity": "blocking",
                    "message": "Risk score is too high for safe publication.",
                    "refs": {"route_id": route_id, "risk_score": risk_score},
                }
            )
            suggestions.append("Address highest-risk factors before publishing this route.")
        elif risk_score >= 55.0:
            warnings.append(
                {
                    "issue_code": "risk_score_elevated",
                    "severity": "warning",
                    "message": "Risk score is elevated and needs mitigation coverage.",
                    "refs": {"route_id": route_id, "risk_score": risk_score},
                }
            )
            suggestions.append("Add mitigation evidence for elevated risk dimensions.")

        if support_score < 35.0:
            blocking_issues.append(
                {
                    "issue_code": "support_score_low",
                    "severity": "blocking",
                    "message": "Support score is below publication baseline.",
                    "refs": {"route_id": route_id, "support_score": support_score},
                }
            )
            suggestions.append("Increase evidence and validation support before release.")
        elif support_score < 50.0:
            warnings.append(
                {
                    "issue_code": "support_score_moderate",
                    "severity": "warning",
                    "message": "Support score is moderate and may weaken confidence.",
                    "refs": {"route_id": route_id, "support_score": support_score},
                }
            )
            suggestions.append("Strengthen support factors with additional evidence.")

        if progressability_score < 35.0:
            blocking_issues.append(
                {
                    "issue_code": "progressability_score_low",
                    "severity": "blocking",
                    "message": "Progressability score indicates weak next-step feasibility.",
                    "refs": {
                        "route_id": route_id,
                        "progressability_score": progressability_score,
                    },
                }
            )
            suggestions.append("Clarify executable next validation steps for this route.")
        elif progressability_score < 50.0:
            warnings.append(
                {
                    "issue_code": "progressability_score_moderate",
                    "severity": "warning",
                    "message": "Progressability score is moderate and may stall execution.",
                    "refs": {
                        "route_id": route_id,
                        "progressability_score": progressability_score,
                    },
                }
            )

        for factor in factor_records:
            factor_name = str(factor.get("factor_name", ""))
            if not factor_name:
                continue
            score_dimension = str(factor.get("score_dimension", ""))
            status = str(factor.get("status", "computed"))
            weight = float(factor.get("weight", 0.0))
            refs = factor.get("refs")
            refs_dict = refs if isinstance(refs, dict) else {}
            if status == "missing_input":
                issue = {
                    "issue_code": f"missing_factor:{factor_name}",
                    "severity": (
                        "blocking"
                        if score_dimension in {"support_score", "progressability_score"}
                        and weight >= 0.2
                        else "warning"
                    ),
                    "message": (
                        "Scoring factor is missing required input and can reduce reliability."
                    ),
                    "refs": {
                        "route_id": route_id,
                        "factor_name": factor_name,
                        "score_dimension": score_dimension,
                        "node_ids": list(refs_dict.get("node_ids", [])),
                    },
                }
                if issue["severity"] == "blocking":
                    blocking_issues.append(issue)
                else:
                    warnings.append(issue)
                factor_notes[factor_name] = "Missing input; verify source coverage for this factor."

        for factor in top_factors:
            factor_name = str(factor.get("factor_name", ""))
            score_dimension = str(factor.get("score_dimension", ""))
            weighted_contribution = float(factor.get("weighted_contribution", 0.0))
            if score_dimension == "risk_score" and weighted_contribution >= 0.15:
                warnings.append(
                    {
                        "issue_code": f"risk_dominant_top_factor:{factor_name}",
                        "severity": "warning",
                        "message": "Top factor is risk-dominant and should be mitigated.",
                        "refs": {
                            "route_id": route_id,
                            "factor_name": factor_name,
                            "weighted_contribution": round(weighted_contribution, 6),
                        },
                    }
                )
                factor_notes[factor_name] = (
                    "Risk-dominant factor; include mitigation plan and monitoring."
                )
            elif factor_name and factor_name not in factor_notes:
                factor_notes[factor_name] = (
                    "High-impact factor; keep supporting evidence and rationale explicit."
                )

        normalized_suggestions = [
            text for text in sorted(set(suggestions)) if str(text).strip()
        ]
        if not normalized_suggestions:
            normalized_suggestions = [
                "Maintain current score drivers and keep traceability evidence up to date."
            ]

        readiness = "ready"
        if blocking_issues:
            readiness = "blocked"
        elif warnings:
            readiness = "needs_revision"

        critique = {
            "generated_by": "score_service.reviewer_like_critique.v1",
            "readiness": readiness,
            "blocking_issues": blocking_issues,
            "warnings": warnings,
            "suggestions": normalized_suggestions,
        }
        return critique, factor_notes

    def score_route(
        self,
        *,
        workspace_id: str,
        route_id: str,
        request_id: str,
        template_id: str | None = None,
        focus_node_ids: list[str] | None = None,
    ) -> dict[str, object]:
        focus_node_ids = focus_node_ids or []
        try:
            route = self._store.get_route(route_id)
            if route is None:
                self._raise(
                    status_code=404,
                    error_code="research.not_found",
                    message="route not found",
                    details={"route_id": route_id},
                )
            if str(route["workspace_id"]) != workspace_id:
                self._raise(
                    status_code=409,
                    error_code="research.conflict",
                    message="workspace_id does not match route ownership",
                    details={"route_id": route_id},
                )

            graph_nodes = self._store.list_graph_nodes(workspace_id)
            graph_edges = self._store.list_graph_edges(workspace_id)
            if not graph_nodes:
                self._raise(
                    status_code=409,
                    error_code="research.invalid_state",
                    message="graph is not ready for scoring",
                    details={"workspace_id": workspace_id},
                )
            node_id_set = {str(node["node_id"]) for node in graph_nodes}
            invalid_focus = sorted(set(focus_node_ids) - node_id_set)
            if invalid_focus:
                self._raise(
                    status_code=400,
                    error_code="research.invalid_request",
                    message="focus_node_ids contain unknown node references",
                    details={"focus_node_ids": invalid_focus},
                )
            effective_graph_nodes = graph_nodes
            effective_graph_edges = graph_edges
            if focus_node_ids:
                focus_node_id_set = set(focus_node_ids)
                effective_graph_nodes = [
                    node
                    for node in graph_nodes
                    if str(node["node_id"]) in focus_node_id_set
                ]
                effective_graph_edges = [
                    edge
                    for edge in graph_edges
                    if str(edge["source_node_id"]) in focus_node_id_set
                    and str(edge["target_node_id"]) in focus_node_id_set
                ]

            relation_tags = route.get("relation_tags")
            relation_tag_values = (
                relation_tags if isinstance(relation_tags, list) else []
            )
            try:
                template = resolve_scoring_template(
                    template_id=template_id,
                    relation_tags=[str(tag) for tag in relation_tag_values],
                )
                validate_template_contract(template)
            except ValueError as exc:
                self._raise(
                    status_code=400,
                    error_code="research.invalid_request",
                    message="invalid scoring template",
                    details={"reason": str(exc)},
                )

            confirmed_objects = self._store.list_confirmed_objects(workspace_id)
            effective_confirmed_objects = confirmed_objects
            if focus_node_ids:
                referenced_object_keys = {
                    (
                        str(node.get("object_ref_type", "")),
                        str(node.get("object_ref_id", "")),
                    )
                    for node in effective_graph_nodes
                }
                effective_confirmed_objects = [
                    obj
                    for obj in confirmed_objects
                    if (str(obj.get("object_type", "")), str(obj.get("object_id", "")))
                    in referenced_object_keys
                ]
            factor_inputs = build_factor_inputs(
                route=route,
                confirmed_objects=effective_confirmed_objects,
                graph_nodes=effective_graph_nodes,
                graph_edges=effective_graph_edges,
            )

            dimension_breakdown: dict[str, dict[str, object]] = {}
            factor_records: list[dict[str, object]] = []
            main_scores: dict[str, float] = {}

            for dimension, ordered_factors in FACTOR_ORDER_BY_DIMENSION.items():
                weights = template.weights.get(dimension, {})
                weighted_sum = 0.0
                records_for_dimension: list[dict[str, object]] = []
                for factor_name in ordered_factors:
                    if factor_name not in factor_inputs:
                        self._raise(
                            status_code=400,
                            error_code="research.invalid_request",
                            message="template references unsupported factor",
                            details={"factor_name": factor_name},
                        )
                    if factor_name not in weights:
                        self._raise(
                            status_code=400,
                            error_code="research.invalid_request",
                            message="template weight missing for factor",
                            details={"factor_name": factor_name},
                        )

                    factor_input = factor_inputs[factor_name]
                    weight = float(weights[factor_name])
                    normalized_value = clamp01(float(factor_input.normalized_value))
                    weighted_contribution = weight * normalized_value
                    weighted_sum += weighted_contribution
                    record = {
                        "factor_name": factor_name,
                        "score_dimension": dimension,
                        "normalized_value": round(normalized_value, 6),
                        "weight": round(weight, 6),
                        "weighted_contribution": round(weighted_contribution, 6),
                        "status": factor_input.status,
                        "reason": factor_input.reason,
                        "refs": factor_input.refs,
                        "metrics": factor_input.metrics,
                    }
                    record["explanation"] = build_factor_explanation(record)
                    records_for_dimension.append(record)
                    factor_records.append(record)

                normalized_score = clamp01(weighted_sum)
                score = round(normalized_score * 100, 1)
                main_scores[dimension] = score
                dimension_breakdown[dimension] = {
                    "normalized_score": round(normalized_score, 6),
                    "score": score,
                    "factors": records_for_dimension,
                }

            top_factors = select_top_factors(factor_records, limit=3)
            critique, factor_notes = self._build_reviewer_like_critique(
                route=route,
                main_scores=main_scores,
                factor_records=factor_records,
                top_factors=top_factors,
            )
            ranked_top_factors: list[dict[str, object]] = []
            for index, factor in enumerate(top_factors, start=1):
                factor_name = str(factor.get("factor_name", ""))
                ranked_top_factors.append(
                    {
                        **factor,
                        "rank": index,
                        "reviewer_note": factor_notes.get(factor_name, ""),
                    }
                )

            node_breakdown = build_node_score_breakdown(
                graph_nodes=effective_graph_nodes,
                factor_records=factor_records,
                focus_node_ids=focus_node_ids if focus_node_ids else None,
            )
            support_breakdown = dimension_breakdown.get("support_score")
            if isinstance(support_breakdown, dict):
                support_breakdown["reviewer_critique"] = critique

            updated_route = self._store.update_route_scores(
                route_id=route_id,
                support_score=main_scores["support_score"],
                risk_score=main_scores["risk_score"],
                progressability_score=main_scores["progressability_score"],
                scoring_template_id=template.template_id,
                top_factors=ranked_top_factors,
                score_breakdown=dimension_breakdown,
                node_score_breakdown=node_breakdown,
            )
            if updated_route is None:
                self._raise(
                    status_code=404,
                    error_code="research.not_found",
                    message="route not found",
                    details={"route_id": route_id},
                )

            self._store.emit_event(
                event_name="score_recalculated",
                request_id=request_id,
                job_id=None,
                workspace_id=workspace_id,
                component="score_service",
                step="score_route",
                status="completed",
                refs={"route_id": route_id, "node_ids": focus_node_ids},
                metrics={
                    "support_score": main_scores["support_score"],
                    "risk_score": main_scores["risk_score"],
                    "progressability_score": main_scores["progressability_score"],
                    "factor_count": len(factor_records),
                },
            )
            return updated_route
        except ScoreServiceError as exc:
            self._emit_failure_event(
                request_id=request_id,
                workspace_id=workspace_id,
                route_id=route_id,
                focus_node_ids=focus_node_ids,
                error=exc,
            )
            raise
