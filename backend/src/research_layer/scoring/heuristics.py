from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FactorInput:
    factor_name: str
    normalized_value: float
    status: str
    reason: str
    refs: dict[str, object]
    metrics: dict[str, object]


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _missing_factor(
    *,
    factor_name: str,
    reason: str,
    refs: dict[str, object] | None = None,
    metrics: dict[str, object] | None = None,
) -> FactorInput:
    return FactorInput(
        factor_name=factor_name,
        normalized_value=0.0,
        status="missing_input",
        reason=reason,
        refs=refs or {},
        metrics=metrics or {},
    )


def _computed_factor(
    *,
    factor_name: str,
    value: float,
    reason: str,
    refs: dict[str, object] | None = None,
    metrics: dict[str, object] | None = None,
) -> FactorInput:
    return FactorInput(
        factor_name=factor_name,
        normalized_value=clamp01(value),
        status="computed",
        reason=reason,
        refs=refs or {},
        metrics=metrics or {},
    )


def build_factor_inputs(
    *,
    route: dict[str, object],
    confirmed_objects: list[dict[str, object]],
    graph_nodes: list[dict[str, object]],
    graph_edges: list[dict[str, object]],
) -> dict[str, FactorInput]:
    by_type: dict[str, list[dict[str, object]]] = {
        "evidence": [],
        "assumption": [],
        "conflict": [],
        "failure": [],
        "validation": [],
    }
    for obj in confirmed_objects:
        object_type = str(obj.get("object_type", ""))
        if object_type in by_type:
            by_type[object_type].append(obj)

    nodes_by_type: dict[str, list[dict[str, object]]] = {
        "evidence": [],
        "assumption": [],
        "conflict": [],
        "failure": [],
        "validation": [],
        "private_dependency": [],
    }
    for node in graph_nodes:
        node_type = str(node.get("node_type", ""))
        if node_type in nodes_by_type:
            nodes_by_type[node_type].append(node)

    total_confirmed = len(confirmed_objects)
    total_nodes = len(graph_nodes)
    total_edges = len(graph_edges)

    evidence_objects = by_type["evidence"]
    assumption_objects = by_type["assumption"]
    validation_objects = by_type["validation"]

    evidence_nodes = nodes_by_type["evidence"]
    conflict_nodes = nodes_by_type["conflict"]
    failure_nodes = nodes_by_type["failure"]
    assumption_nodes = nodes_by_type["assumption"]
    validation_nodes = nodes_by_type["validation"]
    private_dependency_nodes = nodes_by_type["private_dependency"]
    failed_nodes = [node for node in graph_nodes if str(node.get("status")) == "failed"]

    evidence_node_ids = [str(node["node_id"]) for node in evidence_nodes]
    conflict_node_ids = [str(node["node_id"]) for node in conflict_nodes]
    failure_node_ids = [str(node["node_id"]) for node in failure_nodes]
    validation_node_ids = [str(node["node_id"]) for node in validation_nodes]
    assumption_node_ids = [str(node["node_id"]) for node in assumption_nodes]
    private_dependency_node_ids = [str(node["node_id"]) for node in private_dependency_nodes]

    evidence_object_ids = [str(obj["object_id"]) for obj in evidence_objects]
    validation_object_ids = [str(obj["object_id"]) for obj in validation_objects]

    evidence_text_quality = 0.0
    if evidence_objects:
        evidence_text_quality = sum(
            min(len(str(obj.get("text", "")).strip()) / 120.0, 1.0)
            for obj in evidence_objects
        ) / len(evidence_objects)

    evidence_edge_strengths: list[float] = []
    evidence_node_id_set = set(evidence_node_ids)
    for edge in graph_edges:
        source_node_id = str(edge.get("source_node_id", ""))
        target_node_id = str(edge.get("target_node_id", ""))
        if source_node_id in evidence_node_id_set or target_node_id in evidence_node_id_set:
            evidence_edge_strengths.append(float(edge.get("strength", 0.0)))
    evidence_edge_quality = (
        sum(evidence_edge_strengths) / len(evidence_edge_strengths)
        if evidence_edge_strengths
        else 0.0
    )

    factors: dict[str, FactorInput] = {}

    if total_confirmed <= 0:
        factors["confirmed_evidence_coverage"] = _missing_factor(
            factor_name="confirmed_evidence_coverage",
            reason="no_confirmed_objects",
        )
    else:
        factors["confirmed_evidence_coverage"] = _computed_factor(
            factor_name="confirmed_evidence_coverage",
            value=len(evidence_objects) / total_confirmed,
            reason="evidence_over_confirmed_objects",
            refs={"object_ids": evidence_object_ids, "node_ids": evidence_node_ids},
            metrics={"evidence_count": len(evidence_objects), "confirmed_count": total_confirmed},
        )

    if not evidence_objects:
        factors["evidence_quality"] = _missing_factor(
            factor_name="evidence_quality",
            reason="no_evidence_objects",
        )
    else:
        active_evidence_ratio = len(evidence_nodes) / max(1, len(evidence_objects))
        factors["evidence_quality"] = _computed_factor(
            factor_name="evidence_quality",
            value=0.5 * evidence_text_quality + 0.3 * active_evidence_ratio + 0.2 * evidence_edge_quality,
            reason="text_quality_active_ratio_edge_strength",
            refs={"object_ids": evidence_object_ids, "node_ids": evidence_node_ids},
            metrics={
                "text_quality": round(evidence_text_quality, 4),
                "active_evidence_ratio": round(active_evidence_ratio, 4),
                "edge_quality": round(evidence_edge_quality, 4),
            },
        )

    if not evidence_objects:
        factors["cross_source_consistency"] = _missing_factor(
            factor_name="cross_source_consistency",
            reason="no_evidence_objects",
        )
    else:
        distinct_sources = len({str(obj.get("source_id", "")) for obj in evidence_objects})
        consistency_base = min(1.0, distinct_sources / 3.0)
        conflict_ratio = len(conflict_nodes) / max(1, total_nodes)
        factors["cross_source_consistency"] = _computed_factor(
            factor_name="cross_source_consistency",
            value=consistency_base * (1.0 - conflict_ratio),
            reason="distinct_sources_adjusted_by_conflicts",
            refs={
                "source_ids": sorted({str(obj.get("source_id", "")) for obj in evidence_objects}),
                "node_ids": evidence_node_ids + conflict_node_ids,
            },
            metrics={
                "distinct_source_count": distinct_sources,
                "conflict_ratio": round(conflict_ratio, 4),
            },
        )

    if not validation_objects:
        factors["validation_backing"] = _missing_factor(
            factor_name="validation_backing",
            reason="no_validation_objects",
            refs={"object_ids": [], "node_ids": []},
            metrics={"validation_count": 0, "evidence_count": len(evidence_objects)},
        )
    else:
        factors["validation_backing"] = _computed_factor(
            factor_name="validation_backing",
            value=len(validation_objects) / max(1, len(evidence_objects)),
            reason="validation_over_evidence",
            refs={"object_ids": validation_object_ids, "node_ids": validation_node_ids},
            metrics={"validation_count": len(validation_objects), "evidence_count": len(evidence_objects)},
        )

    if total_nodes <= 0:
        factors["traceability_completeness"] = _missing_factor(
            factor_name="traceability_completeness",
            reason="graph_not_built",
        )
    else:
        traced_nodes = [
            node
            for node in graph_nodes
            if str(node.get("object_ref_type", "")).strip() and str(node.get("object_ref_id", "")).strip()
        ]
        traced_edges = [
            edge
            for edge in graph_edges
            if str(edge.get("object_ref_type", "")).strip() and str(edge.get("object_ref_id", "")).strip()
        ]
        node_ratio = len(traced_nodes) / max(1, total_nodes)
        edge_ratio = 1.0 if total_edges == 0 else len(traced_edges) / total_edges
        factors["traceability_completeness"] = _computed_factor(
            factor_name="traceability_completeness",
            value=0.7 * node_ratio + 0.3 * edge_ratio,
            reason="traceable_node_and_edge_ratio",
            refs={
                "node_ids": [str(node["node_id"]) for node in traced_nodes],
                "edge_ids": [str(edge["edge_id"]) for edge in traced_edges],
            },
            metrics={
                "traced_node_count": len(traced_nodes),
                "traced_edge_count": len(traced_edges),
                "total_node_count": total_nodes,
                "total_edge_count": total_edges,
            },
        )

    if total_nodes <= 0:
        factors["unresolved_conflict_pressure"] = _missing_factor(
            factor_name="unresolved_conflict_pressure",
            reason="graph_not_built",
        )
    else:
        factors["unresolved_conflict_pressure"] = _computed_factor(
            factor_name="unresolved_conflict_pressure",
            value=len(conflict_nodes) / total_nodes,
            reason="conflict_nodes_over_total_nodes",
            refs={"node_ids": conflict_node_ids},
            metrics={"conflict_count": len(conflict_nodes), "total_node_count": total_nodes},
        )

    if total_nodes <= 0:
        factors["failure_pressure"] = _missing_factor(
            factor_name="failure_pressure",
            reason="graph_not_built",
        )
    else:
        factors["failure_pressure"] = _computed_factor(
            factor_name="failure_pressure",
            value=(len(failure_nodes) + 0.5 * len(failed_nodes)) / total_nodes,
            reason="failure_and_failed_nodes_over_total_nodes",
            refs={"node_ids": failure_node_ids + [str(node["node_id"]) for node in failed_nodes]},
            metrics={
                "failure_node_count": len(failure_nodes),
                "failed_node_count": len(failed_nodes),
                "total_node_count": total_nodes,
            },
        )

    if total_nodes <= 0:
        factors["assumption_burden"] = _missing_factor(
            factor_name="assumption_burden",
            reason="graph_not_built",
        )
    else:
        assumption_pressure = len(assumption_nodes) / max(1, len(evidence_nodes))
        assumption_density = len(assumption_nodes) / total_nodes
        factors["assumption_burden"] = _computed_factor(
            factor_name="assumption_burden",
            value=0.7 * assumption_pressure + 0.3 * assumption_density,
            reason="assumption_pressure_and_density",
            refs={"node_ids": assumption_node_ids},
            metrics={
                "assumption_count": len(assumption_nodes),
                "evidence_node_count": len(evidence_nodes),
                "total_node_count": total_nodes,
            },
        )

    if total_nodes <= 0:
        factors["private_dependency_pressure"] = _missing_factor(
            factor_name="private_dependency_pressure",
            reason="graph_not_built",
        )
    else:
        factors["private_dependency_pressure"] = _computed_factor(
            factor_name="private_dependency_pressure",
            value=len(private_dependency_nodes) / total_nodes,
            reason="private_dependency_nodes_over_total_nodes",
            refs={"node_ids": private_dependency_node_ids},
            metrics={
                "private_dependency_count": len(private_dependency_nodes),
                "total_node_count": total_nodes,
            },
        )

    if not evidence_objects:
        factors["missing_validation_pressure"] = _missing_factor(
            factor_name="missing_validation_pressure",
            reason="no_evidence_objects",
            refs={"object_ids": [], "node_ids": []},
            metrics={"evidence_count": 0, "validation_count": len(validation_objects)},
        )
    else:
        factors["missing_validation_pressure"] = _computed_factor(
            factor_name="missing_validation_pressure",
            value=1.0 - min(1.0, len(validation_objects) / max(1, len(evidence_objects))),
            reason="missing_validation_over_evidence",
            refs={"object_ids": validation_object_ids, "node_ids": validation_node_ids},
            metrics={"evidence_count": len(evidence_objects), "validation_count": len(validation_objects)},
        )

    action_text = str(route.get("next_validation_action", "")).strip()
    if not action_text:
        factors["next_action_clarity"] = _missing_factor(
            factor_name="next_action_clarity",
            reason="missing_next_validation_action",
        )
    else:
        action_keywords = ("run", "measure", "compare", "validate", "ablation", "test")
        action_lower = action_text.lower()
        keyword_hit = 1.0 if any(keyword in action_lower for keyword in action_keywords) else 0.0
        token_count = len(action_text.split())
        length_score = min(1.0, len(action_text) / 100.0)
        token_score = min(1.0, token_count / 12.0)
        factors["next_action_clarity"] = _computed_factor(
            factor_name="next_action_clarity",
            value=0.5 * length_score + 0.3 * token_score + 0.2 * keyword_hit,
            reason="action_length_tokens_keywords",
            refs={},
            metrics={
                "action_length": len(action_text),
                "token_count": token_count,
                "keyword_hit": keyword_hit,
            },
        )

    if total_nodes <= 0:
        factors["execution_cost_feasibility"] = _missing_factor(
            factor_name="execution_cost_feasibility",
            reason="graph_not_built",
        )
    else:
        conflict_ratio = len(conflict_nodes) / total_nodes
        failure_ratio = len(failure_nodes) / total_nodes
        factors["execution_cost_feasibility"] = _computed_factor(
            factor_name="execution_cost_feasibility",
            value=1.0 - (0.6 * conflict_ratio + 0.4 * failure_ratio),
            reason="inverse_of_conflict_and_failure_pressure",
            refs={"node_ids": conflict_node_ids + failure_node_ids},
            metrics={
                "conflict_ratio": round(conflict_ratio, 4),
                "failure_ratio": round(failure_ratio, 4),
            },
        )

    if total_nodes <= 0:
        factors["execution_time_feasibility"] = _missing_factor(
            factor_name="execution_time_feasibility",
            reason="graph_not_built",
        )
    else:
        failed_ratio = len(failed_nodes) / total_nodes
        edge_load = min(1.0, total_edges / max(1, total_nodes * 2))
        factors["execution_time_feasibility"] = _computed_factor(
            factor_name="execution_time_feasibility",
            value=1.0 - (0.5 * failed_ratio + 0.5 * edge_load),
            reason="inverse_of_failed_nodes_and_edge_load",
            refs={"node_ids": [str(node["node_id"]) for node in failed_nodes]},
            metrics={
                "failed_ratio": round(failed_ratio, 4),
                "edge_load": round(edge_load, 4),
            },
        )

    if not evidence_objects:
        factors["expected_signal_strength"] = _missing_factor(
            factor_name="expected_signal_strength",
            reason="no_evidence_objects",
        )
    else:
        validation_ratio = len(validation_objects) / max(1, len(evidence_objects))
        factors["expected_signal_strength"] = _computed_factor(
            factor_name="expected_signal_strength",
            value=0.6 * evidence_text_quality + 0.4 * validation_ratio,
            reason="evidence_text_quality_and_validation_ratio",
            refs={"object_ids": evidence_object_ids + validation_object_ids},
            metrics={
                "evidence_text_quality": round(evidence_text_quality, 4),
                "validation_ratio": round(validation_ratio, 4),
            },
        )

    if total_nodes <= 0:
        factors["dependency_readiness"] = _missing_factor(
            factor_name="dependency_readiness",
            reason="graph_not_built",
        )
    else:
        blocked_count = len(private_dependency_nodes) + len(failed_nodes) + len(conflict_nodes)
        factors["dependency_readiness"] = _computed_factor(
            factor_name="dependency_readiness",
            value=1.0 - (blocked_count / total_nodes),
            reason="inverse_of_blocked_nodes",
            refs={
                "node_ids": private_dependency_node_ids
                + [str(node["node_id"]) for node in failed_nodes]
                + conflict_node_ids
            },
            metrics={
                "blocked_count": blocked_count,
                "total_node_count": total_nodes,
            },
        )

    # Preserve assumption object trace even when assumptions have no direct factor lead.
    if assumption_objects and "assumption_burden" in factors:
        assumption_factor = factors["assumption_burden"]
        factors["assumption_burden"] = FactorInput(
            factor_name=assumption_factor.factor_name,
            normalized_value=assumption_factor.normalized_value,
            status=assumption_factor.status,
            reason=assumption_factor.reason,
            refs={
                **assumption_factor.refs,
                "object_ids": [str(obj["object_id"]) for obj in assumption_objects],
            },
            metrics=assumption_factor.metrics,
        )

    return factors
