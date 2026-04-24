from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from core.observation.logger import get_logger
from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.services.claim_conflict_service import ClaimConflictService
from research_layer.services.evermemos_bridge_service import ResearchMemoryBridge
from research_layer.services.scholarly_source_service import ScholarlySourceService

logger = get_logger(__name__)


def normalize_candidate_text(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", text.strip())
    return collapsed.lower()


@dataclass(slots=True)
class CandidateConfirmationError(Exception):
    status_code: int
    error_code: str
    message: str
    details: dict[str, object]

    def __str__(self) -> str:
        return self.message


class CandidateConfirmationService:
    def __init__(self, store: ResearchApiStateStore) -> None:
        self._store = store
        self._active_statuses = {"active", "weakened", "conflicted", "failed"}
        self._scholarly_source_service = ScholarlySourceService(store)
        self._memory_bridge = ResearchMemoryBridge(store)
        self._claim_conflict_service = ClaimConflictService(store)

    def _node_type_for_object_type(self, object_type: str) -> str:
        return {
            "evidence": "evidence",
            "assumption": "assumption",
            "conclusion": "conclusion",
            "gap": "gap",
            "conflict": "conflict",
            "failure": "failure",
            "validation": "validation",
        }.get(object_type, "evidence")

    def _edge_type_for_node_type(self, node_type: str) -> str:
        if node_type == "assumption":
            return "requires"
        if node_type == "conflict":
            return "conflicts"
        if node_type == "failure":
            return "weakens"
        if node_type == "validation":
            return "validates"
        return "derives"

    def _build_short_label(self, raw_text: str) -> str:
        collapsed = re.sub(r"\s+", " ", str(raw_text or "").strip())
        if not collapsed:
            return "未命名节点"
        sentence_parts = re.split(r"[。！？!?;；]\s*", collapsed)
        first_sentence = next((part.strip() for part in sentence_parts if part.strip()), "")
        preferred = first_sentence or collapsed
        normalized_first_sentence = re.split(r"[。！？!?;；]\s*", collapsed)
        if normalized_first_sentence:
            preferred = normalized_first_sentence[0].strip() or preferred
        max_len = 36
        if len(preferred) <= max_len:
            return preferred
        return f"{preferred[:max_len].rstrip()}..."

    def _build_source_refs(
        self, candidate: dict[str, object], *, claim_id: str | None = None
    ) -> list[dict[str, object]]:
        source_span = candidate.get("source_span")
        normalized_span = source_span if isinstance(source_span, dict) else {}
        trace_refs = candidate.get("trace_refs")
        normalized_trace_refs = trace_refs if isinstance(trace_refs, dict) else {}
        return [
            {
                "source_id": str(candidate.get("source_id", "")),
                "candidate_id": str(candidate.get("candidate_id", "")),
                "candidate_batch_id": candidate.get("candidate_batch_id"),
                "artifact_id": normalized_trace_refs.get("source_artifact_id"),
                "anchor_id": normalized_trace_refs.get("source_anchor_id"),
                "claim_id": claim_id,
                "source_span": normalized_span,
                "quote": candidate.get("quote"),
            }
        ]

    def _build_graph_source_ref(
        self,
        *,
        record: dict[str, object],
        claim_id: str | None,
    ) -> dict[str, object]:
        source_id = str(record.get("source_id") or "").strip()
        resolved_claim_id = str(claim_id or "").strip()
        if not source_id or not resolved_claim_id:
            return {}
        source_span = record.get("source_span")
        normalized_span = source_span if isinstance(source_span, dict) else {}
        trace_refs = record.get("trace_refs")
        normalized_trace_refs = trace_refs if isinstance(trace_refs, dict) else {}
        return {
            "source_id": source_id,
            "candidate_id": str(record.get("candidate_id") or ""),
            "candidate_batch_id": record.get("candidate_batch_id"),
            "claim_id": resolved_claim_id,
            "artifact_id": normalized_trace_refs.get("source_artifact_id"),
            "anchor_id": normalized_trace_refs.get("source_anchor_id"),
            "source_span": normalized_span,
            "quote": record.get("quote"),
        }

    def _build_edge_source_ref(
        self,
        *,
        source_object: dict[str, object],
        target_object: dict[str, object],
        relation_id: str | None,
        relation_type: str | None,
    ) -> dict[str, object]:
        source_ref = self._build_graph_source_ref(
            record=target_object,
            claim_id=str(target_object.get("claim_id") or ""),
        )
        if not source_ref:
            return {}
        source_ref["source_claim_id"] = source_object.get("claim_id")
        source_ref["target_claim_id"] = target_object.get("claim_id")
        if relation_id:
            source_ref["relation_candidate_id"] = relation_id
        if relation_type:
            source_ref["relation_type"] = relation_type
        return source_ref

    def _build_short_tags(self, candidate: dict[str, object]) -> list[str]:
        semantic_type = str(candidate.get("semantic_type") or "").strip()
        if not semantic_type:
            return []
        return [semantic_type]

    def _require_graph_traceability(
        self,
        *,
        candidate: dict[str, object],
        claim: dict[str, object],
    ) -> dict[str, object]:
        source_ref = self._build_graph_source_ref(
            record=candidate,
            claim_id=str(claim.get("claim_id") or ""),
        )
        if source_ref:
            return source_ref
        raise CandidateConfirmationError(
            status_code=409,
            error_code="research.graph_projection_blocked",
            message="candidate confirmation cannot project node without claim/source traceability",
            details={
                "candidate_id": candidate["candidate_id"],
                "claim_id": claim.get("claim_id"),
                "source_id": candidate.get("source_id"),
            },
        )

    def _list_active_nodes(
        self, workspace_id: str, *, conn: sqlite3.Connection | None = None
    ) -> list[dict[str, object]]:
        return [
            node
            for node in self._store.list_graph_nodes(workspace_id, conn=conn)
            if str(node.get("status")) in self._active_statuses
        ]

    def _list_active_edges(
        self, workspace_id: str, *, conn: sqlite3.Connection | None = None
    ) -> list[dict[str, object]]:
        return [
            edge
            for edge in self._store.list_graph_edges(workspace_id, conn=conn)
            if str(edge.get("status")) in self._active_statuses
        ]

    def _resolve_active_node_by_object_ref(
        self,
        *,
        workspace_id: str,
        object_ref_type: str,
        object_ref_id: str,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, object] | None:
        matched = [
            node
            for node in self._list_active_nodes(workspace_id, conn=conn)
            if str(node["object_ref_type"]) == object_ref_type
            and str(node["object_ref_id"]) == object_ref_id
        ]
        if not matched:
            return None
        return matched[-1]

    def _confirmed_object_by_candidate_id(
        self,
        *,
        workspace_id: str,
        candidate_id: str,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, object] | None:
        for item in self._store.list_confirmed_objects(workspace_id, conn=conn):
            if str(item.get("candidate_id")) == candidate_id:
                return item
        return None

    def _materialize_resolved_relation_edges(
        self,
        *,
        workspace_id: str,
        source_id: str,
        candidate: dict[str, object],
        conn: sqlite3.Connection | None = None,
    ) -> list[str]:
        relations = self._store.list_relation_candidates(
            workspace_id=workspace_id,
            source_id=source_id,
            candidate_batch_id=str(candidate.get("candidate_batch_id") or ""),
            conn=conn,
        )
        if not relations:
            return []

        candidate_id = str(candidate["candidate_id"])
        edge_ids: list[str] = []
        for relation in relations:
            if str(relation.get("relation_status")) != "resolved":
                continue
            relation_type = str(relation.get("relation_type") or "").strip()
            if not relation_type:
                continue
            source_candidate_id = str(relation.get("source_candidate_id") or "")
            target_candidate_id = str(relation.get("target_candidate_id") or "")
            if candidate_id not in {source_candidate_id, target_candidate_id}:
                continue
            source_object = self._confirmed_object_by_candidate_id(
                workspace_id=workspace_id,
                candidate_id=source_candidate_id,
                conn=conn,
            )
            target_object = self._confirmed_object_by_candidate_id(
                workspace_id=workspace_id,
                candidate_id=target_candidate_id,
                conn=conn,
            )
            if source_object is None or target_object is None:
                continue
            source_node = self._resolve_active_node_by_object_ref(
                workspace_id=workspace_id,
                object_ref_type=str(source_object["object_type"]),
                object_ref_id=str(source_object["object_id"]),
                conn=conn,
            )
            target_node = self._resolve_active_node_by_object_ref(
                workspace_id=workspace_id,
                object_ref_type=str(target_object["object_type"]),
                object_ref_id=str(target_object["object_id"]),
                conn=conn,
            )
            if source_node is None or target_node is None:
                continue
            if str(source_node["node_id"]) == str(target_node["node_id"]):
                continue
            relation_id = str(relation["relation_candidate_id"])
            edge_source_ref = self._build_edge_source_ref(
                source_object=source_object,
                target_object=target_object,
                relation_id=relation_id,
                relation_type=relation_type,
            )
            target_claim_id = str(target_object.get("claim_id") or "").strip()
            if not target_claim_id or not edge_source_ref:
                continue
            existing_edge = self._store.find_graph_edge_by_ref(
                workspace_id=workspace_id,
                source_node_id=str(source_node["node_id"]),
                target_node_id=str(target_node["node_id"]),
                edge_type=relation_type,
                object_ref_type="relation_candidate",
                object_ref_id=relation_id,
                conn=conn,
            )
            edge = existing_edge
            if edge is None or str(edge.get("status")) not in self._active_statuses:
                edge = self._store.create_graph_edge(
                    workspace_id=workspace_id,
                    source_node_id=str(source_node["node_id"]),
                    target_node_id=str(target_node["node_id"]),
                    edge_type=relation_type,
                    object_ref_type="relation_candidate",
                    object_ref_id=relation_id,
                    strength=0.9,
                    claim_id=target_claim_id,
                    source_ref=edge_source_ref,
                    status="active",
                    conn=conn,
                )
            edge_ids.append(str(edge["edge_id"]))
        return edge_ids

    def _materialize_graph_version_for_confirmation(
        self,
        *,
        candidate: dict[str, object],
        claim: dict[str, object],
        formal_object: dict[str, str],
        request_id: str,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, object]:
        workspace_id = str(candidate["workspace_id"])
        source_id = str(candidate["source_id"])
        candidate_id = str(candidate["candidate_id"])
        object_type = str(formal_object["object_type"])
        object_id = str(formal_object["object_id"])
        claim_id = str(claim["claim_id"])
        source_ref = self._require_graph_traceability(candidate=candidate, claim=claim)

        node = self._resolve_active_node_by_object_ref(
            workspace_id=workspace_id,
            object_ref_type=object_type,
            object_ref_id=object_id,
            conn=conn,
        )
        node_created = False
        if node is None:
            node = self._store.create_graph_node(
                workspace_id=workspace_id,
                node_type=self._node_type_for_object_type(object_type),
                object_ref_type=object_type,
                object_ref_id=object_id,
                short_label=self._build_short_label(str(candidate["text"])),
                full_description=str(candidate["text"]),
                short_tags=self._build_short_tags(candidate),
                source_refs=self._build_source_refs(candidate, claim_id=claim_id),
                claim_id=claim_id,
                source_ref=source_ref,
                status="active",
                conn=conn,
            )
            node_created = True

        confirmed_objects = self._store.list_confirmed_objects(workspace_id, conn=conn)
        object_source_map = {
            str(item["object_id"]): str(item["source_id"]) for item in confirmed_objects
        }
        same_source_nodes = [
            item
            for item in self._list_active_nodes(workspace_id, conn=conn)
            if str(item["node_id"]) != str(node["node_id"])
            and object_source_map.get(str(item["object_ref_id"])) == source_id
        ]
        evidence_anchor = next(
            (item for item in same_source_nodes if str(item["node_type"]) == "evidence"),
            None,
        )
        anchor = evidence_anchor or (same_source_nodes[0] if same_source_nodes else None)

        relation_candidates = self._store.list_relation_candidates(
            workspace_id=workspace_id,
            source_id=source_id,
            candidate_batch_id=str(candidate.get("candidate_batch_id") or ""),
            conn=conn,
        )
        edge_ids = self._materialize_resolved_relation_edges(
            workspace_id=workspace_id,
            source_id=source_id,
            candidate=candidate,
            conn=conn,
        )
        if (
            not relation_candidates
            and anchor is not None
            and str(anchor["node_id"]) != str(node["node_id"])
        ):
            edge_type = self._edge_type_for_node_type(str(node["node_type"]))
            existing_edge = self._store.find_graph_edge_by_ref(
                workspace_id=workspace_id,
                source_node_id=str(anchor["node_id"]),
                target_node_id=str(node["node_id"]),
                edge_type=edge_type,
                object_ref_type=object_type,
                object_ref_id=object_id,
                conn=conn,
            )
            edge = existing_edge
            if edge is None or str(edge.get("status")) not in self._active_statuses:
                edge = self._store.create_graph_edge(
                    workspace_id=workspace_id,
                    source_node_id=str(anchor["node_id"]),
                    target_node_id=str(node["node_id"]),
                    edge_type=edge_type,
                    object_ref_type=object_type,
                    object_ref_id=object_id,
                    strength=0.8,
                    claim_id=claim_id,
                    source_ref={
                        **source_ref,
                        "anchor_claim_id": anchor.get("claim_id"),
                    },
                    status="active",
                    conn=conn,
                )
            edge_ids.append(str(edge["edge_id"]))

        diff_payload = {
            "change_type": "candidate_confirm_materialization",
            "candidate_id": candidate_id,
            "candidate_batch_id": candidate.get("candidate_batch_id"),
            "formal_object_type": object_type,
            "formal_object_id": object_id,
            "claim_id": claim_id,
            "source_id": source_id,
            "request_id": request_id,
            "added": {
                "nodes": [str(node["node_id"])] if node_created else [],
                "edges": edge_ids,
            },
            "archived": {"nodes": [], "edges": []},
            "weakened": {"nodes": [], "edges": [], "routes": []},
            "invalidated": {"nodes": [], "edges": [], "routes": []},
            "branch_changes": {
                "created_branch_node_ids": [],
                "created_branch_edge_ids": [],
            },
            "route_score_changes": [],
        }
        version = self._store.create_graph_version(
            workspace_id=workspace_id,
            trigger_type="confirm_candidate",
            change_summary=f"confirm candidate {candidate_id}",
            diff_payload=diff_payload,
            request_id=request_id,
            conn=conn,
        )
        active_nodes = self._list_active_nodes(workspace_id, conn=conn)
        active_edges = self._list_active_edges(workspace_id, conn=conn)
        self._store.upsert_graph_workspace(
            workspace_id=workspace_id,
            latest_version_id=str(version["version_id"]),
            status="ready",
            node_count=len(active_nodes),
            edge_count=len(active_edges),
            conn=conn,
        )
        self._store.emit_event(
            event_name="graph_materialization_completed",
            request_id=request_id,
            job_id=None,
            workspace_id=workspace_id,
            source_id=source_id,
            candidate_batch_id=candidate.get("candidate_batch_id"),
            component="candidate_confirmation_service",
            step="graph_materialization",
            status="completed",
            refs={
                "candidate_id": candidate_id,
                "node_id": str(node["node_id"]),
                "edge_ids": edge_ids,
                "version_id": version["version_id"],
                "result_ref": {
                    "resource_type": "graph_version",
                    "resource_id": version["version_id"],
                },
            },
            metrics={
                "node_count": len(active_nodes),
                "edge_count": len(active_edges),
            },
            conn=conn,
        )
        self._store.emit_event(
            event_name="graph_version_created",
            request_id=request_id,
            job_id=None,
            workspace_id=workspace_id,
            source_id=source_id,
            candidate_batch_id=candidate.get("candidate_batch_id"),
            component="candidate_confirmation_service",
            step="version_create",
            status="completed",
            refs={
                "candidate_id": candidate_id,
                "version_id": version["version_id"],
                "result_ref": {
                    "resource_type": "graph_version",
                    "resource_id": version["version_id"],
                },
            },
            conn=conn,
        )
        return {
            "graph_node_id": str(node["node_id"]),
            "graph_edge_ids": edge_ids,
            "graph_version_id": str(version["version_id"]),
            "node_count": len(active_nodes),
            "edge_count": len(active_edges),
        }

    def _load_candidate(self, *, workspace_id: str, candidate_id: str) -> dict[str, object]:
        candidate = self._store.get_candidate(candidate_id)
        if candidate is None:
            raise CandidateConfirmationError(
                status_code=404,
                error_code="research.not_found",
                message="candidate not found",
                details={"candidate_id": candidate_id},
            )
        if candidate["workspace_id"] != workspace_id:
            raise CandidateConfirmationError(
                status_code=409,
                error_code="research.conflict",
                message="workspace_id does not match candidate ownership",
                details={"candidate_id": candidate_id},
            )
        return candidate

    def _ensure_pending(self, *, candidate: dict[str, object], action: str) -> None:
        if candidate["status"] != "pending":
            raise CandidateConfirmationError(
                status_code=409,
                error_code="research.invalid_state",
                message=f"candidate cannot be {action}ed in current status",
                details={"candidate_id": candidate["candidate_id"], "status": candidate["status"]},
            )

    def _detect_claim_conflicts_best_effort(
        self,
        *,
        workspace_id: str,
        claim: dict[str, object],
        candidate: dict[str, object],
        request_id: str,
    ) -> None:
        try:
            existing_claim_ids = [
                str(item["claim_id"])
                for item in self._store.list_claims(workspace_id)
                if str(item["claim_id"]) != str(claim["claim_id"])
            ]
            result = self._claim_conflict_service.detect_for_claim(
                workspace_id=workspace_id,
                new_claim_id=str(claim["claim_id"]),
                candidate_claim_ids=existing_claim_ids,
                request_id=request_id,
            )
            self._store.emit_event(
                event_name="claim_conflict_detection_completed",
                request_id=request_id,
                job_id=None,
                workspace_id=workspace_id,
                source_id=str(candidate["source_id"]),
                candidate_batch_id=candidate.get("candidate_batch_id"),
                component="candidate_confirmation_service",
                step="claim_conflict_detection",
                status="completed",
                refs={
                    "claim_id": claim["claim_id"],
                    "created_count": result["created_count"],
                    "conflict_ids": result["conflict_ids"],
                },
            )
        except Exception as exc:  # pragma: no cover - defensive best-effort guard
            logger.exception(
                "claim conflict detection failed for claim_id=%s workspace_id=%s",
                claim.get("claim_id"),
                workspace_id,
            )
            self._store.emit_event(
                event_name="claim_conflict_detection_completed",
                request_id=request_id,
                job_id=None,
                workspace_id=workspace_id,
                source_id=str(candidate["source_id"]),
                candidate_batch_id=candidate.get("candidate_batch_id"),
                component="candidate_confirmation_service",
                step="claim_conflict_detection",
                status="failed",
                refs={
                    "claim_id": claim["claim_id"],
                    "reason": "claim_conflict_detection_exception",
                },
                error={"message": str(exc)},
            )

    def confirm(
        self,
        *,
        workspace_id: str,
        candidate_id: str,
        request_id: str,
    ) -> dict[str, object]:
        candidate = self._load_candidate(
            workspace_id=workspace_id,
            candidate_id=candidate_id,
        )
        self._ensure_pending(candidate=candidate, action="confirm")

        normalized_text = normalize_candidate_text(str(candidate["text"]))
        conflict = self._store.find_confirmed_object_by_normalized_text(
            workspace_id=workspace_id,
            normalized_text=normalized_text,
        )
        if conflict is not None:
            reason = (
                "duplicate_confirmed_object"
                if conflict["object_type"] == candidate["candidate_type"]
                else "cross_type_confirmed_conflict"
            )
            error = CandidateConfirmationError(
                status_code=409,
                error_code="research.conflict",
                message="candidate confirmation conflicts with existing confirmed object",
                details={
                    "candidate_id": candidate_id,
                    "reason": reason,
                    "conflict_object_type": conflict["object_type"],
                    "conflict_object_id": conflict["object_id"],
                },
            )
            self._store.emit_event(
                event_name="candidate_confirmation_failed",
                request_id=request_id,
                job_id=None,
                workspace_id=workspace_id,
                source_id=str(candidate["source_id"]),
                candidate_batch_id=candidate.get("candidate_batch_id"),
                component="candidate_confirmation_service",
                step="confirm",
                status="failed",
                refs={
                    "candidate_id": candidate_id,
                    "conflict_object_id": conflict["object_id"],
                    "conflict_object_type": conflict["object_type"],
                },
                error={
                    "error_code": error.error_code,
                    "message": error.message,
                    "details": error.details,
                },
            )
            raise error

        formal_object: dict[str, str] | None = None
        claim: dict[str, object] | None = None
        try:
            def _confirm_txn(
                conn: sqlite3.Connection,
            ) -> tuple[dict[str, object], dict[str, str], dict[str, object]]:
                nonlocal claim, formal_object
                claim = self._store.create_claim_from_candidate(
                    candidate=candidate,
                    normalized_text=normalized_text,
                    conn=conn,
                )
                formal_object = self._store.create_confirmed_object_from_candidate(
                    candidate=candidate,
                    normalized_text=normalized_text,
                    request_id=request_id,
                    conn=conn,
                )
                self._scholarly_source_service.persist_evidence_refs_for_confirmation(
                    candidate=candidate,
                    object_type=str(formal_object["object_type"]),
                    object_id=str(formal_object["object_id"]),
                    request_id=request_id,
                    conn=conn,
                )
                self._store.update_candidate_status(
                    candidate_id=candidate_id,
                    status="confirmed",
                    conn=conn,
                )
                self._store.emit_event(
                    event_name="candidate_confirmed",
                    request_id=request_id,
                    job_id=None,
                    workspace_id=workspace_id,
                    source_id=str(candidate["source_id"]),
                    candidate_batch_id=candidate.get("candidate_batch_id"),
                    component="candidate_confirmation_service",
                    step="confirm",
                    status="completed",
                    refs={
                        "candidate_id": candidate_id,
                        "formal_object_type": formal_object["object_type"],
                        "formal_object_id": formal_object["object_id"],
                        "source_id": candidate["source_id"],
                        "extraction_job_id": candidate.get("extraction_job_id"),
                    },
                    conn=conn,
                )
                self._store.emit_event(
                    event_name="claim_created",
                    request_id=request_id,
                    job_id=None,
                    workspace_id=workspace_id,
                    source_id=str(candidate["source_id"]),
                    candidate_batch_id=candidate.get("candidate_batch_id"),
                    component="candidate_confirmation_service",
                    step="claim_create",
                    status="completed",
                    refs={
                        "candidate_id": candidate_id,
                        "claim_id": claim["claim_id"],
                        "claim_type": claim["claim_type"],
                        "source_id": candidate["source_id"],
                    },
                    conn=conn,
                )
                graph_result = self._materialize_graph_version_for_confirmation(
                    candidate=candidate,
                    claim=claim,
                    formal_object=formal_object,
                    request_id=request_id,
                    conn=conn,
                )
                return claim, formal_object, graph_result

            claim, formal_object, graph_result = self._store.run_in_transaction(_confirm_txn)
        except CandidateConfirmationError:
            raise
        except Exception as exc:
            error = CandidateConfirmationError(
                status_code=409,
                error_code="research.version_diff_unavailable",
                message="graph/version persistence failed during candidate confirmation",
                details={
                    "candidate_id": candidate_id,
                    "reason": str(exc),
                },
            )
            self._store.emit_event(
                event_name="candidate_confirmation_failed",
                request_id=request_id,
                job_id=None,
                workspace_id=workspace_id,
                source_id=str(candidate["source_id"]),
                candidate_batch_id=candidate.get("candidate_batch_id"),
                component="candidate_confirmation_service",
                step="graph_materialization",
                status="failed",
                refs={
                    "candidate_id": candidate_id,
                    "formal_object_type": (
                        formal_object["object_type"] if formal_object is not None else None
                    ),
                    "formal_object_id": (
                        formal_object["object_id"] if formal_object is not None else None
                    ),
                },
                error={
                    "error_code": error.error_code,
                    "message": error.message,
                    "details": error.details,
                },
            )
            raise error
        assert formal_object is not None
        assert claim is not None
        try:
            memory_link = self._memory_bridge.sync_claim(claim=claim, request_id=request_id)
        except Exception as exc:  # pragma: no cover - defensive best-effort guard
            self._store.emit_event(
                event_name="claim_memory_bridge_completed",
                request_id=request_id,
                job_id=None,
                workspace_id=workspace_id,
                source_id=str(candidate["source_id"]),
                candidate_batch_id=candidate.get("candidate_batch_id"),
                component="candidate_confirmation_service",
                step="memory_bridge",
                status="failed",
                refs={"claim_id": claim["claim_id"], "reason": "bridge_service_exception"},
                error={"message": str(exc)},
            )
            memory_link = {
                "claim_id": claim["claim_id"],
                "memory_id": None,
                "sync_mode": "best_effort_record",
                "status": "failed",
                "reason": "bridge_service_exception",
                "last_error": {"message": str(exc)},
            }
        self._detect_claim_conflicts_best_effort(
            workspace_id=workspace_id,
            claim=claim,
            candidate=candidate,
            request_id=request_id,
        )
        return {
            "candidate_id": candidate_id,
            "candidate_status": "confirmed",
            "claim_id": claim["claim_id"],
            "claim_memory_sync_status": memory_link["status"],
            "formal_object_type": formal_object["object_type"],
            "formal_object_id": formal_object["object_id"],
            "graph_node_id": graph_result["graph_node_id"],
            "graph_edge_ids": graph_result["graph_edge_ids"],
            "graph_version_id": graph_result["graph_version_id"],
        }

    def reject(
        self,
        *,
        workspace_id: str,
        candidate_id: str,
        reason: str,
        request_id: str,
    ) -> dict[str, object]:
        candidate = self._load_candidate(
            workspace_id=workspace_id,
            candidate_id=candidate_id,
        )
        self._ensure_pending(candidate=candidate, action="reject")

        self._store.update_candidate_status(
            candidate_id=candidate_id,
            status="rejected",
            reject_reason=reason,
        )
        self._store.emit_event(
            event_name="candidate_rejected",
            request_id=request_id,
            job_id=None,
            workspace_id=workspace_id,
            source_id=str(candidate["source_id"]),
            candidate_batch_id=candidate.get("candidate_batch_id"),
            component="candidate_confirmation_service",
            step="reject",
            status="completed",
            refs={
                "candidate_id": candidate_id,
                "reason": reason,
                "source_id": candidate["source_id"],
                "extraction_job_id": candidate.get("extraction_job_id"),
            },
        )
        return {
            "candidate_id": candidate_id,
            "candidate_status": "rejected",
        }
