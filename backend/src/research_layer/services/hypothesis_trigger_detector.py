from __future__ import annotations

import re
from collections import Counter, defaultdict

from research_layer.api.controllers._state_store import ResearchApiStateStore

_TERMINAL_NODE_STATUSES = {"archived", "superseded"}
_TOPIC_TERM_RE = re.compile(r"^[a-z0-9_]+$")


class HypothesisTriggerDetector:
    def __init__(self, store: ResearchApiStateStore) -> None:
        self._store = store

    def list_triggers(self, *, workspace_id: str) -> list[dict[str, object]]:
        triggers: list[dict[str, object]] = []
        triggers.extend(self._collect_gap_triggers(workspace_id=workspace_id))
        triggers.extend(self._collect_conflict_triggers(workspace_id=workspace_id))
        triggers.extend(self._collect_failure_triggers(workspace_id=workspace_id))
        triggers.extend(self._collect_weak_support_triggers(workspace_id=workspace_id))
        triggers.extend(self._collect_topic_gap_cluster_triggers(workspace_id=workspace_id))
        return sorted(triggers, key=lambda item: str(item["trigger_id"]))

    def resolve_trigger_ids(
        self, *, workspace_id: str, trigger_ids: list[str]
    ) -> list[dict[str, object]]:
        trigger_map = {
            str(item["trigger_id"]): item
            for item in self.list_triggers(workspace_id=workspace_id)
        }
        return [trigger_map[trigger_id] for trigger_id in trigger_ids if trigger_id in trigger_map]

    def _collect_gap_triggers(self, *, workspace_id: str) -> list[dict[str, object]]:
        results: list[dict[str, object]] = []
        for node in self._store.list_graph_nodes(workspace_id):
            if str(node.get("node_type", "")) != "gap":
                continue
            status = str(node.get("status", ""))
            if status in _TERMINAL_NODE_STATUSES:
                continue
            node_id = str(node["node_id"])
            results.append(
                {
                    "trigger_id": f"trigger_gap_{node_id}",
                    "trigger_type": "gap",
                    "workspace_id": workspace_id,
                    "object_ref_type": "graph_node",
                    "object_ref_id": node_id,
                    "summary": str(node.get("short_label", "gap trigger")),
                    "trace_refs": {
                        "graph_node_id": node_id,
                        "object_ref_type": str(node.get("object_ref_type", "")),
                        "object_ref_id": str(node.get("object_ref_id", "")),
                        "node_status": status,
                    },
                    "related_object_ids": [
                        {"object_type": "graph_node", "object_id": node_id}
                    ],
                    "metrics": {"node_status": status},
                }
            )
        return results

    def _collect_conflict_triggers(
        self, *, workspace_id: str
    ) -> list[dict[str, object]]:
        results: list[dict[str, object]] = []
        seen_object_ids: set[str] = set()
        for node in self._store.list_graph_nodes(workspace_id):
            if str(node.get("node_type", "")) != "conflict":
                continue
            node_id = str(node["node_id"])
            conflict_ref_id = str(node.get("object_ref_id", node_id))
            seen_object_ids.add(conflict_ref_id)
            results.append(
                {
                    "trigger_id": f"trigger_conflict_node_{node_id}",
                    "trigger_type": "conflict",
                    "workspace_id": workspace_id,
                    "object_ref_type": "graph_node",
                    "object_ref_id": node_id,
                    "summary": str(node.get("short_label", "conflict trigger")),
                    "trace_refs": {
                        "graph_node_id": node_id,
                        "conflict_ref_id": conflict_ref_id,
                        "node_status": str(node.get("status", "")),
                    },
                    "related_object_ids": [
                        {"object_type": "graph_node", "object_id": node_id},
                        {"object_type": "conflict", "object_id": conflict_ref_id},
                    ],
                    "metrics": {"node_status": str(node.get("status", ""))},
                }
            )

        for obj in self._store.list_confirmed_objects(workspace_id):
            if str(obj.get("object_type", "")) != "conflict":
                continue
            object_id = str(obj.get("object_id", ""))
            if not object_id or object_id in seen_object_ids:
                continue
            results.append(
                {
                    "trigger_id": f"trigger_conflict_object_{object_id}",
                    "trigger_type": "conflict",
                    "workspace_id": workspace_id,
                    "object_ref_type": "conflict",
                    "object_ref_id": object_id,
                    "summary": str(obj.get("text", "conflict trigger")),
                    "trace_refs": {
                        "conflict_id": object_id,
                        "source_id": str(obj.get("source_id", "")),
                    },
                    "related_object_ids": [
                        {"object_type": "conflict", "object_id": object_id}
                    ],
                    "metrics": {},
                }
            )
        return results

    def _collect_failure_triggers(
        self, *, workspace_id: str
    ) -> list[dict[str, object]]:
        results: list[dict[str, object]] = []
        for failure in self._store.list_failures(workspace_id=workspace_id):
            failure_id = str(failure["failure_id"])
            attached_targets = [
                {
                    "target_type": str(item.get("target_type", "")),
                    "target_id": str(item.get("target_id", "")),
                }
                for item in failure.get("attached_targets", [])
                if isinstance(item, dict)
            ]
            related_objects: list[dict[str, str]] = [
                {"object_type": "failure", "object_id": failure_id}
            ]
            for target in attached_targets:
                target_type = target["target_type"]
                target_id = target["target_id"]
                if target_type == "node":
                    related_objects.append(
                        {"object_type": "graph_node", "object_id": target_id}
                    )
                elif target_type == "edge":
                    related_objects.append(
                        {"object_type": "graph_edge", "object_id": target_id}
                    )
            results.append(
                {
                    "trigger_id": f"trigger_failure_{failure_id}",
                    "trigger_type": "failure",
                    "workspace_id": workspace_id,
                    "object_ref_type": "failure",
                    "object_ref_id": failure_id,
                    "summary": str(failure.get("failure_reason", "failure trigger")),
                    "trace_refs": {
                        "failure_id": failure_id,
                        "attached_targets": attached_targets,
                    },
                    "related_object_ids": related_objects,
                    "metrics": {"attached_target_count": len(attached_targets)},
                }
            )
        return results

    def _collect_weak_support_triggers(
        self, *, workspace_id: str
    ) -> list[dict[str, object]]:
        results: list[dict[str, object]] = []
        for route in self._store.list_routes(workspace_id):
            route_id = str(route["route_id"])
            support_score = float(route.get("support_score", 0.0))
            status = str(route.get("status", ""))
            has_missing_support = self._has_missing_support_factor(
                score_breakdown=route.get("score_breakdown")
            )
            if not (
                support_score < 60
                or status in {"weakened", "failed"}
                or has_missing_support
            ):
                continue
            route_node_ids = [str(node_id) for node_id in route.get("route_node_ids", [])]
            results.append(
                {
                    "trigger_id": f"trigger_weak_support_{route_id}",
                    "trigger_type": "weak_support",
                    "workspace_id": workspace_id,
                    "object_ref_type": "route",
                    "object_ref_id": route_id,
                    "summary": f"Weak support detected on route {route_id}",
                    "trace_refs": {
                        "route_id": route_id,
                        "version_id": route.get("version_id"),
                        "route_node_ids": route_node_ids,
                    },
                    "related_object_ids": [
                        {"object_type": "route", "object_id": route_id},
                        *[
                            {"object_type": "graph_node", "object_id": node_id}
                            for node_id in route_node_ids
                        ],
                    ],
                    "metrics": {
                        "support_score": support_score,
                        "route_status": status,
                        "has_missing_support_factor": has_missing_support,
                    },
                }
            )
        return results

    def _has_missing_support_factor(self, *, score_breakdown: object) -> bool:
        if not isinstance(score_breakdown, dict):
            return False
        support = score_breakdown.get("support_score")
        if not isinstance(support, dict):
            return False
        factors = support.get("factors")
        if not isinstance(factors, list):
            return False
        for factor in factors:
            if not isinstance(factor, dict):
                continue
            if str(factor.get("status", "")) == "missing_input":
                return True
        return False

    def _collect_topic_gap_cluster_triggers(
        self, *, workspace_id: str
    ) -> list[dict[str, object]]:
        clusters = self._store.list_source_topic_clusters(workspace_id=workspace_id)
        if not clusters:
            return []
        aggregated: dict[str, dict[str, object]] = {}
        for cluster in clusters:
            raw_keywords = cluster.get("keywords")
            if not isinstance(raw_keywords, list):
                continue
            keywords = [
                self._normalize_topic_term(keyword)
                for keyword in raw_keywords
                if self._normalize_topic_term(keyword)
            ]
            if not keywords:
                continue
            theme_key = keywords[0]
            cluster_id = f"topic_cluster_{theme_key}"
            current = aggregated.setdefault(
                cluster_id,
                {
                    "cluster_id": cluster_id,
                    "cluster_label": str(cluster.get("cluster_label") or theme_key),
                    "source_ids": set(),
                    "keyword_counter": Counter(),
                    "signal_score": 0,
                    "evidence_hits": 0,
                },
            )
            source_id = str(cluster.get("source_id", "")).strip()
            if source_id:
                current["source_ids"].add(source_id)
            current["keyword_counter"].update(keywords)
            current["signal_score"] = int(current["signal_score"]) + int(
                cluster.get("signal_score") or 0
            )
            current["evidence_hits"] = int(current["evidence_hits"]) + int(
                cluster.get("evidence_hits") or 0
            )

        routes = self._store.list_routes(workspace_id)
        route_documents: list[tuple[str, str, float]] = []
        for route in routes:
            route_id = str(route.get("route_id", ""))
            support_score = float(route.get("support_score", 0.0))
            chunks = [
                str(route.get("title", "")),
                str(route.get("summary", "")),
                str(route.get("conclusion", "")),
            ]
            for field in ("key_supports", "assumptions", "risks"):
                values = route.get(field, [])
                if isinstance(values, list):
                    chunks.extend(str(item) for item in values if str(item).strip())
            route_documents.append((route_id, " ".join(chunks).lower(), support_score))

        conflict_documents: list[dict[str, str]] = []
        for node in self._store.list_graph_nodes(workspace_id):
            if str(node.get("node_type", "")) != "conflict":
                continue
            node_id = str(node.get("node_id", ""))
            text = " ".join(
                [
                    str(node.get("short_label", "")),
                    str(node.get("full_description", "")),
                    str(node.get("object_ref_id", "")),
                ]
            ).lower()
            conflict_documents.append(
                {
                    "object_type": "graph_node",
                    "object_id": node_id,
                    "text": text,
                }
            )
        for item in self._store.list_confirmed_objects(workspace_id):
            if str(item.get("object_type", "")) != "conflict":
                continue
            object_id = str(item.get("object_id", ""))
            conflict_documents.append(
                {
                    "object_type": "conflict",
                    "object_id": object_id,
                    "text": str(item.get("text", "")).lower(),
                }
            )

        triggers: list[dict[str, object]] = []
        for aggregate in aggregated.values():
            source_ids = sorted(str(item) for item in aggregate["source_ids"])
            keyword_counter = aggregate["keyword_counter"]
            if not isinstance(keyword_counter, Counter):
                continue
            keywords = [
                term
                for term, _ in sorted(
                    keyword_counter.items(),
                    key=lambda item: (-item[1], item[0]),
                )[:6]
            ]
            if not keywords:
                continue
            matched_route_ids: list[str] = []
            matched_support_scores: list[float] = []
            for route_id, route_text, support_score in route_documents:
                if any(
                    self._contains_topic_term(route_text, keyword)
                    for keyword in keywords
                ):
                    matched_route_ids.append(route_id)
                    matched_support_scores.append(support_score)
            matched_conflict_refs: list[dict[str, str]] = []
            for conflict in conflict_documents:
                if any(
                    self._contains_topic_term(str(conflict.get("text", "")), keyword)
                    for keyword in keywords
                ):
                    matched_conflict_refs.append(
                        {
                            "object_type": str(conflict.get("object_type", "")),
                            "object_id": str(conflict.get("object_id", "")),
                        }
                    )
            average_support = (
                sum(matched_support_scores) / len(matched_support_scores)
                if matched_support_scores
                else 0.0
            )
            reasons: list[str] = []
            if matched_route_ids and average_support < 60.0:
                reasons.append("low_support")
            if len(matched_conflict_refs) >= 1:
                reasons.append("high_conflict")
            if (
                not matched_route_ids
                and not matched_conflict_refs
                and len(source_ids) >= 2
            ):
                reasons.append("empty_theme")
            reason_to_trigger_type = {
                "low_support": "weak_support",
                "high_conflict": "conflict",
                "empty_theme": "gap",
            }
            for reason in reasons:
                trigger_type = reason_to_trigger_type[reason]
                object_ref_id = f"{aggregate['cluster_id']}:{reason}"
                summary = (
                    f"Topic gap cluster {aggregate['cluster_id']} detected as {reason}; "
                    f"keywords={', '.join(keywords[:3])}"
                )
                related_objects: list[dict[str, str]] = [
                    {"object_type": "research_gap_cluster", "object_id": object_ref_id}
                ]
                related_objects.extend(
                    {"object_type": "source", "object_id": source_id}
                    for source_id in source_ids
                )
                related_objects.extend(
                    {"object_type": "route", "object_id": route_id}
                    for route_id in matched_route_ids[:10]
                )
                related_objects.extend(matched_conflict_refs[:10])
                triggers.append(
                    {
                        "trigger_id": f"trigger_topic_gap_{reason}_{aggregate['cluster_id']}",
                        "trigger_type": trigger_type,
                        "workspace_id": workspace_id,
                        "object_ref_type": "research_gap_cluster",
                        "object_ref_id": object_ref_id,
                        "summary": summary,
                        "trace_refs": {
                            "topic_cluster_id": aggregate["cluster_id"],
                            "topic_cluster_label": aggregate["cluster_label"],
                            "gap_reason": reason,
                            "cluster_keywords": keywords,
                            "source_ids": source_ids,
                            "matched_route_ids": matched_route_ids[:10],
                            "matched_conflict_refs": matched_conflict_refs[:10],
                        },
                        "related_object_ids": related_objects,
                        "metrics": {
                            "source_count": len(source_ids),
                            "keyword_count": len(keywords),
                            "signal_score": int(aggregate["signal_score"]),
                            "evidence_hits": int(aggregate["evidence_hits"]),
                            "matched_route_count": len(matched_route_ids),
                            "matched_conflict_count": len(matched_conflict_refs),
                            "average_support_score": round(average_support, 3),
                        },
                    }
                )
        return triggers

    def _normalize_topic_term(self, raw: object) -> str:
        value = str(raw or "").strip().lower()
        if not value:
            return ""
        return re.sub(r"\s+", "_", value)

    def _contains_topic_term(self, haystack: str, term: str) -> bool:
        normalized_term = self._normalize_topic_term(term)
        if not normalized_term:
            return False
        search_text = haystack.lower()
        if _TOPIC_TERM_RE.fullmatch(normalized_term):
            pattern = r"\b" + re.escape(normalized_term).replace(r"\_", "_") + r"\b"
            return re.search(pattern, search_text) is not None
        return normalized_term in search_text
