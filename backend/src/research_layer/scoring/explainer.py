from __future__ import annotations

from research_layer.scoring.templates import TOP_FACTOR_TIE_BREAK_ORDER


def build_factor_explanation(factor_record: dict[str, object]) -> str:
    factor_name = str(factor_record.get("factor_name", "factor"))
    status = str(factor_record.get("status", "computed"))
    reason = str(factor_record.get("reason", ""))
    normalized_value = float(factor_record.get("normalized_value", 0.0))
    weighted_contribution = float(factor_record.get("weighted_contribution", 0.0))
    if status == "missing_input":
        return f"{factor_name} missing_input ({reason}); normalized=0.0, contribution=0.0"
    return (
        f"{factor_name} computed ({reason}); normalized={normalized_value:.4f}, "
        f"weighted_contribution={weighted_contribution:.4f}"
    )


def select_top_factors(
    factor_records: list[dict[str, object]],
    *,
    limit: int = 3,
) -> list[dict[str, object]]:
    tie_break = {name: index for index, name in enumerate(TOP_FACTOR_TIE_BREAK_ORDER)}

    def _sort_key(record: dict[str, object]) -> tuple[float, int, str]:
        factor_name = str(record.get("factor_name", ""))
        return (
            -float(record.get("weighted_contribution", 0.0)),
            tie_break.get(factor_name, len(tie_break)),
            factor_name,
        )

    ranked = sorted(factor_records, key=_sort_key)
    return ranked[: max(0, limit)]


def build_node_score_breakdown(
    *,
    graph_nodes: list[dict[str, object]],
    factor_records: list[dict[str, object]],
    focus_node_ids: list[str] | None,
) -> list[dict[str, object]]:
    node_map: dict[str, dict[str, object]] = {}
    for node in graph_nodes:
        node_id = str(node.get("node_id", ""))
        if not node_id:
            continue
        node_map[node_id] = {
            "node_id": node_id,
            "node_type": str(node.get("node_type", "")),
            "status": str(node.get("status", "")),
            "object_ref_type": str(node.get("object_ref_type", "")),
            "object_ref_id": str(node.get("object_ref_id", "")),
            "support_contribution": 0.0,
            "risk_contribution": 0.0,
            "progressability_contribution": 0.0,
            "factor_contributions": [],
        }

    selected_nodes = set(focus_node_ids or node_map.keys())
    selected_nodes &= set(node_map.keys())

    for factor in factor_records:
        refs = factor.get("refs")
        refs_dict = refs if isinstance(refs, dict) else {}
        raw_node_ids = refs_dict.get("node_ids", [])
        if not isinstance(raw_node_ids, list):
            continue
        attached = [str(node_id) for node_id in raw_node_ids if str(node_id) in selected_nodes]
        if not attached:
            continue
        contribution = float(factor.get("weighted_contribution", 0.0)) / len(attached)
        score_dimension = str(factor.get("score_dimension", ""))
        for node_id in attached:
            node_entry = node_map[node_id]
            if score_dimension == "support_score":
                node_entry["support_contribution"] += contribution
            elif score_dimension == "risk_score":
                node_entry["risk_contribution"] += contribution
            elif score_dimension == "progressability_score":
                node_entry["progressability_contribution"] += contribution
            node_entry["factor_contributions"].append(
                {
                    "factor_name": str(factor.get("factor_name", "")),
                    "score_dimension": score_dimension,
                    "contribution": round(contribution, 6),
                }
            )

    results: list[dict[str, object]] = []
    for node_id in selected_nodes:
        node_entry = node_map[node_id]
        support = float(node_entry["support_contribution"])
        risk = float(node_entry["risk_contribution"])
        progressability = float(node_entry["progressability_contribution"])
        total_contribution = support + risk + progressability
        results.append(
            {
                "node_id": node_entry["node_id"],
                "node_type": node_entry["node_type"],
                "status": node_entry["status"],
                "object_ref_type": node_entry["object_ref_type"],
                "object_ref_id": node_entry["object_ref_id"],
                "support_contribution": round(support, 6),
                "risk_contribution": round(risk, 6),
                "progressability_contribution": round(progressability, 6),
                "total_contribution": round(total_contribution, 6),
                "factor_contributions": node_entry["factor_contributions"],
            }
        )

    return sorted(
        results,
        key=lambda item: (-float(item["total_contribution"]), str(item["node_id"])),
    )
