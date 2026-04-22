from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Callable, TypeVar
from uuid import uuid4

from research_layer.api.schemas.common import JobStatus

_TxnResult = TypeVar("_TxnResult")


class ResearchApiStateStore:
    def __init__(self, db_path: str | None = None) -> None:
        resolved_db_path = db_path or os.getenv("RESEARCH_SLICE2_DB_PATH")
        if resolved_db_path is None:
            repo_root = Path(__file__).resolve().parents[4]
            resolved_db_path = str(repo_root / "data" / "research_slice2.sqlite3")
        self.db_path = resolved_db_path
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._ensure_schema()

    def gen_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid4().hex[:12]}"

    def now(self) -> datetime:
        return datetime.now(UTC)

    def _to_iso(self, dt: datetime | None) -> str | None:
        return None if dt is None else dt.isoformat()

    def _from_iso(self, raw: str | None) -> datetime | None:
        return None if raw is None else datetime.fromisoformat(raw)

    def _dumps(self, payload: object) -> str:
        return json.dumps(payload, ensure_ascii=False, default=str)

    def _loads(self, raw: str | None) -> object:
        if raw is None:
            return None
        return json.loads(raw)

    def _loads_safe(self, raw: str | None) -> object | None:
        if raw is None:
            return None
        try:
            return self._loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    def _loads_list(self, raw: str | None) -> list[object]:
        decoded = self._loads_safe(raw)
        if isinstance(decoded, list):
            return decoded
        return []

    def _loads_dict(self, raw: str | None) -> dict[str, object]:
        decoded = self._loads_safe(raw)
        if isinstance(decoded, dict):
            return decoded
        return {}

    def _normalize_usage(self, usage: object) -> dict[str, object] | None:
        if usage is None:
            return None
        raw = usage if isinstance(usage, dict) else {}

        def _as_non_negative_int(value: object) -> int:
            if isinstance(value, bool):
                return int(value)
            if isinstance(value, int):
                return max(value, 0)
            if isinstance(value, float):
                return max(int(value), 0)
            if isinstance(value, str):
                stripped = value.strip()
                if stripped.isdigit():
                    return int(stripped)
            return 0

        normalized = dict(raw)
        normalized["prompt_tokens"] = _as_non_negative_int(raw.get("prompt_tokens"))
        normalized["completion_tokens"] = _as_non_negative_int(
            raw.get("completion_tokens")
        )
        total_tokens = _as_non_negative_int(raw.get("total_tokens"))
        if total_tokens == 0:
            total_tokens = int(normalized["prompt_tokens"]) + int(
                normalized["completion_tokens"]
            )
        normalized["total_tokens"] = total_tokens
        return normalized

    def _decode_route_edge_ids_json(
        self, raw: str | None
    ) -> tuple[list[str], bool, bool, str | None]:
        if raw is None:
            return [], False, False, "missing"
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            return [], True, False, "malformed_json"
        if not isinstance(decoded, list):
            return [], True, False, "non_array"
        if any(not isinstance(item, str) for item in decoded):
            return [], True, False, "non_string_member"
        return list(decoded), True, True, None

    def _compute_route_confidence(
        self, *, support_score: float, risk_score: float, progressability_score: float
    ) -> tuple[float, str]:
        confidence_score = round(
            (float(support_score) + (100.0 - float(risk_score)) + float(progressability_score))
            / 3.0,
            1,
        )
        if confidence_score >= 80.0:
            return confidence_score, "high"
        if confidence_score >= 65.0:
            return confidence_score, "medium"
        return confidence_score, "low"

    def _execute(
        self,
        sql: str,
        params: tuple[object, ...] = (),
        *,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        if conn is not None:
            conn.execute(sql, params)
            return
        with self._lock:
            with sqlite3.connect(self.db_path) as local_conn:
                local_conn.execute(sql, params)
                local_conn.commit()

    def _fetchone(
        self,
        sql: str,
        params: tuple[object, ...] = (),
        *,
        conn: sqlite3.Connection | None = None,
    ) -> sqlite3.Row | None:
        if conn is not None:
            return conn.execute(sql, params).fetchone()
        with self._lock:
            with sqlite3.connect(self.db_path) as local_conn:
                local_conn.row_factory = sqlite3.Row
                return local_conn.execute(sql, params).fetchone()

    def _fetchall(
        self,
        sql: str,
        params: tuple[object, ...] = (),
        *,
        conn: sqlite3.Connection | None = None,
    ) -> list[sqlite3.Row]:
        if conn is not None:
            return conn.execute(sql, params).fetchall()
        with self._lock:
            with sqlite3.connect(self.db_path) as local_conn:
                local_conn.row_factory = sqlite3.Row
                return local_conn.execute(sql, params).fetchall()

    def run_in_transaction(
        self, func: Callable[[sqlite3.Connection], _TxnResult]
    ) -> _TxnResult:
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                try:
                    result = func(conn)
                    conn.commit()
                    return result
                except Exception:
                    conn.rollback()
                    raise

    def _ensure_schema(self) -> None:
        statements = [
            """
            CREATE TABLE IF NOT EXISTS sources (
                source_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                source_type TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                normalized_content TEXT,
                status TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                import_request_id TEXT,
                last_extract_job_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS candidates (
                candidate_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                candidate_type TEXT NOT NULL,
                semantic_type TEXT,
                text TEXT NOT NULL,
                status TEXT NOT NULL,
                source_span_json TEXT NOT NULL,
                quote TEXT,
                trace_refs_json TEXT,
                candidate_batch_id TEXT,
                extraction_job_id TEXT,
                extractor_name TEXT,
                reject_reason TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS extraction_results (
                candidate_batch_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                job_id TEXT NOT NULL,
                request_id TEXT,
                candidate_ids_json TEXT NOT NULL,
                status TEXT NOT NULL,
                error_json TEXT,
                created_at TEXT NOT NULL,
                finished_at TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS routes (
                route_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                status TEXT NOT NULL,
                support_score REAL NOT NULL,
                risk_score REAL NOT NULL,
                progressability_score REAL NOT NULL,
                confidence_score REAL,
                confidence_grade TEXT,
                rank INTEGER,
                novelty_level TEXT,
                relation_tags_json TEXT,
                top_factors_json TEXT,
                score_breakdown_json TEXT,
                node_score_breakdown_json TEXT,
                scoring_template_id TEXT,
                scored_at TEXT,
                conclusion TEXT NOT NULL,
                key_supports_json TEXT NOT NULL,
                assumptions_json TEXT NOT NULL,
                risks_json TEXT NOT NULL,
                next_validation_action TEXT NOT NULL,
                conclusion_node_id TEXT,
                route_node_ids_json TEXT,
                route_edge_ids_json TEXT,
                key_support_node_ids_json TEXT,
                key_assumption_node_ids_json TEXT,
                risk_node_ids_json TEXT,
                next_validation_node_id TEXT,
                version_id TEXT,
                key_strengths_json TEXT,
                key_risks_json TEXT,
                open_questions_json TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS graph_nodes (
                node_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                node_type TEXT NOT NULL,
                object_ref_type TEXT NOT NULL,
                object_ref_id TEXT NOT NULL,
                short_label TEXT NOT NULL,
                full_description TEXT NOT NULL,
                short_tags_json TEXT NOT NULL DEFAULT '[]',
                visibility TEXT NOT NULL DEFAULT 'workspace',
                source_refs_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS research_evidences (
                evidence_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                candidate_id TEXT NOT NULL UNIQUE,
                source_id TEXT NOT NULL,
                text TEXT NOT NULL,
                normalized_text TEXT NOT NULL,
                source_span_json TEXT NOT NULL,
                candidate_batch_id TEXT,
                extraction_job_id TEXT,
                created_at TEXT NOT NULL,
                created_request_id TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS research_assumptions (
                assumption_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                candidate_id TEXT NOT NULL UNIQUE,
                source_id TEXT NOT NULL,
                text TEXT NOT NULL,
                normalized_text TEXT NOT NULL,
                source_span_json TEXT NOT NULL,
                candidate_batch_id TEXT,
                extraction_job_id TEXT,
                created_at TEXT NOT NULL,
                created_request_id TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS research_conclusions (
                conclusion_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                candidate_id TEXT NOT NULL UNIQUE,
                source_id TEXT NOT NULL,
                text TEXT NOT NULL,
                normalized_text TEXT NOT NULL,
                source_span_json TEXT NOT NULL,
                semantic_type TEXT,
                quote TEXT,
                trace_refs_json TEXT,
                candidate_batch_id TEXT,
                extraction_job_id TEXT,
                created_at TEXT NOT NULL,
                created_request_id TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS research_gaps (
                gap_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                candidate_id TEXT NOT NULL UNIQUE,
                source_id TEXT NOT NULL,
                text TEXT NOT NULL,
                normalized_text TEXT NOT NULL,
                source_span_json TEXT NOT NULL,
                semantic_type TEXT,
                quote TEXT,
                trace_refs_json TEXT,
                candidate_batch_id TEXT,
                extraction_job_id TEXT,
                created_at TEXT NOT NULL,
                created_request_id TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS research_conflicts (
                conflict_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                candidate_id TEXT NOT NULL UNIQUE,
                source_id TEXT NOT NULL,
                text TEXT NOT NULL,
                normalized_text TEXT NOT NULL,
                source_span_json TEXT NOT NULL,
                candidate_batch_id TEXT,
                extraction_job_id TEXT,
                created_at TEXT NOT NULL,
                created_request_id TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS research_failures (
                failure_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                candidate_id TEXT NOT NULL UNIQUE,
                source_id TEXT NOT NULL,
                text TEXT NOT NULL,
                normalized_text TEXT NOT NULL,
                source_span_json TEXT NOT NULL,
                candidate_batch_id TEXT,
                extraction_job_id TEXT,
                created_at TEXT NOT NULL,
                created_request_id TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS research_validations (
                validation_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                candidate_id TEXT NOT NULL UNIQUE,
                source_id TEXT NOT NULL,
                text TEXT NOT NULL,
                normalized_text TEXT NOT NULL,
                source_span_json TEXT NOT NULL,
                candidate_batch_id TEXT,
                extraction_job_id TEXT,
                created_at TEXT NOT NULL,
                created_request_id TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS graph_edges (
                edge_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                source_node_id TEXT NOT NULL,
                target_node_id TEXT NOT NULL,
                edge_type TEXT NOT NULL,
                object_ref_type TEXT NOT NULL,
                object_ref_id TEXT NOT NULL,
                strength REAL NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS relation_candidates (
                relation_candidate_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                candidate_batch_id TEXT,
                extraction_job_id TEXT,
                source_candidate_id TEXT,
                target_candidate_id TEXT,
                semantic_relation_type TEXT,
                relation_type TEXT,
                relation_status TEXT NOT NULL,
                quote TEXT,
                trace_refs_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS graph_versions (
                version_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                change_summary TEXT NOT NULL,
                diff_payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                request_id TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS graph_workspaces (
                workspace_id TEXT PRIMARY KEY,
                latest_version_id TEXT,
                status TEXT NOT NULL,
                node_count INTEGER NOT NULL,
                edge_count INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS failures (
                failure_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                attached_targets_json TEXT NOT NULL,
                observed_outcome TEXT NOT NULL,
                expected_difference TEXT NOT NULL,
                failure_reason TEXT NOT NULL,
                severity TEXT NOT NULL,
                reporter TEXT NOT NULL,
                impact_summary_json TEXT,
                impact_updated_at TEXT,
                derived_from_validation_id TEXT,
                derived_from_validation_result_id TEXT,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS validations (
                validation_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                target_object TEXT NOT NULL,
                method TEXT NOT NULL,
                success_signal TEXT NOT NULL,
                weakening_signal TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                latest_outcome TEXT,
                latest_result_id TEXT,
                updated_at TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS validation_results (
                result_id TEXT PRIMARY KEY,
                validation_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                outcome TEXT NOT NULL,
                target_type TEXT,
                target_id TEXT,
                note TEXT,
                request_id TEXT,
                triggered_failure_id TEXT,
                recompute_job_id TEXT,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS memory_actions (
                action_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                action_type TEXT NOT NULL,
                memory_view_type TEXT NOT NULL,
                memory_result_id TEXT NOT NULL,
                route_id TEXT,
                hypothesis_id TEXT,
                validation_id TEXT,
                request_id TEXT,
                note TEXT,
                memory_ref_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS hypotheses (
                hypothesis_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                statement TEXT NOT NULL,
                status TEXT NOT NULL,
                trigger_object_ids_json TEXT NOT NULL,
                title TEXT,
                summary TEXT,
                premise TEXT,
                rationale TEXT,
                stage TEXT,
                trigger_refs_json TEXT,
                related_object_ids_json TEXT,
                novelty_typing TEXT,
                minimum_validation_action_json TEXT,
                weakening_signal_json TEXT,
                decision_note TEXT,
                decision_source_type TEXT,
                decision_source_ref TEXT,
                decided_at TEXT,
                decided_request_id TEXT,
                created_at TEXT,
                updated_at TEXT,
                generation_job_id TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS hypothesis_candidate_pools (
                pool_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                status TEXT NOT NULL,
                orchestration_mode TEXT NOT NULL,
                trigger_refs_json TEXT NOT NULL,
                reasoning_subgraph_json TEXT NOT NULL,
                top_k INTEGER NOT NULL,
                max_rounds INTEGER NOT NULL,
                candidate_count INTEGER NOT NULL,
                current_round_number INTEGER NOT NULL,
                research_goal TEXT NOT NULL,
                constraints_json TEXT NOT NULL,
                preference_profile_json TEXT NOT NULL,
                created_job_id TEXT,
                created_request_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS hypothesis_candidates (
                candidate_id TEXT PRIMARY KEY,
                pool_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                title TEXT NOT NULL,
                statement TEXT NOT NULL,
                summary TEXT NOT NULL,
                rationale TEXT NOT NULL,
                trigger_refs_json TEXT NOT NULL,
                related_object_ids_json TEXT NOT NULL,
                reasoning_chain_json TEXT NOT NULL,
                minimum_validation_action_json TEXT NOT NULL,
                weakening_signal_json TEXT NOT NULL,
                novelty_typing TEXT NOT NULL,
                status TEXT NOT NULL,
                origin_type TEXT NOT NULL,
                origin_round_number INTEGER NOT NULL,
                elo_rating REAL NOT NULL,
                survival_score REAL NOT NULL,
                lineage_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS hypothesis_rounds (
                round_id TEXT PRIMARY KEY,
                pool_id TEXT NOT NULL,
                round_number INTEGER NOT NULL,
                status TEXT NOT NULL,
                start_reason TEXT NOT NULL,
                stop_reason TEXT,
                generation_count INTEGER NOT NULL,
                review_count INTEGER NOT NULL,
                match_count INTEGER NOT NULL,
                evolution_count INTEGER NOT NULL,
                meta_review_id TEXT,
                created_at TEXT NOT NULL,
                completed_at TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS hypothesis_reviews (
                review_id TEXT PRIMARY KEY,
                pool_id TEXT NOT NULL,
                round_id TEXT NOT NULL,
                candidate_id TEXT NOT NULL,
                review_type TEXT NOT NULL,
                strengths_json TEXT NOT NULL,
                weaknesses_json TEXT NOT NULL,
                missing_evidence_json TEXT NOT NULL,
                testability_issues_json TEXT NOT NULL,
                weakest_step_ref_json TEXT NOT NULL,
                recommended_actions_json TEXT NOT NULL,
                trace_refs_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS hypothesis_matches (
                match_id TEXT PRIMARY KEY,
                pool_id TEXT NOT NULL,
                round_id TEXT NOT NULL,
                left_candidate_id TEXT NOT NULL,
                right_candidate_id TEXT NOT NULL,
                winner_candidate_id TEXT NOT NULL,
                loser_candidate_id TEXT NOT NULL,
                match_reason TEXT NOT NULL,
                compare_vector_json TEXT NOT NULL,
                left_elo_before REAL NOT NULL,
                right_elo_before REAL NOT NULL,
                left_elo_after REAL NOT NULL,
                right_elo_after REAL NOT NULL,
                judge_trace_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS hypothesis_evolutions (
                evolution_id TEXT PRIMARY KEY,
                pool_id TEXT NOT NULL,
                round_id TEXT NOT NULL,
                source_candidate_id TEXT NOT NULL,
                new_candidate_id TEXT NOT NULL,
                evolution_mode TEXT NOT NULL,
                driving_review_ids_json TEXT NOT NULL,
                change_summary TEXT NOT NULL,
                preserved_claims_json TEXT NOT NULL,
                modified_claims_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS hypothesis_meta_reviews (
                meta_review_id TEXT PRIMARY KEY,
                pool_id TEXT NOT NULL,
                round_id TEXT NOT NULL,
                recurring_issues_json TEXT NOT NULL,
                strong_patterns_json TEXT NOT NULL,
                weak_patterns_json TEXT NOT NULL,
                continue_recommendation TEXT NOT NULL,
                stop_recommendation TEXT NOT NULL,
                diversity_assessment TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS hypothesis_proximity_edges (
                edge_id TEXT PRIMARY KEY,
                pool_id TEXT NOT NULL,
                from_candidate_id TEXT NOT NULL,
                to_candidate_id TEXT NOT NULL,
                similarity_score REAL NOT NULL,
                shared_trigger_ratio REAL NOT NULL,
                shared_object_ratio REAL NOT NULL,
                shared_chain_overlap REAL NOT NULL,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS hypothesis_search_tree_nodes (
                tree_node_id TEXT PRIMARY KEY,
                pool_id TEXT NOT NULL,
                parent_tree_node_id TEXT,
                candidate_id TEXT,
                node_role TEXT NOT NULL,
                depth INTEGER NOT NULL,
                visits INTEGER NOT NULL,
                mean_reward REAL NOT NULL,
                uct_score REAL NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS hypothesis_search_tree_edges (
                edge_id TEXT PRIMARY KEY,
                pool_id TEXT NOT NULL,
                from_tree_node_id TEXT NOT NULL,
                to_tree_node_id TEXT NOT NULL,
                edge_type TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS packages (
                package_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                included_route_ids_json TEXT NOT NULL,
                included_node_ids_json TEXT NOT NULL,
                included_validation_ids_json TEXT NOT NULL,
                status TEXT NOT NULL,
                snapshot_type TEXT,
                snapshot_version TEXT,
                private_dependency_flags_json TEXT,
                public_gap_nodes_json TEXT,
                boundary_notes_json TEXT,
                traceability_refs_json TEXT,
                snapshot_payload_json TEXT,
                replay_ready INTEGER,
                build_request_id TEXT,
                created_at TEXT,
                updated_at TEXT,
                published_at TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS package_publish_results (
                publish_result_id TEXT PRIMARY KEY,
                package_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                snapshot_type TEXT NOT NULL,
                snapshot_version TEXT NOT NULL,
                boundary_notes_json TEXT NOT NULL,
                published_snapshot_json TEXT NOT NULL,
                published_at TEXT NOT NULL,
                request_id TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                job_type TEXT NOT NULL,
                status TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                request_id TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                result_ref_type TEXT,
                result_ref_id TEXT,
                error_json TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS research_events (
                event_id TEXT PRIMARY KEY,
                event_name TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                request_id TEXT,
                job_id TEXT,
                workspace_id TEXT,
                source_id TEXT,
                candidate_batch_id TEXT,
                component TEXT NOT NULL,
                step TEXT,
                status TEXT NOT NULL,
                refs_json TEXT NOT NULL,
                metrics_json TEXT NOT NULL,
                error_json TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS evidence_refs (
                ref_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                object_type TEXT NOT NULL,
                object_id TEXT NOT NULL,
                ref_type TEXT NOT NULL,
                layer TEXT NOT NULL,
                title TEXT NOT NULL,
                doi TEXT,
                url TEXT,
                venue TEXT,
                publication_year INTEGER,
                authors_json TEXT NOT NULL,
                excerpt TEXT NOT NULL,
                locator_json TEXT NOT NULL,
                authority_score REAL NOT NULL,
                authority_tier TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                confirmed_at TEXT,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS scholarly_source_cache (
                cache_id TEXT PRIMARY KEY,
                normalized_query TEXT NOT NULL,
                provider_name TEXT NOT NULL,
                provider_record_id TEXT NOT NULL,
                title TEXT NOT NULL,
                doi TEXT,
                url TEXT,
                venue TEXT,
                publication_year INTEGER,
                authors_json TEXT NOT NULL,
                abstract_excerpt TEXT,
                metadata_json TEXT NOT NULL,
                authority_tier TEXT NOT NULL,
                authority_score REAL NOT NULL,
                created_at TEXT NOT NULL
            )
            """,
        ]
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                for statement in statements:
                    conn.execute(statement)
                self._ensure_column(conn, "sources", "normalized_content", "TEXT")
                self._ensure_column(conn, "sources", "import_request_id", "TEXT")
                self._ensure_column(conn, "sources", "last_extract_job_id", "TEXT")
                self._ensure_column(conn, "candidates", "candidate_batch_id", "TEXT")
                self._ensure_column(conn, "candidates", "extraction_job_id", "TEXT")
                self._ensure_column(conn, "candidates", "extractor_name", "TEXT")
                self._ensure_column(conn, "candidates", "semantic_type", "TEXT")
                self._ensure_column(conn, "candidates", "quote", "TEXT")
                self._ensure_column(conn, "candidates", "trace_refs_json", "TEXT")
                self._ensure_column(
                    conn, "candidates", "provider_backend", "TEXT"
                )
                self._ensure_column(conn, "candidates", "provider_model", "TEXT")
                self._ensure_column(conn, "candidates", "llm_request_id", "TEXT")
                self._ensure_column(conn, "candidates", "llm_response_id", "TEXT")
                self._ensure_column(conn, "candidates", "usage_json", "TEXT")
                self._ensure_column(conn, "candidates", "fallback_used", "INTEGER")
                self._ensure_column(conn, "candidates", "degraded", "INTEGER")
                self._ensure_column(conn, "candidates", "degraded_reason", "TEXT")
                self._ensure_column(conn, "jobs", "request_id", "TEXT")
                self._ensure_column(
                    conn, "extraction_results", "provider_backend", "TEXT"
                )
                self._ensure_column(conn, "extraction_results", "provider_model", "TEXT")
                self._ensure_column(
                    conn, "extraction_results", "llm_request_id", "TEXT"
                )
                self._ensure_column(
                    conn, "extraction_results", "llm_response_id", "TEXT"
                )
                self._ensure_column(conn, "extraction_results", "usage_json", "TEXT")
                self._ensure_column(
                    conn, "extraction_results", "fallback_used", "INTEGER"
                )
                self._ensure_column(conn, "extraction_results", "degraded", "INTEGER")
                self._ensure_column(
                    conn, "extraction_results", "degraded_reason", "TEXT"
                )
                self._ensure_column(
                    conn, "extraction_results", "partial_failure_count", "INTEGER"
                )
                self._ensure_column(conn, "routes", "novelty_level", "TEXT")
                self._ensure_column(conn, "routes", "relation_tags_json", "TEXT")
                self._ensure_column(conn, "routes", "top_factors_json", "TEXT")
                self._ensure_column(conn, "routes", "score_breakdown_json", "TEXT")
                self._ensure_column(conn, "routes", "node_score_breakdown_json", "TEXT")
                self._ensure_column(conn, "routes", "scoring_template_id", "TEXT")
                self._ensure_column(conn, "routes", "scored_at", "TEXT")
                self._ensure_column(conn, "routes", "confidence_score", "REAL")
                self._ensure_column(conn, "routes", "confidence_grade", "TEXT")
                self._ensure_column(conn, "routes", "rank", "INTEGER")
                self._ensure_column(conn, "routes", "conclusion_node_id", "TEXT")
                self._ensure_column(conn, "routes", "route_node_ids_json", "TEXT")
                self._ensure_column(conn, "routes", "key_support_node_ids_json", "TEXT")
                self._ensure_column(
                    conn, "routes", "key_assumption_node_ids_json", "TEXT"
                )
                self._ensure_column(conn, "routes", "risk_node_ids_json", "TEXT")
                self._ensure_column(conn, "routes", "next_validation_node_id", "TEXT")
                self._ensure_column(conn, "routes", "version_id", "TEXT")
                self._ensure_column(conn, "routes", "provider_backend", "TEXT")
                self._ensure_column(conn, "routes", "provider_model", "TEXT")
                self._ensure_column(conn, "routes", "llm_request_id", "TEXT")
                self._ensure_column(conn, "routes", "llm_response_id", "TEXT")
                self._ensure_column(conn, "routes", "usage_json", "TEXT")
                self._ensure_column(conn, "routes", "fallback_used", "INTEGER")
                self._ensure_column(conn, "routes", "degraded", "INTEGER")
                self._ensure_column(conn, "routes", "degraded_reason", "TEXT")
                self._ensure_column(
                    conn, "routes", "summary_generation_mode", "TEXT"
                )
                self._ensure_column(conn, "routes", "route_edge_ids_json", "TEXT")
                self._ensure_column(conn, "routes", "key_strengths_json", "TEXT")
                self._ensure_column(conn, "routes", "key_risks_json", "TEXT")
                self._ensure_column(conn, "routes", "open_questions_json", "TEXT")
                self._ensure_column(conn, "graph_nodes", "object_ref_type", "TEXT")
                self._ensure_column(conn, "graph_nodes", "object_ref_id", "TEXT")
                self._ensure_column(
                    conn,
                    "graph_nodes",
                    "short_tags_json",
                    "TEXT NOT NULL DEFAULT '[]'",
                )
                self._ensure_column(
                    conn,
                    "graph_nodes",
                    "visibility",
                    "TEXT NOT NULL DEFAULT 'workspace'",
                )
                self._ensure_column(
                    conn,
                    "graph_nodes",
                    "source_refs_json",
                    "TEXT NOT NULL DEFAULT '[]'",
                )
                self._ensure_column(conn, "graph_nodes", "created_at", "TEXT")
                self._ensure_column(conn, "graph_nodes", "updated_at", "TEXT")
                self._ensure_column(conn, "graph_edges", "object_ref_type", "TEXT")
                self._ensure_column(conn, "graph_edges", "object_ref_id", "TEXT")
                self._ensure_column(conn, "graph_edges", "created_at", "TEXT")
                self._ensure_column(conn, "graph_edges", "updated_at", "TEXT")
                for table_name in (
                    "research_evidences",
                    "research_assumptions",
                    "research_conclusions",
                    "research_gaps",
                    "research_conflicts",
                    "research_failures",
                    "research_validations",
                ):
                    self._ensure_column(conn, table_name, "semantic_type", "TEXT")
                    self._ensure_column(conn, table_name, "quote", "TEXT")
                    self._ensure_column(conn, table_name, "trace_refs_json", "TEXT")
                self._ensure_column(conn, "graph_versions", "created_at", "TEXT")
                self._ensure_column(conn, "graph_versions", "request_id", "TEXT")
                self._ensure_column(conn, "hypotheses", "title", "TEXT")
                self._ensure_column(conn, "hypotheses", "summary", "TEXT")
                self._ensure_column(conn, "hypotheses", "premise", "TEXT")
                self._ensure_column(conn, "hypotheses", "rationale", "TEXT")
                self._ensure_column(conn, "hypotheses", "testability_hint", "TEXT")
                self._ensure_column(conn, "hypotheses", "novelty_hint", "TEXT")
                self._ensure_column(
                    conn, "hypotheses", "suggested_next_steps_json", "TEXT"
                )
                self._ensure_column(conn, "hypotheses", "confidence_hint", "REAL")
                self._ensure_column(conn, "hypotheses", "stage", "TEXT")
                self._ensure_column(conn, "hypotheses", "trigger_refs_json", "TEXT")
                self._ensure_column(
                    conn, "hypotheses", "related_object_ids_json", "TEXT"
                )
                self._ensure_column(conn, "hypotheses", "novelty_typing", "TEXT")
                self._ensure_column(
                    conn, "hypotheses", "minimum_validation_action_json", "TEXT"
                )
                self._ensure_column(conn, "hypotheses", "weakening_signal_json", "TEXT")
                self._ensure_column(conn, "hypotheses", "decision_source_type", "TEXT")
                self._ensure_column(conn, "hypotheses", "decision_source_ref", "TEXT")
                self._ensure_column(conn, "hypotheses", "decided_at", "TEXT")
                self._ensure_column(conn, "hypotheses", "decided_request_id", "TEXT")
                self._ensure_column(conn, "hypotheses", "created_at", "TEXT")
                self._ensure_column(conn, "hypotheses", "updated_at", "TEXT")
                self._ensure_column(conn, "hypotheses", "generation_job_id", "TEXT")
                self._ensure_column(conn, "hypotheses", "provider_backend", "TEXT")
                self._ensure_column(conn, "hypotheses", "provider_model", "TEXT")
                self._ensure_column(conn, "hypotheses", "llm_request_id", "TEXT")
                self._ensure_column(conn, "hypotheses", "llm_response_id", "TEXT")
                self._ensure_column(conn, "hypotheses", "usage_json", "TEXT")
                self._ensure_column(conn, "hypotheses", "fallback_used", "INTEGER")
                self._ensure_column(conn, "hypotheses", "degraded", "INTEGER")
                self._ensure_column(conn, "hypotheses", "degraded_reason", "TEXT")
                self._ensure_column(conn, "hypotheses", "source_pool_id", "TEXT")
                self._ensure_column(conn, "hypotheses", "source_candidate_id", "TEXT")
                self._ensure_column(conn, "hypotheses", "source_round_id", "TEXT")
                self._ensure_column(conn, "hypotheses", "finalizing_match_id", "TEXT")
                self._ensure_column(conn, "hypotheses", "search_tree_node_id", "TEXT")
                self._ensure_column(conn, "hypotheses", "reasoning_chain_id", "TEXT")
                self._ensure_column(conn, "hypotheses", "weakest_step_ref_json", "TEXT")
                self._ensure_column(conn, "memory_actions", "request_id", "TEXT")
                self._ensure_column(conn, "memory_actions", "note", "TEXT")
                self._ensure_column(conn, "memory_actions", "memory_ref_json", "TEXT")
                self._ensure_column(conn, "memory_actions", "created_at", "TEXT")
                self._ensure_column(conn, "failures", "impact_summary_json", "TEXT")
                self._ensure_column(conn, "failures", "impact_updated_at", "TEXT")
                self._ensure_column(
                    conn, "failures", "derived_from_validation_id", "TEXT"
                )
                self._ensure_column(
                    conn,
                    "failures",
                    "derived_from_validation_result_id",
                    "TEXT",
                )
                self._ensure_column(conn, "validations", "status", "TEXT")
                self._ensure_column(conn, "validations", "latest_outcome", "TEXT")
                self._ensure_column(conn, "validations", "latest_result_id", "TEXT")
                self._ensure_column(conn, "validations", "updated_at", "TEXT")
                self._ensure_column(conn, "packages", "snapshot_type", "TEXT")
                self._ensure_column(conn, "packages", "snapshot_version", "TEXT")
                self._ensure_column(
                    conn, "packages", "private_dependency_flags_json", "TEXT"
                )
                self._ensure_column(conn, "packages", "public_gap_nodes_json", "TEXT")
                self._ensure_column(conn, "packages", "boundary_notes_json", "TEXT")
                self._ensure_column(conn, "packages", "traceability_refs_json", "TEXT")
                self._ensure_column(conn, "packages", "snapshot_payload_json", "TEXT")
                self._ensure_column(conn, "packages", "replay_ready", "INTEGER")
                self._ensure_column(conn, "packages", "build_request_id", "TEXT")
                self._ensure_column(conn, "packages", "created_at", "TEXT")
                self._ensure_column(conn, "packages", "updated_at", "TEXT")
                self._ensure_column(conn, "packages", "published_at", "TEXT")
                self._ensure_column(
                    conn, "package_publish_results", "request_id", "TEXT"
                )
                self._ensure_column(conn, "evidence_refs", "doi", "TEXT")
                self._ensure_column(conn, "evidence_refs", "url", "TEXT")
                self._ensure_column(conn, "evidence_refs", "venue", "TEXT")
                self._ensure_column(conn, "evidence_refs", "publication_year", "INTEGER")
                self._ensure_column(conn, "evidence_refs", "authors_json", "TEXT NOT NULL DEFAULT '[]'")
                self._ensure_column(conn, "evidence_refs", "locator_json", "TEXT NOT NULL DEFAULT '{}'")
                self._ensure_column(conn, "evidence_refs", "metadata_json", "TEXT NOT NULL DEFAULT '{}'")
                self._ensure_column(conn, "evidence_refs", "confirmed_at", "TEXT")
                self._ensure_column(conn, "scholarly_source_cache", "doi", "TEXT")
                self._ensure_column(conn, "scholarly_source_cache", "url", "TEXT")
                self._ensure_column(conn, "scholarly_source_cache", "venue", "TEXT")
                self._ensure_column(
                    conn, "scholarly_source_cache", "publication_year", "INTEGER"
                )
                self._ensure_column(
                    conn,
                    "scholarly_source_cache",
                    "authors_json",
                    "TEXT NOT NULL DEFAULT '[]'",
                )
                self._ensure_column(
                    conn,
                    "scholarly_source_cache",
                    "metadata_json",
                    "TEXT NOT NULL DEFAULT '{}'",
                )
                conn.commit()

    def _ensure_column(
        self, conn: sqlite3.Connection, table: str, column: str, definition: str
    ) -> None:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        existing = {row[1] for row in rows}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def reset_all(self) -> None:
        tables = [
            "sources",
            "candidates",
            "extraction_results",
            "routes",
            "research_evidences",
            "research_assumptions",
            "research_conclusions",
            "research_gaps",
            "research_conflicts",
            "research_failures",
            "research_validations",
            "relation_candidates",
            "graph_nodes",
            "graph_edges",
            "graph_versions",
            "graph_workspaces",
            "failures",
            "validations",
            "validation_results",
            "memory_actions",
            "hypotheses",
            "hypothesis_candidate_pools",
            "hypothesis_candidates",
            "hypothesis_rounds",
            "hypothesis_reviews",
            "hypothesis_matches",
            "hypothesis_evolutions",
            "hypothesis_meta_reviews",
            "hypothesis_proximity_edges",
            "hypothesis_search_tree_nodes",
            "hypothesis_search_tree_edges",
            "packages",
            "package_publish_results",
            "jobs",
            "research_events",
            "evidence_refs",
            "scholarly_source_cache",
        ]
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                for table in tables:
                    conn.execute(f"DELETE FROM {table}")
                conn.commit()
        if hasattr(self, "_hypothesis_multi_orchestrator"):
            setattr(self, "_hypothesis_multi_orchestrator", None)

    def create_source(
        self,
        *,
        source_id: str | None = None,
        workspace_id: str,
        source_type: str,
        title: str,
        content: str,
        metadata: dict[str, object],
        import_request_id: str | None,
    ) -> dict[str, object]:
        resolved_source_id = source_id or self.gen_id("src")
        now = self.now()
        self._execute(
            """
            INSERT INTO sources (
                source_id, workspace_id, source_type, title, content, normalized_content,
                status, metadata_json, import_request_id, last_extract_job_id, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                resolved_source_id,
                workspace_id,
                source_type,
                title,
                content,
                None,
                "raw",
                self._dumps(metadata),
                import_request_id,
                None,
                self._to_iso(now),
                self._to_iso(now),
            ),
        )
        return self.get_source(resolved_source_id)

    def get_source(
        self, source_id: str, *, conn: sqlite3.Connection | None = None
    ) -> dict[str, object] | None:
        row = self._fetchone(
            "SELECT * FROM sources WHERE source_id = ?",
            (source_id,),
            conn=conn,
        )
        if row is None:
            return None
        last_extract_job_id = row["last_extract_job_id"]
        latest_result = None
        if last_extract_job_id:
            latest_result = self._fetchone(
                """
                SELECT *
                FROM extraction_results
                WHERE source_id = ? AND job_id = ?
                ORDER BY created_at DESC, candidate_batch_id DESC
                LIMIT 1
                """,
                (source_id, last_extract_job_id),
                conn=conn,
            )
        if latest_result is None:
            latest_result = self._fetchone(
                """
                SELECT *
                FROM extraction_results
                WHERE source_id = ?
                ORDER BY created_at DESC, candidate_batch_id DESC
                LIMIT 1
                """,
                (source_id,),
                conn=conn,
            )
        latest_error = self._loads(latest_result["error_json"]) if latest_result is not None else None
        return {
            "source_id": row["source_id"],
            "workspace_id": row["workspace_id"],
            "source_type": row["source_type"],
            "title": row["title"],
            "content": row["content"],
            "normalized_content": row["normalized_content"],
            "status": row["status"],
            "metadata": self._loads(row["metadata_json"]),
            "import_request_id": row["import_request_id"],
            "last_extract_job_id": last_extract_job_id,
            "last_candidate_batch_id": latest_result["candidate_batch_id"] if latest_result is not None else None,
            "last_extract_status": latest_result["status"] if latest_result is not None else None,
            "last_extract_error": latest_error if isinstance(latest_error, dict) else None,
            "created_at": self._from_iso(row["created_at"]),
            "updated_at": self._from_iso(row["updated_at"]),
        }

    def list_sources(self, *, workspace_id: str) -> list[dict[str, object]]:
        rows = self._fetchall(
            """
            SELECT source_id
            FROM sources
            WHERE workspace_id = ?
            ORDER BY created_at DESC, source_id DESC
            """,
            (workspace_id,),
        )
        items: list[dict[str, object]] = []
        for row in rows:
            source = self.get_source(str(row["source_id"]))
            if source is not None:
                items.append(source)
        return items

    def list_workspaces(self) -> list[dict[str, object]]:
        rows = self._fetchall(
            """
            WITH workspace_ids AS (
                SELECT workspace_id FROM sources
                UNION
                SELECT workspace_id FROM candidates
                UNION
                SELECT workspace_id FROM graph_nodes
                UNION
                SELECT workspace_id FROM graph_edges
                UNION
                SELECT workspace_id FROM routes
            ),
            source_counts AS (
                SELECT workspace_id, COUNT(*) AS source_count
                FROM sources
                GROUP BY workspace_id
            ),
            candidate_counts AS (
                SELECT workspace_id, COUNT(*) AS candidate_count
                FROM candidates
                GROUP BY workspace_id
            ),
            node_counts AS (
                SELECT workspace_id, COUNT(*) AS node_count
                FROM graph_nodes
                GROUP BY workspace_id
            ),
            edge_counts AS (
                SELECT workspace_id, COUNT(*) AS edge_count
                FROM graph_edges
                GROUP BY workspace_id
            ),
            route_counts AS (
                SELECT workspace_id, COUNT(*) AS route_count
                FROM routes
                GROUP BY workspace_id
            ),
            updates AS (
                SELECT workspace_id, MAX(updated_at) AS updated_at
                FROM (
                    SELECT workspace_id, updated_at FROM sources
                    UNION ALL
                    SELECT workspace_id, updated_at FROM graph_nodes
                    UNION ALL
                    SELECT workspace_id, updated_at FROM graph_edges
                )
                GROUP BY workspace_id
            )
            SELECT
                w.workspace_id,
                COALESCE(s.source_count, 0) AS source_count,
                COALESCE(c.candidate_count, 0) AS candidate_count,
                COALESCE(n.node_count, 0) AS node_count,
                COALESCE(e.edge_count, 0) AS edge_count,
                COALESCE(r.route_count, 0) AS route_count,
                u.updated_at AS updated_at
            FROM workspace_ids w
            LEFT JOIN source_counts s ON s.workspace_id = w.workspace_id
            LEFT JOIN candidate_counts c ON c.workspace_id = w.workspace_id
            LEFT JOIN node_counts n ON n.workspace_id = w.workspace_id
            LEFT JOIN edge_counts e ON e.workspace_id = w.workspace_id
            LEFT JOIN route_counts r ON r.workspace_id = w.workspace_id
            LEFT JOIN updates u ON u.workspace_id = w.workspace_id
            ORDER BY u.updated_at DESC NULLS LAST, w.workspace_id ASC
            """
        )
        return [
            {
                "workspace_id": row["workspace_id"],
                "source_count": int(row["source_count"] or 0),
                "candidate_count": int(row["candidate_count"] or 0),
                "node_count": int(row["node_count"] or 0),
                "edge_count": int(row["edge_count"] or 0),
                "route_count": int(row["route_count"] or 0),
                "updated_at": (
                    self._from_iso(row["updated_at"])
                    if row["updated_at"] is not None
                    else None
                ),
            }
            for row in rows
        ]

    def list_source_topic_clusters(self, *, workspace_id: str) -> list[dict[str, object]]:
        rows = self._fetchall(
            """
            SELECT source_id, metadata_json
            FROM sources
            WHERE workspace_id = ?
            ORDER BY created_at DESC, source_id DESC
            """,
            (workspace_id,),
        )
        items: list[dict[str, object]] = []
        for row in rows:
            source_id = str(row["source_id"])
            metadata = self._loads_dict(row["metadata_json"])
            raw_clusters = metadata.get("topic_clusters")
            if not isinstance(raw_clusters, list):
                continue
            for index, item in enumerate(raw_clusters):
                if not isinstance(item, dict):
                    continue
                raw_keywords = item.get("keywords")
                if not isinstance(raw_keywords, list):
                    continue
                keywords = [
                    str(keyword).strip()
                    for keyword in raw_keywords
                    if str(keyword).strip()
                ]
                if not keywords:
                    continue
                cluster_id = str(item.get("cluster_id") or "").strip()
                if not cluster_id:
                    cluster_id = f"source_{source_id}_topic_{index}"
                items.append(
                    {
                        "source_id": source_id,
                        "cluster_id": cluster_id,
                        "cluster_label": str(item.get("cluster_label") or "").strip(),
                        "keywords": keywords,
                        "signal_score": int(item.get("signal_score") or 0),
                        "evidence_hits": int(item.get("evidence_hits") or 0),
                    }
                )
        return items

    def update_source_metadata(
        self, *, source_id: str, metadata: dict[str, object]
    ) -> dict[str, object] | None:
        source = self.get_source(source_id)
        if source is None:
            return None
        self._execute(
            """
            UPDATE sources
            SET metadata_json = ?, updated_at = ?
            WHERE source_id = ?
            """,
            (self._dumps(metadata), self._to_iso(self.now()), source_id),
        )
        return self.get_source(source_id)

    def update_source_processing(
        self,
        *,
        source_id: str,
        status: str,
        normalized_content: str | None = None,
        last_extract_job_id: str | None = None,
    ) -> None:
        current = self.get_source(source_id)
        if current is None:
            return
        self._execute(
            """
            UPDATE sources
            SET status = ?, normalized_content = ?, last_extract_job_id = ?, updated_at = ?
            WHERE source_id = ?
            """,
            (
                status,
                (
                    normalized_content
                    if normalized_content is not None
                    else current["normalized_content"]
                ),
                (
                    last_extract_job_id
                    if last_extract_job_id is not None
                    else current["last_extract_job_id"]
                ),
                self._to_iso(self.now()),
                source_id,
            ),
        )

    def get_candidate(self, candidate_id: str) -> dict[str, object] | None:
        row = self._fetchone(
            "SELECT * FROM candidates WHERE candidate_id = ?", (candidate_id,)
        )
        if row is None:
            return None
        degraded_reason_raw = row["degraded_reason"]
        degraded = bool(row["degraded"] or degraded_reason_raw)
        degraded_reason = (
            str(degraded_reason_raw).strip() if degraded and degraded_reason_raw else None
        )
        return {
            "candidate_id": row["candidate_id"],
            "workspace_id": row["workspace_id"],
            "source_id": row["source_id"],
            "candidate_type": row["candidate_type"],
            "semantic_type": row["semantic_type"],
            "text": row["text"],
            "status": row["status"],
            "source_span": self._loads(row["source_span_json"]),
            "quote": row["quote"],
            "trace_refs": self._loads_dict(row["trace_refs_json"]),
            "candidate_batch_id": row["candidate_batch_id"],
            "extraction_job_id": row["extraction_job_id"],
            "extractor_name": row["extractor_name"],
            "reject_reason": row["reject_reason"],
            "provider_backend": row["provider_backend"],
            "provider_model": row["provider_model"],
            "request_id": row["llm_request_id"],
            "llm_response_id": row["llm_response_id"],
            "usage": self._loads(row["usage_json"]) if row["usage_json"] else None,
            "fallback_used": bool(row["fallback_used"] or 0),
            "degraded": degraded,
            "degraded_reason": degraded_reason,
        }

    def create_candidate_batch(
        self, *, workspace_id: str, source_id: str, job_id: str, request_id: str | None
    ) -> dict[str, object]:
        candidate_batch_id = self.gen_id("batch")
        now = self.now()
        self._execute(
            """
            INSERT INTO extraction_results (
                candidate_batch_id, workspace_id, source_id, job_id, request_id,
                candidate_ids_json, status, error_json, created_at, finished_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate_batch_id,
                workspace_id,
                source_id,
                job_id,
                request_id,
                self._dumps([]),
                "running",
                None,
                self._to_iso(now),
                None,
            ),
        )
        return self.get_candidate_batch(candidate_batch_id)

    def add_candidates_to_batch(
        self,
        *,
        candidate_batch_id: str,
        workspace_id: str,
        source_id: str,
        job_id: str,
        candidates: list[dict[str, object]],
        llm_trace: dict[str, object] | None = None,
    ) -> list[dict[str, object]]:
        created: list[dict[str, object]] = []
        for candidate in candidates:
            candidate_id = self.gen_id("cand")
            self._execute(
                """
                INSERT INTO candidates (
                    candidate_id, workspace_id, source_id, candidate_type, semantic_type, text, status,
                    source_span_json, quote, trace_refs_json, candidate_batch_id, extraction_job_id, extractor_name, reject_reason,
                    provider_backend, provider_model, llm_request_id, llm_response_id, usage_json, fallback_used, degraded, degraded_reason
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate_id,
                    workspace_id,
                    source_id,
                    candidate["candidate_type"],
                    candidate.get("semantic_type"),
                    candidate["text"],
                    "pending",
                    self._dumps(candidate["source_span"]),
                    candidate.get("quote"),
                    self._dumps(candidate.get("trace_refs") or {}),
                    candidate_batch_id,
                    job_id,
                    candidate["extractor_name"],
                    None,
                    (
                        candidate.get("provider_backend")
                        or (llm_trace or {}).get("provider_backend")
                    ),
                    (
                        candidate.get("provider_model")
                        or (llm_trace or {}).get("provider_model")
                    ),
                    candidate.get("request_id")
                    or (llm_trace or {}).get("request_id"),
                    candidate.get("llm_response_id")
                    or (llm_trace or {}).get("llm_response_id"),
                    self._dumps(
                        candidate.get("usage")
                        or (llm_trace or {}).get("usage")
                        or {}
                    ),
                    int(
                        bool(
                            candidate.get("fallback_used")
                            if "fallback_used" in candidate
                            else (llm_trace or {}).get("fallback_used", False)
                        )
                    ),
                    int(
                        bool(
                            candidate.get("degraded")
                            if "degraded" in candidate
                            else (llm_trace or {}).get("degraded", False)
                        )
                    ),
                    (
                        candidate.get("degraded_reason")
                        or (llm_trace or {}).get("degraded_reason")
                    ),
                ),
            )
            loaded = self.get_candidate(candidate_id)
            if loaded is not None:
                created.append(loaded)

        self._execute(
            """
            UPDATE extraction_results
            SET candidate_ids_json = ?, status = ?, finished_at = ?, error_json = NULL
            WHERE candidate_batch_id = ?
            """,
            (
                self._dumps([item["candidate_id"] for item in created]),
                "succeeded",
                self._to_iso(self.now()),
                candidate_batch_id,
            ),
        )
        return created

    def add_relation_candidates_to_batch(
        self,
        *,
        candidate_batch_id: str,
        workspace_id: str,
        source_id: str,
        job_id: str,
        relations: list[dict[str, object]],
        conn: sqlite3.Connection | None = None,
    ) -> list[dict[str, object]]:
        created: list[dict[str, object]] = []
        for relation in relations:
            relation_candidate_id = self.gen_id("relcand")
            self._execute(
                """
                INSERT INTO relation_candidates (
                    relation_candidate_id, workspace_id, source_id, candidate_batch_id, extraction_job_id,
                    source_candidate_id, target_candidate_id, semantic_relation_type, relation_type,
                    relation_status, quote, trace_refs_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    relation_candidate_id,
                    workspace_id,
                    source_id,
                    candidate_batch_id,
                    job_id,
                    relation.get("source_candidate_id"),
                    relation.get("target_candidate_id"),
                    relation.get("semantic_relation_type"),
                    relation.get("relation_type"),
                    str(relation.get("relation_status") or "unresolved"),
                    relation.get("quote"),
                    self._dumps(relation.get("trace_refs") or {}),
                    self._to_iso(self.now()),
                ),
                conn=conn,
            )
            loaded = self.get_relation_candidate(relation_candidate_id, conn=conn)
            if loaded is not None:
                created.append(loaded)
        return created

    def get_relation_candidate(
        self,
        relation_candidate_id: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, object] | None:
        row = self._fetchone(
            "SELECT * FROM relation_candidates WHERE relation_candidate_id = ?",
            (relation_candidate_id,),
            conn=conn,
        )
        if row is None:
            return None
        return {
            "relation_candidate_id": row["relation_candidate_id"],
            "workspace_id": row["workspace_id"],
            "source_id": row["source_id"],
            "candidate_batch_id": row["candidate_batch_id"],
            "extraction_job_id": row["extraction_job_id"],
            "source_candidate_id": row["source_candidate_id"],
            "target_candidate_id": row["target_candidate_id"],
            "semantic_relation_type": row["semantic_relation_type"],
            "relation_type": row["relation_type"],
            "relation_status": row["relation_status"],
            "quote": row["quote"],
            "trace_refs": self._loads_dict(row["trace_refs_json"]),
            "created_at": self._from_iso(row["created_at"]),
        }

    def list_relation_candidates(
        self,
        *,
        workspace_id: str,
        source_id: str | None = None,
        candidate_batch_id: str | None = None,
        relation_status: str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> list[dict[str, object]]:
        sql = "SELECT relation_candidate_id FROM relation_candidates WHERE workspace_id = ?"
        params: list[object] = [workspace_id]
        if source_id is not None:
            sql += " AND source_id = ?"
            params.append(source_id)
        if candidate_batch_id is not None:
            sql += " AND candidate_batch_id = ?"
            params.append(candidate_batch_id)
        if relation_status is not None:
            sql += " AND relation_status = ?"
            params.append(relation_status)
        sql += " ORDER BY created_at ASC, relation_candidate_id ASC"
        rows = self._fetchall(sql, tuple(params), conn=conn)
        results: list[dict[str, object]] = []
        for row in rows:
            relation = self.get_relation_candidate(
                str(row["relation_candidate_id"]),
                conn=conn,
            )
            if relation is not None:
                results.append(relation)
        return results

    def fail_candidate_batch(
        self, *, candidate_batch_id: str, error: dict[str, object]
    ) -> None:
        self._execute(
            """
            UPDATE extraction_results
            SET status = ?, error_json = ?, finished_at = ?
            WHERE candidate_batch_id = ?
            """,
            (
                "failed",
                self._dumps(error),
                self._to_iso(self.now()),
                candidate_batch_id,
            ),
        )

    def update_candidate_batch_llm_trace(
        self,
        *,
        candidate_batch_id: str,
        provider_backend: str | None,
        provider_model: str | None,
        llm_request_id: str | None,
        llm_response_id: str | None,
        usage: dict[str, object] | None,
        fallback_used: bool,
        degraded: bool,
        degraded_reason: str | None,
        partial_failure_count: int = 0,
    ) -> None:
        normalized_degraded = bool(degraded or degraded_reason)
        normalized_degraded_reason = (
            str(degraded_reason).strip() if degraded_reason and normalized_degraded else None
        )
        self._execute(
            """
            UPDATE extraction_results
            SET provider_backend = ?,
                provider_model = ?,
                llm_request_id = ?,
                llm_response_id = ?,
                usage_json = ?,
                fallback_used = ?,
                degraded = ?,
                degraded_reason = ?,
                partial_failure_count = ?
            WHERE candidate_batch_id = ?
            """,
            (
                provider_backend,
                provider_model,
                llm_request_id,
                llm_response_id,
                self._dumps(usage or {}),
                int(bool(fallback_used)),
                int(normalized_degraded),
                normalized_degraded_reason,
                int(partial_failure_count),
                candidate_batch_id,
            ),
        )

    def get_candidate_batch(self, candidate_batch_id: str) -> dict[str, object] | None:
        row = self._fetchone(
            "SELECT * FROM extraction_results WHERE candidate_batch_id = ?",
            (candidate_batch_id,),
        )
        if row is None:
            return None
        degraded_reason_raw = row["degraded_reason"]
        degraded = bool(row["degraded"] or degraded_reason_raw)
        degraded_reason = (
            str(degraded_reason_raw).strip() if degraded and degraded_reason_raw else None
        )
        return {
            "candidate_batch_id": row["candidate_batch_id"],
            "workspace_id": row["workspace_id"],
            "source_id": row["source_id"],
            "job_id": row["job_id"],
            "request_id": row["request_id"],
            "candidate_ids": self._loads(row["candidate_ids_json"]),
            "status": row["status"],
            "error": self._loads(row["error_json"]),
            "provider_backend": row["provider_backend"],
            "provider_model": row["provider_model"],
            "llm_request_id": row["llm_request_id"],
            "llm_response_id": row["llm_response_id"],
            "usage": self._normalize_usage(
                self._loads(row["usage_json"]) if row["usage_json"] else None
            ),
            "fallback_used": bool(row["fallback_used"] or 0),
            "degraded": degraded,
            "degraded_reason": degraded_reason,
            "partial_failure_count": int(row["partial_failure_count"] or 0),
            "created_at": self._from_iso(row["created_at"]),
            "finished_at": self._from_iso(row["finished_at"]),
        }

    def get_candidate_batch_for_source(
        self, *, source_id: str, candidate_batch_id: str, workspace_id: str
    ) -> dict[str, object] | None:
        row = self._fetchone(
            """
            SELECT * FROM extraction_results
            WHERE candidate_batch_id = ? AND source_id = ? AND workspace_id = ?
            """,
            (candidate_batch_id, source_id, workspace_id),
        )
        if row is None:
            return None
        return self.get_candidate_batch(candidate_batch_id)

    def list_candidates(
        self,
        *,
        workspace_id: str,
        source_id: str | None,
        candidate_type: str | None,
        status: str | None = None,
    ) -> list[dict[str, object]]:
        sql = "SELECT * FROM candidates WHERE workspace_id = ?"
        params: list[object] = [workspace_id]
        if source_id is not None:
            sql += " AND source_id = ?"
            params.append(source_id)
        if candidate_type is not None:
            sql += " AND candidate_type = ?"
            params.append(candidate_type)
        if status is not None:
            sql += " AND status = ?"
            params.append(status)
        rows = self._fetchall(sql, tuple(params))
        results: list[dict[str, object]] = []
        for row in rows:
            degraded_reason_raw = row["degraded_reason"]
            degraded = bool(row["degraded"] or degraded_reason_raw)
            degraded_reason = (
                str(degraded_reason_raw).strip() if degraded and degraded_reason_raw else None
            )
            results.append(
                {
                "candidate_id": row["candidate_id"],
                "workspace_id": row["workspace_id"],
                "source_id": row["source_id"],
                "candidate_type": row["candidate_type"],
                "semantic_type": row["semantic_type"],
                "text": row["text"],
                "status": row["status"],
                "source_span": self._loads(row["source_span_json"]),
                "quote": row["quote"],
                "trace_refs": self._loads_dict(row["trace_refs_json"]),
                "candidate_batch_id": row["candidate_batch_id"],
                "extraction_job_id": row["extraction_job_id"],
                "extractor_name": row["extractor_name"],
                "provider_backend": row["provider_backend"],
                "provider_model": row["provider_model"],
                "request_id": row["llm_request_id"],
                "llm_response_id": row["llm_response_id"],
                "usage": self._normalize_usage(
                    self._loads(row["usage_json"]) if row["usage_json"] else None
                ),
                "fallback_used": bool(row["fallback_used"] or 0),
                "degraded": degraded,
                "degraded_reason": degraded_reason,
            }
            )
        return results

    def update_candidate_status(
        self,
        *,
        candidate_id: str,
        status: str,
        reject_reason: str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        self._execute(
            "UPDATE candidates SET status = ?, reject_reason = ? WHERE candidate_id = ?",
            (status, reject_reason, candidate_id),
            conn=conn,
        )

    def find_confirmed_object_by_normalized_text(
        self,
        *,
        workspace_id: str,
        normalized_text: str,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, str] | None:
        queries = [
            ("evidence", "research_evidences", "evidence_id"),
            ("assumption", "research_assumptions", "assumption_id"),
            ("conclusion", "research_conclusions", "conclusion_id"),
            ("gap", "research_gaps", "gap_id"),
            ("conflict", "research_conflicts", "conflict_id"),
            ("failure", "research_failures", "failure_id"),
            ("validation", "research_validations", "validation_id"),
        ]
        for object_type, table, id_col in queries:
            row = self._fetchone(
                f"SELECT {id_col} AS object_id FROM {table} WHERE workspace_id = ? AND normalized_text = ? LIMIT 1",
                (workspace_id, normalized_text),
                conn=conn,
            )
            if row is not None:
                return {"object_type": object_type, "object_id": row["object_id"]}
        return None

    def create_confirmed_object_from_candidate(
        self,
        *,
        candidate: dict[str, object],
        normalized_text: str,
        request_id: str,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, str]:
        candidate_type = str(candidate["candidate_type"])
        table_map = {
            "evidence": ("research_evidences", "evidence_id"),
            "assumption": ("research_assumptions", "assumption_id"),
            "conclusion": ("research_conclusions", "conclusion_id"),
            "gap": ("research_gaps", "gap_id"),
            "conflict": ("research_conflicts", "conflict_id"),
            "failure": ("research_failures", "failure_id"),
            "validation": ("research_validations", "validation_id"),
        }
        table_info = table_map.get(candidate_type)
        if table_info is None:
            raise ValueError(f"unsupported candidate_type: {candidate_type}")

        table_name, id_column = table_info
        object_id = self.gen_id(candidate_type[:3])
        now = self._to_iso(self.now())
        self._execute(
            f"""
            INSERT INTO {table_name} (
                {id_column}, workspace_id, candidate_id, source_id, text, normalized_text,
                source_span_json, semantic_type, quote, trace_refs_json,
                candidate_batch_id, extraction_job_id, created_at, created_request_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                object_id,
                str(candidate["workspace_id"]),
                str(candidate["candidate_id"]),
                str(candidate["source_id"]),
                str(candidate["text"]),
                normalized_text,
                self._dumps(candidate["source_span"]),
                candidate.get("semantic_type"),
                candidate.get("quote"),
                self._dumps(candidate.get("trace_refs") or {}),
                candidate.get("candidate_batch_id"),
                candidate.get("extraction_job_id"),
                now,
                request_id,
            ),
            conn=conn,
        )
        return {"object_type": candidate_type, "object_id": object_id}

    def create_route(
        self,
        *,
        workspace_id: str,
        title: str,
        summary: str,
        status: str,
        support_score: float,
        risk_score: float,
        progressability_score: float,
        conclusion: str,
        key_supports: list[str],
        assumptions: list[str],
        risks: list[str],
        next_validation_action: str,
        novelty_level: str = "incremental",
        relation_tags: list[str] | None = None,
        top_factors: list[dict[str, object]] | None = None,
        score_breakdown: dict[str, object] | None = None,
        node_score_breakdown: list[dict[str, object]] | None = None,
        scoring_template_id: str | None = None,
        conclusion_node_id: str | None = None,
        route_node_ids: list[str] | None = None,
        route_edge_ids: list[str] | None = None,
        key_support_node_ids: list[str] | None = None,
        key_assumption_node_ids: list[str] | None = None,
        risk_node_ids: list[str] | None = None,
        next_validation_node_id: str | None = None,
        version_id: str | None = None,
        provider_backend: str | None = None,
        provider_model: str | None = None,
        llm_request_id: str | None = None,
        llm_response_id: str | None = None,
        usage: dict[str, object] | None = None,
        fallback_used: bool = False,
        degraded: bool = False,
        degraded_reason: str | None = None,
        summary_generation_mode: str = "llm",
        key_strengths: list[dict[str, object]] | None = None,
        key_risks: list[dict[str, object]] | None = None,
        open_questions: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        route_id = self.gen_id("route")
        confidence_score, confidence_grade = self._compute_route_confidence(
            support_score=support_score,
            risk_score=risk_score,
            progressability_score=progressability_score,
        )
        self._execute(
            """
            INSERT INTO routes (
                route_id, workspace_id, title, summary, status, support_score, risk_score, progressability_score,
                confidence_score, confidence_grade, rank,
                novelty_level, relation_tags_json, top_factors_json, score_breakdown_json, node_score_breakdown_json,
                scoring_template_id, scored_at, conclusion, key_supports_json, assumptions_json, risks_json, next_validation_action,
                conclusion_node_id, route_node_ids_json, route_edge_ids_json, key_support_node_ids_json, key_assumption_node_ids_json,
                risk_node_ids_json, next_validation_node_id, version_id, key_strengths_json, key_risks_json, open_questions_json,
                provider_backend, provider_model, llm_request_id, llm_response_id, usage_json, fallback_used, degraded, degraded_reason, summary_generation_mode
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                route_id,
                workspace_id,
                title,
                summary,
                status,
                support_score,
                risk_score,
                progressability_score,
                confidence_score,
                confidence_grade,
                None,
                novelty_level,
                self._dumps(relation_tags or []),
                self._dumps(top_factors or []),
                self._dumps(score_breakdown or {}),
                self._dumps(node_score_breakdown or []),
                scoring_template_id,
                self._to_iso(self.now()) if score_breakdown is not None else None,
                conclusion,
                self._dumps(key_supports),
                self._dumps(assumptions),
                self._dumps(risks),
                next_validation_action,
                conclusion_node_id,
                self._dumps(route_node_ids or []),
                self._dumps(route_edge_ids or []),
                self._dumps(key_support_node_ids or []),
                self._dumps(key_assumption_node_ids or []),
                self._dumps(risk_node_ids or []),
                next_validation_node_id,
                version_id,
                self._dumps(key_strengths or []),
                self._dumps(key_risks or []),
                self._dumps(open_questions or []),
                provider_backend,
                provider_model,
                llm_request_id,
                llm_response_id,
                self._dumps(usage or {}),
                int(bool(fallback_used)),
                int(bool(degraded)),
                degraded_reason,
                summary_generation_mode,
            ),
        )
        return self.get_route(route_id)

    def get_route(self, route_id: str) -> dict[str, object] | None:
        row = self._fetchone("SELECT * FROM routes WHERE route_id = ?", (route_id,))
        if row is None:
            return None
        (
            route_edge_ids,
            route_edge_ids_canonical_present,
            route_edge_ids_canonical_valid,
            route_edge_ids_canonical_error,
        ) = self._decode_route_edge_ids_json(row["route_edge_ids_json"])
        support_score = float(row["support_score"])
        risk_score = float(row["risk_score"])
        progressability_score = float(row["progressability_score"])
        fallback_confidence_score, fallback_confidence_grade = self._compute_route_confidence(
            support_score=support_score,
            risk_score=risk_score,
            progressability_score=progressability_score,
        )
        return {
            "route_id": row["route_id"],
            "workspace_id": row["workspace_id"],
            "title": row["title"],
            "summary": row["summary"],
            "status": row["status"],
            "support_score": support_score,
            "risk_score": risk_score,
            "progressability_score": progressability_score,
            "confidence_score": (
                float(row["confidence_score"])
                if row["confidence_score"] is not None
                else fallback_confidence_score
            ),
            "confidence_grade": (
                str(row["confidence_grade"])
                if row["confidence_grade"]
                else fallback_confidence_grade
            ),
            "rank": int(row["rank"]) if row["rank"] is not None else None,
            "novelty_level": row["novelty_level"] or "incremental",
            "relation_tags": self._loads(row["relation_tags_json"]) or [],
            "top_factors": self._loads(row["top_factors_json"]) or [],
            "score_breakdown": self._loads(row["score_breakdown_json"]) or {},
            "node_score_breakdown": self._loads(row["node_score_breakdown_json"]) or [],
            "scoring_template_id": row["scoring_template_id"],
            "scored_at": self._from_iso(row["scored_at"]),
            "conclusion": row["conclusion"],
            "key_supports": self._loads(row["key_supports_json"]),
            "assumptions": self._loads(row["assumptions_json"]),
            "risks": self._loads(row["risks_json"]),
            "next_validation_action": row["next_validation_action"],
            "conclusion_node_id": row["conclusion_node_id"],
            "route_node_ids": self._loads(row["route_node_ids_json"]) or [],
            "route_edge_ids": route_edge_ids,
            "route_edge_ids_canonical_present": route_edge_ids_canonical_present,
            "route_edge_ids_canonical_valid": route_edge_ids_canonical_valid,
            "route_edge_ids_canonical_error": route_edge_ids_canonical_error,
            "key_support_node_ids": self._loads(row["key_support_node_ids_json"]) or [],
            "key_assumption_node_ids": self._loads(row["key_assumption_node_ids_json"])
            or [],
            "risk_node_ids": self._loads(row["risk_node_ids_json"]) or [],
            "next_validation_node_id": row["next_validation_node_id"],
            "version_id": row["version_id"],
            "provider_backend": row["provider_backend"],
            "provider_model": row["provider_model"],
            "request_id": row["llm_request_id"],
            "llm_response_id": row["llm_response_id"],
            "usage": self._loads(row["usage_json"]) if row["usage_json"] else None,
            "fallback_used": bool(row["fallback_used"] or 0),
            "degraded": bool(row["degraded"] or 0),
            "degraded_reason": row["degraded_reason"],
            "summary_generation_mode": row["summary_generation_mode"] or "llm",
            "key_strengths": self._loads(row["key_strengths_json"]) or [],
            "key_risks": self._loads(row["key_risks_json"]) or [],
            "open_questions": self._loads(row["open_questions_json"]) or [],
        }

    def list_routes(self, workspace_id: str) -> list[dict[str, object]]:
        rows = self._fetchall(
            "SELECT * FROM routes WHERE workspace_id = ?", (workspace_id,)
        )
        results: list[dict[str, object]] = []
        for row in rows:
            (
                route_edge_ids,
                route_edge_ids_canonical_present,
                route_edge_ids_canonical_valid,
                route_edge_ids_canonical_error,
            ) = self._decode_route_edge_ids_json(row["route_edge_ids_json"])
            support_score = float(row["support_score"])
            risk_score = float(row["risk_score"])
            progressability_score = float(row["progressability_score"])
            fallback_confidence_score, fallback_confidence_grade = self._compute_route_confidence(
                support_score=support_score,
                risk_score=risk_score,
                progressability_score=progressability_score,
            )
            results.append(
                {
                "route_id": row["route_id"],
                "workspace_id": row["workspace_id"],
                "title": row["title"],
                "summary": row["summary"],
                "status": row["status"],
                "support_score": support_score,
                "risk_score": risk_score,
                "progressability_score": progressability_score,
                "confidence_score": (
                    float(row["confidence_score"])
                    if row["confidence_score"] is not None
                    else fallback_confidence_score
                ),
                "confidence_grade": (
                    str(row["confidence_grade"])
                    if row["confidence_grade"]
                    else fallback_confidence_grade
                ),
                "rank": int(row["rank"]) if row["rank"] is not None else None,
                "novelty_level": row["novelty_level"] or "incremental",
                "relation_tags": self._loads(row["relation_tags_json"]) or [],
                "top_factors": self._loads(row["top_factors_json"]) or [],
                "score_breakdown": self._loads(row["score_breakdown_json"]) or {},
                "node_score_breakdown": self._loads(row["node_score_breakdown_json"])
                or [],
                "scoring_template_id": row["scoring_template_id"],
                "scored_at": self._from_iso(row["scored_at"]),
                "conclusion": row["conclusion"],
                "key_supports": self._loads(row["key_supports_json"]),
                "assumptions": self._loads(row["assumptions_json"]),
                "risks": self._loads(row["risks_json"]),
                "next_validation_action": row["next_validation_action"],
                "conclusion_node_id": row["conclusion_node_id"],
                "route_node_ids": self._loads(row["route_node_ids_json"]) or [],
                "route_edge_ids": route_edge_ids,
                "route_edge_ids_canonical_present": route_edge_ids_canonical_present,
                "route_edge_ids_canonical_valid": route_edge_ids_canonical_valid,
                "route_edge_ids_canonical_error": route_edge_ids_canonical_error,
                "key_support_node_ids": self._loads(row["key_support_node_ids_json"])
                or [],
                "key_assumption_node_ids": self._loads(
                    row["key_assumption_node_ids_json"]
                )
                or [],
                "risk_node_ids": self._loads(row["risk_node_ids_json"]) or [],
                "next_validation_node_id": row["next_validation_node_id"],
                "version_id": row["version_id"],
                "provider_backend": row["provider_backend"],
                "provider_model": row["provider_model"],
                "request_id": row["llm_request_id"],
                "llm_response_id": row["llm_response_id"],
                "usage": self._loads(row["usage_json"]) if row["usage_json"] else None,
                "fallback_used": bool(row["fallback_used"] or 0),
                "degraded": bool(row["degraded"] or 0),
                "degraded_reason": row["degraded_reason"],
                "summary_generation_mode": row["summary_generation_mode"] or "llm",
                "key_strengths": self._loads(row["key_strengths_json"]) or [],
                "key_risks": self._loads(row["key_risks_json"]) or [],
                "open_questions": self._loads(row["open_questions_json"]) or [],
            }
            )
        return results

    def update_route_scores(
        self,
        *,
        route_id: str,
        support_score: float,
        risk_score: float,
        progressability_score: float,
        scoring_template_id: str,
        top_factors: list[dict[str, object]],
        score_breakdown: dict[str, object],
        node_score_breakdown: list[dict[str, object]],
    ) -> dict[str, object] | None:
        confidence_score, confidence_grade = self._compute_route_confidence(
            support_score=support_score,
            risk_score=risk_score,
            progressability_score=progressability_score,
        )
        self._execute(
            """
            UPDATE routes
            SET support_score = ?,
                risk_score = ?,
                progressability_score = ?,
                confidence_score = ?,
                confidence_grade = ?,
                scoring_template_id = ?,
                top_factors_json = ?,
                score_breakdown_json = ?,
                node_score_breakdown_json = ?,
                scored_at = ?
            WHERE route_id = ?
            """,
            (
                support_score,
                risk_score,
                progressability_score,
                confidence_score,
                confidence_grade,
                scoring_template_id,
                self._dumps(top_factors),
                self._dumps(score_breakdown),
                self._dumps(node_score_breakdown),
                self._to_iso(self.now()),
                route_id,
            ),
        )
        return self.get_route(route_id)

    def update_route_projection(
        self,
        *,
        route_id: str,
        title: str,
        summary: str,
        conclusion: str,
        key_supports: list[str],
        assumptions: list[str],
        risks: list[str],
        next_validation_action: str,
        conclusion_node_id: str | None,
        route_node_ids: list[str],
        route_edge_ids: list[str],
        key_support_node_ids: list[str],
        key_assumption_node_ids: list[str],
        risk_node_ids: list[str],
        next_validation_node_id: str | None,
        version_id: str | None,
        provider_backend: str | None = None,
        provider_model: str | None = None,
        llm_request_id: str | None = None,
        llm_response_id: str | None = None,
        usage: dict[str, object] | None = None,
        fallback_used: bool = False,
        degraded: bool = False,
        degraded_reason: str | None = None,
        summary_generation_mode: str = "llm",
        key_strengths: list[dict[str, object]] | None = None,
        key_risks: list[dict[str, object]] | None = None,
        open_questions: list[dict[str, object]] | None = None,
    ) -> dict[str, object] | None:
        self._execute(
            """
            UPDATE routes
            SET title = ?,
                summary = ?,
                conclusion = ?,
                key_supports_json = ?,
                assumptions_json = ?,
                risks_json = ?,
                next_validation_action = ?,
                conclusion_node_id = ?,
                route_node_ids_json = ?,
                route_edge_ids_json = ?,
                key_support_node_ids_json = ?,
                key_assumption_node_ids_json = ?,
                risk_node_ids_json = ?,
                next_validation_node_id = ?,
                version_id = ?,
                key_strengths_json = ?,
                key_risks_json = ?,
                open_questions_json = ?,
                provider_backend = ?,
                provider_model = ?,
                llm_request_id = ?,
                llm_response_id = ?,
                usage_json = ?,
                fallback_used = ?,
                degraded = ?,
                degraded_reason = ?,
                summary_generation_mode = ?
            WHERE route_id = ?
            """,
            (
                title,
                summary,
                conclusion,
                self._dumps(key_supports),
                self._dumps(assumptions),
                self._dumps(risks),
                next_validation_action,
                conclusion_node_id,
                self._dumps(route_node_ids),
                self._dumps(route_edge_ids),
                self._dumps(key_support_node_ids),
                self._dumps(key_assumption_node_ids),
                self._dumps(risk_node_ids),
                next_validation_node_id,
                version_id,
                self._dumps(key_strengths or []),
                self._dumps(key_risks or []),
                self._dumps(open_questions or []),
                provider_backend,
                provider_model,
                llm_request_id,
                llm_response_id,
                self._dumps(usage or {}),
                int(bool(fallback_used)),
                int(bool(degraded)),
                degraded_reason,
                summary_generation_mode,
                route_id,
            ),
        )
        return self.get_route(route_id)

    def update_route_status(
        self, *, route_id: str, status: str
    ) -> dict[str, object] | None:
        self._execute(
            "UPDATE routes SET status = ? WHERE route_id = ?", (status, route_id)
        )
        return self.get_route(route_id)

    def update_route_rank(self, *, route_id: str, rank: int) -> dict[str, object] | None:
        self._execute("UPDATE routes SET rank = ? WHERE route_id = ?", (rank, route_id))
        return self.get_route(route_id)

    def set_routes_version_for_workspace(
        self, *, workspace_id: str, version_id: str
    ) -> None:
        self._execute(
            "UPDATE routes SET version_id = ? WHERE workspace_id = ?",
            (version_id, workspace_id),
        )

    def delete_routes_by_workspace(self, workspace_id: str) -> None:
        self._execute("DELETE FROM routes WHERE workspace_id = ?", (workspace_id,))

    def delete_route(self, route_id: str) -> None:
        self._execute("DELETE FROM routes WHERE route_id = ?", (route_id,))

    def list_confirmed_objects(
        self, workspace_id: str, *, conn: sqlite3.Connection | None = None
    ) -> list[dict[str, object]]:
        table_specs = [
            ("evidence", "research_evidences", "evidence_id"),
            ("assumption", "research_assumptions", "assumption_id"),
            ("conclusion", "research_conclusions", "conclusion_id"),
            ("gap", "research_gaps", "gap_id"),
            ("conflict", "research_conflicts", "conflict_id"),
            ("failure", "research_failures", "failure_id"),
            ("validation", "research_validations", "validation_id"),
        ]
        objects: list[dict[str, object]] = []
        for object_type, table_name, id_col in table_specs:
            rows = self._fetchall(
                f"""
                SELECT {id_col} AS object_id, candidate_id, source_id, text,
                       source_span_json, semantic_type, quote, trace_refs_json, created_at
                FROM {table_name}
                WHERE workspace_id = ?
                ORDER BY created_at ASC
                """,
                (workspace_id,),
                conn=conn,
            )
            objects.extend(
                [
                    {
                        "object_type": object_type,
                        "object_id": row["object_id"],
                        "candidate_id": row["candidate_id"],
                        "workspace_id": workspace_id,
                        "source_id": row["source_id"],
                        "text": row["text"],
                        "source_span": self._loads(row["source_span_json"]) or {},
                        "semantic_type": row["semantic_type"],
                        "quote": row["quote"],
                        "trace_refs": self._loads_dict(row["trace_refs_json"]),
                        "created_at": row["created_at"],
                    }
                    for row in rows
                ]
            )
        return objects

    def create_evidence_ref(
        self,
        *,
        workspace_id: str,
        source_id: str,
        object_type: str,
        object_id: str,
        ref_type: str,
        layer: str,
        title: str,
        doi: str | None,
        url: str | None,
        venue: str | None,
        publication_year: int | None,
        authors: list[str],
        excerpt: str,
        locator: dict[str, object],
        authority_score: float,
        authority_tier: str,
        metadata: dict[str, object],
        confirmed_at: datetime | None,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, object]:
        ref_id = self.gen_id("eref")
        created_at = self._to_iso(self.now())
        self._execute(
            """
            INSERT INTO evidence_refs (
                ref_id, workspace_id, source_id, object_type, object_id, ref_type, layer,
                title, doi, url, venue, publication_year, authors_json, excerpt, locator_json,
                authority_score, authority_tier, metadata_json, confirmed_at, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ref_id,
                workspace_id,
                source_id,
                object_type,
                object_id,
                ref_type,
                layer,
                title,
                doi,
                url,
                venue,
                publication_year,
                self._dumps(authors),
                excerpt,
                self._dumps(locator),
                authority_score,
                authority_tier,
                self._dumps(metadata),
                self._to_iso(confirmed_at),
                created_at,
            ),
            conn=conn,
        )
        record = self.get_evidence_ref(ref_id, conn=conn)
        assert record is not None
        return record

    def get_evidence_ref(
        self, ref_id: str, *, conn: sqlite3.Connection | None = None
    ) -> dict[str, object] | None:
        row = self._fetchone(
            "SELECT * FROM evidence_refs WHERE ref_id = ?",
            (ref_id,),
            conn=conn,
        )
        if row is None:
            return None
        return self._evidence_ref_row_to_dict(row)

    def list_evidence_refs(
        self,
        *,
        workspace_id: str | None = None,
        object_type: str | None = None,
        object_id: str | None = None,
        formal_refs: list[dict[str, str]] | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> list[dict[str, object]]:
        if formal_refs:
            items: list[dict[str, object]] = []
            seen: set[str] = set()
            for formal in formal_refs:
                current = self.list_evidence_refs(
                    workspace_id=workspace_id,
                    object_type=str(formal.get("object_type", "")) or None,
                    object_id=str(formal.get("object_id", "")) or None,
                    conn=conn,
                )
                for record in current:
                    if str(record["ref_id"]) in seen:
                        continue
                    seen.add(str(record["ref_id"]))
                    items.append(record)
            return items

        query = "SELECT * FROM evidence_refs WHERE 1=1"
        params: list[object] = []
        if workspace_id is not None:
            query += " AND workspace_id = ?"
            params.append(workspace_id)
        if object_type is not None:
            query += " AND object_type = ?"
            params.append(object_type)
        if object_id is not None:
            query += " AND object_id = ?"
            params.append(object_id)
        query += " ORDER BY created_at ASC, ref_id ASC"
        rows = self._fetchall(query, tuple(params), conn=conn)
        return [self._evidence_ref_row_to_dict(row) for row in rows]

    def _evidence_ref_row_to_dict(self, row: sqlite3.Row) -> dict[str, object]:
        return {
            "ref_id": row["ref_id"],
            "workspace_id": row["workspace_id"],
            "source_id": row["source_id"],
            "object_type": row["object_type"],
            "object_id": row["object_id"],
            "ref_type": row["ref_type"],
            "layer": row["layer"],
            "title": row["title"],
            "doi": row["doi"],
            "url": row["url"],
            "venue": row["venue"],
            "publication_year": row["publication_year"],
            "authors": self._loads(row["authors_json"]) or [],
            "excerpt": row["excerpt"],
            "locator": self._loads(row["locator_json"]) or {},
            "authority_score": float(row["authority_score"]),
            "authority_tier": row["authority_tier"],
            "metadata": self._loads(row["metadata_json"]) or {},
            "confirmed_at": self._from_iso(row["confirmed_at"]),
            "created_at": self._from_iso(row["created_at"]),
        }

    def create_scholarly_cache_record(
        self,
        *,
        normalized_query: str,
        provider_name: str,
        provider_record_id: str,
        title: str,
        doi: str | None,
        url: str | None,
        venue: str | None,
        publication_year: int | None,
        authors: list[str],
        abstract_excerpt: str | None,
        metadata: dict[str, object],
        authority_tier: str,
        authority_score: float,
    ) -> dict[str, object]:
        cache_id = self.gen_id("scache")
        self._execute(
            """
            INSERT INTO scholarly_source_cache (
                cache_id, normalized_query, provider_name, provider_record_id, title, doi,
                url, venue, publication_year, authors_json, abstract_excerpt, metadata_json,
                authority_tier, authority_score, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cache_id,
                normalized_query,
                provider_name,
                provider_record_id,
                title,
                doi,
                url,
                venue,
                publication_year,
                self._dumps(authors),
                abstract_excerpt,
                self._dumps(metadata),
                authority_tier,
                authority_score,
                self._to_iso(self.now()),
            ),
        )
        record = self.get_scholarly_cache_record(cache_id)
        assert record is not None
        return record

    def get_scholarly_cache_record(self, cache_id: str) -> dict[str, object] | None:
        row = self._fetchone(
            "SELECT * FROM scholarly_source_cache WHERE cache_id = ?",
            (cache_id,),
        )
        if row is None:
            return None
        return self._scholarly_cache_row_to_dict(row)

    def list_scholarly_cache_records(
        self,
        *,
        normalized_query: str | None = None,
        provider_name: str | None = None,
    ) -> list[dict[str, object]]:
        query = "SELECT * FROM scholarly_source_cache WHERE 1=1"
        params: list[object] = []
        if normalized_query is not None:
            query += " AND normalized_query = ?"
            params.append(normalized_query)
        if provider_name is not None:
            query += " AND provider_name = ?"
            params.append(provider_name)
        query += " ORDER BY created_at DESC, cache_id DESC"
        rows = self._fetchall(query, tuple(params))
        return [self._scholarly_cache_row_to_dict(row) for row in rows]

    def _scholarly_cache_row_to_dict(self, row: sqlite3.Row) -> dict[str, object]:
        return {
            "cache_id": row["cache_id"],
            "normalized_query": row["normalized_query"],
            "provider_name": row["provider_name"],
            "provider_record_id": row["provider_record_id"],
            "title": row["title"],
            "doi": row["doi"],
            "url": row["url"],
            "venue": row["venue"],
            "publication_year": row["publication_year"],
            "authors": self._loads(row["authors_json"]) or [],
            "abstract_excerpt": row["abstract_excerpt"],
            "metadata": self._loads(row["metadata_json"]) or {},
            "authority_tier": row["authority_tier"],
            "authority_score": float(row["authority_score"]),
            "created_at": self._from_iso(row["created_at"]),
        }

    def clear_graph_workspace(self, workspace_id: str) -> None:
        now = self._to_iso(self.now())
        self._execute(
            """
            UPDATE graph_edges
            SET status = ?, updated_at = ?
            WHERE workspace_id = ? AND status NOT IN ('archived', 'superseded')
            """,
            ("superseded", now, workspace_id),
        )
        self._execute(
            """
            UPDATE graph_nodes
            SET status = ?, updated_at = ?
            WHERE workspace_id = ? AND status NOT IN ('archived', 'superseded')
            """,
            ("superseded", now, workspace_id),
        )

    def create_graph_node(
        self,
        *,
        workspace_id: str,
        node_type: str,
        object_ref_type: str,
        object_ref_id: str,
        short_label: str,
        full_description: str,
        short_tags: list[str] | None = None,
        visibility: str = "workspace",
        source_refs: list[dict[str, object]] | None = None,
        status: str = "active",
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, object]:
        node_id = self.gen_id("node")
        now = self._to_iso(self.now())
        normalized_short_tags: list[str] = []
        for raw_tag in short_tags or []:
            tag = str(raw_tag).strip()
            if not tag or tag in normalized_short_tags:
                continue
            normalized_short_tags.append(tag)
            if len(normalized_short_tags) >= 3:
                break
        normalized_source_refs: list[dict[str, object]] = []
        for raw_ref in source_refs or []:
            if isinstance(raw_ref, dict):
                normalized_source_refs.append(dict(raw_ref))
        self._execute(
            """
            INSERT INTO graph_nodes (
                node_id, workspace_id, node_type, object_ref_type, object_ref_id,
                short_label, full_description, short_tags_json, visibility, source_refs_json,
                status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                node_id,
                workspace_id,
                node_type,
                object_ref_type,
                object_ref_id,
                short_label,
                full_description,
                self._dumps(normalized_short_tags),
                visibility,
                self._dumps(normalized_source_refs),
                status,
                now,
                now,
            ),
            conn=conn,
        )
        return self.get_graph_node(node_id, conn=conn)

    def get_graph_node(
        self, node_id: str, *, conn: sqlite3.Connection | None = None
    ) -> dict[str, object] | None:
        row = self._fetchone(
            "SELECT * FROM graph_nodes WHERE node_id = ?",
            (node_id,),
            conn=conn,
        )
        if row is None:
            return None
        return {
            "node_id": row["node_id"],
            "workspace_id": row["workspace_id"],
            "node_type": row["node_type"],
            "object_ref_type": row["object_ref_type"],
            "object_ref_id": row["object_ref_id"],
            "short_label": row["short_label"],
            "full_description": row["full_description"],
            "short_tags": self._loads(row["short_tags_json"]) or [],
            "visibility": row["visibility"] or "workspace",
            "source_refs": self._loads(row["source_refs_json"]) or [],
            "status": row["status"],
            "created_at": self._from_iso(row["created_at"]),
            "updated_at": self._from_iso(row["updated_at"]),
        }

    def find_graph_node_by_object_ref(
        self,
        *,
        workspace_id: str,
        object_ref_type: str,
        object_ref_id: str,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, object] | None:
        row = self._fetchone(
            """
            SELECT node_id
            FROM graph_nodes
            WHERE workspace_id = ? AND object_ref_type = ? AND object_ref_id = ?
            LIMIT 1
            """,
            (workspace_id, object_ref_type, object_ref_id),
            conn=conn,
        )
        if row is None:
            return None
        return self.get_graph_node(row["node_id"], conn=conn)

    def update_graph_node(
        self,
        *,
        node_id: str,
        short_label: str | None,
        full_description: str | None,
        short_tags: list[str] | None = None,
        visibility: str | None = None,
        source_refs: list[dict[str, object]] | None = None,
        status: str | None,
    ) -> dict[str, object] | None:
        node = self.get_graph_node(node_id)
        if node is None:
            return None
        normalized_short_tags = node["short_tags"]
        if short_tags is not None:
            normalized_short_tags = []
            for raw_tag in short_tags:
                tag = str(raw_tag).strip()
                if not tag or tag in normalized_short_tags:
                    continue
                normalized_short_tags.append(tag)
                if len(normalized_short_tags) >= 3:
                    break
        normalized_source_refs = node["source_refs"]
        if source_refs is not None:
            normalized_source_refs = [
                dict(raw_ref)
                for raw_ref in source_refs
                if isinstance(raw_ref, dict)
            ]
        self._execute(
            """
            UPDATE graph_nodes
            SET short_label = ?,
                full_description = ?,
                short_tags_json = ?,
                visibility = ?,
                source_refs_json = ?,
                status = ?,
                updated_at = ?
            WHERE node_id = ?
            """,
            (
                short_label if short_label is not None else node["short_label"],
                (
                    full_description
                    if full_description is not None
                    else node["full_description"]
                ),
                self._dumps(normalized_short_tags),
                visibility if visibility is not None else node["visibility"],
                self._dumps(normalized_source_refs),
                status if status is not None else node["status"],
                self._to_iso(self.now()),
                node_id,
            ),
        )
        return self.get_graph_node(node_id)

    def list_graph_nodes(
        self, workspace_id: str, *, conn: sqlite3.Connection | None = None
    ) -> list[dict[str, object]]:
        rows = self._fetchall(
            "SELECT * FROM graph_nodes WHERE workspace_id = ?",
            (workspace_id,),
            conn=conn,
        )
        return [
            {
                "node_id": row["node_id"],
                "workspace_id": row["workspace_id"],
                "node_type": row["node_type"],
                "object_ref_type": row["object_ref_type"],
                "object_ref_id": row["object_ref_id"],
                "short_label": row["short_label"],
                "full_description": row["full_description"],
                "short_tags": self._loads(row["short_tags_json"]) or [],
                "visibility": row["visibility"] or "workspace",
                "source_refs": self._loads(row["source_refs_json"]) or [],
                "status": row["status"],
                "created_at": self._from_iso(row["created_at"]),
                "updated_at": self._from_iso(row["updated_at"]),
            }
            for row in rows
        ]

    def create_graph_edge(
        self,
        *,
        workspace_id: str,
        source_node_id: str,
        target_node_id: str,
        edge_type: str,
        object_ref_type: str,
        object_ref_id: str,
        strength: float,
        status: str = "active",
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, object]:
        edge_id = self.gen_id("edge")
        now = self._to_iso(self.now())
        self._execute(
            """
            INSERT INTO graph_edges (
                edge_id, workspace_id, source_node_id, target_node_id, edge_type,
                object_ref_type, object_ref_id, strength, status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                edge_id,
                workspace_id,
                source_node_id,
                target_node_id,
                edge_type,
                object_ref_type,
                object_ref_id,
                strength,
                status,
                now,
                now,
            ),
            conn=conn,
        )
        return self.get_graph_edge(edge_id, conn=conn)

    def get_graph_edge(
        self, edge_id: str, *, conn: sqlite3.Connection | None = None
    ) -> dict[str, object] | None:
        row = self._fetchone(
            "SELECT * FROM graph_edges WHERE edge_id = ?",
            (edge_id,),
            conn=conn,
        )
        if row is None:
            return None
        return {
            "edge_id": row["edge_id"],
            "workspace_id": row["workspace_id"],
            "source_node_id": row["source_node_id"],
            "target_node_id": row["target_node_id"],
            "edge_type": row["edge_type"],
            "object_ref_type": row["object_ref_type"],
            "object_ref_id": row["object_ref_id"],
            "strength": row["strength"],
            "status": row["status"],
            "created_at": self._from_iso(row["created_at"]),
            "updated_at": self._from_iso(row["updated_at"]),
        }

    def update_graph_edge(
        self, *, edge_id: str, status: str | None, strength: float | None
    ) -> dict[str, object] | None:
        edge = self.get_graph_edge(edge_id)
        if edge is None:
            return None
        self._execute(
            """
            UPDATE graph_edges
            SET status = ?, strength = ?, updated_at = ?
            WHERE edge_id = ?
            """,
            (
                status if status is not None else edge["status"],
                strength if strength is not None else edge["strength"],
                self._to_iso(self.now()),
                edge_id,
            ),
        )
        return self.get_graph_edge(edge_id)

    def list_graph_edges(
        self, workspace_id: str, *, conn: sqlite3.Connection | None = None
    ) -> list[dict[str, object]]:
        rows = self._fetchall(
            "SELECT * FROM graph_edges WHERE workspace_id = ?",
            (workspace_id,),
            conn=conn,
        )
        return [
            {
                "edge_id": row["edge_id"],
                "workspace_id": row["workspace_id"],
                "source_node_id": row["source_node_id"],
                "target_node_id": row["target_node_id"],
                "edge_type": row["edge_type"],
                "object_ref_type": row["object_ref_type"],
                "object_ref_id": row["object_ref_id"],
                "strength": row["strength"],
                "status": row["status"],
                "created_at": self._from_iso(row["created_at"]),
                "updated_at": self._from_iso(row["updated_at"]),
            }
            for row in rows
        ]

    def find_graph_edge_by_ref(
        self,
        *,
        workspace_id: str,
        source_node_id: str,
        target_node_id: str,
        edge_type: str,
        object_ref_type: str,
        object_ref_id: str,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, object] | None:
        row = self._fetchone(
            """
            SELECT edge_id
            FROM graph_edges
            WHERE workspace_id = ?
              AND source_node_id = ?
              AND target_node_id = ?
              AND edge_type = ?
              AND object_ref_type = ?
              AND object_ref_id = ?
            LIMIT 1
            """,
            (
                workspace_id,
                source_node_id,
                target_node_id,
                edge_type,
                object_ref_type,
                object_ref_id,
            ),
            conn=conn,
        )
        if row is None:
            return None
        return self.get_graph_edge(row["edge_id"], conn=conn)

    def create_graph_version(
        self,
        *,
        workspace_id: str,
        trigger_type: str,
        change_summary: str,
        diff_payload: dict[str, object],
        request_id: str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, object]:
        version_id = self.gen_id("ver")
        created_at = self._to_iso(self.now())
        self._execute(
            """
            INSERT INTO graph_versions (
                version_id, workspace_id, trigger_type, change_summary, diff_payload_json, created_at, request_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                version_id,
                workspace_id,
                trigger_type,
                change_summary,
                self._dumps(diff_payload),
                created_at,
                request_id,
            ),
            conn=conn,
        )
        return self.get_graph_version(version_id, conn=conn)

    def update_graph_version_diff_payload(
        self, *, version_id: str, diff_payload: dict[str, object]
    ) -> dict[str, object] | None:
        self._execute(
            "UPDATE graph_versions SET diff_payload_json = ? WHERE version_id = ?",
            (self._dumps(diff_payload), version_id),
        )
        return self.get_graph_version(version_id)

    def get_graph_version(
        self, version_id: str, *, conn: sqlite3.Connection | None = None
    ) -> dict[str, object] | None:
        row = self._fetchone(
            "SELECT * FROM graph_versions WHERE version_id = ?",
            (version_id,),
            conn=conn,
        )
        if row is None:
            return None
        return {
            "version_id": row["version_id"],
            "workspace_id": row["workspace_id"],
            "trigger_type": row["trigger_type"],
            "change_summary": row["change_summary"],
            "diff_payload": self._loads(row["diff_payload_json"]),
            "created_at": self._from_iso(row["created_at"]),
            "request_id": row["request_id"],
        }

    def list_graph_versions(
        self, workspace_id: str, *, conn: sqlite3.Connection | None = None
    ) -> list[dict[str, object]]:
        rows = self._fetchall(
            """
            SELECT *
            FROM graph_versions
            WHERE workspace_id = ?
            ORDER BY created_at ASC, rowid ASC
            """,
            (workspace_id,),
            conn=conn,
        )
        return [
            {
                "version_id": row["version_id"],
                "workspace_id": row["workspace_id"],
                "trigger_type": row["trigger_type"],
                "change_summary": row["change_summary"],
                "created_at": self._from_iso(row["created_at"]),
                "request_id": row["request_id"],
            }
            for row in rows
        ]

    def upsert_graph_workspace(
        self,
        *,
        workspace_id: str,
        latest_version_id: str | None,
        status: str,
        node_count: int,
        edge_count: int,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, object]:
        now = self._to_iso(self.now())
        self._execute(
            """
            INSERT INTO graph_workspaces (workspace_id, latest_version_id, status, node_count, edge_count, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(workspace_id)
            DO UPDATE SET
                latest_version_id=excluded.latest_version_id,
                status=excluded.status,
                node_count=excluded.node_count,
                edge_count=excluded.edge_count,
                updated_at=excluded.updated_at
            """,
            (workspace_id, latest_version_id, status, node_count, edge_count, now),
            conn=conn,
        )
        return self.get_graph_workspace(workspace_id, conn=conn)

    def get_graph_workspace(
        self, workspace_id: str, *, conn: sqlite3.Connection | None = None
    ) -> dict[str, object] | None:
        row = self._fetchone(
            "SELECT * FROM graph_workspaces WHERE workspace_id = ?",
            (workspace_id,),
            conn=conn,
        )
        if row is None:
            return None
        return {
            "workspace_id": row["workspace_id"],
            "latest_version_id": row["latest_version_id"],
            "status": row["status"],
            "node_count": row["node_count"],
            "edge_count": row["edge_count"],
            "updated_at": self._from_iso(row["updated_at"]),
        }

    def create_failure(
        self,
        *,
        workspace_id: str,
        attached_targets: list[dict[str, str]],
        observed_outcome: str,
        expected_difference: str,
        failure_reason: str,
        severity: str,
        reporter: str,
        derived_from_validation_id: str | None = None,
        derived_from_validation_result_id: str | None = None,
    ) -> dict[str, object]:
        failure_id = self.gen_id("failure")
        now = self.now()
        self._execute(
            """
            INSERT INTO failures (failure_id, workspace_id, attached_targets_json, observed_outcome, expected_difference,
                                  failure_reason, severity, reporter, impact_summary_json, impact_updated_at,
                                  derived_from_validation_id, derived_from_validation_result_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                failure_id,
                workspace_id,
                self._dumps(attached_targets),
                observed_outcome,
                expected_difference,
                failure_reason,
                severity,
                reporter,
                self._dumps({}),
                None,
                derived_from_validation_id,
                derived_from_validation_result_id,
                self._to_iso(now),
            ),
        )
        return self.get_failure(failure_id)

    def _failure_row_to_dict(self, row: sqlite3.Row) -> dict[str, object]:
        return {
            "failure_id": row["failure_id"],
            "workspace_id": row["workspace_id"],
            "attached_targets": self._loads(row["attached_targets_json"]) or [],
            "observed_outcome": row["observed_outcome"],
            "expected_difference": row["expected_difference"],
            "failure_reason": row["failure_reason"],
            "severity": row["severity"],
            "reporter": row["reporter"],
            "created_at": self._from_iso(row["created_at"]),
            "impact_summary": self._loads_dict(row["impact_summary_json"]),
            "impact_updated_at": self._from_iso(row["impact_updated_at"]),
            "derived_from_validation_id": row["derived_from_validation_id"],
            "derived_from_validation_result_id": row[
                "derived_from_validation_result_id"
            ],
        }

    def update_failure_impact(
        self,
        *,
        failure_id: str,
        impact_summary: dict[str, object],
        impact_updated_at: datetime | None,
    ) -> None:
        self._execute(
            """
            UPDATE failures
            SET impact_summary_json = ?, impact_updated_at = ?
            WHERE failure_id = ?
            """,
            (
                self._dumps(impact_summary),
                self._to_iso(impact_updated_at),
                failure_id,
            ),
        )

    def update_failure_provenance(
        self,
        *,
        failure_id: str,
        derived_from_validation_result_id: str | None,
    ) -> None:
        self._execute(
            """
            UPDATE failures
            SET derived_from_validation_result_id = ?
            WHERE failure_id = ?
            """,
            (derived_from_validation_result_id, failure_id),
        )

    def _latest_failure_impact_snapshot(
        self, *, workspace_id: str, failure_id: str
    ) -> tuple[dict[str, object], datetime | None] | None:
        event = self.find_latest_event(
            workspace_id=workspace_id,
            event_name="failure_attached",
            ref_key="failure_id",
            ref_value=failure_id,
        )
        if event is None:
            return None
        refs = event.get("refs", {})
        if not isinstance(refs, dict):
            return None
        impact_summary = refs.get("impact_summary")
        if not isinstance(impact_summary, dict):
            return None
        timestamp = event.get("timestamp")
        return impact_summary, timestamp if isinstance(timestamp, datetime) else None

    def get_failure(self, failure_id: str) -> dict[str, object] | None:
        row = self._fetchone(
            "SELECT * FROM failures WHERE failure_id = ?", (failure_id,)
        )
        if row is None:
            return None
        record = self._failure_row_to_dict(row)
        latest_snapshot = self._latest_failure_impact_snapshot(
            workspace_id=str(record["workspace_id"]),
            failure_id=failure_id,
        )
        if latest_snapshot is not None:
            impact_summary, impact_updated_at = latest_snapshot
            current_updated_at = record["impact_updated_at"]
            should_backfill = (
                not record["impact_summary"]
                or current_updated_at is None
                or (
                    impact_updated_at is not None
                    and isinstance(current_updated_at, datetime)
                    and impact_updated_at > current_updated_at
                )
            )
            if should_backfill:
                self.update_failure_impact(
                    failure_id=failure_id,
                    impact_summary=impact_summary,
                    impact_updated_at=impact_updated_at,
                )
                record["impact_summary"] = impact_summary
                record["impact_updated_at"] = impact_updated_at
        return record

    def list_failures(self, *, workspace_id: str) -> list[dict[str, object]]:
        rows = self._fetchall(
            "SELECT * FROM failures WHERE workspace_id = ? ORDER BY created_at ASC",
            (workspace_id,),
        )
        return [self._failure_row_to_dict(row) for row in rows]

    def create_validation(
        self,
        *,
        workspace_id: str,
        target_object: str,
        method: str,
        success_signal: str,
        weakening_signal: str,
    ) -> dict[str, object]:
        validation_id = self.gen_id("validation")
        now = self._to_iso(self.now())
        self._execute(
            """
            INSERT INTO validations (
                validation_id, workspace_id, target_object, method, success_signal, weakening_signal,
                status, latest_outcome, latest_result_id, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                validation_id,
                workspace_id,
                target_object,
                method,
                success_signal,
                weakening_signal,
                "pending",
                None,
                None,
                now,
            ),
        )
        created = self.get_validation(validation_id)
        assert created is not None
        return created

    def get_validation(self, validation_id: str) -> dict[str, object] | None:
        row = self._fetchone(
            "SELECT * FROM validations WHERE validation_id = ?",
            (validation_id,),
        )
        if row is None:
            return None
        return {
            "validation_id": row["validation_id"],
            "workspace_id": row["workspace_id"],
            "target_object": row["target_object"],
            "method": row["method"],
            "success_signal": row["success_signal"],
            "weakening_signal": row["weakening_signal"],
            "status": row["status"] or "pending",
            "latest_outcome": row["latest_outcome"],
            "latest_result_id": row["latest_result_id"],
            "updated_at": self._from_iso(row["updated_at"]),
        }

    def list_validations(self, *, workspace_id: str) -> list[dict[str, object]]:
        rows = self._fetchall(
            "SELECT * FROM validations WHERE workspace_id = ? ORDER BY validation_id ASC",
            (workspace_id,),
        )
        return [
            {
                "validation_id": row["validation_id"],
                "workspace_id": row["workspace_id"],
                "target_object": row["target_object"],
                "method": row["method"],
                "success_signal": row["success_signal"],
                "weakening_signal": row["weakening_signal"],
                "status": row["status"] or "pending",
                "latest_outcome": row["latest_outcome"],
                "latest_result_id": row["latest_result_id"],
                "updated_at": self._from_iso(row["updated_at"]),
            }
            for row in rows
        ]

    def create_validation_result(
        self,
        *,
        validation_id: str,
        workspace_id: str,
        outcome: str,
        target_type: str | None,
        target_id: str | None,
        note: str | None,
        request_id: str | None,
        triggered_failure_id: str | None,
        recompute_job_id: str | None,
    ) -> dict[str, object]:
        result_id = self.gen_id("validation_result")
        now = self._to_iso(self.now())
        self._execute(
            """
            INSERT INTO validation_results (
                result_id, validation_id, workspace_id, outcome, target_type, target_id,
                note, request_id, triggered_failure_id, recompute_job_id, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result_id,
                validation_id,
                workspace_id,
                outcome,
                target_type,
                target_id,
                note,
                request_id,
                triggered_failure_id,
                recompute_job_id,
                now,
            ),
        )
        self._execute(
            """
            UPDATE validations
            SET status = ?, latest_outcome = ?, latest_result_id = ?, updated_at = ?
            WHERE validation_id = ?
            """,
            (outcome, outcome, result_id, now, validation_id),
        )
        return {
            "result_id": result_id,
            "validation_id": validation_id,
            "workspace_id": workspace_id,
            "outcome": outcome,
            "target_type": target_type,
            "target_id": target_id,
            "note": note,
            "request_id": request_id,
            "triggered_failure_id": triggered_failure_id,
            "recompute_job_id": recompute_job_id,
            "created_at": self._from_iso(now),
        }

    def create_memory_action(
        self,
        *,
        workspace_id: str,
        action_type: str,
        memory_view_type: str,
        memory_result_id: str,
        route_id: str | None,
        hypothesis_id: str | None,
        validation_id: str | None,
        request_id: str | None,
        note: str | None,
        memory_ref: dict[str, object],
    ) -> dict[str, object]:
        action_id = self.gen_id("memory_action")
        created_at = self.now()
        self._execute(
            """
            INSERT INTO memory_actions (
                action_id, workspace_id, action_type, memory_view_type, memory_result_id,
                route_id, hypothesis_id, validation_id, request_id, note, memory_ref_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                action_id,
                workspace_id,
                action_type,
                memory_view_type,
                memory_result_id,
                route_id,
                hypothesis_id,
                validation_id,
                request_id,
                note,
                self._dumps(memory_ref),
                self._to_iso(created_at),
            ),
        )
        return self.get_memory_action(action_id)

    def get_memory_action(self, action_id: str) -> dict[str, object] | None:
        row = self._fetchone(
            "SELECT * FROM memory_actions WHERE action_id = ?", (action_id,)
        )
        if row is None:
            return None
        memory_ref = self._loads(row["memory_ref_json"])
        if not isinstance(memory_ref, dict):
            memory_ref = {}
        return {
            "action_id": row["action_id"],
            "workspace_id": row["workspace_id"],
            "action_type": row["action_type"],
            "memory_view_type": row["memory_view_type"],
            "memory_result_id": row["memory_result_id"],
            "route_id": row["route_id"],
            "hypothesis_id": row["hypothesis_id"],
            "validation_id": row["validation_id"],
            "request_id": row["request_id"],
            "note": row["note"],
            "memory_ref": memory_ref,
            "created_at": self._from_iso(row["created_at"]),
        }

    def find_memory_action(
        self,
        *,
        workspace_id: str,
        action_type: str,
        memory_view_type: str,
        memory_result_id: str,
        route_id: str | None = None,
    ) -> dict[str, object] | None:
        if route_id is None:
            row = self._fetchone(
                """
                SELECT action_id
                FROM memory_actions
                WHERE workspace_id = ?
                  AND action_type = ?
                  AND memory_view_type = ?
                  AND memory_result_id = ?
                  AND route_id IS NULL
                ORDER BY created_at DESC, action_id DESC
                LIMIT 1
                """,
                (workspace_id, action_type, memory_view_type, memory_result_id),
            )
        else:
            row = self._fetchone(
                """
                SELECT action_id
                FROM memory_actions
                WHERE workspace_id = ?
                  AND action_type = ?
                  AND memory_view_type = ?
                  AND memory_result_id = ?
                  AND route_id = ?
                ORDER BY created_at DESC, action_id DESC
                LIMIT 1
                """,
                (
                    workspace_id,
                    action_type,
                    memory_view_type,
                    memory_result_id,
                    route_id,
                ),
            )
        if row is None:
            return None
        return self.get_memory_action(str(row["action_id"]))

    def create_hypothesis_candidate_pool(
        self,
        *,
        workspace_id: str,
        status: str,
        orchestration_mode: str,
        trigger_refs: list[dict[str, object]] | None = None,
        reasoning_subgraph: dict[str, object] | None = None,
        top_k: int = 8,
        max_rounds: int = 3,
        candidate_count: int = 0,
        current_round_number: int = 0,
        research_goal: str = "",
        constraints: dict[str, object] | None = None,
        preference_profile: dict[str, object] | None = None,
        created_job_id: str | None = None,
        created_request_id: str | None = None,
    ) -> dict[str, object]:
        pool_id = self.gen_id("hyp_pool")
        now_iso = self._to_iso(self.now())
        self._execute(
            """
            INSERT INTO hypothesis_candidate_pools (
                pool_id, workspace_id, status, orchestration_mode, trigger_refs_json,
                reasoning_subgraph_json, top_k, max_rounds, candidate_count, current_round_number,
                research_goal, constraints_json, preference_profile_json, created_job_id,
                created_request_id, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pool_id,
                workspace_id,
                status,
                orchestration_mode,
                self._dumps(trigger_refs or []),
                self._dumps(reasoning_subgraph or {}),
                top_k,
                max_rounds,
                candidate_count,
                current_round_number,
                research_goal,
                self._dumps(constraints or {}),
                self._dumps(preference_profile or {}),
                created_job_id,
                created_request_id,
                now_iso,
                now_iso,
            ),
        )
        record = self.get_hypothesis_candidate_pool(pool_id)
        assert record is not None
        return record

    def get_hypothesis_candidate_pool(
        self, pool_id: str
    ) -> dict[str, object] | None:
        row = self._fetchone(
            "SELECT * FROM hypothesis_candidate_pools WHERE pool_id = ?",
            (pool_id,),
        )
        if row is None:
            return None
        return self._hypothesis_candidate_pool_row_to_dict(row)

    def list_hypothesis_candidate_pools(
        self,
        *,
        workspace_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, object]]:
        query = "SELECT * FROM hypothesis_candidate_pools WHERE 1=1"
        params: list[object] = []
        if workspace_id is not None:
            query += " AND workspace_id = ?"
            params.append(workspace_id)
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY updated_at DESC, created_at DESC, pool_id DESC"
        rows = self._fetchall(query, tuple(params))
        return [self._hypothesis_candidate_pool_row_to_dict(row) for row in rows]

    def update_hypothesis_candidate_pool(
        self,
        *,
        pool_id: str,
        status: str | None = None,
        orchestration_mode: str | None = None,
        trigger_refs: list[dict[str, object]] | None = None,
        reasoning_subgraph: dict[str, object] | None = None,
        top_k: int | None = None,
        max_rounds: int | None = None,
        candidate_count: int | None = None,
        current_round_number: int | None = None,
        research_goal: str | None = None,
        constraints: dict[str, object] | None = None,
        preference_profile: dict[str, object] | None = None,
        created_job_id: str | None = None,
        created_request_id: str | None = None,
    ) -> dict[str, object] | None:
        assignments: list[str] = []
        params: list[object] = []
        if status is not None:
            assignments.append("status = ?")
            params.append(status)
        if orchestration_mode is not None:
            assignments.append("orchestration_mode = ?")
            params.append(orchestration_mode)
        if trigger_refs is not None:
            assignments.append("trigger_refs_json = ?")
            params.append(self._dumps(trigger_refs))
        if reasoning_subgraph is not None:
            assignments.append("reasoning_subgraph_json = ?")
            params.append(self._dumps(reasoning_subgraph))
        if top_k is not None:
            assignments.append("top_k = ?")
            params.append(top_k)
        if max_rounds is not None:
            assignments.append("max_rounds = ?")
            params.append(max_rounds)
        if candidate_count is not None:
            assignments.append("candidate_count = ?")
            params.append(candidate_count)
        if current_round_number is not None:
            assignments.append("current_round_number = ?")
            params.append(current_round_number)
        if research_goal is not None:
            assignments.append("research_goal = ?")
            params.append(research_goal)
        if constraints is not None:
            assignments.append("constraints_json = ?")
            params.append(self._dumps(constraints))
        if preference_profile is not None:
            assignments.append("preference_profile_json = ?")
            params.append(self._dumps(preference_profile))
        if created_job_id is not None:
            assignments.append("created_job_id = ?")
            params.append(created_job_id)
        if created_request_id is not None:
            assignments.append("created_request_id = ?")
            params.append(created_request_id)
        if not assignments:
            return self.get_hypothesis_candidate_pool(pool_id)
        assignments.append("updated_at = ?")
        params.append(self._to_iso(self.now()))
        params.append(pool_id)
        self._execute(
            f"UPDATE hypothesis_candidate_pools SET {', '.join(assignments)} WHERE pool_id = ?",
            tuple(params),
        )
        return self.get_hypothesis_candidate_pool(pool_id)

    def _hypothesis_candidate_pool_row_to_dict(
        self, row: sqlite3.Row
    ) -> dict[str, object]:
        return {
            "pool_id": row["pool_id"],
            "workspace_id": row["workspace_id"],
            "status": row["status"],
            "orchestration_mode": row["orchestration_mode"],
            "trigger_refs": self._loads_list(row["trigger_refs_json"]),
            "reasoning_subgraph": self._loads_dict(row["reasoning_subgraph_json"]),
            "top_k": int(row["top_k"] or 0),
            "max_rounds": int(row["max_rounds"] or 0),
            "candidate_count": int(row["candidate_count"] or 0),
            "current_round_number": int(row["current_round_number"] or 0),
            "research_goal": row["research_goal"],
            "constraints": self._loads_dict(row["constraints_json"]),
            "preference_profile": self._loads_dict(row["preference_profile_json"]),
            "created_job_id": row["created_job_id"],
            "created_request_id": row["created_request_id"],
            "created_at": self._from_iso(row["created_at"]),
            "updated_at": self._from_iso(row["updated_at"]),
        }

    def create_hypothesis_candidate(
        self,
        *,
        pool_id: str,
        workspace_id: str,
        title: str,
        statement: str,
        summary: str,
        rationale: str,
        trigger_refs: list[dict[str, object]] | None = None,
        related_object_ids: list[object] | None = None,
        reasoning_chain: list[object] | None = None,
        minimum_validation_action: dict[str, object] | None = None,
        weakening_signal: dict[str, object] | None = None,
        novelty_typing: str = "incremental",
        status: str = "candidate",
        origin_type: str = "seed",
        origin_round_number: int = 0,
        elo_rating: float = 1000.0,
        survival_score: float = 1.0,
        lineage: dict[str, object] | None = None,
    ) -> dict[str, object]:
        candidate_id = self.gen_id("hyp_cand")
        now_iso = self._to_iso(self.now())
        self._execute(
            """
            INSERT INTO hypothesis_candidates (
                candidate_id, pool_id, workspace_id, title, statement, summary, rationale,
                trigger_refs_json, related_object_ids_json, reasoning_chain_json,
                minimum_validation_action_json, weakening_signal_json, novelty_typing,
                status, origin_type, origin_round_number, elo_rating, survival_score,
                lineage_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate_id,
                pool_id,
                workspace_id,
                title,
                statement,
                summary,
                rationale,
                self._dumps(trigger_refs or []),
                self._dumps(related_object_ids or []),
                self._dumps(reasoning_chain or []),
                self._dumps(minimum_validation_action or {}),
                self._dumps(weakening_signal or {}),
                novelty_typing,
                status,
                origin_type,
                origin_round_number,
                float(elo_rating),
                float(survival_score),
                self._dumps(lineage or {}),
                now_iso,
                now_iso,
            ),
        )
        record = self.get_hypothesis_candidate(candidate_id)
        assert record is not None
        return record

    def get_hypothesis_candidate(
        self, candidate_id: str
    ) -> dict[str, object] | None:
        row = self._fetchone(
            "SELECT * FROM hypothesis_candidates WHERE candidate_id = ?",
            (candidate_id,),
        )
        if row is None:
            return None
        return self._hypothesis_candidate_row_to_dict(row)

    def list_hypothesis_candidates(
        self,
        *,
        workspace_id: str | None = None,
        pool_id: str | None = None,
        pool_ids: list[str] | None = None,
        status: str | None = None,
    ) -> list[dict[str, object]]:
        query = "SELECT * FROM hypothesis_candidates WHERE 1=1"
        params: list[object] = []
        if workspace_id is not None:
            query += " AND workspace_id = ?"
            params.append(workspace_id)
        if status is not None:
            query += " AND status = ?"
            params.append(status)

        resolved_pool_ids: list[str] = []
        if pool_id is not None and pool_id.strip():
            resolved_pool_ids.append(pool_id.strip())
        for raw_pool_id in pool_ids or []:
            text = str(raw_pool_id).strip()
            if text and text not in resolved_pool_ids:
                resolved_pool_ids.append(text)
        if pool_ids is not None and not resolved_pool_ids:
            return []
        if resolved_pool_ids:
            placeholders = ", ".join("?" for _ in resolved_pool_ids)
            query += f" AND pool_id IN ({placeholders})"
            params.extend(resolved_pool_ids)

        query += " ORDER BY updated_at DESC, created_at DESC, candidate_id DESC"
        rows = self._fetchall(query, tuple(params))
        return [self._hypothesis_candidate_row_to_dict(row) for row in rows]

    def update_hypothesis_candidate(
        self,
        *,
        candidate_id: str,
        elo_rating: float | None = None,
        status: str | None = None,
        survival_score: float | None = None,
        lineage: dict[str, object] | None = None,
    ) -> dict[str, object] | None:
        assignments: list[str] = []
        params: list[object] = []
        if elo_rating is not None:
            assignments.append("elo_rating = ?")
            params.append(float(elo_rating))
        if status is not None:
            assignments.append("status = ?")
            params.append(status)
        if survival_score is not None:
            assignments.append("survival_score = ?")
            params.append(float(survival_score))
        if lineage is not None:
            assignments.append("lineage_json = ?")
            params.append(self._dumps(lineage))
        if not assignments:
            return self.get_hypothesis_candidate(candidate_id)
        assignments.append("updated_at = ?")
        params.append(self._to_iso(self.now()))
        params.append(candidate_id)
        self._execute(
            f"UPDATE hypothesis_candidates SET {', '.join(assignments)} WHERE candidate_id = ?",
            tuple(params),
        )
        return self.get_hypothesis_candidate(candidate_id)

    def _hypothesis_candidate_row_to_dict(
        self, row: sqlite3.Row
    ) -> dict[str, object]:
        return {
            "candidate_id": row["candidate_id"],
            "pool_id": row["pool_id"],
            "workspace_id": row["workspace_id"],
            "title": row["title"],
            "statement": row["statement"],
            "summary": row["summary"],
            "rationale": row["rationale"],
            "trigger_refs": self._loads_list(row["trigger_refs_json"]),
            "related_object_ids": self._loads_list(row["related_object_ids_json"]),
            "reasoning_chain": self._loads_list(row["reasoning_chain_json"]),
            "minimum_validation_action": self._loads_dict(
                row["minimum_validation_action_json"]
            ),
            "weakening_signal": self._loads_dict(row["weakening_signal_json"]),
            "novelty_typing": row["novelty_typing"],
            "status": row["status"],
            "origin_type": row["origin_type"],
            "origin_round_number": int(row["origin_round_number"] or 0),
            "elo_rating": float(row["elo_rating"] or 0.0),
            "survival_score": float(row["survival_score"] or 0.0),
            "lineage": self._loads_dict(row["lineage_json"]),
            "created_at": self._from_iso(row["created_at"]),
            "updated_at": self._from_iso(row["updated_at"]),
        }

    def create_hypothesis_round(
        self,
        *,
        pool_id: str,
        round_number: int,
        start_reason: str,
        status: str = "running",
        stop_reason: str | None = None,
        generation_count: int = 0,
        review_count: int = 0,
        match_count: int = 0,
        evolution_count: int = 0,
        meta_review_id: str | None = None,
    ) -> dict[str, object]:
        round_id = self.gen_id("hyp_round")
        self._execute(
            """
            INSERT INTO hypothesis_rounds (
                round_id, pool_id, round_number, status, start_reason, stop_reason,
                generation_count, review_count, match_count, evolution_count,
                meta_review_id, created_at, completed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                round_id,
                pool_id,
                round_number,
                status,
                start_reason,
                stop_reason,
                generation_count,
                review_count,
                match_count,
                evolution_count,
                meta_review_id,
                self._to_iso(self.now()),
                None,
            ),
        )
        record = self.get_hypothesis_round(round_id)
        assert record is not None
        return record

    def get_hypothesis_round(self, round_id: str) -> dict[str, object] | None:
        row = self._fetchone(
            "SELECT * FROM hypothesis_rounds WHERE round_id = ?",
            (round_id,),
        )
        if row is None:
            return None
        return self._hypothesis_round_row_to_dict(row)

    def list_hypothesis_rounds(
        self,
        *,
        pool_id: str,
        status: str | None = None,
    ) -> list[dict[str, object]]:
        query = "SELECT * FROM hypothesis_rounds WHERE pool_id = ?"
        params: list[object] = [pool_id]
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY round_number ASC, created_at ASC, round_id ASC"
        rows = self._fetchall(query, tuple(params))
        return [self._hypothesis_round_row_to_dict(row) for row in rows]

    def complete_hypothesis_round(
        self,
        *,
        round_id: str,
        stop_reason: str | None = None,
        generation_count: int | None = None,
        review_count: int | None = None,
        match_count: int | None = None,
        evolution_count: int | None = None,
        meta_review_id: str | None = None,
        status: str = "completed",
        completed_at: datetime | None = None,
    ) -> dict[str, object] | None:
        assignments = ["status = ?", "completed_at = ?"]
        params: list[object] = [status, self._to_iso(completed_at or self.now())]
        if stop_reason is not None:
            assignments.append("stop_reason = ?")
            params.append(stop_reason)
        if generation_count is not None:
            assignments.append("generation_count = ?")
            params.append(generation_count)
        if review_count is not None:
            assignments.append("review_count = ?")
            params.append(review_count)
        if match_count is not None:
            assignments.append("match_count = ?")
            params.append(match_count)
        if evolution_count is not None:
            assignments.append("evolution_count = ?")
            params.append(evolution_count)
        if meta_review_id is not None:
            assignments.append("meta_review_id = ?")
            params.append(meta_review_id)
        params.append(round_id)
        self._execute(
            f"UPDATE hypothesis_rounds SET {', '.join(assignments)} WHERE round_id = ?",
            tuple(params),
        )
        return self.get_hypothesis_round(round_id)

    def _hypothesis_round_row_to_dict(self, row: sqlite3.Row) -> dict[str, object]:
        return {
            "round_id": row["round_id"],
            "pool_id": row["pool_id"],
            "round_number": int(row["round_number"] or 0),
            "status": row["status"],
            "start_reason": row["start_reason"],
            "stop_reason": row["stop_reason"],
            "generation_count": int(row["generation_count"] or 0),
            "review_count": int(row["review_count"] or 0),
            "match_count": int(row["match_count"] or 0),
            "evolution_count": int(row["evolution_count"] or 0),
            "meta_review_id": row["meta_review_id"],
            "created_at": self._from_iso(row["created_at"]),
            "completed_at": self._from_iso(row["completed_at"]),
        }

    def create_hypothesis_review(
        self,
        *,
        pool_id: str,
        round_id: str,
        candidate_id: str,
        review_type: str,
        strengths: list[object] | None = None,
        weaknesses: list[object] | None = None,
        missing_evidence: list[object] | None = None,
        testability_issues: list[object] | None = None,
        weakest_step_ref: dict[str, object] | None = None,
        recommended_actions: list[object] | None = None,
        trace_refs: list[object] | None = None,
    ) -> dict[str, object]:
        review_id = self.gen_id("hyp_review")
        self._execute(
            """
            INSERT INTO hypothesis_reviews (
                review_id, pool_id, round_id, candidate_id, review_type,
                strengths_json, weaknesses_json, missing_evidence_json,
                testability_issues_json, weakest_step_ref_json,
                recommended_actions_json, trace_refs_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                review_id,
                pool_id,
                round_id,
                candidate_id,
                review_type,
                self._dumps(strengths or []),
                self._dumps(weaknesses or []),
                self._dumps(missing_evidence or []),
                self._dumps(testability_issues or []),
                self._dumps(weakest_step_ref or {}),
                self._dumps(recommended_actions or []),
                self._dumps(trace_refs or []),
                self._to_iso(self.now()),
            ),
        )
        record = self.get_hypothesis_review(review_id)
        assert record is not None
        return record

    def get_hypothesis_review(self, review_id: str) -> dict[str, object] | None:
        row = self._fetchone(
            "SELECT * FROM hypothesis_reviews WHERE review_id = ?",
            (review_id,),
        )
        if row is None:
            return None
        return self._hypothesis_review_row_to_dict(row)

    def list_hypothesis_reviews(
        self,
        *,
        pool_id: str | None = None,
        round_id: str | None = None,
        candidate_id: str | None = None,
    ) -> list[dict[str, object]]:
        query = "SELECT * FROM hypothesis_reviews WHERE 1=1"
        params: list[object] = []
        if pool_id is not None:
            query += " AND pool_id = ?"
            params.append(pool_id)
        if round_id is not None:
            query += " AND round_id = ?"
            params.append(round_id)
        if candidate_id is not None:
            query += " AND candidate_id = ?"
            params.append(candidate_id)
        query += " ORDER BY created_at ASC, review_id ASC"
        rows = self._fetchall(query, tuple(params))
        return [self._hypothesis_review_row_to_dict(row) for row in rows]

    def _hypothesis_review_row_to_dict(self, row: sqlite3.Row) -> dict[str, object]:
        return {
            "review_id": row["review_id"],
            "pool_id": row["pool_id"],
            "round_id": row["round_id"],
            "candidate_id": row["candidate_id"],
            "review_type": row["review_type"],
            "strengths": self._loads_list(row["strengths_json"]),
            "weaknesses": self._loads_list(row["weaknesses_json"]),
            "missing_evidence": self._loads_list(row["missing_evidence_json"]),
            "testability_issues": self._loads_list(row["testability_issues_json"]),
            "weakest_step_ref": self._loads_dict(row["weakest_step_ref_json"]),
            "recommended_actions": self._loads_list(row["recommended_actions_json"]),
            "trace_refs": self._loads_list(row["trace_refs_json"]),
            "created_at": self._from_iso(row["created_at"]),
        }

    def create_hypothesis_match(
        self,
        *,
        pool_id: str,
        round_id: str,
        left_candidate_id: str,
        right_candidate_id: str,
        winner_candidate_id: str,
        loser_candidate_id: str,
        match_reason: str,
        compare_vector: dict[str, object] | None = None,
        left_elo_before: float = 0.0,
        right_elo_before: float = 0.0,
        left_elo_after: float = 0.0,
        right_elo_after: float = 0.0,
        judge_trace: dict[str, object] | None = None,
    ) -> dict[str, object]:
        match_id = self.gen_id("hyp_match")
        self._execute(
            """
            INSERT INTO hypothesis_matches (
                match_id, pool_id, round_id, left_candidate_id, right_candidate_id,
                winner_candidate_id, loser_candidate_id, match_reason, compare_vector_json,
                left_elo_before, right_elo_before, left_elo_after, right_elo_after,
                judge_trace_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                match_id,
                pool_id,
                round_id,
                left_candidate_id,
                right_candidate_id,
                winner_candidate_id,
                loser_candidate_id,
                match_reason,
                self._dumps(compare_vector or {}),
                float(left_elo_before),
                float(right_elo_before),
                float(left_elo_after),
                float(right_elo_after),
                self._dumps(judge_trace or {}),
                self._to_iso(self.now()),
            ),
        )
        record = self.get_hypothesis_match(match_id)
        assert record is not None
        return record

    def get_hypothesis_match(self, match_id: str) -> dict[str, object] | None:
        row = self._fetchone(
            "SELECT * FROM hypothesis_matches WHERE match_id = ?",
            (match_id,),
        )
        if row is None:
            return None
        return self._hypothesis_match_row_to_dict(row)

    def list_hypothesis_matches(
        self,
        *,
        pool_id: str | None = None,
        round_id: str | None = None,
    ) -> list[dict[str, object]]:
        query = "SELECT * FROM hypothesis_matches WHERE 1=1"
        params: list[object] = []
        if pool_id is not None:
            query += " AND pool_id = ?"
            params.append(pool_id)
        if round_id is not None:
            query += " AND round_id = ?"
            params.append(round_id)
        query += " ORDER BY created_at ASC, match_id ASC"
        rows = self._fetchall(query, tuple(params))
        return [self._hypothesis_match_row_to_dict(row) for row in rows]

    def _hypothesis_match_row_to_dict(self, row: sqlite3.Row) -> dict[str, object]:
        return {
            "match_id": row["match_id"],
            "pool_id": row["pool_id"],
            "round_id": row["round_id"],
            "left_candidate_id": row["left_candidate_id"],
            "right_candidate_id": row["right_candidate_id"],
            "winner_candidate_id": row["winner_candidate_id"],
            "loser_candidate_id": row["loser_candidate_id"],
            "match_reason": row["match_reason"],
            "compare_vector": self._loads_dict(row["compare_vector_json"]),
            "left_elo_before": float(row["left_elo_before"] or 0.0),
            "right_elo_before": float(row["right_elo_before"] or 0.0),
            "left_elo_after": float(row["left_elo_after"] or 0.0),
            "right_elo_after": float(row["right_elo_after"] or 0.0),
            "judge_trace": self._loads_dict(row["judge_trace_json"]),
            "created_at": self._from_iso(row["created_at"]),
        }

    def create_hypothesis_evolution(
        self,
        *,
        pool_id: str,
        round_id: str,
        source_candidate_id: str,
        new_candidate_id: str,
        evolution_mode: str,
        driving_review_ids: list[str] | None = None,
        change_summary: str = "",
        preserved_claims: list[object] | None = None,
        modified_claims: list[object] | None = None,
    ) -> dict[str, object]:
        evolution_id = self.gen_id("hyp_evo")
        self._execute(
            """
            INSERT INTO hypothesis_evolutions (
                evolution_id, pool_id, round_id, source_candidate_id, new_candidate_id,
                evolution_mode, driving_review_ids_json, change_summary,
                preserved_claims_json, modified_claims_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evolution_id,
                pool_id,
                round_id,
                source_candidate_id,
                new_candidate_id,
                evolution_mode,
                self._dumps(driving_review_ids or []),
                change_summary,
                self._dumps(preserved_claims or []),
                self._dumps(modified_claims or []),
                self._to_iso(self.now()),
            ),
        )
        record = self.get_hypothesis_evolution(evolution_id)
        assert record is not None
        return record

    def get_hypothesis_evolution(
        self, evolution_id: str
    ) -> dict[str, object] | None:
        row = self._fetchone(
            "SELECT * FROM hypothesis_evolutions WHERE evolution_id = ?",
            (evolution_id,),
        )
        if row is None:
            return None
        return self._hypothesis_evolution_row_to_dict(row)

    def list_hypothesis_evolutions(
        self,
        *,
        pool_id: str | None = None,
        round_id: str | None = None,
        source_candidate_id: str | None = None,
    ) -> list[dict[str, object]]:
        query = "SELECT * FROM hypothesis_evolutions WHERE 1=1"
        params: list[object] = []
        if pool_id is not None:
            query += " AND pool_id = ?"
            params.append(pool_id)
        if round_id is not None:
            query += " AND round_id = ?"
            params.append(round_id)
        if source_candidate_id is not None:
            query += " AND source_candidate_id = ?"
            params.append(source_candidate_id)
        query += " ORDER BY created_at ASC, evolution_id ASC"
        rows = self._fetchall(query, tuple(params))
        return [self._hypothesis_evolution_row_to_dict(row) for row in rows]

    def _hypothesis_evolution_row_to_dict(
        self, row: sqlite3.Row
    ) -> dict[str, object]:
        return {
            "evolution_id": row["evolution_id"],
            "pool_id": row["pool_id"],
            "round_id": row["round_id"],
            "source_candidate_id": row["source_candidate_id"],
            "new_candidate_id": row["new_candidate_id"],
            "evolution_mode": row["evolution_mode"],
            "driving_review_ids": self._loads_list(row["driving_review_ids_json"]),
            "change_summary": row["change_summary"],
            "preserved_claims": self._loads_list(row["preserved_claims_json"]),
            "modified_claims": self._loads_list(row["modified_claims_json"]),
            "created_at": self._from_iso(row["created_at"]),
        }

    def create_hypothesis_meta_review(
        self,
        *,
        pool_id: str,
        round_id: str,
        recurring_issues: list[object] | None = None,
        strong_patterns: list[object] | None = None,
        weak_patterns: list[object] | None = None,
        continue_recommendation: str = "",
        stop_recommendation: str = "",
        diversity_assessment: str = "",
    ) -> dict[str, object]:
        meta_review_id = self.gen_id("hyp_meta")
        self._execute(
            """
            INSERT INTO hypothesis_meta_reviews (
                meta_review_id, pool_id, round_id, recurring_issues_json, strong_patterns_json,
                weak_patterns_json, continue_recommendation, stop_recommendation,
                diversity_assessment, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                meta_review_id,
                pool_id,
                round_id,
                self._dumps(recurring_issues or []),
                self._dumps(strong_patterns or []),
                self._dumps(weak_patterns or []),
                continue_recommendation,
                stop_recommendation,
                diversity_assessment,
                self._to_iso(self.now()),
            ),
        )
        record = self.get_hypothesis_meta_review(meta_review_id)
        assert record is not None
        return record

    def get_hypothesis_meta_review(
        self, meta_review_id: str
    ) -> dict[str, object] | None:
        row = self._fetchone(
            "SELECT * FROM hypothesis_meta_reviews WHERE meta_review_id = ?",
            (meta_review_id,),
        )
        if row is None:
            return None
        return self._hypothesis_meta_review_row_to_dict(row)

    def list_hypothesis_meta_reviews(
        self,
        *,
        pool_id: str | None = None,
        round_id: str | None = None,
    ) -> list[dict[str, object]]:
        query = "SELECT * FROM hypothesis_meta_reviews WHERE 1=1"
        params: list[object] = []
        if pool_id is not None:
            query += " AND pool_id = ?"
            params.append(pool_id)
        if round_id is not None:
            query += " AND round_id = ?"
            params.append(round_id)
        query += " ORDER BY created_at ASC, meta_review_id ASC"
        rows = self._fetchall(query, tuple(params))
        return [self._hypothesis_meta_review_row_to_dict(row) for row in rows]

    def _hypothesis_meta_review_row_to_dict(
        self, row: sqlite3.Row
    ) -> dict[str, object]:
        return {
            "meta_review_id": row["meta_review_id"],
            "pool_id": row["pool_id"],
            "round_id": row["round_id"],
            "recurring_issues": self._loads_list(row["recurring_issues_json"]),
            "strong_patterns": self._loads_list(row["strong_patterns_json"]),
            "weak_patterns": self._loads_list(row["weak_patterns_json"]),
            "continue_recommendation": row["continue_recommendation"],
            "stop_recommendation": row["stop_recommendation"],
            "diversity_assessment": row["diversity_assessment"],
            "created_at": self._from_iso(row["created_at"]),
        }

    def create_hypothesis_proximity_edge(
        self,
        *,
        pool_id: str,
        from_candidate_id: str,
        to_candidate_id: str,
        similarity_score: float,
        shared_trigger_ratio: float,
        shared_object_ratio: float,
        shared_chain_overlap: float,
    ) -> dict[str, object]:
        edge_id = self.gen_id("hyp_edge")
        self._execute(
            """
            INSERT INTO hypothesis_proximity_edges (
                edge_id, pool_id, from_candidate_id, to_candidate_id, similarity_score,
                shared_trigger_ratio, shared_object_ratio, shared_chain_overlap, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                edge_id,
                pool_id,
                from_candidate_id,
                to_candidate_id,
                float(similarity_score),
                float(shared_trigger_ratio),
                float(shared_object_ratio),
                float(shared_chain_overlap),
                self._to_iso(self.now()),
            ),
        )
        record = self.get_hypothesis_proximity_edge(edge_id)
        assert record is not None
        return record

    def get_hypothesis_proximity_edge(
        self, edge_id: str
    ) -> dict[str, object] | None:
        row = self._fetchone(
            "SELECT * FROM hypothesis_proximity_edges WHERE edge_id = ?",
            (edge_id,),
        )
        if row is None:
            return None
        return self._hypothesis_proximity_edge_row_to_dict(row)

    def list_hypothesis_proximity_edges(
        self,
        *,
        pool_id: str | None = None,
        from_candidate_id: str | None = None,
        to_candidate_id: str | None = None,
    ) -> list[dict[str, object]]:
        query = "SELECT * FROM hypothesis_proximity_edges WHERE 1=1"
        params: list[object] = []
        if pool_id is not None:
            query += " AND pool_id = ?"
            params.append(pool_id)
        if from_candidate_id is not None:
            query += " AND from_candidate_id = ?"
            params.append(from_candidate_id)
        if to_candidate_id is not None:
            query += " AND to_candidate_id = ?"
            params.append(to_candidate_id)
        query += " ORDER BY created_at ASC, edge_id ASC"
        rows = self._fetchall(query, tuple(params))
        return [self._hypothesis_proximity_edge_row_to_dict(row) for row in rows]

    def _hypothesis_proximity_edge_row_to_dict(
        self, row: sqlite3.Row
    ) -> dict[str, object]:
        return {
            "edge_id": row["edge_id"],
            "pool_id": row["pool_id"],
            "from_candidate_id": row["from_candidate_id"],
            "to_candidate_id": row["to_candidate_id"],
            "similarity_score": float(row["similarity_score"] or 0.0),
            "shared_trigger_ratio": float(row["shared_trigger_ratio"] or 0.0),
            "shared_object_ratio": float(row["shared_object_ratio"] or 0.0),
            "shared_chain_overlap": float(row["shared_chain_overlap"] or 0.0),
            "created_at": self._from_iso(row["created_at"]),
        }

    def create_hypothesis_search_tree_node(
        self,
        *,
        pool_id: str,
        node_role: str,
        depth: int,
        parent_tree_node_id: str | None = None,
        candidate_id: str | None = None,
        visits: int = 0,
        mean_reward: float = 0.0,
        uct_score: float = 0.0,
        status: str = "active",
    ) -> dict[str, object]:
        tree_node_id = self.gen_id("hyp_tn")
        now_iso = self._to_iso(self.now())
        self._execute(
            """
            INSERT INTO hypothesis_search_tree_nodes (
                tree_node_id, pool_id, parent_tree_node_id, candidate_id, node_role,
                depth, visits, mean_reward, uct_score, status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tree_node_id,
                pool_id,
                parent_tree_node_id,
                candidate_id,
                node_role,
                depth,
                visits,
                float(mean_reward),
                float(uct_score),
                status,
                now_iso,
                now_iso,
            ),
        )
        record = self.get_hypothesis_search_tree_node(tree_node_id)
        assert record is not None
        return record

    def get_hypothesis_search_tree_node(
        self, tree_node_id: str
    ) -> dict[str, object] | None:
        row = self._fetchone(
            "SELECT * FROM hypothesis_search_tree_nodes WHERE tree_node_id = ?",
            (tree_node_id,),
        )
        if row is None:
            return None
        return self._hypothesis_search_tree_node_row_to_dict(row)

    def list_hypothesis_search_tree_nodes(
        self,
        *,
        pool_id: str,
        parent_tree_node_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, object]]:
        query = "SELECT * FROM hypothesis_search_tree_nodes WHERE pool_id = ?"
        params: list[object] = [pool_id]
        if parent_tree_node_id is not None:
            query += " AND parent_tree_node_id = ?"
            params.append(parent_tree_node_id)
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY depth ASC, created_at ASC, tree_node_id ASC"
        rows = self._fetchall(query, tuple(params))
        return [self._hypothesis_search_tree_node_row_to_dict(row) for row in rows]

    def update_hypothesis_search_tree_node(
        self,
        *,
        tree_node_id: str,
        visits: int | None = None,
        mean_reward: float | None = None,
        uct_score: float | None = None,
        status: str | None = None,
    ) -> dict[str, object] | None:
        assignments: list[str] = []
        params: list[object] = []
        if visits is not None:
            assignments.append("visits = ?")
            params.append(int(visits))
        if mean_reward is not None:
            assignments.append("mean_reward = ?")
            params.append(float(mean_reward))
        if uct_score is not None:
            assignments.append("uct_score = ?")
            params.append(float(uct_score))
        if status is not None:
            assignments.append("status = ?")
            params.append(status)
        if not assignments:
            return self.get_hypothesis_search_tree_node(tree_node_id)
        assignments.append("updated_at = ?")
        params.append(self._to_iso(self.now()))
        params.append(tree_node_id)
        self._execute(
            f"UPDATE hypothesis_search_tree_nodes SET {', '.join(assignments)} WHERE tree_node_id = ?",
            tuple(params),
        )
        return self.get_hypothesis_search_tree_node(tree_node_id)

    def _hypothesis_search_tree_node_row_to_dict(
        self, row: sqlite3.Row
    ) -> dict[str, object]:
        return {
            "tree_node_id": row["tree_node_id"],
            "pool_id": row["pool_id"],
            "parent_tree_node_id": row["parent_tree_node_id"],
            "candidate_id": row["candidate_id"],
            "node_role": row["node_role"],
            "depth": int(row["depth"] or 0),
            "visits": int(row["visits"] or 0),
            "mean_reward": float(row["mean_reward"] or 0.0),
            "uct_score": float(row["uct_score"] or 0.0),
            "status": row["status"],
            "created_at": self._from_iso(row["created_at"]),
            "updated_at": self._from_iso(row["updated_at"]),
        }

    def create_hypothesis_search_tree_edge(
        self,
        *,
        pool_id: str,
        from_tree_node_id: str,
        to_tree_node_id: str,
        edge_type: str,
    ) -> dict[str, object]:
        edge_id = self.gen_id("hyp_te")
        self._execute(
            """
            INSERT INTO hypothesis_search_tree_edges (
                edge_id, pool_id, from_tree_node_id, to_tree_node_id, edge_type, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                edge_id,
                pool_id,
                from_tree_node_id,
                to_tree_node_id,
                edge_type,
                self._to_iso(self.now()),
            ),
        )
        record = self.get_hypothesis_search_tree_edge(edge_id)
        assert record is not None
        return record

    def get_hypothesis_search_tree_edge(
        self, edge_id: str
    ) -> dict[str, object] | None:
        row = self._fetchone(
            "SELECT * FROM hypothesis_search_tree_edges WHERE edge_id = ?",
            (edge_id,),
        )
        if row is None:
            return None
        return self._hypothesis_search_tree_edge_row_to_dict(row)

    def list_hypothesis_search_tree_edges(
        self,
        *,
        pool_id: str,
        from_tree_node_id: str | None = None,
        to_tree_node_id: str | None = None,
    ) -> list[dict[str, object]]:
        query = "SELECT * FROM hypothesis_search_tree_edges WHERE pool_id = ?"
        params: list[object] = [pool_id]
        if from_tree_node_id is not None:
            query += " AND from_tree_node_id = ?"
            params.append(from_tree_node_id)
        if to_tree_node_id is not None:
            query += " AND to_tree_node_id = ?"
            params.append(to_tree_node_id)
        query += " ORDER BY created_at ASC, edge_id ASC"
        rows = self._fetchall(query, tuple(params))
        return [self._hypothesis_search_tree_edge_row_to_dict(row) for row in rows]

    def _hypothesis_search_tree_edge_row_to_dict(
        self, row: sqlite3.Row
    ) -> dict[str, object]:
        return {
            "edge_id": row["edge_id"],
            "pool_id": row["pool_id"],
            "from_tree_node_id": row["from_tree_node_id"],
            "to_tree_node_id": row["to_tree_node_id"],
            "edge_type": row["edge_type"],
            "created_at": self._from_iso(row["created_at"]),
        }

    def create_hypothesis(
        self,
        *,
        workspace_id: str,
        statement: str | None = None,
        title: str,
        summary: str,
        premise: str,
        rationale: str,
        testability_hint: str = "",
        novelty_hint: str = "",
        suggested_next_steps: list[str] | None = None,
        confidence_hint: float | None = None,
        trigger_refs: list[dict[str, object]],
        related_object_ids: list[dict[str, str]],
        novelty_typing: str,
        minimum_validation_action: dict[str, object],
        weakening_signal: dict[str, object],
        generation_job_id: str | None = None,
        provider_backend: str | None = None,
        provider_model: str | None = None,
        llm_request_id: str | None = None,
        llm_response_id: str | None = None,
        usage: dict[str, object] | None = None,
        fallback_used: bool = False,
        degraded: bool = False,
        degraded_reason: str | None = None,
        source_pool_id: str | None = None,
        source_candidate_id: str | None = None,
        source_round_id: str | None = None,
        finalizing_match_id: str | None = None,
        search_tree_node_id: str | None = None,
        reasoning_chain_id: str | None = None,
        weakest_step_ref: dict[str, object] | None = None,
    ) -> dict[str, object]:
        hypothesis_id = self.gen_id("hypothesis")
        now = self._to_iso(self.now())
        resolved_statement = (
            str(statement).strip() if statement is not None else f"{title}: {summary}"
        )
        if not resolved_statement:
            resolved_statement = f"{title}: {summary}"
        cleaned_next_steps = [
            str(step).strip()
            for step in (suggested_next_steps or [])
            if str(step).strip()
        ]
        trigger_object_ids = [
            str(item.get("object_ref_id", ""))
            for item in trigger_refs
            if isinstance(item, dict) and item.get("object_ref_id")
        ]
        self._execute(
            """
            INSERT INTO hypotheses (
                hypothesis_id, workspace_id, statement, status, trigger_object_ids_json,
                title, summary, premise, rationale, testability_hint, novelty_hint, suggested_next_steps_json, confidence_hint,
                stage, trigger_refs_json, related_object_ids_json,
                novelty_typing, minimum_validation_action_json, weakening_signal_json,
                decision_note, decision_source_type, decision_source_ref, decided_at, decided_request_id,
                created_at, updated_at, generation_job_id,
                provider_backend, provider_model, llm_request_id, llm_response_id, usage_json, fallback_used, degraded, degraded_reason,
                source_pool_id, source_candidate_id, source_round_id, finalizing_match_id, search_tree_node_id, reasoning_chain_id, weakest_step_ref_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                hypothesis_id,
                workspace_id,
                resolved_statement,
                "candidate",
                self._dumps(trigger_object_ids),
                title,
                summary,
                premise,
                rationale,
                testability_hint,
                novelty_hint,
                self._dumps(cleaned_next_steps),
                confidence_hint,
                "exploratory",
                self._dumps(trigger_refs),
                self._dumps(related_object_ids),
                novelty_typing,
                self._dumps(minimum_validation_action),
                self._dumps(weakening_signal),
                None,
                None,
                None,
                None,
                None,
                now,
                now,
                generation_job_id,
                provider_backend,
                provider_model,
                llm_request_id,
                llm_response_id,
                self._dumps(usage or {}),
                int(bool(fallback_used)),
                int(bool(degraded)),
                degraded_reason,
                source_pool_id,
                source_candidate_id,
                source_round_id,
                finalizing_match_id,
                search_tree_node_id,
                reasoning_chain_id,
                self._dumps(weakest_step_ref or {}),
            ),
        )
        return self.get_hypothesis(hypothesis_id)

    def get_hypothesis(self, hypothesis_id: str) -> dict[str, object] | None:
        row = self._fetchone(
            "SELECT * FROM hypotheses WHERE hypothesis_id = ?", (hypothesis_id,)
        )
        if row is None:
            return None
        trigger_refs = self._loads(row["trigger_refs_json"])
        related_object_ids = self._loads(row["related_object_ids_json"])
        minimum_validation_action = self._loads(row["minimum_validation_action_json"])
        weakening_signal = self._loads(row["weakening_signal_json"])
        suggested_next_steps = self._loads(row["suggested_next_steps_json"])
        return {
            "hypothesis_id": row["hypothesis_id"],
            "workspace_id": row["workspace_id"],
            "statement": row["statement"],
            "title": row["title"] or row["statement"],
            "summary": row["summary"] or "",
            "premise": row["premise"] or "",
            "rationale": row["rationale"] or "",
            "testability_hint": row["testability_hint"] or "",
            "novelty_hint": row["novelty_hint"] or "",
            "suggested_next_steps": (
                suggested_next_steps if isinstance(suggested_next_steps, list) else []
            ),
            "confidence_hint": row["confidence_hint"],
            "status": row["status"],
            "stage": row["stage"] or "exploratory",
            "trigger_object_ids": self._loads(row["trigger_object_ids_json"]) or [],
            "trigger_refs": trigger_refs if isinstance(trigger_refs, list) else [],
            "related_object_ids": (
                related_object_ids if isinstance(related_object_ids, list) else []
            ),
            "novelty_typing": row["novelty_typing"] or "incremental",
            "minimum_validation_action": (
                minimum_validation_action
                if isinstance(minimum_validation_action, dict)
                else {}
            ),
            "weakening_signal": (
                weakening_signal if isinstance(weakening_signal, dict) else {}
            ),
            "decision_note": row["decision_note"],
            "decision_source_type": row["decision_source_type"],
            "decision_source_ref": row["decision_source_ref"],
            "decided_at": self._from_iso(row["decided_at"]),
            "decided_request_id": row["decided_request_id"],
            "created_at": self._from_iso(row["created_at"]),
            "updated_at": self._from_iso(row["updated_at"]),
            "generation_job_id": row["generation_job_id"],
            "provider_backend": row["provider_backend"],
            "provider_model": row["provider_model"],
            "request_id": row["llm_request_id"],
            "llm_response_id": row["llm_response_id"],
            "usage": self._loads(row["usage_json"]) if row["usage_json"] else None,
            "fallback_used": bool(row["fallback_used"] or 0),
            "degraded": bool(row["degraded"] or 0),
            "degraded_reason": row["degraded_reason"],
            "source_pool_id": row["source_pool_id"],
            "source_candidate_id": row["source_candidate_id"],
            "source_round_id": row["source_round_id"],
            "finalizing_match_id": row["finalizing_match_id"],
            "search_tree_node_id": row["search_tree_node_id"],
            "reasoning_chain_id": row["reasoning_chain_id"],
            "weakest_step_ref": self._loads(row["weakest_step_ref_json"]) or {},
        }

    def list_hypotheses(self, *, workspace_id: str) -> list[dict[str, object]]:
        rows = self._fetchall(
            """
            SELECT hypothesis_id
            FROM hypotheses
            WHERE workspace_id = ?
            ORDER BY updated_at DESC, created_at DESC, hypothesis_id DESC
            """,
            (workspace_id,),
        )
        results: list[dict[str, object]] = []
        for row in rows:
            hypothesis = self.get_hypothesis(str(row["hypothesis_id"]))
            if hypothesis is not None:
                results.append(hypothesis)
        return results

    def update_hypothesis_status(
        self,
        *,
        hypothesis_id: str,
        status: str,
        decision_note: str,
        decision_source_type: str,
        decision_source_ref: str,
        decided_request_id: str,
    ) -> dict[str, object] | None:
        self._execute(
            """
            UPDATE hypotheses
            SET status = ?,
                decision_note = ?,
                decision_source_type = ?,
                decision_source_ref = ?,
                decided_at = ?,
                decided_request_id = ?,
                updated_at = ?
            WHERE hypothesis_id = ?
            """,
            (
                status,
                decision_note,
                decision_source_type,
                decision_source_ref,
                self._to_iso(self.now()),
                decided_request_id,
                self._to_iso(self.now()),
                hypothesis_id,
            ),
        )
        return self.get_hypothesis(hypothesis_id)

    def create_hypothesis_pool(
        self,
        *,
        workspace_id: str,
        status: str,
        orchestration_mode: str,
        trigger_refs: list[dict[str, object]],
        reasoning_subgraph: dict[str, object] | None,
        top_k: int,
        max_rounds: int,
        candidate_count: int,
        current_round_number: int,
        research_goal: str,
        constraints: dict[str, object] | None,
        preference_profile: dict[str, object] | None,
        created_job_id: str | None,
        created_request_id: str | None,
    ) -> dict[str, object]:
        pool_id = self.gen_id("hyp_pool")
        now = self._to_iso(self.now())
        self._execute(
            """
            INSERT INTO hypothesis_candidate_pools (
                pool_id, workspace_id, status, orchestration_mode, trigger_refs_json, reasoning_subgraph_json,
                top_k, max_rounds, candidate_count, current_round_number, research_goal,
                constraints_json, preference_profile_json, created_job_id, created_request_id, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pool_id,
                workspace_id,
                status,
                orchestration_mode,
                self._dumps(trigger_refs),
                self._dumps(reasoning_subgraph or {}),
                int(top_k),
                int(max_rounds),
                int(candidate_count),
                int(current_round_number),
                research_goal,
                self._dumps(constraints or {}),
                self._dumps(preference_profile or {}),
                created_job_id,
                created_request_id,
                now,
                now,
            ),
        )
        return self.get_hypothesis_pool(pool_id)

    def get_hypothesis_pool(self, pool_id: str) -> dict[str, object] | None:
        row = self._fetchone(
            "SELECT * FROM hypothesis_candidate_pools WHERE pool_id = ?",
            (pool_id,),
        )
        if row is None:
            return None
        return {
            "pool_id": row["pool_id"],
            "workspace_id": row["workspace_id"],
            "status": row["status"],
            "orchestration_mode": row["orchestration_mode"],
            "trigger_refs": self._loads_list(row["trigger_refs_json"]),
            "reasoning_subgraph": self._loads_dict(row["reasoning_subgraph_json"]),
            "top_k": int(row["top_k"] or 0),
            "max_rounds": int(row["max_rounds"] or 0),
            "candidate_count": int(row["candidate_count"] or 0),
            "current_round_number": int(row["current_round_number"] or 0),
            "research_goal": row["research_goal"] or "",
            "constraints": self._loads_dict(row["constraints_json"]),
            "preference_profile": self._loads_dict(row["preference_profile_json"]),
            "created_job_id": row["created_job_id"],
            "created_request_id": row["created_request_id"],
            "created_at": self._from_iso(row["created_at"]),
            "updated_at": self._from_iso(row["updated_at"]),
        }

    def list_hypothesis_pools(self, *, workspace_id: str) -> list[dict[str, object]]:
        rows = self._fetchall(
            """
            SELECT pool_id
            FROM hypothesis_candidate_pools
            WHERE workspace_id = ?
            ORDER BY updated_at DESC, created_at DESC, pool_id DESC
            """,
            (workspace_id,),
        )
        items: list[dict[str, object]] = []
        for row in rows:
            item = self.get_hypothesis_pool(str(row["pool_id"]))
            if item is not None:
                items.append(item)
        return items

    def update_hypothesis_pool(
        self,
        *,
        pool_id: str,
        status: str | None = None,
        current_round_number: int | None = None,
        reasoning_subgraph: dict[str, object] | None = None,
    ) -> dict[str, object] | None:
        current = self.get_hypothesis_pool(pool_id)
        if current is None:
            return None
        self._execute(
            """
            UPDATE hypothesis_candidate_pools
            SET status = ?, current_round_number = ?, reasoning_subgraph_json = ?, updated_at = ?
            WHERE pool_id = ?
            """,
            (
                status if status is not None else current["status"],
                (
                    int(current_round_number)
                    if current_round_number is not None
                    else int(current["current_round_number"])
                ),
                self._dumps(
                    reasoning_subgraph
                    if reasoning_subgraph is not None
                    else current["reasoning_subgraph"]
                ),
                self._to_iso(self.now()),
                pool_id,
            ),
        )
        return self.get_hypothesis_pool(pool_id)

    def create_hypothesis_candidate(
        self,
        *,
        pool_id: str,
        workspace_id: str,
        title: str,
        statement: str,
        summary: str,
        rationale: str,
        trigger_refs: list[dict[str, object]],
        related_object_ids: list[dict[str, object]],
        reasoning_chain: dict[str, object],
        minimum_validation_action: dict[str, object],
        weakening_signal: dict[str, object],
        novelty_typing: str,
        status: str,
        origin_type: str,
        origin_round_number: int,
        elo_rating: float,
        survival_score: float,
        lineage: dict[str, object] | None,
    ) -> dict[str, object]:
        candidate_id = self.gen_id("hyp_cand")
        now = self._to_iso(self.now())
        self._execute(
            """
            INSERT INTO hypothesis_candidates (
                candidate_id, pool_id, workspace_id, title, statement, summary, rationale,
                trigger_refs_json, related_object_ids_json, reasoning_chain_json,
                minimum_validation_action_json, weakening_signal_json, novelty_typing, status,
                origin_type, origin_round_number, elo_rating, survival_score, lineage_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate_id,
                pool_id,
                workspace_id,
                title,
                statement,
                summary,
                rationale,
                self._dumps(trigger_refs),
                self._dumps(related_object_ids),
                self._dumps(reasoning_chain),
                self._dumps(minimum_validation_action),
                self._dumps(weakening_signal),
                novelty_typing,
                status,
                origin_type,
                int(origin_round_number),
                float(elo_rating),
                float(survival_score),
                self._dumps(lineage or {}),
                now,
                now,
            ),
        )
        return self.get_hypothesis_candidate(candidate_id)

    def get_hypothesis_candidate(self, candidate_id: str) -> dict[str, object] | None:
        row = self._fetchone(
            "SELECT * FROM hypothesis_candidates WHERE candidate_id = ?",
            (candidate_id,),
        )
        if row is None:
            return None
        reasoning_chain = self._loads_safe(row["reasoning_chain_json"])
        return {
            "candidate_id": row["candidate_id"],
            "pool_id": row["pool_id"],
            "workspace_id": row["workspace_id"],
            "title": row["title"],
            "statement": row["statement"],
            "summary": row["summary"],
            "rationale": row["rationale"],
            "trigger_refs": self._loads_list(row["trigger_refs_json"]),
            "related_object_ids": self._loads_list(row["related_object_ids_json"]),
            "reasoning_chain": (
                reasoning_chain if reasoning_chain is not None else {}
            ),
            "minimum_validation_action": self._loads_dict(
                row["minimum_validation_action_json"]
            ),
            "weakening_signal": self._loads_dict(row["weakening_signal_json"]),
            "novelty_typing": row["novelty_typing"],
            "status": row["status"],
            "origin_type": row["origin_type"],
            "origin_round_number": int(row["origin_round_number"] or 0),
            "elo_rating": float(row["elo_rating"] or 0.0),
            "survival_score": float(row["survival_score"] or 0.0),
            "lineage": self._loads_dict(row["lineage_json"]),
            "created_at": self._from_iso(row["created_at"]),
            "updated_at": self._from_iso(row["updated_at"]),
        }

    def list_hypothesis_candidates(
        self,
        *,
        pool_id: str | None = None,
        pool_ids: list[str] | None = None,
        status: str | None = None,
    ) -> list[dict[str, object]]:
        resolved_pool_ids: list[str] = []
        if pool_id is not None and pool_id.strip():
            resolved_pool_ids.append(pool_id.strip())
        for raw_pool_id in pool_ids or []:
            text = str(raw_pool_id).strip()
            if text and text not in resolved_pool_ids:
                resolved_pool_ids.append(text)
        if not resolved_pool_ids:
            return []

        placeholders = ", ".join("?" for _ in resolved_pool_ids)
        query = f"""
            SELECT candidate_id
            FROM hypothesis_candidates
            WHERE pool_id IN ({placeholders})
        """
        params: list[object] = list(resolved_pool_ids)
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY elo_rating DESC, updated_at DESC, candidate_id DESC"
        rows = self._fetchall(query, tuple(params))
        items: list[dict[str, object]] = []
        for row in rows:
            item = self.get_hypothesis_candidate(str(row["candidate_id"]))
            if item is not None:
                items.append(item)
        return items

    def update_hypothesis_candidate(
        self,
        *,
        candidate_id: str,
        status: str | None = None,
        elo_rating: float | None = None,
        survival_score: float | None = None,
        lineage: dict[str, object] | None = None,
    ) -> dict[str, object] | None:
        current = self.get_hypothesis_candidate(candidate_id)
        if current is None:
            return None
        self._execute(
            """
            UPDATE hypothesis_candidates
            SET status = ?, elo_rating = ?, survival_score = ?, lineage_json = ?, updated_at = ?
            WHERE candidate_id = ?
            """,
            (
                status if status is not None else current["status"],
                float(elo_rating) if elo_rating is not None else current["elo_rating"],
                (
                    float(survival_score)
                    if survival_score is not None
                    else current["survival_score"]
                ),
                self._dumps(lineage if lineage is not None else current["lineage"]),
                self._to_iso(self.now()),
                candidate_id,
            ),
        )
        return self.get_hypothesis_candidate(candidate_id)

    def create_hypothesis_round(
        self,
        *,
        pool_id: str,
        round_number: int,
        status: str,
        start_reason: str,
    ) -> dict[str, object]:
        round_id = self.gen_id("hyp_round")
        now = self._to_iso(self.now())
        self._execute(
            """
            INSERT INTO hypothesis_rounds (
                round_id, pool_id, round_number, status, start_reason, stop_reason,
                generation_count, review_count, match_count, evolution_count, meta_review_id, created_at, completed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                round_id,
                pool_id,
                int(round_number),
                status,
                start_reason,
                None,
                0,
                0,
                0,
                0,
                None,
                now,
                None,
            ),
        )
        return self.get_hypothesis_round(round_id)

    def get_hypothesis_round(self, round_id: str) -> dict[str, object] | None:
        row = self._fetchone(
            "SELECT * FROM hypothesis_rounds WHERE round_id = ?",
            (round_id,),
        )
        if row is None:
            return None
        return {
            "round_id": row["round_id"],
            "pool_id": row["pool_id"],
            "round_number": int(row["round_number"] or 0),
            "status": row["status"],
            "start_reason": row["start_reason"],
            "stop_reason": row["stop_reason"],
            "generation_count": int(row["generation_count"] or 0),
            "review_count": int(row["review_count"] or 0),
            "match_count": int(row["match_count"] or 0),
            "evolution_count": int(row["evolution_count"] or 0),
            "meta_review_id": row["meta_review_id"],
            "created_at": self._from_iso(row["created_at"]),
            "completed_at": self._from_iso(row["completed_at"]),
        }

    def list_hypothesis_rounds(self, *, pool_id: str) -> list[dict[str, object]]:
        rows = self._fetchall(
            """
            SELECT round_id
            FROM hypothesis_rounds
            WHERE pool_id = ?
            ORDER BY round_number ASC, created_at ASC, round_id ASC
            """,
            (pool_id,),
        )
        items: list[dict[str, object]] = []
        for row in rows:
            item = self.get_hypothesis_round(str(row["round_id"]))
            if item is not None:
                items.append(item)
        return items

    def update_hypothesis_round(
        self,
        *,
        round_id: str,
        status: str | None = None,
        stop_reason: str | None = None,
        generation_count: int | None = None,
        review_count: int | None = None,
        match_count: int | None = None,
        evolution_count: int | None = None,
        meta_review_id: str | None = None,
        completed: bool = False,
    ) -> dict[str, object] | None:
        current = self.get_hypothesis_round(round_id)
        if current is None:
            return None
        self._execute(
            """
            UPDATE hypothesis_rounds
            SET status = ?, stop_reason = ?, generation_count = ?, review_count = ?,
                match_count = ?, evolution_count = ?, meta_review_id = ?, completed_at = ?
            WHERE round_id = ?
            """,
            (
                status if status is not None else current["status"],
                stop_reason if stop_reason is not None else current["stop_reason"],
                (
                    int(generation_count)
                    if generation_count is not None
                    else int(current["generation_count"])
                ),
                int(review_count)
                if review_count is not None
                else int(current["review_count"]),
                int(match_count)
                if match_count is not None
                else int(current["match_count"]),
                int(evolution_count)
                if evolution_count is not None
                else int(current["evolution_count"]),
                meta_review_id
                if meta_review_id is not None
                else current["meta_review_id"],
                self._to_iso(self.now()) if completed else current["completed_at"],
                round_id,
            ),
        )
        return self.get_hypothesis_round(round_id)

    def complete_hypothesis_round(
        self,
        *,
        round_id: str,
        stop_reason: str | None = None,
        generation_count: int | None = None,
        review_count: int | None = None,
        match_count: int | None = None,
        evolution_count: int | None = None,
        meta_review_id: str | None = None,
        status: str = "completed",
    ) -> dict[str, object] | None:
        return self.update_hypothesis_round(
            round_id=round_id,
            status=status,
            stop_reason=stop_reason,
            generation_count=generation_count,
            review_count=review_count,
            match_count=match_count,
            evolution_count=evolution_count,
            meta_review_id=meta_review_id,
            completed=True,
        )

    def create_hypothesis_review(
        self,
        *,
        pool_id: str,
        round_id: str,
        candidate_id: str,
        review_type: str,
        strengths: list[str],
        weaknesses: list[str],
        missing_evidence: list[str],
        testability_issues: list[str],
        weakest_step_ref: dict[str, object],
        recommended_actions: list[str],
        trace_refs: dict[str, object] | None = None,
    ) -> dict[str, object]:
        review_id = self.gen_id("hyp_review")
        self._execute(
            """
            INSERT INTO hypothesis_reviews (
                review_id, pool_id, round_id, candidate_id, review_type,
                strengths_json, weaknesses_json, missing_evidence_json, testability_issues_json,
                weakest_step_ref_json, recommended_actions_json, trace_refs_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                review_id,
                pool_id,
                round_id,
                candidate_id,
                review_type,
                self._dumps(strengths),
                self._dumps(weaknesses),
                self._dumps(missing_evidence),
                self._dumps(testability_issues),
                self._dumps(weakest_step_ref),
                self._dumps(recommended_actions),
                self._dumps(trace_refs or {}),
                self._to_iso(self.now()),
            ),
        )
        return self.get_hypothesis_review(review_id)

    def get_hypothesis_review(self, review_id: str) -> dict[str, object] | None:
        row = self._fetchone(
            "SELECT * FROM hypothesis_reviews WHERE review_id = ?",
            (review_id,),
        )
        if row is None:
            return None
        trace_refs = self._loads_safe(row["trace_refs_json"])
        return {
            "review_id": row["review_id"],
            "pool_id": row["pool_id"],
            "round_id": row["round_id"],
            "candidate_id": row["candidate_id"],
            "review_type": row["review_type"],
            "strengths": self._loads_list(row["strengths_json"]),
            "weaknesses": self._loads_list(row["weaknesses_json"]),
            "missing_evidence": self._loads_list(row["missing_evidence_json"]),
            "testability_issues": self._loads_list(row["testability_issues_json"]),
            "weakest_step_ref": self._loads_dict(row["weakest_step_ref_json"]),
            "recommended_actions": self._loads_list(row["recommended_actions_json"]),
            "trace_refs": trace_refs if trace_refs is not None else {},
            "created_at": self._from_iso(row["created_at"]),
        }

    def list_hypothesis_reviews(
        self,
        *,
        pool_id: str,
        round_id: str | None = None,
        candidate_id: str | None = None,
    ) -> list[dict[str, object]]:
        query = "SELECT review_id FROM hypothesis_reviews WHERE pool_id = ?"
        params: list[object] = [pool_id]
        if round_id is not None:
            query += " AND round_id = ?"
            params.append(round_id)
        if candidate_id is not None:
            query += " AND candidate_id = ?"
            params.append(candidate_id)
        query += " ORDER BY created_at ASC, review_id ASC"
        rows = self._fetchall(query, tuple(params))
        items: list[dict[str, object]] = []
        for row in rows:
            item = self.get_hypothesis_review(str(row["review_id"]))
            if item is not None:
                items.append(item)
        return items

    def create_hypothesis_match(
        self,
        *,
        pool_id: str,
        round_id: str,
        left_candidate_id: str,
        right_candidate_id: str,
        winner_candidate_id: str,
        loser_candidate_id: str,
        match_reason: str,
        compare_vector: dict[str, object],
        left_elo_before: float,
        right_elo_before: float,
        left_elo_after: float,
        right_elo_after: float,
        judge_trace: dict[str, object] | None = None,
    ) -> dict[str, object]:
        match_id = self.gen_id("hyp_match")
        self._execute(
            """
            INSERT INTO hypothesis_matches (
                match_id, pool_id, round_id, left_candidate_id, right_candidate_id,
                winner_candidate_id, loser_candidate_id, match_reason, compare_vector_json,
                left_elo_before, right_elo_before, left_elo_after, right_elo_after,
                judge_trace_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                match_id,
                pool_id,
                round_id,
                left_candidate_id,
                right_candidate_id,
                winner_candidate_id,
                loser_candidate_id,
                match_reason,
                self._dumps(compare_vector),
                float(left_elo_before),
                float(right_elo_before),
                float(left_elo_after),
                float(right_elo_after),
                self._dumps(judge_trace or {}),
                self._to_iso(self.now()),
            ),
        )
        return self.get_hypothesis_match(match_id)

    def get_hypothesis_match(self, match_id: str) -> dict[str, object] | None:
        row = self._fetchone(
            "SELECT * FROM hypothesis_matches WHERE match_id = ?",
            (match_id,),
        )
        if row is None:
            return None
        return {
            "match_id": row["match_id"],
            "pool_id": row["pool_id"],
            "round_id": row["round_id"],
            "left_candidate_id": row["left_candidate_id"],
            "right_candidate_id": row["right_candidate_id"],
            "winner_candidate_id": row["winner_candidate_id"],
            "loser_candidate_id": row["loser_candidate_id"],
            "match_reason": row["match_reason"],
            "compare_vector": self._loads_dict(row["compare_vector_json"]),
            "left_elo_before": float(row["left_elo_before"] or 0.0),
            "right_elo_before": float(row["right_elo_before"] or 0.0),
            "left_elo_after": float(row["left_elo_after"] or 0.0),
            "right_elo_after": float(row["right_elo_after"] or 0.0),
            "judge_trace": self._loads_dict(row["judge_trace_json"]),
            "created_at": self._from_iso(row["created_at"]),
        }

    def list_hypothesis_matches(
        self, *, pool_id: str, round_id: str | None = None
    ) -> list[dict[str, object]]:
        if round_id is None:
            rows = self._fetchall(
                """
                SELECT match_id
                FROM hypothesis_matches
                WHERE pool_id = ?
                ORDER BY created_at ASC, match_id ASC
                """,
                (pool_id,),
            )
        else:
            rows = self._fetchall(
                """
                SELECT match_id
                FROM hypothesis_matches
                WHERE pool_id = ? AND round_id = ?
                ORDER BY created_at ASC, match_id ASC
                """,
                (pool_id, round_id),
            )
        items: list[dict[str, object]] = []
        for row in rows:
            item = self.get_hypothesis_match(str(row["match_id"]))
            if item is not None:
                items.append(item)
        return items

    def create_hypothesis_evolution(
        self,
        *,
        pool_id: str,
        round_id: str,
        source_candidate_id: str,
        new_candidate_id: str,
        evolution_mode: str,
        driving_review_ids: list[str],
        change_summary: str,
        preserved_claims: list[str],
        modified_claims: list[str],
    ) -> dict[str, object]:
        evolution_id = self.gen_id("hyp_evo")
        self._execute(
            """
            INSERT INTO hypothesis_evolutions (
                evolution_id, pool_id, round_id, source_candidate_id, new_candidate_id,
                evolution_mode, driving_review_ids_json, change_summary,
                preserved_claims_json, modified_claims_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evolution_id,
                pool_id,
                round_id,
                source_candidate_id,
                new_candidate_id,
                evolution_mode,
                self._dumps(driving_review_ids),
                change_summary,
                self._dumps(preserved_claims),
                self._dumps(modified_claims),
                self._to_iso(self.now()),
            ),
        )
        return self.get_hypothesis_evolution(evolution_id)

    def get_hypothesis_evolution(self, evolution_id: str) -> dict[str, object] | None:
        row = self._fetchone(
            "SELECT * FROM hypothesis_evolutions WHERE evolution_id = ?",
            (evolution_id,),
        )
        if row is None:
            return None
        return {
            "evolution_id": row["evolution_id"],
            "pool_id": row["pool_id"],
            "round_id": row["round_id"],
            "source_candidate_id": row["source_candidate_id"],
            "new_candidate_id": row["new_candidate_id"],
            "evolution_mode": row["evolution_mode"],
            "driving_review_ids": self._loads_list(row["driving_review_ids_json"]),
            "change_summary": row["change_summary"],
            "preserved_claims": self._loads_list(row["preserved_claims_json"]),
            "modified_claims": self._loads_list(row["modified_claims_json"]),
            "created_at": self._from_iso(row["created_at"]),
        }

    def list_hypothesis_evolutions(
        self, *, pool_id: str, round_id: str | None = None
    ) -> list[dict[str, object]]:
        if round_id is None:
            rows = self._fetchall(
                """
                SELECT evolution_id
                FROM hypothesis_evolutions
                WHERE pool_id = ?
                ORDER BY created_at ASC, evolution_id ASC
                """,
                (pool_id,),
            )
        else:
            rows = self._fetchall(
                """
                SELECT evolution_id
                FROM hypothesis_evolutions
                WHERE pool_id = ? AND round_id = ?
                ORDER BY created_at ASC, evolution_id ASC
                """,
                (pool_id, round_id),
            )
        items: list[dict[str, object]] = []
        for row in rows:
            item = self.get_hypothesis_evolution(str(row["evolution_id"]))
            if item is not None:
                items.append(item)
        return items

    def create_hypothesis_meta_review(
        self,
        *,
        pool_id: str,
        round_id: str,
        recurring_issues: list[str],
        strong_patterns: list[str],
        weak_patterns: list[str],
        continue_recommendation: str,
        stop_recommendation: str,
        diversity_assessment: str,
    ) -> dict[str, object]:
        meta_review_id = self.gen_id("hyp_meta")
        self._execute(
            """
            INSERT INTO hypothesis_meta_reviews (
                meta_review_id, pool_id, round_id, recurring_issues_json, strong_patterns_json,
                weak_patterns_json, continue_recommendation, stop_recommendation, diversity_assessment, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                meta_review_id,
                pool_id,
                round_id,
                self._dumps(recurring_issues),
                self._dumps(strong_patterns),
                self._dumps(weak_patterns),
                continue_recommendation,
                stop_recommendation,
                diversity_assessment,
                self._to_iso(self.now()),
            ),
        )
        return self.get_hypothesis_meta_review(meta_review_id)

    def get_hypothesis_meta_review(
        self, meta_review_id: str
    ) -> dict[str, object] | None:
        row = self._fetchone(
            "SELECT * FROM hypothesis_meta_reviews WHERE meta_review_id = ?",
            (meta_review_id,),
        )
        if row is None:
            return None
        return {
            "meta_review_id": row["meta_review_id"],
            "pool_id": row["pool_id"],
            "round_id": row["round_id"],
            "recurring_issues": self._loads_list(row["recurring_issues_json"]),
            "strong_patterns": self._loads_list(row["strong_patterns_json"]),
            "weak_patterns": self._loads_list(row["weak_patterns_json"]),
            "continue_recommendation": row["continue_recommendation"],
            "stop_recommendation": row["stop_recommendation"],
            "diversity_assessment": row["diversity_assessment"],
            "created_at": self._from_iso(row["created_at"]),
        }

    def list_hypothesis_meta_reviews(
        self, *, pool_id: str, round_id: str | None = None
    ) -> list[dict[str, object]]:
        if round_id is None:
            rows = self._fetchall(
                """
                SELECT meta_review_id
                FROM hypothesis_meta_reviews
                WHERE pool_id = ?
                ORDER BY created_at ASC, meta_review_id ASC
                """,
                (pool_id,),
            )
        else:
            rows = self._fetchall(
                """
                SELECT meta_review_id
                FROM hypothesis_meta_reviews
                WHERE pool_id = ? AND round_id = ?
                ORDER BY created_at ASC, meta_review_id ASC
                """,
                (pool_id, round_id),
            )
        items: list[dict[str, object]] = []
        for row in rows:
            item = self.get_hypothesis_meta_review(str(row["meta_review_id"]))
            if item is not None:
                items.append(item)
        return items

    def create_hypothesis_proximity_edge(
        self,
        *,
        pool_id: str,
        from_candidate_id: str,
        to_candidate_id: str,
        similarity_score: float,
        shared_trigger_ratio: float,
        shared_object_ratio: float,
        shared_chain_overlap: float,
    ) -> dict[str, object]:
        edge_id = self.gen_id("hyp_prox")
        self._execute(
            """
            INSERT INTO hypothesis_proximity_edges (
                edge_id, pool_id, from_candidate_id, to_candidate_id, similarity_score,
                shared_trigger_ratio, shared_object_ratio, shared_chain_overlap, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                edge_id,
                pool_id,
                from_candidate_id,
                to_candidate_id,
                float(similarity_score),
                float(shared_trigger_ratio),
                float(shared_object_ratio),
                float(shared_chain_overlap),
                self._to_iso(self.now()),
            ),
        )
        return self.get_hypothesis_proximity_edge(edge_id)

    def get_hypothesis_proximity_edge(self, edge_id: str) -> dict[str, object] | None:
        row = self._fetchone(
            "SELECT * FROM hypothesis_proximity_edges WHERE edge_id = ?",
            (edge_id,),
        )
        if row is None:
            return None
        return {
            "edge_id": row["edge_id"],
            "pool_id": row["pool_id"],
            "from_candidate_id": row["from_candidate_id"],
            "to_candidate_id": row["to_candidate_id"],
            "similarity_score": float(row["similarity_score"] or 0.0),
            "shared_trigger_ratio": float(row["shared_trigger_ratio"] or 0.0),
            "shared_object_ratio": float(row["shared_object_ratio"] or 0.0),
            "shared_chain_overlap": float(row["shared_chain_overlap"] or 0.0),
            "created_at": self._from_iso(row["created_at"]),
        }

    def list_hypothesis_proximity_edges(self, *, pool_id: str) -> list[dict[str, object]]:
        rows = self._fetchall(
            """
            SELECT edge_id
            FROM hypothesis_proximity_edges
            WHERE pool_id = ?
            ORDER BY similarity_score DESC, created_at ASC, edge_id ASC
            """,
            (pool_id,),
        )
        items: list[dict[str, object]] = []
        for row in rows:
            item = self.get_hypothesis_proximity_edge(str(row["edge_id"]))
            if item is not None:
                items.append(item)
        return items

    def create_hypothesis_search_tree_node(
        self,
        *,
        pool_id: str,
        parent_tree_node_id: str | None,
        candidate_id: str | None,
        node_role: str,
        depth: int,
        visits: int,
        mean_reward: float,
        uct_score: float,
        status: str,
    ) -> dict[str, object]:
        tree_node_id = self.gen_id("hyp_tree")
        now = self._to_iso(self.now())
        self._execute(
            """
            INSERT INTO hypothesis_search_tree_nodes (
                tree_node_id, pool_id, parent_tree_node_id, candidate_id, node_role,
                depth, visits, mean_reward, uct_score, status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tree_node_id,
                pool_id,
                parent_tree_node_id,
                candidate_id,
                node_role,
                int(depth),
                int(visits),
                float(mean_reward),
                float(uct_score),
                status,
                now,
                now,
            ),
        )
        return self.get_hypothesis_search_tree_node(tree_node_id)

    def get_hypothesis_search_tree_node(
        self, tree_node_id: str
    ) -> dict[str, object] | None:
        row = self._fetchone(
            "SELECT * FROM hypothesis_search_tree_nodes WHERE tree_node_id = ?",
            (tree_node_id,),
        )
        if row is None:
            return None
        child_edges = self.list_hypothesis_search_tree_edges(
            pool_id=str(row["pool_id"]),
            from_tree_node_id=str(row["tree_node_id"]),
        )
        return {
            "tree_node_id": row["tree_node_id"],
            "pool_id": row["pool_id"],
            "parent_tree_node_id": row["parent_tree_node_id"],
            "candidate_id": row["candidate_id"],
            "node_role": row["node_role"],
            "depth": int(row["depth"] or 0),
            "visits": int(row["visits"] or 0),
            "mean_reward": float(row["mean_reward"] or 0.0),
            "uct_score": float(row["uct_score"] or 0.0),
            "status": row["status"],
            "created_at": self._from_iso(row["created_at"]),
            "updated_at": self._from_iso(row["updated_at"]),
            "child_edges": child_edges,
        }

    def list_hypothesis_search_tree_nodes(
        self, *, pool_id: str
    ) -> list[dict[str, object]]:
        rows = self._fetchall(
            """
            SELECT tree_node_id
            FROM hypothesis_search_tree_nodes
            WHERE pool_id = ?
            ORDER BY depth ASC, visits DESC, tree_node_id ASC
            """,
            (pool_id,),
        )
        items: list[dict[str, object]] = []
        for row in rows:
            item = self.get_hypothesis_search_tree_node(str(row["tree_node_id"]))
            if item is not None:
                items.append(item)
        return items

    def update_hypothesis_search_tree_node(
        self,
        *,
        tree_node_id: str,
        visits: int | None = None,
        mean_reward: float | None = None,
        uct_score: float | None = None,
        status: str | None = None,
    ) -> dict[str, object] | None:
        current = self.get_hypothesis_search_tree_node(tree_node_id)
        if current is None:
            return None
        self._execute(
            """
            UPDATE hypothesis_search_tree_nodes
            SET visits = ?, mean_reward = ?, uct_score = ?, status = ?, updated_at = ?
            WHERE tree_node_id = ?
            """,
            (
                int(visits) if visits is not None else int(current["visits"]),
                (
                    float(mean_reward)
                    if mean_reward is not None
                    else float(current["mean_reward"])
                ),
                float(uct_score)
                if uct_score is not None
                else float(current["uct_score"]),
                status if status is not None else current["status"],
                self._to_iso(self.now()),
                tree_node_id,
            ),
        )
        return self.get_hypothesis_search_tree_node(tree_node_id)

    def create_hypothesis_search_tree_edge(
        self,
        *,
        pool_id: str,
        from_tree_node_id: str,
        to_tree_node_id: str,
        edge_type: str,
    ) -> dict[str, object]:
        edge_id = self.gen_id("hyp_tree_edge")
        self._execute(
            """
            INSERT INTO hypothesis_search_tree_edges (
                edge_id, pool_id, from_tree_node_id, to_tree_node_id, edge_type, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                edge_id,
                pool_id,
                from_tree_node_id,
                to_tree_node_id,
                edge_type,
                self._to_iso(self.now()),
            ),
        )
        return self.get_hypothesis_search_tree_edge(edge_id)

    def get_hypothesis_search_tree_edge(
        self, edge_id: str
    ) -> dict[str, object] | None:
        row = self._fetchone(
            "SELECT * FROM hypothesis_search_tree_edges WHERE edge_id = ?",
            (edge_id,),
        )
        if row is None:
            return None
        return {
            "edge_id": row["edge_id"],
            "pool_id": row["pool_id"],
            "from_tree_node_id": row["from_tree_node_id"],
            "to_tree_node_id": row["to_tree_node_id"],
            "edge_type": row["edge_type"],
            "created_at": self._from_iso(row["created_at"]),
        }

    def list_hypothesis_search_tree_edges(
        self,
        *,
        pool_id: str,
        from_tree_node_id: str | None = None,
    ) -> list[dict[str, object]]:
        if from_tree_node_id is None:
            rows = self._fetchall(
                """
                SELECT edge_id
                FROM hypothesis_search_tree_edges
                WHERE pool_id = ?
                ORDER BY created_at ASC, edge_id ASC
                """,
                (pool_id,),
            )
        else:
            rows = self._fetchall(
                """
                SELECT edge_id
                FROM hypothesis_search_tree_edges
                WHERE pool_id = ? AND from_tree_node_id = ?
                ORDER BY created_at ASC, edge_id ASC
                """,
                (pool_id, from_tree_node_id),
            )
        items: list[dict[str, object]] = []
        for row in rows:
            item = self.get_hypothesis_search_tree_edge(str(row["edge_id"]))
            if item is not None:
                items.append(item)
        return items

    def create_package(
        self,
        *,
        package_id: str | None = None,
        workspace_id: str,
        title: str,
        summary: str,
        included_route_ids: list[str],
        included_node_ids: list[str],
        included_validation_ids: list[str],
        status: str = "draft",
        snapshot_type: str = "research_package_snapshot",
        snapshot_version: str = "slice11.v1",
        private_dependency_flags: list[dict[str, object]] | None = None,
        public_gap_nodes: list[dict[str, object]] | None = None,
        boundary_notes: list[str] | None = None,
        traceability_refs: dict[str, object] | None = None,
        snapshot_payload: dict[str, object] | None = None,
        replay_ready: bool = True,
        build_request_id: str | None = None,
    ) -> dict[str, object]:
        resolved_package_id = package_id or self.gen_id("pkg")
        now_iso = self._to_iso(self.now())
        self._execute(
            """
            INSERT INTO packages (package_id, workspace_id, title, summary, included_route_ids_json,
                                  included_node_ids_json, included_validation_ids_json, status,
                                  snapshot_type, snapshot_version, private_dependency_flags_json, public_gap_nodes_json,
                                  boundary_notes_json, traceability_refs_json, snapshot_payload_json, replay_ready,
                                  build_request_id, created_at, updated_at, published_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                resolved_package_id,
                workspace_id,
                title,
                summary,
                self._dumps(included_route_ids),
                self._dumps(included_node_ids),
                self._dumps(included_validation_ids),
                status,
                snapshot_type,
                snapshot_version,
                self._dumps(private_dependency_flags or []),
                self._dumps(public_gap_nodes or []),
                self._dumps(boundary_notes or []),
                self._dumps(traceability_refs or {}),
                self._dumps(snapshot_payload or {}),
                1 if replay_ready else 0,
                build_request_id,
                now_iso,
                now_iso,
                None,
            ),
        )
        return self.get_package(resolved_package_id)

    def list_packages(
        self, *, workspace_id: str, status: str | None = None
    ) -> list[dict[str, object]]:
        if status is None:
            rows = self._fetchall(
                "SELECT * FROM packages WHERE workspace_id = ? ORDER BY created_at DESC",
                (workspace_id,),
            )
        else:
            rows = self._fetchall(
                """
                SELECT * FROM packages
                WHERE workspace_id = ? AND status = ?
                ORDER BY created_at DESC
                """,
                (workspace_id, status),
            )
        return [self._package_row_to_dict(row) for row in rows]

    def get_package(self, package_id: str) -> dict[str, object] | None:
        row = self._fetchone(
            "SELECT * FROM packages WHERE package_id = ?", (package_id,)
        )
        if row is None:
            return None
        return self._package_row_to_dict(row)

    def _package_row_to_dict(self, row: sqlite3.Row) -> dict[str, object]:
        private_dependency_flags = self._loads(row["private_dependency_flags_json"])
        if not isinstance(private_dependency_flags, list):
            private_dependency_flags = []
        public_gap_nodes = self._loads(row["public_gap_nodes_json"])
        if not isinstance(public_gap_nodes, list):
            public_gap_nodes = []
        boundary_notes = self._loads(row["boundary_notes_json"])
        if not isinstance(boundary_notes, list):
            boundary_notes = []
        traceability_refs = self._loads(row["traceability_refs_json"])
        if not isinstance(traceability_refs, dict):
            traceability_refs = {}
        snapshot_payload = self._loads(row["snapshot_payload_json"])
        if not isinstance(snapshot_payload, dict):
            snapshot_payload = {}
        return {
            "package_id": row["package_id"],
            "workspace_id": row["workspace_id"],
            "title": row["title"],
            "summary": row["summary"],
            "included_route_ids": self._loads(row["included_route_ids_json"]),
            "included_node_ids": self._loads(row["included_node_ids_json"]),
            "included_validation_ids": self._loads(row["included_validation_ids_json"]),
            "status": row["status"],
            "snapshot_type": row["snapshot_type"] or "research_package_snapshot",
            "snapshot_version": row["snapshot_version"] or "slice11.v1",
            "private_dependency_flags": private_dependency_flags,
            "public_gap_nodes": public_gap_nodes,
            "boundary_notes": boundary_notes,
            "traceability_refs": traceability_refs,
            "snapshot_payload": snapshot_payload,
            "replay_ready": (
                bool(row["replay_ready"]) if row["replay_ready"] is not None else False
            ),
            "build_request_id": row["build_request_id"],
            "created_at": self._from_iso(row["created_at"]),
            "updated_at": self._from_iso(row["updated_at"]),
            "published_at": self._from_iso(row["published_at"]),
        }

    def update_package_status(
        self, *, package_id: str, status: str, published_at: str | None = None
    ) -> dict[str, object] | None:
        self._execute(
            """
            UPDATE packages
            SET status = ?, updated_at = ?, published_at = COALESCE(?, published_at)
            WHERE package_id = ?
            """,
            (status, self._to_iso(self.now()), published_at, package_id),
        )
        return self.get_package(package_id)

    def create_package_publish_result(
        self,
        *,
        package_id: str,
        workspace_id: str,
        snapshot_type: str,
        snapshot_version: str,
        boundary_notes: list[str],
        published_snapshot: dict[str, object],
        request_id: str | None = None,
    ) -> dict[str, object]:
        publish_result_id = self.gen_id("pkg_publish")
        published_at = self._to_iso(self.now())
        self._execute(
            """
            INSERT INTO package_publish_results (
                publish_result_id, package_id, workspace_id, snapshot_type, snapshot_version,
                boundary_notes_json, published_snapshot_json, published_at, request_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                publish_result_id,
                package_id,
                workspace_id,
                snapshot_type,
                snapshot_version,
                self._dumps(boundary_notes),
                self._dumps(published_snapshot),
                published_at,
                request_id,
            ),
        )
        return self.get_package_publish_result(publish_result_id)

    def get_package_publish_result(
        self, publish_result_id: str
    ) -> dict[str, object] | None:
        row = self._fetchone(
            "SELECT * FROM package_publish_results WHERE publish_result_id = ?",
            (publish_result_id,),
        )
        if row is None:
            return None
        boundary_notes = self._loads(row["boundary_notes_json"])
        if not isinstance(boundary_notes, list):
            boundary_notes = []
        snapshot_payload = self._loads(row["published_snapshot_json"])
        if not isinstance(snapshot_payload, dict):
            snapshot_payload = {}
        return {
            "publish_result_id": row["publish_result_id"],
            "package_id": row["package_id"],
            "workspace_id": row["workspace_id"],
            "snapshot_type": row["snapshot_type"],
            "snapshot_version": row["snapshot_version"],
            "boundary_notes": boundary_notes,
            "snapshot_payload": snapshot_payload,
            "published_at": self._from_iso(row["published_at"]),
            "request_id": row["request_id"],
        }

    def create_job(
        self, *, job_type: str, workspace_id: str, request_id: str | None = None
    ) -> dict[str, object]:
        job_id = self.gen_id("job")
        now = self.now()
        self._execute(
            """
            INSERT INTO jobs (job_id, job_type, status, workspace_id, created_at, started_at, finished_at,
                              result_ref_type, result_ref_id, error_json, request_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                job_type,
                JobStatus.QUEUED.value,
                workspace_id,
                self._to_iso(now),
                None,
                None,
                None,
                None,
                None,
                request_id,
            ),
        )
        return self.get_job(job_id)

    def start_job(self, job_id: str) -> dict[str, object] | None:
        self._execute(
            "UPDATE jobs SET status = ?, started_at = ? WHERE job_id = ?",
            (JobStatus.RUNNING.value, self._to_iso(self.now()), job_id),
        )
        return self.get_job(job_id)

    def finish_job_success(
        self, *, job_id: str, result_ref: dict[str, str]
    ) -> dict[str, object] | None:
        self._execute(
            """
            UPDATE jobs
            SET status = ?, finished_at = ?, result_ref_type = ?, result_ref_id = ?, error_json = NULL
            WHERE job_id = ?
            """,
            (
                JobStatus.SUCCEEDED.value,
                self._to_iso(self.now()),
                result_ref["resource_type"],
                result_ref["resource_id"],
                job_id,
            ),
        )
        return self.get_job(job_id)

    def finish_job_failed(
        self, *, job_id: str, error: dict[str, object]
    ) -> dict[str, object] | None:
        self._execute(
            """
            UPDATE jobs
            SET status = ?, finished_at = ?, error_json = ?
            WHERE job_id = ?
            """,
            (
                JobStatus.FAILED.value,
                self._to_iso(self.now()),
                self._dumps(error),
                job_id,
            ),
        )
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> dict[str, object] | None:
        row = self._fetchone("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
        if row is None:
            return None
        result_ref = None
        if row["result_ref_type"] and row["result_ref_id"]:
            result_ref = {
                "resource_type": row["result_ref_type"],
                "resource_id": row["result_ref_id"],
            }
        return {
            "job_id": row["job_id"],
            "job_type": row["job_type"],
            "status": row["status"],
            "workspace_id": row["workspace_id"],
            "request_id": row["request_id"],
            "created_at": self._from_iso(row["created_at"]),
            "started_at": self._from_iso(row["started_at"]),
            "finished_at": self._from_iso(row["finished_at"]),
            "result_ref": result_ref,
            "error": self._loads(row["error_json"]),
        }

    def emit_event(
        self,
        *,
        event_name: str,
        request_id: str | None,
        job_id: str | None,
        workspace_id: str | None,
        source_id: str | None = None,
        candidate_batch_id: str | None = None,
        component: str,
        step: str,
        status: str,
        refs: dict[str, object] | None = None,
        metrics: dict[str, object] | None = None,
        error: dict[str, object] | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        self._execute(
            """
            INSERT INTO research_events (
                event_id, event_name, timestamp, request_id, job_id, workspace_id, source_id,
                candidate_batch_id, component, step, status, refs_json, metrics_json, error_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.gen_id("event"),
                event_name,
                self._to_iso(self.now()),
                request_id,
                job_id,
                workspace_id,
                source_id,
                candidate_batch_id,
                component,
                step,
                status,
                self._dumps(refs or {}),
                self._dumps(metrics or {}),
                self._dumps(error) if error is not None else None,
            ),
            conn=conn,
        )

    def list_jobs(
        self,
        *,
        workspace_id: str,
        request_id: str | None = None,
        job_id: str | None = None,
    ) -> list[dict[str, object]]:
        query = "SELECT * FROM jobs WHERE workspace_id = ?"
        params: list[object] = [workspace_id]
        if request_id is not None:
            query += " AND request_id = ?"
            params.append(request_id)
        if job_id is not None:
            query += " AND job_id = ?"
            params.append(job_id)
        query += " ORDER BY created_at ASC, job_id ASC"
        rows = self._fetchall(query, tuple(params))
        results: list[dict[str, object]] = []
        for row in rows:
            converted = self.get_job(str(row["job_id"]))
            if converted is not None:
                results.append(converted)
        return results

    def list_events(
        self,
        *,
        workspace_id: str,
        request_id: str | None = None,
        job_id: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, object]]:
        safe_limit = min(max(limit, 1), 5000)
        query = "SELECT * FROM research_events WHERE workspace_id = ?"
        params: list[object] = [workspace_id]
        if request_id is not None:
            query += " AND request_id = ?"
            params.append(request_id)
        if job_id is not None:
            query += " AND job_id = ?"
            params.append(job_id)
        query += " ORDER BY timestamp ASC, rowid ASC LIMIT ?"
        params.append(safe_limit)
        rows = self._fetchall(query, tuple(params))
        return [self._event_row_to_dict(row) for row in rows]

    def find_latest_event(
        self,
        *,
        workspace_id: str,
        event_name: str,
        ref_key: str | None = None,
        ref_value: object | None = None,
    ) -> dict[str, object] | None:
        events = self.list_events(workspace_id=workspace_id, limit=5000)
        for event in reversed(events):
            if event["event_name"] != event_name:
                continue
            if ref_key is None:
                return event
            refs = event.get("refs", {})
            if isinstance(refs, dict) and refs.get(ref_key) == ref_value:
                return event
        return None

    def _event_row_to_dict(self, row: sqlite3.Row) -> dict[str, object]:
        refs = self._loads(row["refs_json"])
        metrics = self._loads(row["metrics_json"])
        error = self._loads(row["error_json"])
        return {
            "event_id": row["event_id"],
            "event_name": row["event_name"],
            "timestamp": self._from_iso(row["timestamp"]),
            "request_id": row["request_id"],
            "job_id": row["job_id"],
            "workspace_id": row["workspace_id"],
            "source_id": row["source_id"],
            "candidate_batch_id": row["candidate_batch_id"],
            "component": row["component"],
            "step": row["step"],
            "status": row["status"],
            "refs": refs if isinstance(refs, dict) else {},
            "metrics": metrics if isinstance(metrics, dict) else {},
            "error": error if isinstance(error, dict) else None,
        }


STORE = ResearchApiStateStore()
