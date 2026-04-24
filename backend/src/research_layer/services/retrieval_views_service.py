from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.api.schemas.retrieval import RETRIEVAL_VIEW_VALUES, RETRIEVE_METHOD_VALUES
from research_layer.services.evermemos_bridge_service import EverMemOSRecallService

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
_AUTHORITY_TIER_ORDER = {
    "tier_a_peer_reviewed": 5,
    "tier_b_preprint_or_official_report": 4,
    "tier_c_internal_research_note": 3,
    "tier_d_feedback_or_dialogue": 2,
    "tier_e_unverified_external": 1,
}


@dataclass(slots=True)
class RetrievalServiceError(Exception):
    status_code: int
    error_code: str
    message: str
    details: dict[str, object]

    def __str__(self) -> str:
        return self.message


@dataclass(slots=True)
class RetrievalDocument:
    result_id: str
    title: str
    text: str
    source_ref: dict[str, object]
    graph_refs: dict[str, object]
    formal_refs: list[dict[str, str]]
    supporting_refs: dict[str, object]
    metadata: dict[str, object]


class RetrievalContext:
    def __init__(self, store: ResearchApiStateStore, workspace_id: str) -> None:
        self._store = store
        self.workspace_id = workspace_id
        self._source_cache: dict[str, dict[str, object]] = {}
        self.confirmed_objects = store.list_confirmed_objects(workspace_id)
        self.confirmed_by_ref: dict[tuple[str, str], dict[str, object]] = {
            (str(item["object_type"]), str(item["object_id"])): item
            for item in self.confirmed_objects
        }
        self.graph_nodes = store.list_graph_nodes(workspace_id)
        self.graph_edges = store.list_graph_edges(workspace_id)
        self.graph_node_by_id: dict[str, dict[str, object]] = {
            str(node["node_id"]): node for node in self.graph_nodes
        }
        self.graph_edge_by_id: dict[str, dict[str, object]] = {
            str(edge["edge_id"]): edge for edge in self.graph_edges
        }
        self.node_ids_by_object: dict[tuple[str, str], list[str]] = defaultdict(list)
        self.node_status_by_object: dict[tuple[str, str], list[str]] = defaultdict(list)
        self.edge_ids_by_node: dict[str, list[str]] = defaultdict(list)
        for node in self.graph_nodes:
            key = (str(node["object_ref_type"]), str(node["object_ref_id"]))
            self.node_ids_by_object[key].append(str(node["node_id"]))
            self.node_status_by_object[key].append(str(node["status"]))
        for edge in self.graph_edges:
            edge_id = str(edge["edge_id"])
            self.edge_ids_by_node[str(edge["source_node_id"])].append(edge_id)
            self.edge_ids_by_node[str(edge["target_node_id"])].append(edge_id)
        workspace = store.get_graph_workspace(workspace_id)
        self.version_id = (
            str(workspace["latest_version_id"])
            if workspace and workspace.get("latest_version_id")
            else None
        )

    def evidence_refs_for_formal_refs(
        self, formal_refs: list[dict[str, str]]
    ) -> list[dict[str, object]]:
        return self._store.list_evidence_refs(
            workspace_id=self.workspace_id, formal_refs=formal_refs
        )

    def authority_summary_for_formal_refs(
        self, formal_refs: list[dict[str, str]]
    ) -> dict[str, object]:
        evidence_refs = self.evidence_refs_for_formal_refs(formal_refs)
        if not evidence_refs:
            return {
                "top_authority_tier": None,
                "mean_authority_score": 0.0,
                "source_count": 0,
            }
        tiers = [str(item.get("authority_tier") or "") for item in evidence_refs]
        scores = [
            float(item.get("authority_score") or 0.0)
            for item in evidence_refs
            if item.get("authority_score") is not None
        ]
        source_ids = {
            str(item.get("source_id"))
            for item in evidence_refs
            if str(item.get("source_id") or "").strip()
        }
        return {
            "top_authority_tier": (
                max(tiers, key=lambda value: _AUTHORITY_TIER_ORDER.get(value, 0))
                if tiers
                else None
            ),
            "mean_authority_score": round(sum(scores) / len(scores), 4) if scores else 0.0,
            "source_count": len(source_ids),
        }

    def get_source_ref(self, source_id: str | None) -> dict[str, object]:
        if not source_id:
            return {}
        sid = str(source_id)
        if sid not in self._source_cache:
            source = self._store.get_source(sid)
            self._source_cache[sid] = source or {}
        source = self._source_cache[sid]
        if not source:
            return {"source_id": sid}
        return {
            "source_id": sid,
            "source_type": source.get("source_type"),
            "title": source.get("title"),
        }

    def source_id_for_formal_ref(self, object_type: str, object_id: str) -> str | None:
        obj = self.confirmed_by_ref.get((object_type, object_id))
        if obj is None:
            return None
        source_id = obj.get("source_id")
        return str(source_id) if source_id else None

    def claim_id_for_formal_ref(self, object_type: str, object_id: str) -> str | None:
        obj = self.confirmed_by_ref.get((object_type, object_id))
        if obj is None:
            return None
        claim_id = obj.get("claim_id")
        return str(claim_id) if claim_id else None

    def source_id_for_node_ref(self, node_id: str) -> str | None:
        node = self._store.get_graph_node(node_id)
        if node is None:
            return None
        object_type = str(node.get("object_ref_type", "")).strip()
        object_id = str(node.get("object_ref_id", "")).strip()
        if not object_type or not object_id:
            return None
        return self.source_id_for_formal_ref(object_type, object_id)

    def graph_refs_for_formal_refs(
        self,
        formal_refs: list[dict[str, str]],
        *,
        extra_node_ids: list[str] | None = None,
        extra_edge_ids: list[str] | None = None,
    ) -> dict[str, object]:
        node_ids: set[str] = set(extra_node_ids or [])
        edge_ids: set[str] = set(extra_edge_ids or [])
        node_statuses: list[str] = []
        for formal_ref in formal_refs:
            key = (
                str(formal_ref.get("object_type", "")),
                str(formal_ref.get("object_id", "")),
            )
            current_nodes = self.node_ids_by_object.get(key, [])
            node_ids.update(current_nodes)
            node_statuses.extend(self.node_status_by_object.get(key, []))
        for node_id in list(node_ids):
            edge_ids.update(self.edge_ids_by_node.get(node_id, []))
        return {
            "node_ids": sorted(node_ids),
            "edge_ids": sorted(edge_ids),
            "node_statuses": sorted({status for status in node_statuses if status}),
            "version_id": self.version_id,
        }


class RetrievalViewServiceBase:
    view_type: str = ""
    allowed_filter_keys: set[str] = set()

    def collect_documents(
        self,
        *,
        context: RetrievalContext,
    ) -> list[RetrievalDocument]:
        raise NotImplementedError


class EvidenceRetrieverService(RetrievalViewServiceBase):
    view_type = "evidence"
    allowed_filter_keys = {"source_id", "node_status"}

    def collect_documents(self, *, context: RetrievalContext) -> list[RetrievalDocument]:
        docs: list[RetrievalDocument] = []
        for item in context.confirmed_objects:
            if str(item["object_type"]) != "evidence":
                continue
            object_id = str(item["object_id"])
            source_id = str(item.get("source_id", ""))
            formal_refs = [{"object_type": "evidence", "object_id": object_id}]
            graph_refs = context.graph_refs_for_formal_refs(formal_refs)
            docs.append(
                RetrievalDocument(
                    result_id=f"evidence:{object_id}",
                    title=f"Evidence {object_id}",
                    text=str(item.get("text", "")),
                    source_ref=context.get_source_ref(source_id),
                    graph_refs=graph_refs,
                    formal_refs=formal_refs,
                    supporting_refs={"source_id": source_id},
                    metadata={
                        "source_id": source_id,
                        "node_status": graph_refs.get("node_statuses", []),
                    },
                )
            )
        return docs


class ContradictionRetrieverService(RetrievalViewServiceBase):
    view_type = "contradiction"
    allowed_filter_keys = {"source_id", "node_status"}

    def collect_documents(self, *, context: RetrievalContext) -> list[RetrievalDocument]:
        docs: list[RetrievalDocument] = []
        for item in context.confirmed_objects:
            if str(item["object_type"]) != "conflict":
                continue
            object_id = str(item["object_id"])
            source_id = str(item.get("source_id", ""))
            formal_refs = [{"object_type": "conflict", "object_id": object_id}]
            graph_refs = context.graph_refs_for_formal_refs(formal_refs)
            docs.append(
                RetrievalDocument(
                    result_id=f"contradiction:{object_id}",
                    title=f"Contradiction {object_id}",
                    text=str(item.get("text", "")),
                    source_ref=context.get_source_ref(source_id),
                    graph_refs=graph_refs,
                    formal_refs=formal_refs,
                    supporting_refs={"source_id": source_id},
                    metadata={
                        "source_id": source_id,
                        "node_status": graph_refs.get("node_statuses", []),
                    },
                )
            )
        return docs


class FailurePatternRetrieverService(RetrievalViewServiceBase):
    view_type = "failure_pattern"
    allowed_filter_keys = {"severity", "target_type"}

    def collect_documents(self, *, context: RetrievalContext) -> list[RetrievalDocument]:
        docs: list[RetrievalDocument] = []
        for failure in context._store.list_failures(workspace_id=context.workspace_id):
            failure_id = str(failure["failure_id"])
            attached_targets = [
                target
                for target in failure.get("attached_targets", [])
                if isinstance(target, dict)
            ]
            node_ids = [
                str(target.get("target_id", ""))
                for target in attached_targets
                if str(target.get("target_type", "")) == "node"
            ]
            edge_ids = [
                str(target.get("target_id", ""))
                for target in attached_targets
                if str(target.get("target_type", "")) == "edge"
            ]
            inferred_formal_refs: list[dict[str, str]] = [
                {"object_type": "failure_report", "object_id": failure_id}
            ]
            source_ids: set[str] = set()
            for node_id in node_ids:
                node = context._store.get_graph_node(node_id)
                if node is None:
                    continue
                object_type = str(node.get("object_ref_type", "")).strip()
                object_id = str(node.get("object_ref_id", "")).strip()
                if object_type and object_id:
                    inferred_formal_refs.append(
                        {"object_type": object_type, "object_id": object_id}
                    )
                    source_id = context.source_id_for_formal_ref(object_type, object_id)
                    if source_id:
                        source_ids.add(source_id)
            graph_refs = context.graph_refs_for_formal_refs(
                inferred_formal_refs,
                extra_node_ids=node_ids,
                extra_edge_ids=edge_ids,
            )
            primary_source_id = sorted(source_ids)[0] if source_ids else None
            docs.append(
                RetrievalDocument(
                    result_id=f"failure_pattern:{failure_id}",
                    title=f"Failure Pattern {failure_id}",
                    text=(
                        f"{failure.get('failure_reason', '')}. "
                        f"{failure.get('observed_outcome', '')}. "
                        f"{failure.get('expected_difference', '')}"
                    ).strip(),
                    source_ref=context.get_source_ref(primary_source_id),
                    graph_refs=graph_refs,
                    formal_refs=inferred_formal_refs,
                    supporting_refs={
                        "failure_id": failure_id,
                        "attached_targets": attached_targets,
                    },
                    metadata={
                        "severity": str(failure.get("severity", "")),
                        "target_type": [
                            str(item.get("target_type", ""))
                            for item in attached_targets
                            if str(item.get("target_type", ""))
                        ],
                    },
                )
            )
        return docs


class ValidationHistoryRetrieverService(RetrievalViewServiceBase):
    view_type = "validation_history"
    allowed_filter_keys = {"method", "target_object"}

    def collect_documents(self, *, context: RetrievalContext) -> list[RetrievalDocument]:
        docs: list[RetrievalDocument] = []
        for item in context.confirmed_objects:
            if str(item["object_type"]) != "validation":
                continue
            object_id = str(item["object_id"])
            source_id = str(item.get("source_id", ""))
            formal_refs = [{"object_type": "validation", "object_id": object_id}]
            graph_refs = context.graph_refs_for_formal_refs(formal_refs)
            docs.append(
                RetrievalDocument(
                    result_id=f"validation_object:{object_id}",
                    title=f"Validation Object {object_id}",
                    text=str(item.get("text", "")),
                    source_ref=context.get_source_ref(source_id),
                    graph_refs=graph_refs,
                    formal_refs=formal_refs,
                    supporting_refs={"source_id": source_id},
                    metadata={
                        "method": "confirmed_validation_object",
                        "target_object": f"validation:{object_id}",
                    },
                )
            )

        for item in context._store.list_validations(workspace_id=context.workspace_id):
            validation_id = str(item["validation_id"])
            target_object = str(item.get("target_object", ""))
            target_type, _, target_id = target_object.partition(":")
            formal_refs = [
                {"object_type": "validation_action", "object_id": validation_id}
            ]
            source_id: str | None = None
            extra_node_ids: list[str] = []
            extra_edge_ids: list[str] = []
            if target_type == "node" and target_id:
                extra_node_ids.append(target_id)
                node = context._store.get_graph_node(target_id)
                if node is not None:
                    object_type = str(node.get("object_ref_type", "")).strip()
                    object_id = str(node.get("object_ref_id", "")).strip()
                    if object_type and object_id:
                        formal_refs.append(
                            {"object_type": object_type, "object_id": object_id}
                        )
                        source_id = context.source_id_for_formal_ref(
                            object_type, object_id
                        )
                if source_id is None:
                    source_id = context.source_id_for_node_ref(target_id)
            elif target_type == "edge" and target_id:
                extra_edge_ids.append(target_id)
                edge = context._store.get_graph_edge(target_id)
                if edge is not None:
                    source_node_id = str(edge.get("source_node_id", ""))
                    target_node_id = str(edge.get("target_node_id", ""))
                    if source_node_id:
                        extra_node_ids.append(source_node_id)
                    if target_node_id:
                        extra_node_ids.append(target_node_id)
                    object_type = str(edge.get("object_ref_type", "")).strip()
                    object_id = str(edge.get("object_ref_id", "")).strip()
                    if object_type and object_id:
                        formal_refs.append(
                            {"object_type": object_type, "object_id": object_id}
                        )
                        source_id = context.source_id_for_formal_ref(
                            object_type, object_id
                        )
                if source_id is None:
                    for node_id in extra_node_ids:
                        source_id = context.source_id_for_node_ref(node_id)
                        if source_id is not None:
                            break
            elif target_type and target_id:
                formal_refs.append({"object_type": target_type, "object_id": target_id})
                source_id = context.source_id_for_formal_ref(target_type, target_id)
            graph_refs = context.graph_refs_for_formal_refs(
                formal_refs,
                extra_node_ids=extra_node_ids,
                extra_edge_ids=extra_edge_ids,
            )
            docs.append(
                RetrievalDocument(
                    result_id=f"validation_action:{validation_id}",
                    title=f"Validation Action {validation_id}",
                    text=(
                        f"{item.get('method', '')}. "
                        f"success: {item.get('success_signal', '')}. "
                        f"weakening: {item.get('weakening_signal', '')}"
                    ).strip(),
                    source_ref=context.get_source_ref(source_id),
                    graph_refs=graph_refs,
                    formal_refs=formal_refs,
                    supporting_refs={"validation_id": validation_id},
                    metadata={
                        "method": str(item.get("method", "")),
                        "target_object": target_object,
                    },
                )
            )
        return docs


class HypothesisSupportRetrieverService(RetrievalViewServiceBase):
    view_type = "hypothesis_support"
    allowed_filter_keys = {"hypothesis_status", "trigger_type"}

    def collect_documents(self, *, context: RetrievalContext) -> list[RetrievalDocument]:
        docs: list[RetrievalDocument] = []
        for hypothesis in context._store.list_hypotheses(workspace_id=context.workspace_id):
            hypothesis_id = str(hypothesis["hypothesis_id"])
            trigger_refs = [
                item for item in hypothesis.get("trigger_refs", []) if isinstance(item, dict)
            ]
            related_object_ids = [
                item
                for item in hypothesis.get("related_object_ids", [])
                if isinstance(item, dict)
            ]
            formal_refs: list[dict[str, str]] = [
                {"object_type": "hypothesis", "object_id": hypothesis_id}
            ]
            for item in related_object_ids:
                object_type = str(item.get("object_type", "")).strip()
                object_id = str(item.get("object_id", "")).strip()
                if object_type and object_id:
                    formal_refs.append({"object_type": object_type, "object_id": object_id})
            extra_node_ids: list[str] = []
            for trigger in trigger_refs:
                trace_refs = trigger.get("trace_refs", {})
                if isinstance(trace_refs, dict):
                    graph_node_id = trace_refs.get("graph_node_id")
                    if graph_node_id:
                        extra_node_ids.append(str(graph_node_id))
                    route_node_ids = trace_refs.get("route_node_ids", [])
                    if isinstance(route_node_ids, list):
                        extra_node_ids.extend(str(node_id) for node_id in route_node_ids)
            graph_refs = context.graph_refs_for_formal_refs(
                formal_refs, extra_node_ids=extra_node_ids
            )
            source_ids: set[str] = set()
            for ref in formal_refs:
                source_id = context.source_id_for_formal_ref(
                    str(ref.get("object_type", "")), str(ref.get("object_id", ""))
                )
                if source_id:
                    source_ids.add(source_id)
            primary_source_id = sorted(source_ids)[0] if source_ids else None
            trigger_types = [
                str(item.get("trigger_type", ""))
                for item in trigger_refs
                if str(item.get("trigger_type", ""))
            ]
            docs.append(
                RetrievalDocument(
                    result_id=f"hypothesis:{hypothesis_id}",
                    title=str(hypothesis.get("title", f"Hypothesis {hypothesis_id}")),
                    text=(
                        f"{hypothesis.get('summary', '')}. "
                        f"{hypothesis.get('premise', '')}. "
                        f"{hypothesis.get('rationale', '')}"
                    ).strip(),
                    source_ref=context.get_source_ref(primary_source_id),
                    graph_refs=graph_refs,
                    formal_refs=formal_refs,
                    supporting_refs={
                        "hypothesis_id": hypothesis_id,
                        "trigger_refs": trigger_refs,
                        "minimum_validation_action": hypothesis.get(
                            "minimum_validation_action", {}
                        ),
                    },
                    metadata={
                        "hypothesis_status": str(hypothesis.get("status", "")),
                        "trigger_type": trigger_types,
                    },
                )
            )
        return docs


class ResearchRetrievalService:
    def __init__(self, store: ResearchApiStateStore) -> None:
        self._store = store
        self._memory_recall_service = EverMemOSRecallService(store)
        self._view_services: dict[str, RetrievalViewServiceBase] = {
            "evidence": EvidenceRetrieverService(),
            "contradiction": ContradictionRetrieverService(),
            "failure_pattern": FailurePatternRetrieverService(),
            "validation_history": ValidationHistoryRetrieverService(),
            "hypothesis_support": HypothesisSupportRetrieverService(),
        }

    def _raise(
        self,
        *,
        status_code: int,
        error_code: str,
        message: str,
        details: dict[str, object] | None = None,
    ) -> None:
        raise RetrievalServiceError(
            status_code=status_code,
            error_code=error_code,
            message=message,
            details=details or {},
        )

    def retrieve(
        self,
        *,
        workspace_id: str,
        view_type: str,
        query: str,
        retrieve_method: str,
        top_k: int,
        metadata_filters: dict[str, object],
        request_id: str,
    ) -> dict[str, object]:
        view = str(view_type).strip()
        method = str(retrieve_method).strip().lower()
        if view not in RETRIEVAL_VIEW_VALUES or view not in self._view_services:
            self._raise(
                status_code=400,
                error_code="research.invalid_request",
                message="unsupported retrieval view_type",
                details={"view_type": view},
            )
        if method not in RETRIEVE_METHOD_VALUES:
            self._raise(
                status_code=400,
                error_code="research.invalid_request",
                message="unsupported retrieve_method",
                details={"retrieve_method": retrieve_method},
            )
        if top_k <= 0 or top_k > 100:
            self._raise(
                status_code=400,
                error_code="research.invalid_request",
                message="top_k must be in [1, 100]",
                details={"top_k": top_k},
            )
        if not isinstance(metadata_filters, dict):
            self._raise(
                status_code=400,
                error_code="research.invalid_request",
                message="metadata_filters must be an object",
                details={"metadata_filters_type": type(metadata_filters).__name__},
            )
        service = self._view_services[view]
        query_ref = self._build_query_ref(query, retrieve_method=method)
        metadata_filter_refs = self._build_filter_refs_from_raw(metadata_filters)

        self._store.emit_event(
            event_name="retrieval_view_started",
            request_id=request_id,
            job_id=None,
            workspace_id=workspace_id,
            component="retrieval_views_service",
            step=view,
            status="started",
            refs={
                "view_type": view,
                "retrieve_method": method,
                "query_ref": query_ref,
                "metadata_filter_refs": metadata_filter_refs,
            },
            metrics={"top_k": top_k},
        )

        try:
            filter_values = self._normalize_filter_values(metadata_filters)
            metadata_filter_refs = self._build_filter_refs(filter_values)
            invalid_filter_keys = sorted(
                key for key in filter_values if key not in service.allowed_filter_keys
            )
            if invalid_filter_keys:
                self._raise(
                    status_code=400,
                    error_code="research.invalid_request",
                    message="unsupported metadata_filters for retrieval view",
                    details={
                        "view_type": view,
                        "invalid_filter_keys": invalid_filter_keys,
                        "allowed_filter_keys": sorted(service.allowed_filter_keys),
                    },
                )
            context = RetrievalContext(self._store, workspace_id)
            docs = service.collect_documents(context=context)
            filtered = self._apply_filters(docs=docs, filters=filter_values)
            ranked = self._rank_documents(
                docs=filtered,
                query=query,
                retrieve_method=method,
                query_ref=query_ref,
            )[:top_k]
            response_items = [
                self._to_response_item(
                    doc=document,
                    score=score,
                    context=context,
                    retrieve_method=method,
                    query_ref=query_ref,
                )
                for document, score in ranked
            ]
            scope_claim_ids = self._scope_claim_ids_for_docs(
                docs=[document for document, _score in ranked],
                context=context,
            )
            memory_recall = self._memory_recall_service.recall(
                workspace_id=workspace_id,
                query_text=query,
                requested_method=method,
                scope_claim_ids=scope_claim_ids,
                scope_mode="prefer",
                top_k=min(top_k, 8),
                request_id=request_id,
                trace_refs={"context_type": "retrieval_view", "view_type": view},
            )
            response = {
                "view_type": view,
                "workspace_id": workspace_id,
                "retrieve_method": method,
                "query_ref": query_ref,
                "metadata_filter_refs": metadata_filter_refs,
                "total": len(response_items),
                "items": response_items,
                "memory_recall": memory_recall,
            }
            self._store.emit_event(
                event_name="retrieval_view_completed",
                request_id=request_id,
                job_id=None,
                workspace_id=workspace_id,
                component="retrieval_views_service",
                step=view,
                status="completed",
                refs={
                    "view_type": view,
                    "retrieve_method": method,
                    "query_ref": query_ref,
                    "metadata_filter_refs": metadata_filter_refs,
                },
                metrics=self._build_result_metrics(response_items, top_k=top_k),
            )
            return response
        except RetrievalServiceError as exc:
            self._store.emit_event(
                event_name="retrieval_view_completed",
                request_id=request_id,
                job_id=None,
                workspace_id=workspace_id,
                component="retrieval_views_service",
                step=view,
                status="failed",
                refs={
                    "view_type": view,
                    "retrieve_method": method,
                    "query_ref": query_ref,
                    "metadata_filter_refs": metadata_filter_refs,
                },
                error={
                    "error_code": exc.error_code,
                    "message": exc.message,
                    "details": exc.details,
                },
            )
            raise

    def _scope_claim_ids_for_docs(
        self,
        *,
        docs: list[RetrievalDocument],
        context: RetrievalContext,
    ) -> list[str]:
        claim_ids: list[str] = []
        seen: set[str] = set()
        for doc in docs:
            for formal_ref in doc.formal_refs:
                if not isinstance(formal_ref, dict):
                    continue
                object_type = str(formal_ref.get("object_type", "")).strip()
                object_id = str(formal_ref.get("object_id", "")).strip()
                if not object_type or not object_id:
                    continue
                claim_id = context.claim_id_for_formal_ref(object_type, object_id)
                if not claim_id or claim_id in seen:
                    continue
                seen.add(claim_id)
                claim_ids.append(claim_id)
        return claim_ids

    def resolve_memory_item(
        self, *, workspace_id: str, view_type: str, result_id: str
    ) -> dict[str, object] | None:
        view = str(view_type).strip()
        if view not in RETRIEVAL_VIEW_VALUES or view not in self._view_services:
            return None
        context = RetrievalContext(self._store, workspace_id)
        service = self._view_services[view]
        for doc in service.collect_documents(context=context):
            if str(doc.result_id) != str(result_id):
                continue
            item = self._to_response_item(
                doc=doc,
                score=1.0,
                context=context,
                retrieve_method="hybrid",
                query_ref={},
            )
            return {
                "result_id": item["result_id"],
                "title": item["title"],
                "snippet": item["snippet"],
                "source_ref": item["source_ref"],
                "graph_refs": item["graph_refs"],
                "formal_refs": item["formal_refs"],
                "supporting_refs": item["supporting_refs"],
                "trace_refs": item["trace_refs"],
                "evidence_refs": item["evidence_refs"],
                "evidence_highlight_spans": item.get("evidence_highlight_spans", []),
                "mechanism_relation_highlights": item.get(
                    "mechanism_relation_highlights", []
                ),
                "authority_summary": item["authority_summary"],
            }
        return None

    def _normalize_filter_values(
        self, metadata_filters: dict[str, object]
    ) -> dict[str, set[str]]:
        normalized: dict[str, set[str]] = {}
        for key, raw_value in metadata_filters.items():
            key_str = str(key).strip()
            if not key_str:
                self._raise(
                    status_code=400,
                    error_code="research.invalid_request",
                    message="metadata filter key must not be empty",
                )
            if isinstance(raw_value, str):
                values = {raw_value.strip()} if raw_value.strip() else set()
            elif isinstance(raw_value, list):
                values = {str(item).strip() for item in raw_value if str(item).strip()}
            else:
                self._raise(
                    status_code=400,
                    error_code="research.invalid_request",
                    message="metadata filter value must be string or array",
                    details={"filter_key": key_str},
                )
            normalized[key_str] = values
        return normalized

    def _apply_filters(
        self, *, docs: list[RetrievalDocument], filters: dict[str, set[str]]
    ) -> list[RetrievalDocument]:
        if not filters:
            return docs
        results: list[RetrievalDocument] = []
        for doc in docs:
            accepted = True
            for key, expected_values in filters.items():
                if not expected_values:
                    continue
                actual = doc.metadata.get(key)
                if isinstance(actual, list):
                    actual_values = {str(item) for item in actual}
                    if not (actual_values & expected_values):
                        accepted = False
                        break
                else:
                    if str(actual) not in expected_values:
                        accepted = False
                        break
            if accepted:
                results.append(doc)
        return results

    def _rank_documents(
        self,
        *,
        docs: list[RetrievalDocument],
        query: str,
        retrieve_method: str,
        query_ref: dict[str, object],
    ) -> list[tuple[RetrievalDocument, float]]:
        ranked: list[tuple[RetrievalDocument, float]] = []
        for doc in docs:
            score = self._score_document(
                query=query,
                text=f"{doc.title}. {doc.text}",
                retrieve_method=retrieve_method,
                query_ref=query_ref,
            )
            ranked.append((doc, score))
        ranked.sort(key=lambda item: (-item[1], item[0].result_id))
        return ranked

    def _score_document(
        self,
        *,
        query: str,
        text: str,
        retrieve_method: str,
        query_ref: dict[str, object],
    ) -> float:
        keyword_score = self._keyword_score(query=query, text=text)
        vector_score = self._vector_score(query=query, text=text)
        if retrieve_method == "keyword":
            return round(keyword_score, 6)
        if retrieve_method == "vector":
            return round(vector_score, 6)
        if retrieve_method == "logical":
            logical_score = self._logical_score(
                query=query,
                text=text,
                logical_subgoals=query_ref.get("logical_subgoals", []),
            )
            return round(
                0.4 * keyword_score + 0.25 * vector_score + 0.35 * logical_score, 6
            )
        return round(0.6 * keyword_score + 0.4 * vector_score, 6)

    def _logical_score(
        self, *, query: str, text: str, logical_subgoals: object
    ) -> float:
        subgoals = (
            logical_subgoals
            if isinstance(logical_subgoals, list)
            else self._extract_logical_subgoals(query)
        )
        if not subgoals:
            return self._keyword_score(query=query, text=text)
        text_tokens = set(self._tokenize(text))
        if not text_tokens:
            return 0.0
        covered = 0
        for subgoal in subgoals:
            if not isinstance(subgoal, dict):
                continue
            token_values = subgoal.get("tokens", [])
            tokens = (
                {str(item).strip().lower() for item in token_values if str(item).strip()}
                if isinstance(token_values, list)
                else set()
            )
            if not tokens:
                continue
            if tokens & text_tokens:
                covered += 1
        if covered == 0:
            return 0.0
        return covered / max(1, len(subgoals))

    def _keyword_score(self, *, query: str, text: str) -> float:
        query_tokens = set(self._tokenize(query))
        if not query_tokens:
            return 1.0
        text_tokens = set(self._tokenize(text))
        if not text_tokens:
            return 0.0
        overlap = len(query_tokens & text_tokens)
        return overlap / max(1, len(query_tokens))

    def _vector_score(self, *, query: str, text: str) -> float:
        query_terms = self._tokenize(query)
        if not query_terms:
            return 1.0
        doc_terms = self._tokenize(text)
        if not doc_terms:
            return 0.0
        query_counter = Counter(query_terms)
        doc_counter = Counter(doc_terms)
        dot = 0.0
        for term, q_value in query_counter.items():
            dot += q_value * doc_counter.get(term, 0.0)
        query_norm = math.sqrt(sum(value * value for value in query_counter.values()))
        doc_norm = math.sqrt(sum(value * value for value in doc_counter.values()))
        if query_norm == 0.0 or doc_norm == 0.0:
            return 0.0
        return dot / (query_norm * doc_norm)

    def _tokenize(self, text: str) -> list[str]:
        return [token.lower() for token in _TOKEN_RE.findall(text or "")]

    def _to_response_item(
        self,
        *,
        doc: RetrievalDocument,
        score: float,
        context: RetrievalContext,
        retrieve_method: str,
        query_ref: dict[str, object],
    ) -> dict[str, object]:
        evidence_refs = context.evidence_refs_for_formal_refs(doc.formal_refs)
        authority_summary = context.authority_summary_for_formal_refs(doc.formal_refs)
        evidence_highlight_spans = self._build_evidence_highlight_spans(
            doc=doc,
            evidence_refs=evidence_refs,
        )
        mechanism_relation_highlights = self._build_mechanism_relation_highlights(
            doc=doc,
            context=context,
            query_ref=query_ref,
            retrieve_method=retrieve_method,
        )
        mutual_index: dict[str, object] | None = None
        if retrieve_method == "logical":
            formal_ref_keys = sorted(
                {
                    f"{str(ref.get('object_type', ''))}:{str(ref.get('object_id', ''))}"
                    for ref in doc.formal_refs
                    if str(ref.get("object_type", "")).strip()
                    and str(ref.get("object_id", "")).strip()
                }
            )
            graph_node_ids = [
                str(item)
                for item in (doc.graph_refs.get("node_ids", []) if doc.graph_refs else [])
                if str(item).strip()
            ]
            graph_edge_ids = [
                str(item)
                for item in (doc.graph_refs.get("edge_ids", []) if doc.graph_refs else [])
                if str(item).strip()
            ]
            query_tokens = set(self._tokenize(str(query_ref.get("query_text", ""))))
            text_tokens = set(self._tokenize(doc.text))
            matched_terms = sorted(query_tokens & text_tokens)
            mutual_index = {
                "graph_to_text": {
                    "formal_ref_keys": formal_ref_keys,
                    "source_id": doc.source_ref.get("source_id"),
                    "graph_node_ids": graph_node_ids,
                },
                "text_to_graph": {
                    "graph_node_ids": graph_node_ids,
                    "graph_edge_ids": graph_edge_ids,
                    "matched_query_terms": matched_terms,
                },
            }
        trace_refs = {
            "source_ref": doc.source_ref,
            "graph_refs": doc.graph_refs,
            "formal_refs": doc.formal_refs,
            "supporting_refs": doc.supporting_refs,
            "evidence_highlight_spans": evidence_highlight_spans,
            "mechanism_relation_highlights": mechanism_relation_highlights,
        }
        if mutual_index is not None:
            trace_refs["mutual_index"] = mutual_index
        return {
            "result_id": doc.result_id,
            "score": score,
            "title": doc.title,
            "snippet": doc.text[:240],
            "source_ref": doc.source_ref,
            "graph_refs": doc.graph_refs,
            "formal_refs": doc.formal_refs,
            "supporting_refs": doc.supporting_refs,
            "trace_refs": trace_refs,
            "evidence_refs": evidence_refs,
            "evidence_highlight_spans": evidence_highlight_spans,
            "mechanism_relation_highlights": mechanism_relation_highlights,
            "authority_summary": authority_summary,
        }

    def _build_evidence_highlight_spans(
        self,
        *,
        doc: RetrievalDocument,
        evidence_refs: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        highlights: list[dict[str, object]] = []
        seen_keys: set[tuple[str, int | None, int | None, str]] = set()
        for ref in evidence_refs:
            locator = ref.get("locator", {})
            locator_dict = locator if isinstance(locator, dict) else {}
            start = self._coerce_optional_int(
                locator_dict.get("char_start", locator_dict.get("start"))
            )
            end = self._coerce_optional_int(
                locator_dict.get("char_end", locator_dict.get("end"))
            )
            if start is not None and end is not None and end < start:
                start, end = end, start
            claim_text = str(
                locator_dict.get("text")
                or ref.get("excerpt")
                or doc.text[:240]
                or ""
            ).strip()
            source_id = str(ref.get("source_id") or doc.source_ref.get("source_id") or "")
            dedupe_key = (source_id, start, end, claim_text)
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            highlights.append(
                {
                    "highlight_id": f"evidence_ref:{str(ref.get('ref_id', ''))}",
                    "claim_text": claim_text,
                    "span": {
                        "char_start": start,
                        "char_end": end,
                        "section": locator_dict.get("section"),
                        "paragraph_index": locator_dict.get("paragraph_index"),
                        "chunk_id": locator_dict.get("chunk_id"),
                    },
                    "source_ref": {
                        "source_id": source_id or None,
                        "title": ref.get("title"),
                    },
                    "trace_ref": {
                        "evidence_ref_id": str(ref.get("ref_id", "")),
                        "layer": str(ref.get("layer", "")),
                        "ref_type": str(ref.get("ref_type", "")),
                        "authority_tier": str(ref.get("authority_tier", "")),
                        "authority_score": ref.get("authority_score"),
                        "locator": locator_dict,
                    },
                }
            )
        if highlights:
            return highlights
        fallback_text = str(doc.text[:240]).strip()
        if not fallback_text:
            return []
        return [
            {
                "highlight_id": f"snippet:{doc.result_id}",
                "claim_text": fallback_text,
                "span": {
                    "char_start": 0,
                    "char_end": len(fallback_text),
                    "section": None,
                    "paragraph_index": None,
                    "chunk_id": None,
                },
                "source_ref": {
                    "source_id": doc.source_ref.get("source_id"),
                    "title": doc.source_ref.get("title"),
                },
                "trace_ref": {
                    "evidence_ref_id": None,
                    "layer": "snippet_fallback",
                    "ref_type": "fallback",
                    "authority_tier": None,
                    "authority_score": None,
                    "locator": {},
                },
            }
        ]

    def _build_mechanism_relation_highlights(
        self,
        *,
        doc: RetrievalDocument,
        context: RetrievalContext,
        query_ref: dict[str, object],
        retrieve_method: str,
    ) -> list[dict[str, object]]:
        graph_refs = doc.graph_refs if isinstance(doc.graph_refs, dict) else {}
        graph_edge_ids = [
            str(edge_id)
            for edge_id in graph_refs.get("edge_ids", [])
            if str(edge_id).strip()
        ]
        if not graph_edge_ids:
            return []
        mechanism_tokens = self._query_mechanism_tokens(query_ref=query_ref)
        highlights: list[dict[str, object]] = []
        for edge_id in graph_edge_ids:
            edge = context.graph_edge_by_id.get(edge_id)
            if edge is None:
                continue
            source_node_id = str(edge.get("source_node_id", "")).strip()
            target_node_id = str(edge.get("target_node_id", "")).strip()
            source_node = context.graph_node_by_id.get(source_node_id, {})
            target_node = context.graph_node_by_id.get(target_node_id, {})
            relation_tokens = self._expand_relation_tokens(
                tokens=self._tokenize(
                    " ".join(
                        [
                            str(edge.get("edge_type", "")),
                            str(edge.get("object_ref_type", "")),
                            str(source_node.get("short_label", "")),
                            str(target_node.get("short_label", "")),
                            str(source_node.get("node_type", "")),
                            str(target_node.get("node_type", "")),
                        ]
                    )
                )
            )
            matched_terms = sorted(mechanism_tokens & relation_tokens)
            if retrieve_method == "logical" and mechanism_tokens and not matched_terms:
                continue
            if retrieve_method != "logical" and mechanism_tokens and not matched_terms:
                continue
            highlights.append(
                {
                    "highlight_id": f"edge:{edge_id}",
                    "edge_ref": {
                        "edge_id": edge_id,
                        "edge_type": str(edge.get("edge_type", "")),
                        "source_node_id": source_node_id,
                        "target_node_id": target_node_id,
                    },
                    "relation_label": (
                        f"{str(source_node.get('short_label', source_node_id))} "
                        f"-[{str(edge.get('edge_type', ''))}]-> "
                        f"{str(target_node.get('short_label', target_node_id))}"
                    ),
                    "matched_query_terms": matched_terms,
                    "trace_ref": {
                        "query_role": "mechanism",
                        "mechanism_query_tokens": sorted(mechanism_tokens),
                        "relation_tokens": sorted(relation_tokens),
                    },
                }
            )
        return highlights

    def _query_mechanism_tokens(self, *, query_ref: dict[str, object]) -> set[str]:
        logical_subgoals = query_ref.get("logical_subgoals", [])
        if isinstance(logical_subgoals, list):
            for subgoal in logical_subgoals:
                if not isinstance(subgoal, dict):
                    continue
                if str(subgoal.get("role", "")) != "mechanism":
                    continue
                tokens = subgoal.get("tokens", [])
                if isinstance(tokens, list):
                    return self._expand_relation_tokens(
                        {
                            str(token).strip().lower()
                            for token in tokens
                            if str(token).strip()
                        }
                    )
        query_text = str(query_ref.get("query_text", ""))
        return self._expand_relation_tokens(set(self._tokenize(query_text)))

    def _expand_relation_tokens(self, tokens: set[str] | list[str]) -> set[str]:
        base = {str(token).strip().lower() for token in tokens if str(token).strip()}
        expanded = set(base)
        for token in list(base):
            if token.endswith("s") and len(token) > 3:
                expanded.add(token[:-1])
            elif len(token) > 2:
                expanded.add(f"{token}s")
        return expanded

    def _coerce_optional_int(self, value: object) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _build_query_ref(self, query: str, *, retrieve_method: str) -> dict[str, object]:
        normalized = " ".join((query or "").strip().split())
        terms = self._tokenize(normalized)
        digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]
        payload: dict[str, object] = {
            "query_sha1": digest,
            "query_length": len(normalized),
            "term_count": len(terms),
            "query_text": normalized,
        }
        if retrieve_method == "logical":
            logical_subgoals = self._extract_logical_subgoals(normalized)
            payload["logical_subgoals"] = logical_subgoals
            payload["logical_subgoal_count"] = len(logical_subgoals)
        return payload

    def _extract_logical_subgoals(self, query: str) -> list[dict[str, object]]:
        normalized = " ".join((query or "").strip().split())
        if not normalized:
            return []
        lowered = normalized.lower()
        segments = [
            part.strip()
            for part in re.split(r"[,;]| then | therefore | so that ", lowered)
            if part.strip()
        ]
        condition_text = ""
        mechanism_text = ""
        outcome_text = ""
        for part in segments:
            if not condition_text and any(
                marker in part for marker in ("if ", "when ", "under ", "given ")
            ):
                condition_text = part
                continue
            if not mechanism_text and any(
                marker in part
                for marker in (
                    "via ",
                    "through ",
                    "mechanism",
                    "reduce",
                    "increase",
                    "mitigate",
                )
            ):
                mechanism_text = part
                continue
            if not outcome_text and any(
                marker in part
                for marker in (
                    "outcome",
                    "result",
                    "latency",
                    "support",
                    "timeout",
                    "accuracy",
                )
            ):
                outcome_text = part
        if not condition_text and segments:
            condition_text = segments[0]
        if not mechanism_text:
            mechanism_text = segments[1] if len(segments) > 1 else normalized
        if not outcome_text:
            outcome_text = segments[-1] if segments else normalized
        role_text_pairs = [
            ("condition", condition_text),
            ("mechanism", mechanism_text),
            ("outcome", outcome_text),
        ]
        subgoals: list[dict[str, object]] = []
        for role, text in role_text_pairs:
            clean_text = " ".join(str(text).split())
            if not clean_text:
                continue
            tokens = sorted(set(self._tokenize(clean_text)))
            subgoals.append({"role": role, "text": clean_text, "tokens": tokens})
        return subgoals

    def _build_filter_refs(self, filters: dict[str, set[str]]) -> dict[str, object]:
        return {
            key: sorted(values)
            for key, values in sorted(filters.items(), key=lambda item: item[0])
        }

    def _build_filter_refs_from_raw(
        self, metadata_filters: dict[str, object]
    ) -> dict[str, object]:
        refs: dict[str, object] = {}
        for raw_key, raw_value in metadata_filters.items():
            key = str(raw_key).strip()
            if not key:
                key = "<empty>"
            if isinstance(raw_value, str):
                refs[key] = [raw_value.strip()] if raw_value.strip() else []
                continue
            if isinstance(raw_value, list):
                refs[key] = [
                    str(item).strip() for item in raw_value if str(item).strip()
                ]
                continue
            refs[key] = [f"<invalid:{type(raw_value).__name__}>"]
        return refs

    def _build_result_metrics(
        self, response_items: list[dict[str, object]], *, top_k: int
    ) -> dict[str, object]:
        source_ids: set[str] = set()
        node_ids: set[str] = set()
        edge_ids: set[str] = set()
        formal_refs: set[tuple[str, str]] = set()
        for item in response_items:
            source_ref = item.get("source_ref", {})
            if isinstance(source_ref, dict):
                source_id = source_ref.get("source_id")
                if source_id:
                    source_ids.add(str(source_id))
            graph_refs = item.get("graph_refs", {})
            if isinstance(graph_refs, dict):
                for node_id in graph_refs.get("node_ids", []):
                    node_ids.add(str(node_id))
                for edge_id in graph_refs.get("edge_ids", []):
                    edge_ids.add(str(edge_id))
            for formal in item.get("formal_refs", []):
                if not isinstance(formal, dict):
                    continue
                object_type = str(formal.get("object_type", ""))
                object_id = str(formal.get("object_id", ""))
                if object_type and object_id:
                    formal_refs.add((object_type, object_id))
        return {
            "hit_count": len(response_items),
            "top_k": top_k,
            "returned_result_ids": [
                str(item.get("result_id", "")) for item in response_items
            ],
            "source_ref_count": len(source_ids),
            "graph_ref_count": len(node_ids) + len(edge_ids),
            "formal_ref_count": len(formal_refs),
        }
