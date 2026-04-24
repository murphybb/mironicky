from __future__ import annotations

from typing import Any

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.api.schemas.retrieval import RETRIEVAL_VIEW_VALUES
from research_layer.services.evermemos_bridge_service import EverMemOSRecallService
from research_layer.services.retrieval_views_service import ResearchRetrievalService

_VIEW_ORDER = [
    "evidence",
    "contradiction",
    "failure_pattern",
    "validation_history",
    "hypothesis_support",
]


class GraphRAGService:
    def __init__(
        self,
        store: ResearchApiStateStore,
        *,
        retrieval_service: Any | None = None,
        recall_service: Any | None = None,
    ) -> None:
        self._store = store
        self._retrieval_service = retrieval_service or ResearchRetrievalService(store)
        self._recall_service = recall_service or EverMemOSRecallService(store)

    def answer(
        self,
        *,
        workspace_id: str,
        question: str,
        request_id: str,
        limit: int = 8,
    ) -> dict[str, object]:
        safe_limit = min(max(int(limit or 8), 1), 25)
        retrievals = self._retrieve_items(
            workspace_id=workspace_id,
            question=question,
            request_id=request_id,
            limit=safe_limit,
        )
        dropped_claim_refs: list[dict[str, object]] = []
        citations = self._build_citations(
            workspace_id=workspace_id,
            items=retrievals["items"],
            limit=safe_limit,
            dropped_claim_refs=dropped_claim_refs,
        )
        claim_ids = self._claim_ids(citations)
        trace_refs = {
            "request_id": request_id,
            "retrieval": retrievals["trace_refs"],
            "claim_ids": claim_ids,
            "graph_refs": self._merge_graph_refs(citations),
            "source_artifact_refs": self._source_artifact_refs(citations),
            "dropped_claim_refs": dropped_claim_refs,
            "skipped_claim_refs": dropped_claim_refs,
        }
        if not citations:
            return {
                "workspace_id": workspace_id,
                "question": question,
                "answer": (
                    "There is not enough claim evidence in this workspace to answer "
                    "the question."
                ),
                "citations": [],
                "memory_recall": self._skipped_memory_recall(
                    workspace_id=workspace_id,
                    question=question,
                    reason="no_claim_citations",
                    trace_refs=trace_refs,
                ),
                "trace_refs": trace_refs,
            }

        memory_recall = self._recall_service.recall(
            workspace_id=workspace_id,
            query_text=question,
            requested_method="hybrid",
            scope_claim_ids=claim_ids,
            scope_mode="require",
            top_k=min(safe_limit, 8),
            request_id=request_id,
            reason="graphrag_query",
            trace_refs={
                "context_type": "graphrag_query",
                "reason": "graphrag_query",
                "request_id": request_id,
                "claim_ids": claim_ids,
            },
        )
        return {
            "workspace_id": workspace_id,
            "question": question,
            "answer": self._summarize(citations),
            "citations": citations,
            "memory_recall": memory_recall,
            "trace_refs": trace_refs,
        }

    def _retrieve_items(
        self,
        *,
        workspace_id: str,
        question: str,
        request_id: str,
        limit: int,
    ) -> dict[str, object]:
        items: list[dict[str, object]] = []
        view_counts: dict[str, int] = {}
        for view_type in _VIEW_ORDER:
            if view_type not in RETRIEVAL_VIEW_VALUES:
                continue
            response = self._retrieval_service.retrieve(
                workspace_id=workspace_id,
                view_type=view_type,
                query=question,
                retrieve_method="hybrid",
                top_k=limit,
                metadata_filters={},
                request_id=request_id,
            )
            view_items = [
                {**item, "_view_type": view_type}
                for item in response.get("items", [])
                if isinstance(item, dict)
            ]
            view_counts[view_type] = len(view_items)
            items.extend(view_items)
        items.sort(
            key=lambda item: (
                -float(item.get("score") or 0.0),
                str(item.get("result_id") or ""),
            )
        )
        return {
            "items": items[:limit],
            "trace_refs": {
                "view_counts": view_counts,
                "views": [view for view in _VIEW_ORDER if view in RETRIEVAL_VIEW_VALUES],
            },
        }

    def _build_citations(
        self,
        *,
        workspace_id: str,
        items: list[dict[str, object]],
        limit: int,
        dropped_claim_refs: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        claim_by_ref = self._claim_id_by_formal_ref(workspace_id)
        citations: list[dict[str, object]] = []
        seen: set[str] = set()
        for item in items:
            claim_ids = self._claim_ids_for_item(item, claim_by_ref=claim_by_ref)
            for claim_id in claim_ids:
                if claim_id in seen:
                    continue
                claim = self._store.get_claim(claim_id)
                if claim is None:
                    dropped_claim_refs.append(
                        self._dropped_claim_ref(
                            claim_id=claim_id,
                            item=item,
                            reason="claim_not_found",
                        )
                    )
                    continue
                text = str(claim.get("text") or "").strip()
                if not text:
                    dropped_claim_refs.append(
                        self._dropped_claim_ref(
                            claim_id=claim_id,
                            item=item,
                            reason="claim_text_missing",
                        )
                    )
                    continue
                seen.add(claim_id)
                citations.append(
                    {
                        "claim_id": claim_id,
                        "text": text,
                        "source_ref": self._source_ref_for_claim(claim),
                        "score": float(item.get("score") or 0.0),
                        "graph_refs": item.get("graph_refs", {}),
                        "source_artifact_refs": self._artifact_refs_for_item(item),
                        "retrieval_result_id": str(item.get("result_id") or ""),
                        "view_type": str(item.get("_view_type") or ""),
                        "formal_refs": self._formal_refs(item),
                        "trace_refs": {
                            "retrieval_trace_refs": item.get("trace_refs", {}),
                            "evidence_refs": item.get("evidence_refs", []),
                            "item_source_ref": item.get("source_ref", {}),
                        },
                    }
                )
                if len(citations) >= limit:
                    return citations
        return citations

    def _claim_id_by_formal_ref(self, workspace_id: str) -> dict[tuple[str, str], str]:
        return {
            (str(item.get("object_type") or ""), str(item.get("object_id") or "")): str(
                item.get("claim_id")
            )
            for item in self._store.list_confirmed_objects(workspace_id)
            if item.get("claim_id")
        }

    def _claim_ids_for_item(
        self,
        item: dict[str, object],
        *,
        claim_by_ref: dict[tuple[str, str], str],
    ) -> list[str]:
        claim_ids: list[str] = []
        for ref in self._formal_refs(item):
            claim_id = claim_by_ref.get(
                (str(ref.get("object_type") or ""), str(ref.get("object_id") or ""))
            )
            if claim_id:
                claim_ids.append(claim_id)
        graph_refs = item.get("graph_refs", {})
        graph_refs_dict = graph_refs if isinstance(graph_refs, dict) else {}
        for node_id in graph_refs_dict.get("node_ids", []):
            node = self._store.get_graph_node(str(node_id))
            if node and node.get("claim_id"):
                claim_ids.append(str(node["claim_id"]))
        for edge_id in graph_refs_dict.get("edge_ids", []):
            edge = self._store.get_graph_edge(str(edge_id))
            if edge and edge.get("claim_id"):
                claim_ids.append(str(edge["claim_id"]))
        supporting_refs = item.get("supporting_refs", {})
        if isinstance(supporting_refs, dict) and supporting_refs.get("claim_id"):
            claim_ids.append(str(supporting_refs["claim_id"]))
        return self._dedupe(claim_ids)

    def _source_ref_for_claim(
        self,
        claim: dict[str, object],
    ) -> dict[str, object]:
        source_id = claim.get("source_id")
        source = self._store.get_source(str(source_id)) if source_id else None
        source_ref = {
            "claim_id": str(claim["claim_id"]),
            "source_id": str(source_id) if source_id else "",
            "source_span": claim.get("source_span", {}),
            "trace_refs": claim.get("trace_refs", {}),
        }
        if not source:
            return source_ref
        source_ref["source_type"] = source.get("source_type")
        source_ref["title"] = source.get("title")
        return source_ref

    def _dropped_claim_ref(
        self,
        *,
        claim_id: str,
        item: dict[str, object],
        reason: str,
    ) -> dict[str, object]:
        return {
            "claim_id": claim_id,
            "reason": reason,
            "retrieval_result_id": str(item.get("result_id") or ""),
            "view_type": str(item.get("_view_type") or ""),
        }

    def _artifact_refs_for_item(self, item: dict[str, object]) -> list[dict[str, object]]:
        refs: list[dict[str, object]] = []
        source_ref = item.get("source_ref", {})
        if isinstance(source_ref, dict) and source_ref:
            refs.append({"ref_type": "source", **source_ref})
        for ref in item.get("evidence_refs", []):
            if isinstance(ref, dict):
                refs.append({"ref_type": "evidence_ref", **ref})
        return refs

    def _formal_refs(self, item: dict[str, object]) -> list[dict[str, str]]:
        refs = item.get("formal_refs", [])
        if not isinstance(refs, list):
            return []
        return [
            {
                "object_type": str(ref.get("object_type") or ""),
                "object_id": str(ref.get("object_id") or ""),
            }
            for ref in refs
            if isinstance(ref, dict)
        ]

    def _summarize(self, citations: list[dict[str, object]]) -> str:
        parts = [
            f"[{citation['claim_id']}] {citation['text']}"
            for citation in citations[:3]
        ]
        suffix = "" if len(citations) <= 3 else f" (+{len(citations) - 3} more claims)"
        return f"Based on {len(citations)} grounded claim(s): " + "; ".join(parts) + suffix

    def _skipped_memory_recall(
        self,
        *,
        workspace_id: str,
        question: str,
        reason: str,
        trace_refs: dict[str, object],
    ) -> dict[str, object]:
        return {
            "status": "skipped",
            "requested_method": "hybrid",
            "applied_method": "hybrid",
            "reason": reason,
            "query_text": question,
            "total": 0,
            "items": [],
            "trace_refs": {
                "workspace_id": workspace_id,
                "context_type": "graphrag_query",
                "context_ref": trace_refs,
            },
        }

    def _claim_ids(self, citations: list[dict[str, object]]) -> list[str]:
        return self._dedupe([str(item["claim_id"]) for item in citations])

    def _merge_graph_refs(self, citations: list[dict[str, object]]) -> dict[str, list[str]]:
        node_ids: list[str] = []
        edge_ids: list[str] = []
        for citation in citations:
            graph_refs = citation.get("graph_refs", {})
            if not isinstance(graph_refs, dict):
                continue
            node_ids.extend(str(item) for item in graph_refs.get("node_ids", []))
            edge_ids.extend(str(item) for item in graph_refs.get("edge_ids", []))
        return {"node_ids": self._dedupe(node_ids), "edge_ids": self._dedupe(edge_ids)}

    def _source_artifact_refs(
        self, citations: list[dict[str, object]]
    ) -> list[dict[str, object]]:
        refs: list[dict[str, object]] = []
        seen: set[str] = set()
        for citation in citations:
            for ref in citation.get("source_artifact_refs", []):
                if not isinstance(ref, dict):
                    continue
                key = repr(sorted(ref.items(), key=lambda item: str(item[0])))
                if key in seen:
                    continue
                seen.add(key)
                refs.append(ref)
        return refs

    def _dedupe(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            normalized = str(value).strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
        return result
