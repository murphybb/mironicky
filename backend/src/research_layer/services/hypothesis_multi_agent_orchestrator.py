from __future__ import annotations

import copy
import json
import math
import time
from typing import Protocol

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.services.hypothesis_agents import (
    EvolutionAgent,
    GenerationAgent,
    MetaReviewAgent,
    ProximityAgent,
    RankingAgent,
    ReflectionAgent,
    SupervisorAgent,
)
from research_layer.services.hypothesis_agents.base import HypothesisAgentBase
from research_layer.services.llm_gateway import ResearchLLMError
from research_layer.services.llm_trace import LLMCallResult
from research_layer.services.prompt_renderer import build_messages_from_prompt
from research_layer.services.research_llm_dependencies import (
    build_research_llm_gateway,
    resolve_research_backend_and_model,
)


class _JsonGateway(Protocol):
    async def invoke_json(self, **kwargs: object) -> LLMCallResult: ...


class HypothesisMultiAgentOrchestrator:
    _ELO_BASE = 1200.0
    _ELO_K = 24.0
    _EVOLUTION_OPERATORS = {
        "grounding",
        "feasibility",
        "combination",
        "simplification",
        "out_of_box",
    }
    _REFLECTION_STAGES = (
        "initial_review",
        "literature_grounding_review",
        "deep_assumption_verification",
        "simulation_or_counterexample_review",
    )
    _REFLECTION_SECTION_FIELDS = (
        "recommendation",
        "recommended_actions",
        "findings",
        "strengths",
        "weaknesses",
        "missing_evidence",
        "testability_issues",
        "evidence_refs",
        "grounding",
    )

    def __init__(
        self, store: ResearchApiStateStore, *, llm_gateway: _JsonGateway | None = None
    ) -> None:
        self._store = store
        self._llm_gateway = llm_gateway or build_research_llm_gateway()
        self._supervisor = SupervisorAgent()
        self._generation = GenerationAgent()
        self._reflection = ReflectionAgent()
        self._ranking = RankingAgent()
        self._evolution = EvolutionAgent()
        self._meta_review = MetaReviewAgent()
        self._proximity = ProximityAgent()

    async def create_pool(
        self,
        *,
        workspace_id: str,
        request_id: str,
        trigger_refs: list[dict[str, object]],
        research_goal: str,
        top_k: int,
        max_rounds: int,
        candidate_count: int,
        constraints: dict[str, object],
        preference_profile: dict[str, object],
        novelty_typing: str,
        related_object_ids: list[dict[str, str]],
        minimum_validation_action: dict[str, object],
        weakening_signal: dict[str, object],
        orchestration_mode: str = "multi_agent_pool",
    ) -> dict[str, object]:
        pool = self._store.create_hypothesis_pool(
            workspace_id=workspace_id,
            status="running",
            orchestration_mode=orchestration_mode,
            trigger_refs=copy.deepcopy(trigger_refs),
            reasoning_subgraph={"request_id": request_id},
            top_k=top_k,
            max_rounds=max_rounds,
            candidate_count=candidate_count,
            current_round_number=0,
            research_goal=research_goal,
            constraints=dict(constraints),
            preference_profile=dict(preference_profile),
            created_job_id=None,
            created_request_id=request_id,
        )
        pool_id = str(pool["pool_id"])
        root = self._store.create_hypothesis_search_tree_node(
            pool_id=pool_id,
            parent_tree_node_id=None,
            candidate_id=None,
            node_role="root",
            depth=0,
            visits=0,
            mean_reward=0.0,
            uct_score=0.0,
            status="alive",
        )
        reasoning_subgraph = dict(pool.get("reasoning_subgraph") or {})
        reasoning_subgraph["root_tree_node_id"] = str(root["tree_node_id"])
        reasoning_subgraph["latest_meta_review_id"] = None
        reasoning_subgraph["agent_execution"] = {
            "mode": "llm_gateway",
            "deterministic_agent_fallback": False,
        }
        reasoning_subgraph["similarity_services"] = [
            {"name": "proximity", "type": "similarity_service", "llm_agent": False}
        ]
        self._store.update_hypothesis_pool(
            pool_id=pool_id, reasoning_subgraph=reasoning_subgraph
        )
        active_retrieval_trace = preference_profile.get("active_retrieval_trace")
        evidence_packets = (
            active_retrieval_trace.get("evidence_packets")
            if isinstance(active_retrieval_trace, dict)
            else []
        )
        if not isinstance(evidence_packets, list):
            evidence_packets = []

        try:
            supervisor_plan, supervisor_tx = await self._invoke_agent(
                agent=self._supervisor,
                pool_id=pool_id,
                round_id=None,
                request_id=request_id,
                variables={
                    "workspace_id": workspace_id,
                    "research_goal": research_goal or "(unspecified)",
                    "trigger_refs": json.dumps(
                        trigger_refs, ensure_ascii=False, default=str
                    ),
                    "trigger_types": json.dumps(
                        self._trigger_types(trigger_refs), ensure_ascii=False
                    ),
                    "top_k": top_k,
                    "max_rounds": max_rounds,
                    "candidate_count": candidate_count,
                    "constraints": constraints,
                    "constraints_json": json.dumps(
                        constraints, ensure_ascii=False, default=str
                    ),
                    "preference_profile": preference_profile,
                    "preference_profile_json": json.dumps(
                        preference_profile, ensure_ascii=False, default=str
                    ),
                    "evidence_packets_json": json.dumps(
                        evidence_packets, ensure_ascii=False, default=str
                    ),
                },
                input_payload={
                    "workspace_id": workspace_id,
                    "research_goal": research_goal,
                    "trigger_refs": trigger_refs,
                    "top_k": top_k,
                    "max_rounds": max_rounds,
                    "candidate_count": candidate_count,
                    "constraints": constraints,
                    "preference_profile": preference_profile,
                    "evidence_packets": copy.deepcopy(evidence_packets),
                },
            )
            reasoning_subgraph["supervisor_plan"] = supervisor_plan
            reasoning_subgraph["supervisor_transcript_id"] = supervisor_tx[
                "transcript_id"
            ]
            self._store.update_hypothesis_pool(
                pool_id=pool_id, reasoning_subgraph=reasoning_subgraph
            )
            initial_decision = (
                str(supervisor_plan.get("decision") or "continue").strip().lower()
            )
            if initial_decision == "evolve":
                self._invalid_agent_output(
                    "supervisor",
                    "initial supervisor decision cannot be evolve without candidates",
                )
            if initial_decision in {"retrieve", "pause", "stop", "finalize"}:
                status_by_decision = {
                    "retrieve": "paused",
                    "pause": "paused",
                    "stop": "stopped",
                    "finalize": "finalizing",
                }
                updated = self._store.update_hypothesis_pool(
                    pool_id=pool_id, status=status_by_decision[initial_decision]
                )
                assert updated is not None
                return self._pool_public(updated)

            for seed_index in range(max(2, candidate_count)):
                generated, generation_tx = await self._invoke_agent(
                    agent=self._generation,
                    pool_id=pool_id,
                    round_id=None,
                    request_id=request_id,
                    variables={
                        "workspace_id": workspace_id,
                        "research_goal": research_goal or "(unspecified)",
                        "seed_index": seed_index,
                        "trigger_context_json": json.dumps(
                            trigger_refs, ensure_ascii=False, default=str
                        ),
                        "supervisor_plan_json": json.dumps(
                            supervisor_plan, ensure_ascii=False, default=str
                        ),
                        "evidence_packets_json": json.dumps(
                            evidence_packets, ensure_ascii=False, default=str
                        ),
                    },
                    input_payload={
                        "seed_index": seed_index,
                        "research_goal": research_goal,
                        "trigger_refs": trigger_refs,
                        "supervisor_plan": supervisor_plan,
                        "evidence_packets": copy.deepcopy(evidence_packets),
                    },
                )
                self._materialize_candidate(
                    pool_id=pool_id,
                    generated=generated,
                    generation_transcript_id=str(generation_tx["transcript_id"]),
                    origin_type="generation",
                    origin_round=0,
                    lineage={"parents": [], "mode": "seed"},
                    parent_tree_node_id=str(root["tree_node_id"]),
                    trigger_refs=trigger_refs,
                    related_object_ids=related_object_ids,
                    minimum_validation_action=minimum_validation_action,
                    weakening_signal=weakening_signal,
                    novelty_typing=novelty_typing,
                )
        except ResearchLLMError:
            self._store.update_hypothesis_pool(pool_id=pool_id, status="failed")
            raise

        await self.run_round(
            pool_id=pool_id,
            request_id=request_id,
            max_matches=min(max(1, candidate_count // 2), 12),
            start_reason="pool_initialized",
        )
        return self.get_pool(pool_id=pool_id) or {}

    async def run_round(
        self,
        *,
        pool_id: str,
        request_id: str,
        max_matches: int,
        start_reason: str = "manual",
    ) -> dict[str, object]:
        pool = self._require_pool(pool_id)
        if str(pool["status"]) in {
            "paused",
            "stopping",
            "stopped",
            "finalizing",
            "finalized",
            "failed",
            "cancelled",
        }:
            raise ValueError(f"pool {pool_id} is not runnable")

        round_number = int(pool["current_round_number"]) + 1
        round_record = self._store.create_hypothesis_round(
            pool_id=pool_id,
            round_number=round_number,
            status="running",
            start_reason=start_reason,
        )
        round_id = str(round_record["round_id"])
        review_count = 0
        match_count = 0
        evolution_count = 0
        meta_review_id: str | None = None
        round_stop_reason = "single_round_complete"
        try:
            alive = self._alive(pool_id)
            round_supervisor, round_supervisor_tx = await self._invoke_agent(
                agent=self._supervisor,
                pool_id=pool_id,
                round_id=round_id,
                request_id=request_id,
                variables={
                    "workspace_id": str(pool["workspace_id"]),
                    "research_goal": str(pool.get("research_goal") or ""),
                    "trigger_refs": pool.get("trigger_refs") or [],
                    "top_k": int(pool.get("top_k") or 0),
                    "max_rounds": int(pool.get("max_rounds") or 0),
                    "candidate_count": len(alive),
                    "constraints": pool.get("constraints") or {},
                    "preference_profile": pool.get("preference_profile") or {},
                    "round_number": round_number,
                    "start_reason": start_reason,
                },
                input_payload={
                    "round_number": round_number,
                    "start_reason": start_reason,
                    "pool": pool,
                    "alive_candidates": alive,
                },
            )
            self._record_round_supervisor_in_pool(
                pool_id=pool_id,
                round_id=round_id,
                transcript_id=str(round_supervisor_tx["transcript_id"]),
                supervisor=round_supervisor,
            )
            supervisor_decision = (
                str(round_supervisor.get("decision") or "continue").strip().lower()
            )
            round_actions = {
                str(item).strip()
                for item in (
                    round_supervisor.get("next_actions")
                    if isinstance(round_supervisor.get("next_actions"), list)
                    else []
                )
                if str(item).strip()
            }
            if supervisor_decision in {"retrieve", "pause", "stop", "finalize"}:
                status_by_decision = {
                    "retrieve": "paused",
                    "pause": "paused",
                    "stop": "stopped",
                    "finalize": "finalizing",
                }
                self._store.update_hypothesis_pool(
                    pool_id=pool_id,
                    status=status_by_decision[supervisor_decision],
                    current_round_number=round_number,
                )
                return (
                    self._store.complete_hypothesis_round(
                        round_id=round_id,
                        stop_reason=str(
                            round_supervisor.get("stop_reason")
                            or f"supervisor_{supervisor_decision}"
                        ),
                        generation_count=0,
                        review_count=0,
                        match_count=0,
                        evolution_count=0,
                        meta_review_id=None,
                        status="completed",
                    )
                    or {}
                )

            alive = self._alive(pool_id)
            for candidate in alive if "reflect" in round_actions else []:
                reflection, transcript = await self._invoke_agent(
                    agent=self._reflection,
                    pool_id=pool_id,
                    round_id=round_id,
                    candidate_id=str(candidate["candidate_id"]),
                    request_id=request_id,
                    variables={
                        "candidate_id": str(candidate["candidate_id"]),
                        "round_number": round_number,
                        "candidate_json": json.dumps(
                            candidate, ensure_ascii=False, default=str
                        ),
                        "evidence_packets_json": json.dumps(
                            self._evidence_packets_for_pool(pool),
                            ensure_ascii=False,
                            default=str,
                        ),
                    },
                    input_payload={
                        "round_number": round_number,
                        "candidate": candidate,
                        "evidence_packets": copy.deepcopy(
                            self._evidence_packets_for_pool(pool)
                        ),
                    },
                )
                self._persist_reflection(
                    candidate=candidate,
                    round_id=round_id,
                    reflection=reflection,
                    transcript_id=str(transcript["transcript_id"]),
                )
                review_count += 1

            survivors = [
                candidate
                for candidate in self._alive(pool_id)
                if self._review_verdict(candidate) == "survive"
            ]
            matches: list[dict[str, object]] = []
            pairings = (
                self._pairings(survivors, max_matches=max(1, max_matches))
                if "rank" in round_actions
                else []
            )
            for left_id, right_id in pairings:
                left = self._require_candidate(left_id)
                right = self._require_candidate(right_id)
                match_id = self._store.gen_id("hyp_match_pending")
                ranking, transcript = await self._invoke_agent(
                    agent=self._ranking,
                    pool_id=pool_id,
                    round_id=round_id,
                    match_id=match_id,
                    request_id=request_id,
                    variables={
                        "left_candidate_json": json.dumps(
                            left, ensure_ascii=False, default=str
                        ),
                        "right_candidate_json": json.dumps(
                            right, ensure_ascii=False, default=str
                        ),
                    },
                    input_payload={"left_candidate": left, "right_candidate": right},
                )
                match = self._persist_ranking_match(
                    pool_id=pool_id,
                    round_id=round_id,
                    left=left,
                    right=right,
                    ranking=ranking,
                    transcript_id=str(transcript["transcript_id"]),
                )
                matches.append(match)
                match_count += 1

            ranked = sorted(
                self._alive(pool_id),
                key=lambda c: float(c.get("elo_rating") or 0.0),
                reverse=True,
            )
            parents = ranked[: max(2, min(4, len(ranked)))]
            if "evolve" not in round_actions:
                parents = []
            elif round_number >= int(pool["max_rounds"]):
                parents = []
                round_stop_reason = "terminal_round_evolution_skipped"
            if parents:
                evolution_parents = self._evolution_parent_prompt_candidates(parents)
                evolution, evolution_tx = await self._invoke_agent(
                    agent=self._evolution,
                    pool_id=pool_id,
                    round_id=round_id,
                    request_id=request_id,
                    variables={
                        "pool_id": pool_id,
                        "round_number": round_number,
                        "parent_candidates_json": json.dumps(
                            evolution_parents, ensure_ascii=False, default=str
                        ),
                        "target_children": max(1, len(parents) // 2),
                    },
                    input_payload={
                        "round_number": round_number,
                        "parent_candidates": evolution_parents,
                        "target_children": max(1, len(parents) // 2),
                    },
                )
                evolution_count = self._persist_evolution_children(
                    pool=pool,
                    round_id=round_id,
                    round_number=round_number,
                    evolution=evolution,
                    transcript_id=str(evolution_tx["transcript_id"]),
                    parent_candidates=parents,
                )

            current_alive = self._alive(pool_id)
            meta, meta_tx = await self._invoke_agent(
                agent=self._meta_review,
                pool_id=pool_id,
                round_id=round_id,
                request_id=request_id,
                variables={
                    "pool_id": pool_id,
                    "round_number": round_number,
                    "candidate_count": len(current_alive),
                    "match_count": len(matches),
                    "evolution_count": evolution_count,
                },
                input_payload={
                    "round_number": round_number,
                    "candidates": current_alive,
                    "matches": matches,
                    "evolution_count": evolution_count,
                },
            )
            meta_review = self._store.create_hypothesis_meta_review(
                pool_id=pool_id,
                round_id=round_id,
                recurring_issues=self._string_list(meta.get("recurring_issues")),
                strong_patterns=self._string_list(meta.get("strong_patterns")),
                weak_patterns=self._string_list(meta.get("weak_patterns")),
                continue_recommendation=str(meta.get("continue_recommendation") or ""),
                stop_recommendation=str(meta.get("stop_recommendation") or ""),
                diversity_assessment=str(meta.get("diversity_assessment") or ""),
                trace_refs={
                    "transcript_id": str(meta_tx["transcript_id"]),
                    "meta_review_summary": self._compact_meta_review_summary(meta),
                },
            )
            meta_review_id = str(meta_review["meta_review_id"])
            self._record_meta_review_in_pool(
                pool_id=pool_id,
                meta_review_id=meta_review_id,
                transcript_id=str(meta_tx["transcript_id"]),
                meta_review=meta,
            )
            self._prune(
                pool_id=pool_id, recommendations=meta.get("prune_recommendations")
            )
            self._persist_proximity(pool_id=pool_id)
            status = "stopped" if round_number >= int(pool["max_rounds"]) else "running"
            self._store.update_hypothesis_pool(
                pool_id=pool_id, status=status, current_round_number=round_number
            )
            return (
                self._store.complete_hypothesis_round(
                    round_id=round_id,
                    stop_reason=round_stop_reason,
                    generation_count=evolution_count,
                    review_count=review_count,
                    match_count=match_count,
                    evolution_count=evolution_count,
                    meta_review_id=meta_review_id,
                    status="completed",
                )
                or {}
            )
        except ResearchLLMError:
            self._store.complete_hypothesis_round(
                round_id=round_id,
                stop_reason="llm_agent_failed",
                generation_count=evolution_count,
                review_count=review_count,
                match_count=match_count,
                evolution_count=evolution_count,
                meta_review_id=meta_review_id,
                status="failed",
            )
            self._store.update_hypothesis_pool(pool_id=pool_id, status="failed")
            raise

    async def finalize_pool(
        self, *, pool_id: str, request_id: str
    ) -> list[dict[str, object]]:
        del request_id
        pool = self._require_pool(pool_id)
        matches = self._store.list_hypothesis_matches(pool_id=pool_id)
        if not matches:
            raise ValueError(
                "pool cannot be finalized before an LLM pairwise judge match"
            )
        pending_recheck_ids = [
            str(candidate.get("candidate_id") or "")
            for candidate in self._alive(pool_id)
            if bool((candidate.get("reasoning_chain") or {}).get("requires_recheck"))
            or bool((candidate.get("reasoning_chain") or {}).get("requires_rerank"))
        ]
        pending_recheck_ids = [item for item in pending_recheck_ids if item]
        if pending_recheck_ids:
            raise ValueError(
                "pool cannot be finalized while candidates require recheck or rerank"
            )
        judged_candidate_ids: set[str] = set()
        for match in matches:
            judged_candidate_ids.add(str(match.get("left_candidate_id") or ""))
            judged_candidate_ids.add(str(match.get("right_candidate_id") or ""))
            judged_candidate_ids.add(str(match.get("winner_candidate_id") or ""))
        judged_candidate_ids.discard("")
        ranked = sorted(
            [
                candidate
                for candidate in self._alive(pool_id)
                if str(candidate.get("candidate_id") or "") in judged_candidate_ids
                and self._review_verdict(candidate) == "survive"
                and not bool((candidate.get("reasoning_chain") or {}).get("requires_recheck"))
                and not bool((candidate.get("reasoning_chain") or {}).get("requires_rerank"))
            ],
            key=lambda c: float(c.get("elo_rating") or 0.0),
            reverse=True,
        )
        if not ranked:
            ranked = sorted(
                [
                    candidate
                    for candidate in self._store.list_hypothesis_candidates(
                        pool_id=pool_id
                    )
                    if str(candidate.get("candidate_id") or "") in judged_candidate_ids
                    and self._review_verdict(candidate) == "survive"
                    and not bool((candidate.get("reasoning_chain") or {}).get("requires_recheck"))
                    and not bool((candidate.get("reasoning_chain") or {}).get("requires_rerank"))
                ],
                key=lambda c: float(c.get("elo_rating") or 0.0),
                reverse=True,
            )
        if not ranked:
            raise ValueError(
                "pool cannot be finalized without candidates ranked by LLM judge"
            )
        selected = self._select_diverse_frontier(
            pool_id=pool_id, ranked=ranked, top_k=max(1, int(pool["top_k"]))
        )
        self._assert_selected_citations_verified(pool_id=pool_id, selected=selected)
        selected_ids = {str(item["candidate_id"]) for item in selected}
        for candidate in self._store.list_hypothesis_candidates(pool_id=pool_id):
            self._store.update_hypothesis_candidate(
                candidate_id=str(candidate["candidate_id"]),
                status=(
                    "finalized"
                    if str(candidate["candidate_id"]) in selected_ids
                    else "pruned"
                ),
            )
        self._store.update_hypothesis_pool(pool_id=pool_id, status="finalized")
        return [self._candidate_public(item) for item in selected]

    def _assert_selected_citations_verified(
        self, *, pool_id: str, selected: list[dict[str, object]]
    ) -> None:
        invalid_refs: list[dict[str, object]] = []
        pool = self._require_pool(pool_id)
        packets_by_id = self._evidence_packets_by_id(pool)
        uploaded_source_ids = self._uploaded_source_ids_for_pool(pool)
        for candidate in selected:
            chain = candidate.get("reasoning_chain")
            if not isinstance(chain, dict):
                continue
            for ref in chain.get("source_refs", []) or []:
                if not isinstance(ref, dict):
                    continue
                packet = packets_by_id.get(str(ref.get("packet_id") or ""))
                origin = str(ref.get("retrieval_origin") or ref.get("origin") or "").strip()
                status = str(ref.get("citation_verification_status") or "").strip()
                source_id = str(ref.get("source_id") or "").strip()
                if not origin and packet is not None:
                    origin = str(packet.get("retrieval_origin") or "").strip()
                if not status and packet is not None:
                    status = str(packet.get("citation_verification_status") or "").strip()
                if not origin:
                    if source_id in uploaded_source_ids:
                        origin = "uploaded"
                    elif str(ref.get("packet_id") or "").strip():
                        origin = "supplemental"
                    else:
                        origin = "uploaded"
                if origin == "supplemental" and status not in {
                    "verified",
                    "uploaded_verified",
                }:
                    invalid_refs.append(
                        {
                            "candidate_id": candidate.get("candidate_id"),
                            "source_id": source_id or ref.get("source_id"),
                            "packet_id": ref.get("packet_id"),
                            "citation_verification_status": status or "missing",
                        }
                    )
        if invalid_refs:
            reasoning_subgraph = dict(pool.get("reasoning_subgraph") or {})
            reasoning_subgraph["finalization_blocker"] = {
                "failure_code": "citation_unverified",
                "invalid_refs": invalid_refs,
            }
            self._store.update_hypothesis_pool(
                pool_id=pool_id, reasoning_subgraph=reasoning_subgraph
            )
            raise ValueError(
                "pool cannot be finalized while selected candidates depend on "
                "unverified supplemental citations"
            )

    def _evidence_packets_for_pool(self, pool: dict[str, object]) -> list[dict[str, object]]:
        trace = (pool.get("preference_profile") or {}).get("active_retrieval_trace")
        if not isinstance(trace, dict):
            return []
        packets = trace.get("evidence_packets")
        return [item for item in packets if isinstance(item, dict)] if isinstance(packets, list) else []

    def _evidence_packets_by_id(
        self, pool: dict[str, object]
    ) -> dict[str, dict[str, object]]:
        return {
            str(packet.get("packet_id") or ""): packet
            for packet in self._evidence_packets_for_pool(pool)
            if str(packet.get("packet_id") or "").strip()
        }

    def _uploaded_source_ids_for_pool(self, pool: dict[str, object]) -> set[str]:
        source_ids: set[str] = set()
        for trigger in pool.get("trigger_refs") or []:
            if not isinstance(trigger, dict):
                continue
            trace_refs = trigger.get("trace_refs")
            if isinstance(trace_refs, dict) and trace_refs.get("source_id"):
                source_ids.add(str(trace_refs["source_id"]))
        for packet in self._evidence_packets_for_pool(pool):
            if str(packet.get("retrieval_origin") or "") == "uploaded" and packet.get("source_id"):
                source_ids.add(str(packet["source_id"]))
        return source_ids

    def get_pool(self, *, pool_id: str) -> dict[str, object] | None:
        pool = self._store.get_hypothesis_pool(pool_id)
        return self._pool_public(pool) if pool is not None else None

    def get_candidate(self, *, candidate_id: str) -> dict[str, object] | None:
        candidate = self._store.get_hypothesis_candidate(candidate_id)
        return self._candidate_public(candidate) if candidate is not None else None

    def control_pool(
        self, *, pool_id: str, request_id: str, action: str
    ) -> dict[str, object]:
        pool = self._require_pool(pool_id)
        status = str(pool.get("status") or "running")
        if status in {"stopped", "finalized", "failed", "cancelled"}:
            raise ValueError(f"pool {pool_id} is terminal")

        reasoning_subgraph = dict(pool.get("reasoning_subgraph") or {})
        control = dict(reasoning_subgraph.get("control") or {})
        normalized_action = str(action).strip()
        if normalized_action == "pause":
            status = "paused"
            control["pause_requested"] = True
        elif normalized_action == "resume":
            status = "running"
            control["pause_requested"] = False
        elif normalized_action == "stop":
            status = "stopping"
            control["stop_requested"] = True
        elif normalized_action == "force_finalize":
            status = "finalizing"
            control["force_finalize_requested"] = True
        elif normalized_action == "disable_retrieval":
            control["disable_retrieval_requested"] = True
        elif normalized_action == "add_sources":
            control["add_sources_requested"] = True
        else:
            raise ValueError(f"unsupported control action: {normalized_action}")
        control["last_action"] = normalized_action
        control["last_request_id"] = request_id
        reasoning_subgraph["control"] = control
        updated = self._store.update_hypothesis_pool(
            pool_id=pool_id, status=status, reasoning_subgraph=reasoning_subgraph
        )
        return self._pool_public(updated or self._require_pool(pool_id))

    def apply_user_intervention(
        self,
        *,
        pool_id: str,
        request_id: str,
        action: str,
        candidate_id: str | None,
        node: dict[str, object] | None,
        candidate_patch: dict[str, object] | None,
        user_hypothesis: dict[str, object] | None,
        control_reason: str | None,
    ) -> dict[str, object]:
        pool = self._require_pool(pool_id)
        if str(pool.get("status") or "") in {
            "stopped",
            "finalized",
            "failed",
            "cancelled",
        }:
            raise ValueError(f"pool {pool_id} is terminal")
        normalized_action = str(action).strip()
        event = {
            "event_id": self._store.gen_id("hyp_user_event"),
            "request_id": request_id,
            "action": normalized_action,
            "control_reason": control_reason or "",
            "created_at": self._store.now().isoformat(),
        }
        if normalized_action == "add_user_hypothesis":
            if not isinstance(user_hypothesis, dict):
                raise ValueError("add_user_hypothesis requires user_hypothesis")
            self._add_user_hypothesis(
                pool=pool, user_hypothesis=user_hypothesis, intervention=event
            )
        else:
            if not candidate_id:
                raise ValueError(f"{normalized_action} requires candidate_id")
            if normalized_action in {
                "edit_reasoning_node",
                "delete_reasoning_node",
                "add_reasoning_node",
            }:
                if not isinstance(node, dict):
                    raise ValueError(f"{normalized_action} requires node")
                self._apply_reasoning_node_intervention(
                    candidate_id=candidate_id,
                    action=normalized_action,
                    node=node,
                    intervention=event,
                )
            elif normalized_action == "edit_candidate":
                if not isinstance(candidate_patch, dict):
                    raise ValueError("edit_candidate requires candidate_patch")
                self._apply_candidate_patch_intervention(
                    candidate_id=candidate_id,
                    candidate_patch=candidate_patch,
                    intervention=event,
                )
            else:
                raise ValueError(f"unsupported user intervention: {normalized_action}")
        self._record_pool_intervention(pool_id=pool_id, intervention=event)
        return self._pool_public(self._require_pool(pool_id))

    def patch_candidate_reasoning_chain(
        self,
        *,
        candidate_id: str,
        request_id: str,
        reasoning_chain: dict[str, object],
        reset_review_state: bool,
    ) -> dict[str, object] | None:
        candidate = self._store.get_hypothesis_candidate(candidate_id)
        if candidate is None:
            return None
        next_chain = dict(candidate.get("reasoning_chain") or {})
        next_chain.update(reasoning_chain if isinstance(reasoning_chain, dict) else {})
        next_chain["reasoning_nodes"] = self._reasoning_nodes(next_chain)
        self._sync_reasoning_chain_from_nodes(next_chain)
        if reset_review_state:
            next_chain["review_status"] = "pending"
            next_chain["review_history"] = []
            next_chain["revise_count"] = 0
            next_chain["requires_recheck"] = True
            next_chain["requires_rerank"] = True
            next_chain["recheck_reason"] = "user_patch"
        next_chain["edited_by_user"] = True
        next_chain["edited_at"] = self._store.now().isoformat()
        intervention = {
            "event_id": self._store.gen_id("hyp_user_event"),
            "request_id": request_id,
            "action": "patch_candidate_reasoning_chain",
            "control_reason": "candidate_patch_endpoint",
            "created_at": next_chain["edited_at"],
        }
        history = list(next_chain.get("user_interventions") or [])
        history.append(intervention)
        next_chain["user_interventions"] = history
        self._sync_agent_trace_candidate(next_chain)
        statement = str(next_chain.get("hypothesis_statement") or "").strip()
        summary = str(next_chain.get("hypothesis_level_conclusion") or "").strip()
        updated = self._store.update_hypothesis_candidate(
            candidate_id=candidate_id,
            statement=statement or str(candidate["statement"]),
            summary=summary or str(candidate["summary"]),
            reasoning_chain=next_chain,
            status="alive",
        )
        return self._candidate_public(updated) if updated is not None else None

    def _apply_reasoning_node_intervention(
        self,
        *,
        candidate_id: str,
        action: str,
        node: dict[str, object],
        intervention: dict[str, object],
    ) -> None:
        candidate = self._require_candidate(candidate_id)
        chain = dict(candidate.get("reasoning_chain") or {})
        nodes = self._reasoning_nodes(chain)
        node_id = str(node.get("node_id") or "").strip()
        if action in {"edit_reasoning_node", "delete_reasoning_node"} and not node_id:
            raise ValueError(f"{action} requires node.node_id")

        if action == "add_reasoning_node":
            node_id = node_id or self._reasoning_node_id(
                str(node.get("node_type") or ""), len(nodes)
            )
            nodes.append(self._normalized_reasoning_node(node, node_id=node_id))
        elif action == "edit_reasoning_node":
            matched = False
            for index, existing in enumerate(nodes):
                if str(existing.get("node_id") or "") == node_id:
                    nodes[index] = self._normalized_reasoning_node(node, node_id=node_id)
                    matched = True
                    break
            if not matched:
                raise ValueError(f"reasoning node not found: {node_id}")
        elif action == "delete_reasoning_node":
            next_nodes = [
                existing
                for existing in nodes
                if str(existing.get("node_id") or "") != node_id
            ]
            if len(next_nodes) == len(nodes):
                raise ValueError(f"reasoning node not found: {node_id}")
            nodes = next_nodes

        chain["reasoning_nodes"] = nodes
        self._sync_reasoning_chain_from_nodes(chain)
        self._persist_user_intervention_candidate_state(
            candidate=candidate, chain=chain, intervention=intervention
        )

    def _apply_candidate_patch_intervention(
        self,
        *,
        candidate_id: str,
        candidate_patch: dict[str, object],
        intervention: dict[str, object],
    ) -> None:
        candidate = self._require_candidate(candidate_id)
        chain = dict(candidate.get("reasoning_chain") or {})
        for key in ("title", "statement", "hypothesis_level_conclusion"):
            value = str(candidate_patch.get(key) or "").strip()
            if value:
                chain[
                    "hypothesis_statement" if key == "statement" else key
                ] = value
        nested = dict(chain.get("reasoning_chain") or {})
        if str(candidate_patch.get("hypothesis_level_conclusion") or "").strip():
            patched_conclusion = str(
                candidate_patch["hypothesis_level_conclusion"]
            ).strip()
            nested["conclusion"] = patched_conclusion
            chain["reasoning_chain"] = nested
            explicit_nodes = self._reasoning_nodes(chain)
            has_conclusion_node = False
            for node in explicit_nodes:
                if node["node_type"] == "conclusion":
                    node["content"] = patched_conclusion
                    has_conclusion_node = True
                    break
            if not has_conclusion_node:
                explicit_nodes.append(
                    {
                        "node_id": self._reasoning_node_id("conclusion", 0),
                        "node_type": "conclusion",
                        "content": patched_conclusion,
                        "source_refs": [],
                    }
                )
            chain["reasoning_nodes"] = explicit_nodes
        else:
            chain["reasoning_nodes"] = self._reasoning_nodes(chain)
        self._sync_reasoning_chain_from_nodes(chain)
        self._persist_user_intervention_candidate_state(
            candidate=candidate, chain=chain, intervention=intervention
        )

    def _persist_user_intervention_candidate_state(
        self,
        *,
        candidate: dict[str, object],
        chain: dict[str, object],
        intervention: dict[str, object],
    ) -> None:
        history = list(chain.get("user_interventions") or [])
        history.append(copy.deepcopy(intervention))
        now = self._store.now().isoformat()
        chain["user_interventions"] = history
        chain["edited_by_user"] = True
        chain["edited_at"] = now
        self._sync_agent_trace_candidate(chain)
        chain["review_status"] = "pending"
        chain["review_history"] = []
        chain["revise_count"] = 0
        chain["requires_recheck"] = True
        chain["requires_rerank"] = True
        chain["recheck_reason"] = str(intervention.get("action") or "user_intervention")
        self._store.update_hypothesis_candidate(
            candidate_id=str(candidate["candidate_id"]),
            title=str(chain.get("title") or candidate.get("title") or ""),
            statement=str(
                chain.get("hypothesis_statement") or candidate.get("statement") or ""
            ),
            summary=str(
                chain.get("hypothesis_level_conclusion")
                or candidate.get("summary")
                or ""
            ),
            reasoning_chain=chain,
            status="alive",
            elo_rating=self._ELO_BASE,
            survival_score=0.5,
        )
        self._mark_evolved_children_requires_recheck(
            pool_id=str(candidate["pool_id"]),
            parent_candidate_id=str(candidate["candidate_id"]),
            intervention=intervention,
        )

    def _add_user_hypothesis(
        self,
        *,
        pool: dict[str, object],
        user_hypothesis: dict[str, object],
        intervention: dict[str, object],
    ) -> None:
        statement = str(user_hypothesis.get("statement") or "").strip()
        if not statement:
            raise ValueError("user_hypothesis.statement is required")
        chain = dict(user_hypothesis.get("reasoning_chain") or {})
        chain.setdefault("hypothesis_statement", statement)
        chain.setdefault(
            "hypothesis_level_conclusion",
            str(user_hypothesis.get("hypothesis_level_conclusion") or statement),
        )
        chain["reasoning_nodes"] = self._reasoning_nodes(chain)
        self._sync_reasoning_chain_from_nodes(chain)
        root_tree_node_id = str(
            (pool.get("reasoning_subgraph") or {}).get("root_tree_node_id") or ""
        )
        if not root_tree_node_id:
            raise ValueError("pool root tree node is missing")
        generated = {
            "agent_role": "human_user",
            "candidate": {
                "title": str(user_hypothesis.get("title") or "User hypothesis"),
                "statement": statement,
                "summary": str(chain.get("hypothesis_level_conclusion") or statement),
                "rationale": "User-authored hypothesis requiring agent recheck.",
                "hypothesis_level_conclusion": str(
                    chain.get("hypothesis_level_conclusion") or statement
                ),
                "reasoning_chain": chain.get("reasoning_chain") or {},
                "source_refs": chain.get("source_refs") or [],
                "testability_hint": chain.get("validation_need")
                or chain.get("required_validation")
                or "Reflection agent must design required validation.",
                "suggested_next_steps": chain.get("suggested_next_steps") or [],
                "confidence_hint": 0.1,
                "retrieval_origin": "user",
            },
        }
        created = self._materialize_candidate(
            pool_id=str(pool["pool_id"]),
            generated=generated,
            generation_transcript_id=str(intervention["event_id"]),
            origin_type="user_hypothesis",
            origin_round=int(pool.get("current_round_number") or 0),
            lineage={"parents": [], "operator": "user_authored"},
            parent_tree_node_id=root_tree_node_id,
            trigger_refs=list(pool.get("trigger_refs") or []),
            related_object_ids=[],
            minimum_validation_action={"validation_id": "user_validation_needed"},
            weakening_signal={"signal_type": "user_authored", "severity_hint": "medium"},
            novelty_typing="user_hypothesis",
        )
        chain = dict(created.get("reasoning_chain") or {})
        chain.update(
            {
                "reasoning_nodes": self._reasoning_nodes(chain),
                "user_interventions": [copy.deepcopy(intervention)],
                "edited_by_user": True,
                "edited_at": self._store.now().isoformat(),
                "requires_recheck": True,
                "requires_rerank": True,
                "recheck_reason": "add_user_hypothesis",
            }
        )
        self._store.update_hypothesis_candidate(
            candidate_id=str(created["candidate_id"]),
            reasoning_chain=chain,
            status="alive",
            elo_rating=self._ELO_BASE,
            survival_score=0.5,
        )

    def _sync_agent_trace_candidate(self, chain: dict[str, object]) -> None:
        agent_trace = chain.get("agent_trace")
        if not isinstance(agent_trace, dict):
            return
        candidate_payload = agent_trace.get("candidate")
        if not isinstance(candidate_payload, dict):
            return
        candidate_payload["statement"] = str(chain.get("hypothesis_statement") or "")
        candidate_payload["hypothesis_level_conclusion"] = str(
            chain.get("hypothesis_level_conclusion") or ""
        )
        candidate_payload["summary"] = str(
            chain.get("hypothesis_level_conclusion")
            or candidate_payload.get("summary")
            or ""
        )
        candidate_payload["reasoning_chain"] = copy.deepcopy(
            chain.get("reasoning_chain") or {}
        )
        candidate_payload["source_refs"] = copy.deepcopy(chain.get("source_refs") or [])
        candidate_payload["reasoning_nodes"] = copy.deepcopy(
            chain.get("reasoning_nodes") or []
        )
        agent_trace["candidate"] = candidate_payload
        chain["agent_trace"] = agent_trace

    def _record_pool_intervention(
        self, *, pool_id: str, intervention: dict[str, object]
    ) -> None:
        pool = self._require_pool(pool_id)
        reasoning_subgraph = dict(pool.get("reasoning_subgraph") or {})
        history = list(reasoning_subgraph.get("user_interventions") or [])
        history.append(copy.deepcopy(intervention))
        reasoning_subgraph["user_interventions"] = history
        reasoning_subgraph["latest_user_intervention"] = copy.deepcopy(intervention)
        self._store.update_hypothesis_pool(
            pool_id=pool_id, reasoning_subgraph=reasoning_subgraph
        )

    def _mark_evolved_children_requires_recheck(
        self,
        *,
        pool_id: str,
        parent_candidate_id: str,
        intervention: dict[str, object],
    ) -> None:
        for candidate in self._store.list_hypothesis_candidates(pool_id=pool_id):
            lineage = candidate.get("lineage") or {}
            parents = lineage.get("parents") if isinstance(lineage, dict) else []
            if parent_candidate_id not in {str(item) for item in parents or []}:
                continue
            chain = dict(candidate.get("reasoning_chain") or {})
            chain["requires_recheck"] = True
            chain["requires_rerank"] = True
            chain["recheck_reason"] = "parent_user_intervention"
            child_events = list(chain.get("parent_intervention_events") or [])
            child_events.append(copy.deepcopy(intervention))
            chain["parent_intervention_events"] = child_events
            self._store.update_hypothesis_candidate(
                candidate_id=str(candidate["candidate_id"]),
                reasoning_chain=chain,
            )

    def _reasoning_nodes(self, chain: dict[str, object]) -> list[dict[str, object]]:
        explicit = chain.get("reasoning_nodes")
        if isinstance(explicit, list) and explicit:
            return [
                self._normalized_reasoning_node(item, node_id=None)
                for item in explicit
                if isinstance(item, dict)
            ]
        nested = chain.get("reasoning_chain")
        nested_chain = nested if isinstance(nested, dict) else chain
        nodes: list[dict[str, object]] = []
        for index, item in enumerate(self._string_list(nested_chain.get("evidence"))):
            nodes.append(
                {
                    "node_id": self._reasoning_node_id("evidence", index),
                    "node_type": "evidence",
                    "content": item,
                    "source_refs": copy.deepcopy(chain.get("source_refs") or []),
                }
            )
        assumption = str(nested_chain.get("assumption") or "").strip()
        if assumption:
            nodes.append(
                {
                    "node_id": self._reasoning_node_id("assumption", 0),
                    "node_type": "assumption",
                    "content": assumption,
                    "source_refs": [],
                }
            )
        for index, item in enumerate(
            self._string_list(nested_chain.get("intermediate_reasoning"))
        ):
            nodes.append(
                {
                    "node_id": self._reasoning_node_id("intermediate_reasoning", index),
                    "node_type": "intermediate_reasoning",
                    "content": item,
                    "source_refs": [],
                }
            )
        for node_type in ("conclusion", "validation_need"):
            content = str(nested_chain.get(node_type) or "").strip()
            if content:
                nodes.append(
                    {
                        "node_id": self._reasoning_node_id(node_type, 0),
                        "node_type": node_type,
                        "content": content,
                        "source_refs": [],
                    }
                )
        return nodes

    def _normalized_reasoning_node(
        self, node: dict[str, object], *, node_id: str | None
    ) -> dict[str, object]:
        resolved_node_id = str(node_id or node.get("node_id") or "").strip()
        node_type = str(node.get("node_type") or "").strip()
        if node_type not in {
            "evidence",
            "assumption",
            "intermediate_reasoning",
            "conclusion",
            "validation_need",
        }:
            raise ValueError(f"unsupported reasoning node type: {node_type}")
        if not resolved_node_id:
            resolved_node_id = self._reasoning_node_id(node_type, 0)
        return {
            "node_id": resolved_node_id,
            "node_type": node_type,
            "content": str(node.get("content") or "").strip(),
            "source_refs": copy.deepcopy(node.get("source_refs") or []),
        }

    @staticmethod
    def _reasoning_node_id(node_type: str, index: int) -> str:
        return f"{node_type}:{index + 1}"

    def _sync_reasoning_chain_from_nodes(self, chain: dict[str, object]) -> None:
        nested = dict(chain.get("reasoning_chain") or {})
        nodes = self._reasoning_nodes(chain)
        by_type: dict[str, list[dict[str, object]]] = {}
        for node in nodes:
            by_type.setdefault(str(node.get("node_type") or ""), []).append(node)
        nested["evidence"] = [
            str(node.get("content") or "")
            for node in by_type.get("evidence", [])
            if str(node.get("content") or "").strip()
        ]
        nested["assumption"] = str(
            (by_type.get("assumption") or [{}])[0].get("content") or ""
        )
        nested["intermediate_reasoning"] = [
            str(node.get("content") or "")
            for node in by_type.get("intermediate_reasoning", [])
            if str(node.get("content") or "").strip()
        ]
        nested["conclusion"] = str(
            (by_type.get("conclusion") or [{}])[0].get("content") or ""
        )
        nested["validation_need"] = str(
            (by_type.get("validation_need") or [{}])[0].get("content") or ""
        )
        chain["reasoning_chain"] = nested
        chain["reasoning_nodes"] = nodes

    def list_pool_candidates(self, *, pool_id: str) -> list[dict[str, object]]:
        return [
            self._candidate_public(item)
            for item in self._store.list_hypothesis_candidates(pool_id=pool_id)
        ]

    def list_pool_rounds(self, *, pool_id: str) -> list[dict[str, object]]:
        return self._store.list_hypothesis_rounds(pool_id=pool_id)

    def get_match(self, *, match_id: str) -> dict[str, object] | None:
        return self._store.get_hypothesis_match(match_id)

    def get_search_tree_node(self, *, tree_node_id: str) -> dict[str, object] | None:
        return self._store.get_hypothesis_search_tree_node(tree_node_id)

    async def _invoke_agent(
        self,
        *,
        agent: HypothesisAgentBase,
        pool_id: str,
        round_id: str | None,
        request_id: str,
        variables: dict[str, object],
        input_payload: dict[str, object],
        candidate_id: str | None = None,
        match_id: str | None = None,
    ) -> tuple[dict[str, object], dict[str, object]]:
        meta_review_context = self._latest_meta_review_context(pool_id=pool_id)
        if meta_review_context is not None and agent.role_name in {
            "supervisor",
            "generation",
            "reflection",
        }:
            variables = {
                **variables,
                "latest_meta_review_id": meta_review_context["latest_meta_review_id"],
                "meta_review_summary_json": json.dumps(
                    meta_review_context["meta_review_summary"],
                    ensure_ascii=False,
                    default=str,
                ),
                "meta_review_summary_text": meta_review_context[
                    "meta_review_summary_text"
                ],
            }
            input_payload = {
                **input_payload,
                "latest_meta_review_id": meta_review_context["latest_meta_review_id"],
                "meta_review_summary": copy.deepcopy(
                    meta_review_context["meta_review_summary"]
                ),
            }
        rendered_prompt = self._render_agent_prompt(agent=agent, variables=variables)
        backend, model = resolve_research_backend_and_model()
        started = time.perf_counter()
        failed_output_payload: dict[str, object] = {}
        try:
            result = await self._llm_gateway.invoke_json(
                request_id=request_id,
                prompt_name=f"hypothesis_multi_agent.{agent.role_name}",
                messages=build_messages_from_prompt(rendered_prompt),
                backend=backend,
                model=model,
                expected_container="dict",
                allow_fallback=False,
            )
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            payload = result.parsed_json
            if not isinstance(payload, dict):
                raise ResearchLLMError(
                    status_code=502,
                    error_code="research.llm_invalid_output",
                    message=f"{agent.role_name} returned non-object JSON",
                    details={
                        "agent_name": agent.role_name,
                        "failure_code": "schema_invalid",
                    },
                )
            failed_output_payload = payload
            self._validate_agent_payload(
                agent_name=agent.role_name, payload=payload, input_payload=input_payload
            )
            transcript = self._store.create_hypothesis_agent_transcript(
                pool_id=pool_id,
                round_id=round_id,
                candidate_id=candidate_id,
                match_id=match_id,
                agent_name=agent.role_name,
                agent_role=agent.role_name,
                prompt_template=agent.prompt_file,
                input_payload={**input_payload, "rendered_prompt": rendered_prompt},
                output_payload=payload,
                provider=result.provider_backend,
                model=result.provider_model,
                token_usage=dict(result.usage or {}),
                latency_ms=elapsed_ms,
                status="completed",
            )
            return payload, transcript
        except ResearchLLMError as exc:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            transcript = self._store.create_hypothesis_agent_transcript(
                pool_id=pool_id,
                round_id=round_id,
                candidate_id=candidate_id,
                match_id=match_id,
                agent_name=agent.role_name,
                agent_role=agent.role_name,
                prompt_template=agent.prompt_file,
                input_payload={**input_payload, "rendered_prompt": rendered_prompt},
                output_payload={
                    "failure_code": exc.details.get("failure_code"),
                    "invalid_output": failed_output_payload,
                },
                provider=backend,
                model=model,
                token_usage={},
                latency_ms=elapsed_ms,
                status="failed",
                error_code=exc.error_code,
                error_message=exc.message,
            )
            exc.details.setdefault("transcript_id", str(transcript["transcript_id"]))
            raise

    def _render_agent_prompt(
        self, *, agent: HypothesisAgentBase, variables: dict[str, object]
    ) -> str:
        schema = self._schema_instruction(agent.role_name)
        prompt = agent._render_prompt(variables).rstrip()
        latest_meta_review_id = str(variables.get("latest_meta_review_id") or "")
        meta_review_summary_text = str(variables.get("meta_review_summary_text") or "")
        if latest_meta_review_id and meta_review_summary_text:
            prompt = (
                f"{prompt}\n\nPRIOR_META_REVIEW_CONTEXT:\n"
                f"latest_meta_review_id={latest_meta_review_id}\n"
                f"compact_summary={meta_review_summary_text}\n"
            )
        return (
            f"{prompt}\n\nOUTPUT_SCHEMA:\n{schema}\n"
        )

    def _schema_instruction(self, agent_name: str) -> str:
        schemas = {
            "supervisor": {
                "decision": "continue|retrieve|evolve|pause|stop|finalize",
                "strategy": "short string",
                "decision_rationale": "string",
                "evidence_coverage_assessment": {},
                "ranking_stability_assessment": {},
                "user_control_state": "none|pause_requested|stop_requested|force_finalize_requested",
                "retrieval_intent": {
                    "needed": "boolean",
                    "query": "string or empty",
                    "evidence_gap": "string or empty",
                    "scope": "string or empty",
                },
                "round_budget": "integer",
                "candidate_budget": "integer",
                "next_actions": ["reflect", "rank", "evolve", "meta_review", "retrieve"],
                "stop_reason": "string or empty",
            },
            "generation": {
                "candidate": {
                    "title": "string",
                    "statement": "string",
                    "hypothesis_level_conclusion": "string",
                    "summary": "string",
                    "rationale": "string",
                    "testability_hint": "string",
                    "novelty_hint": "string",
                    "confidence_hint": "0..1",
                    "suggested_next_steps": ["string"],
                    "source_refs": [{"source_id": "string", "source_span": {}}],
                    "reasoning_chain": {
                        "evidence": ["string"],
                        "assumption": "string",
                        "intermediate_reasoning": ["string"],
                        "conclusion": "string",
                        "validation_need": "string",
                    },
                }
            },
            "reflection": {
                "overall_verdict": "survive|revise|drop",
                "initial_review": {
                    "verdict": "survive|revise|drop",
                    "strengths": ["string"],
                    "weaknesses": ["string"],
                    "findings": ["string"],
                    "recommendation": "string",
                    "evidence_refs": ["string"],
                },
                "literature_grounding_review": {
                    "verdict": "survive|revise|drop",
                    "strengths": ["string"],
                    "weaknesses": ["string"],
                    "findings": ["string"],
                    "recommendation": "string",
                    "evidence_refs": ["string"],
                },
                "deep_assumption_verification": {
                    "verdict": "survive|revise|drop",
                    "strengths": ["string"],
                    "weaknesses": ["string"],
                    "findings": ["string"],
                    "recommendation": "string",
                    "evidence_refs": ["string"],
                },
                "simulation_or_counterexample_review": {
                    "verdict": "survive|revise|drop",
                    "strengths": ["string"],
                    "weaknesses": ["string"],
                    "findings": ["string"],
                    "recommendation": "string",
                    "evidence_refs": ["string"],
                },
                "targeted_node_refs": [],
                "strengths": ["optional legacy string"],
                "weaknesses": ["optional legacy string"],
                "missing_evidence": ["optional legacy string"],
                "testability_issues": ["optional legacy string"],
                "weakest_step_ref": {},
                "recommended_actions": ["optional legacy string"],
                "score_delta": "number",
            },
            "ranking": {
                "winner_candidate_id": "left id, right id, USE_LEFT, or USE_RIGHT",
                "match_reason": "string",
                "debate_transcript": ["non-empty debate turns"],
                "loser_failure_modes": ["non-empty strings"],
                "criterion_scores": {
                    "evidence_strength": "number",
                    "novelty": "number",
                    "testability": "number",
                    "mechanism_specificity": "number",
                    "validation_cost": "number",
                    "contradiction_risk": "number",
                },
                "confidence_in_judgment": "number",
                "match_scheduling_reason": "non-empty string",
                "elo_delta": {},
                "compare_vector": "optional legacy object",
            },
            "evolution": {
                "children": [
                    {
                        "title": "string",
                        "statement": "string",
                        "hypothesis_level_conclusion": "string",
                        "summary": "string",
                        "rationale": "string",
                        "testability_hint": "string",
                        "novelty_hint": "string",
                        "confidence_hint": "0..1",
                        "suggested_next_steps": ["string"],
                        "source_refs": [{"source_id": "string", "source_span": {}}],
                        "reasoning_chain": {
                            "evidence": ["string"],
                            "assumption": "string",
                            "intermediate_reasoning": ["string"],
                            "conclusion": "string",
                            "validation_need": "string",
                        },
                        "lineage": {
                            "parents": ["candidate_id"],
                            "operator": "grounding|feasibility|combination|simplification|out_of_box",
                            "parent_weaknesses": ["string"],
                        },
                        "parent_weaknesses": ["optional string"],
                    }
                ],
                "change_summary": "string",
            },
            "meta_review": {
                "recurring_issues": ["string"],
                "strong_patterns": ["string"],
                "weak_patterns": ["string"],
                "continue_recommendation": "string",
                "stop_recommendation": "string",
                "diversity_assessment": "string",
                "prune_recommendations": ["candidate_id"],
                "generation_feedback": ["string"],
                "reflection_feedback": ["string"],
                "ranking_feedback": ["string"],
                "research_overview": {},
                "stop_or_continue_rationale": "string",
            },
        }
        return json.dumps(schemas.get(agent_name, {}), ensure_ascii=False)

    def _validate_agent_payload(
        self,
        *,
        agent_name: str,
        payload: dict[str, object],
        input_payload: dict[str, object],
    ) -> None:
        if agent_name == "supervisor":
            decision = str(payload.get("decision") or "").strip().lower()
            if decision not in {
                "continue",
                "retrieve",
                "evolve",
                "pause",
                "stop",
                "finalize",
            }:
                self._invalid_agent_output(
                    agent_name,
                    "supervisor decision must be continue|retrieve|evolve|pause|stop|finalize",
                )
            if not str(payload.get("strategy") or "").strip():
                self._invalid_agent_output(agent_name, "supervisor missing strategy")
            if not str(payload.get("decision_rationale") or "").strip():
                self._invalid_agent_output(
                    agent_name, "supervisor missing decision_rationale"
                )
            if not isinstance(payload.get("evidence_coverage_assessment"), dict):
                self._invalid_agent_output(
                    agent_name,
                    "supervisor missing evidence_coverage_assessment",
                )
            if not isinstance(payload.get("ranking_stability_assessment"), dict):
                self._invalid_agent_output(
                    agent_name,
                    "supervisor missing ranking_stability_assessment",
                )
            user_control_state = str(
                payload.get("user_control_state") or ""
            ).strip().lower()
            if user_control_state not in {
                "none",
                "pause_requested",
                "stop_requested",
                "force_finalize_requested",
            }:
                self._invalid_agent_output(
                    agent_name,
                    "supervisor user_control_state must be none|pause_requested|stop_requested|force_finalize_requested",
                )
            retrieval_intent = payload.get("retrieval_intent")
            if not isinstance(retrieval_intent, dict):
                self._invalid_agent_output(
                    agent_name, "supervisor missing retrieval_intent"
                )
            if decision in {"retrieve", "pause", "stop", "finalize"} and not str(
                payload.get("stop_reason") or ""
            ).strip():
                self._invalid_agent_output(
                    agent_name,
                    "supervisor retrieve/pause/stop/finalize decision missing stop_reason",
                )
            actions = payload.get("next_actions")
            if not isinstance(actions, list):
                self._invalid_agent_output(
                    agent_name, "supervisor next_actions must be a list"
                )
            allowed_actions = {"reflect", "rank", "evolve", "meta_review", "retrieve"}
            normalized_actions = {
                str(action).strip() for action in actions if str(action).strip()
            }
            invalid_actions = sorted(normalized_actions - allowed_actions)
            if invalid_actions:
                self._invalid_agent_output(
                    agent_name,
                    "supervisor next_actions contain unsupported actions: "
                    + ",".join(invalid_actions),
                )
            if decision == "continue":
                if not normalized_actions:
                    self._invalid_agent_output(
                        agent_name,
                        "supervisor continue decision must include next_actions",
                    )
                if "meta_review" not in normalized_actions:
                    self._invalid_agent_output(
                        agent_name,
                        "supervisor continue decision must include meta_review",
                    )
                if "retrieve" in normalized_actions:
                    self._invalid_agent_output(
                        agent_name,
                        "supervisor continue decision cannot include retrieve",
                    )
            if decision == "evolve":
                invalid_evolve_actions = sorted(
                    normalized_actions - {"evolve", "meta_review"}
                )
                if invalid_evolve_actions:
                    self._invalid_agent_output(
                        agent_name,
                        "supervisor evolve decision cannot include actions: "
                        + ",".join(invalid_evolve_actions),
                    )
                if not {"evolve", "meta_review"} <= normalized_actions:
                    self._invalid_agent_output(
                        agent_name,
                        "supervisor evolve decision must include evolve and meta_review",
                    )
            if decision == "retrieve":
                invalid_retrieve_actions = sorted(normalized_actions - {"retrieve"})
                if invalid_retrieve_actions:
                    self._invalid_agent_output(
                        agent_name,
                        "supervisor retrieve decision cannot include actions: "
                        + ",".join(invalid_retrieve_actions),
                    )
                if retrieval_intent.get("needed") is not True:
                    self._invalid_agent_output(
                        agent_name,
                        "supervisor retrieve decision requires retrieval_intent.needed=true",
                    )
            if decision in {"pause", "stop", "finalize"} and normalized_actions:
                self._invalid_agent_output(
                    agent_name,
                    f"supervisor {decision} decision cannot include next_actions",
                )
            return
        if agent_name == "generation":
            candidate = payload.get("candidate")
            if not isinstance(candidate, dict):
                self._invalid_agent_output(agent_name, "missing candidate object")
            self._validate_candidate_payload(agent_name=agent_name, payload=candidate)
            return
        if agent_name == "reflection":
            verdict = self._reflection_verdict(payload)
            if verdict not in {"survive", "revise", "drop"}:
                self._invalid_agent_output(
                    agent_name,
                    "reflection overall_verdict or verdict must be survive|revise|drop",
                )
            for stage in self._REFLECTION_STAGES:
                section = payload.get(stage)
                if not isinstance(section, dict):
                    self._invalid_agent_output(
                        agent_name, f"reflection missing {stage}"
                    )
                if not section:
                    self._invalid_agent_output(
                        agent_name, f"reflection {stage} must not be empty"
                    )
                if not self._reflection_section_has_content(section):
                    self._invalid_agent_output(
                        agent_name,
                        f"reflection {stage} lacks substantive review fields",
                    )
            if not isinstance(payload.get("targeted_node_refs"), list):
                self._invalid_agent_output(
                    agent_name, "reflection targeted_node_refs must be a list"
                )
            if verdict == "survive" and not any(
                self._reflection_section_has_grounding(payload[stage])
                for stage in self._REFLECTION_STAGES
                if isinstance(payload.get(stage), dict)
            ):
                self._invalid_agent_output(
                    agent_name,
                    "reflection survive verdict requires grounded strengths or evidence refs in staged reviews",
                )
            return
        if agent_name == "ranking":
            raw_winner = str(payload.get("winner_candidate_id") or "").strip()
            if not raw_winner:
                self._invalid_agent_output(agent_name, "missing winner_candidate_id")
            if not str(payload.get("match_reason") or "").strip():
                self._invalid_agent_output(agent_name, "missing match_reason")
            self._validate_ranking_artifact(payload)
            left = input_payload.get("left_candidate")
            right = input_payload.get("right_candidate")
            if not isinstance(left, dict) or not isinstance(right, dict):
                self._invalid_agent_output(
                    agent_name, "ranking requires left and right candidates"
                )
            left_id = str(left.get("candidate_id") or "")
            right_id = str(right.get("candidate_id") or "")
            winner_id = self._resolve_winner_id(
                raw=raw_winner, left_id=left_id, right_id=right_id
            )
            if winner_id not in {left_id, right_id}:
                self._invalid_agent_output(
                    agent_name, "winner_candidate_id must reference compared candidate"
                )
            return
        if agent_name == "evolution":
            children = payload.get("children")
            if not isinstance(children, list):
                self._invalid_agent_output(agent_name, "children must be a list")
            parent_candidates = input_payload.get("parent_candidates")
            if not isinstance(parent_candidates, list) or not parent_candidates:
                self._invalid_agent_output(
                    agent_name, "evolution requires parent_candidates"
                )
            allowed_parent_ids = {
                str(item.get("candidate_id") or "")
                for item in parent_candidates
                if isinstance(item, dict) and str(item.get("candidate_id") or "")
            }
            for child in children:
                if not isinstance(child, dict):
                    self._invalid_agent_output(agent_name, "child must be an object")
                self._validate_candidate_payload(agent_name=agent_name, payload=child)
                lineage = child.get("lineage")
                if not isinstance(lineage, dict):
                    self._invalid_agent_output(
                        agent_name, "evolution child must include lineage"
                    )
                operator = str(lineage.get("operator") or "").strip()
                if not operator:
                    self._invalid_agent_output(
                        agent_name,
                        "evolution child lineage must include operator",
                    )
                if operator not in self._EVOLUTION_OPERATORS:
                    self._invalid_agent_output(
                        agent_name,
                        "evolution child lineage operator must be one of "
                        + "|".join(sorted(self._EVOLUTION_OPERATORS)),
                    )
                parents = self._string_list(lineage.get("parents"))
                if not parents:
                    self._invalid_agent_output(
                        agent_name,
                        "evolution child lineage parents must reference parent candidates",
                    )
                if any(parent_id not in allowed_parent_ids for parent_id in parents):
                    self._invalid_agent_output(
                        agent_name,
                        "evolution child lineage parents must come from parent_candidates",
                    )
                if not self._evolution_parent_weaknesses(child):
                    self._invalid_agent_output(
                        agent_name,
                        "evolution child must include parent_weaknesses",
                    )
            return
        if agent_name == "meta_review":
            for field in (
                "generation_feedback",
                "reflection_feedback",
                "ranking_feedback",
            ):
                if field not in payload or not isinstance(payload.get(field), list):
                    self._invalid_agent_output(
                        agent_name, f"meta_review must include {field}"
                    )
            if "research_overview" not in payload or not isinstance(
                payload.get("research_overview"), dict
            ):
                self._invalid_agent_output(
                    agent_name, "meta_review must include research_overview"
                )
            if not str(payload.get("stop_or_continue_rationale") or "").strip():
                self._invalid_agent_output(
                    agent_name,
                    "meta_review must include stop_or_continue_rationale",
                )

    def _reflection_verdict(self, reflection: dict[str, object]) -> str:
        return str(reflection.get("overall_verdict") or "").strip().lower()

    def _reflection_section_has_content(self, section: dict[str, object]) -> bool:
        return any(
            self._has_content(section.get(field))
            for field in self._REFLECTION_SECTION_FIELDS
        )

    def _reflection_section_has_grounding(self, section: dict[str, object]) -> bool:
        for field in ("evidence_refs", "source_refs", "grounding", "grounded_claims"):
            if self._has_content(section.get(field)):
                return True
        return any(
            "evidence" in str(key).lower()
            and "missing" not in str(key).lower()
            and "gap" not in str(key).lower()
            and self._has_content(value)
            for key, value in section.items()
        )

    def _has_content(self, value: object) -> bool:
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, list):
            return any(self._has_content(item) for item in value)
        if isinstance(value, dict):
            return any(self._has_content(item) for item in value.values())
        return value is not None

    def _reflection_flat_list(
        self, reflection: dict[str, object], *fields: str
    ) -> list[str]:
        values: list[str] = []
        for field in fields:
            values.extend(self._string_list(reflection.get(field)))
        for stage in self._REFLECTION_STAGES:
            section = reflection.get(stage)
            if not isinstance(section, dict):
                continue
            for field in fields:
                raw = section.get(field)
                if isinstance(raw, str) and raw.strip():
                    values.append(raw.strip())
                else:
                    values.extend(self._string_list(raw))
        return values

    def _reflection_recommended_actions(
        self, reflection: dict[str, object]
    ) -> list[str]:
        actions = self._reflection_flat_list(reflection, "recommended_actions")
        for stage in self._REFLECTION_STAGES:
            section = reflection.get(stage)
            if isinstance(section, dict):
                recommendation = str(section.get("recommendation") or "").strip()
                if recommendation:
                    actions.append(recommendation)
        return actions

    def _reflection_weakest_step_ref(
        self, reflection: dict[str, object]
    ) -> dict[str, object]:
        weakest = reflection.get("weakest_step_ref")
        if isinstance(weakest, dict):
            return weakest
        targeted = reflection.get("targeted_node_refs")
        if isinstance(targeted, list) and targeted:
            return {"targeted_node_refs": targeted}
        return {}

    def _validate_candidate_payload(
        self, *, agent_name: str, payload: dict[str, object]
    ) -> None:
        required_text = [
            "title",
            "statement",
            "hypothesis_level_conclusion",
            "summary",
            "rationale",
            "testability_hint",
            "novelty_hint",
        ]
        for field in required_text:
            if not str(payload.get(field) or "").strip():
                self._invalid_agent_output(agent_name, f"candidate missing {field}")
        source_refs = payload.get("source_refs")
        if not isinstance(source_refs, list) or not source_refs:
            self._invalid_agent_output(agent_name, "candidate must include source_refs")
        for source_ref in source_refs:
            if not isinstance(source_ref, dict):
                self._invalid_agent_output(agent_name, "source_ref must be an object")
            if not str(source_ref.get("source_id") or "").strip():
                self._invalid_agent_output(agent_name, "source_ref missing source_id")
            if not isinstance(source_ref.get("source_span"), dict):
                self._invalid_agent_output(agent_name, "source_ref missing source_span")
        chain = payload.get("reasoning_chain")
        if not isinstance(chain, dict):
            self._invalid_agent_output(
                agent_name, "candidate must include reasoning_chain"
            )
        if not self._string_list(chain.get("evidence")):
            self._invalid_agent_output(agent_name, "reasoning_chain missing evidence")
        if not str(chain.get("assumption") or "").strip():
            self._invalid_agent_output(agent_name, "reasoning_chain missing assumption")
        if not self._string_list(chain.get("intermediate_reasoning")):
            self._invalid_agent_output(
                agent_name, "reasoning_chain missing intermediate_reasoning"
            )
        if not str(chain.get("conclusion") or "").strip():
            self._invalid_agent_output(agent_name, "reasoning_chain missing conclusion")
        if not str(chain.get("validation_need") or "").strip():
            self._invalid_agent_output(
                agent_name, "reasoning_chain missing validation_need"
            )

    def _invalid_agent_output(self, agent_name: str, reason: str) -> None:
        failure_code = self._failure_code_for_invalid_output(reason)
        raise ResearchLLMError(
            status_code=502,
            error_code="research.llm_invalid_output",
            message=f"{agent_name} agent returned invalid output: {reason}",
            details={
                "agent_name": agent_name,
                "reason": reason,
                "failure_code": failure_code,
            },
        )

    def _failure_code_for_invalid_output(self, reason: str) -> str:
        lowered = reason.lower()
        if "evidence" in lowered and (
            "missing" in lowered or "empty" in lowered or "insufficient" in lowered
        ):
            return "evidence_empty"
        if "citation" in lowered and "unverified" in lowered:
            return "citation_unverified"
        if "winner_candidate_id" in lowered or "no_decision" in lowered:
            return "ranking_no_decision"
        if "retrieve" in lowered or "retrieval" in lowered:
            return "tool_failed"
        if "user" in lowered and ("stop" in lowered or "pause" in lowered):
            return "user_stopped"
        return "schema_invalid"

    def _validate_ranking_artifact(self, payload: dict[str, object]) -> None:
        if not self._non_empty_list(payload.get("debate_transcript")):
            self._invalid_agent_output("ranking", "missing debate_transcript")
        if not self._non_empty_list(payload.get("loser_failure_modes")):
            self._invalid_agent_output("ranking", "missing loser_failure_modes")
        if not str(payload.get("match_scheduling_reason") or "").strip():
            self._invalid_agent_output("ranking", "missing match_scheduling_reason")
        if not self._is_number(payload.get("confidence_in_judgment")):
            self._invalid_agent_output("ranking", "missing confidence_in_judgment")
        if not isinstance(payload.get("elo_delta"), dict):
            self._invalid_agent_output("ranking", "missing elo_delta")
        self._validate_ranking_criterion_scores(payload.get("criterion_scores"))

    def _validate_ranking_criterion_scores(self, value: object) -> None:
        if not isinstance(value, dict):
            self._invalid_agent_output("ranking", "missing criterion_scores")
        required_fields = {
            "evidence_strength",
            "novelty",
            "testability",
            "mechanism_specificity",
            "validation_cost",
            "contradiction_risk",
        }
        actual_fields = set(value)
        missing = sorted(required_fields - actual_fields)
        if missing:
            self._invalid_agent_output(
                "ranking",
                "criterion_scores missing fields: " + ",".join(missing),
            )
        extra = sorted(actual_fields - required_fields)
        if extra:
            self._invalid_agent_output(
                "ranking",
                "criterion_scores extra fields: " + ",".join(extra),
            )
        non_numeric = sorted(
            field for field in required_fields if not self._is_number(value.get(field))
        )
        if non_numeric:
            self._invalid_agent_output(
                "ranking",
                "criterion_scores non-numeric fields: " + ",".join(non_numeric),
            )

    def _non_empty_list(self, value: object) -> bool:
        return isinstance(value, list) and any(str(item).strip() for item in value)

    def _is_number(self, value: object) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _evidence_refs(self, value: object) -> list[object]:
        if not isinstance(value, list):
            return []
        return [item for item in value if str(item).strip()]

    def _materialize_candidate(
        self,
        *,
        pool_id: str,
        generated: dict[str, object],
        generation_transcript_id: str,
        origin_type: str,
        origin_round: int,
        lineage: dict[str, object],
        parent_tree_node_id: str,
        trigger_refs: list[dict[str, object]],
        related_object_ids: list[dict[str, str]],
        minimum_validation_action: dict[str, object],
        weakening_signal: dict[str, object],
        novelty_typing: str,
    ) -> dict[str, object]:
        pool = self._require_pool(pool_id)
        payload = generated.get("candidate", {})
        if not isinstance(payload, dict):
            raise ResearchLLMError(
                status_code=502,
                error_code="research.llm_invalid_output",
                message="generation agent output missing candidate object",
                details={"pool_id": pool_id},
            )
        reasoning_chain = self._candidate_reasoning_chain(
            payload=payload,
            generated=generated,
            transcript_id=generation_transcript_id,
            origin_type=origin_type,
        )
        tree_node = self._store.create_hypothesis_search_tree_node(
            pool_id=pool_id,
            parent_tree_node_id=parent_tree_node_id,
            candidate_id=None,
            node_role="candidate",
            depth=1,
            visits=0,
            mean_reward=0.0,
            uct_score=0.0,
            status="alive",
        )
        candidate = self._store.create_hypothesis_candidate(
            pool_id=pool_id,
            workspace_id=str(pool["workspace_id"]),
            title=str(payload["title"]).strip(),
            statement=str(payload["statement"]).strip(),
            summary=str(payload["summary"]).strip(),
            rationale=str(payload["rationale"]).strip(),
            trigger_refs=copy.deepcopy(trigger_refs),
            related_object_ids=copy.deepcopy(related_object_ids),
            reasoning_chain=reasoning_chain,
            minimum_validation_action=copy.deepcopy(minimum_validation_action),
            weakening_signal=copy.deepcopy(weakening_signal),
            novelty_typing=novelty_typing,
            status="alive",
            origin_type=origin_type,
            origin_round_number=origin_round,
            elo_rating=self._ELO_BASE,
            survival_score=0.5,
            lineage=copy.deepcopy(lineage),
        )
        candidate_id = str(candidate["candidate_id"])
        self._store.update_hypothesis_search_tree_node(
            tree_node_id=str(tree_node["tree_node_id"]), status="alive"
        )
        self._store.create_hypothesis_search_tree_edge(
            pool_id=pool_id,
            from_tree_node_id=parent_tree_node_id,
            to_tree_node_id=str(tree_node["tree_node_id"]),
            edge_type=origin_type,
        )
        # Store the node id in the candidate's reasoning chain because the table
        # intentionally has no dedicated search_tree_node_id column.
        reasoning_chain["search_tree_node_id"] = str(tree_node["tree_node_id"])
        self._store.update_hypothesis_candidate(
            candidate_id=candidate_id, reasoning_chain=reasoning_chain
        )
        self._store.update_hypothesis_search_tree_node(
            tree_node_id=str(tree_node["tree_node_id"]), status="alive"
        )
        return self._require_candidate(candidate_id)

    def _candidate_reasoning_chain(
        self,
        *,
        payload: dict[str, object],
        generated: dict[str, object],
        transcript_id: str,
        origin_type: str,
    ) -> dict[str, object]:
        chain = payload.get("reasoning_chain")
        if not isinstance(chain, dict):
            self._invalid_agent_output(
                str(generated.get("agent_role") or origin_type),
                "candidate must include reasoning_chain",
            )
        reasoning_chain = {
            "evidence": self._string_list(chain.get("evidence")),
            "assumption": str(chain.get("assumption") or ""),
            "intermediate_reasoning": self._string_list(
                chain.get("intermediate_reasoning")
            ),
            "conclusion": str(chain.get("conclusion") or ""),
            "validation_need": str(chain.get("validation_need") or ""),
        }
        result = {
            "agent_trace": generated,
            "generation_transcript_id": transcript_id,
            "origin_type": origin_type,
            "hypothesis_statement": str(payload["statement"]),
            "hypothesis_level_conclusion": str(payload["hypothesis_level_conclusion"]),
            "reasoning_chain": reasoning_chain,
            "source_refs": self._source_refs(payload),
            "required_validation": str(payload["testability_hint"]),
            "suggested_next_steps": self._string_list(
                payload.get("suggested_next_steps")
            ),
            "confidence_hint": self._float(payload.get("confidence_hint"), default=0.5),
            "review_status": "pending",
            "review_history": [],
            "retrieval_origin": payload.get("retrieval_origin") or "uploaded",
        }
        result["reasoning_nodes"] = self._reasoning_nodes(result)
        return result

    def _persist_reflection(
        self,
        *,
        candidate: dict[str, object],
        round_id: str,
        reflection: dict[str, object],
        transcript_id: str,
    ) -> None:
        verdict = self._reflection_verdict(reflection) or "revise"
        if verdict not in {"survive", "revise", "drop"}:
            verdict = "revise"
        review = self._store.create_hypothesis_review(
            pool_id=str(candidate["pool_id"]),
            round_id=round_id,
            candidate_id=str(candidate["candidate_id"]),
            review_type=verdict,
            strengths=self._reflection_flat_list(reflection, "strengths"),
            weaknesses=self._reflection_flat_list(reflection, "weaknesses"),
            missing_evidence=self._reflection_flat_list(
                reflection, "missing_evidence", "evidence_gaps"
            ),
            testability_issues=self._reflection_flat_list(
                reflection, "testability_issues"
            ),
            weakest_step_ref=self._reflection_weakest_step_ref(reflection),
            recommended_actions=self._reflection_recommended_actions(reflection),
            trace_refs={"transcript_id": transcript_id},
        )
        chain = dict(candidate.get("reasoning_chain") or {})
        history = list(chain.get("review_history") or [])
        history.append(
            {
                "review_id": review["review_id"],
                "round_id": round_id,
                "transcript_id": transcript_id,
                "verdict": verdict,
                "reflection": reflection,
            }
        )
        chain["review_status"] = verdict
        chain["review_history"] = history
        chain["last_reflection"] = reflection
        chain["requires_recheck"] = False
        chain["requires_rerank"] = verdict == "survive"
        chain["last_recheck_round_id"] = round_id
        score = max(
            0.0,
            min(
                1.0,
                float(candidate.get("survival_score") or 0.0)
                + self._float(reflection.get("score_delta"), default=0.0),
            ),
        )
        status = "alive" if verdict == "survive" else "pruned"
        if verdict == "drop":
            status = "rejected"
        self._store.update_hypothesis_candidate(
            candidate_id=str(candidate["candidate_id"]),
            status=status,
            survival_score=score,
            reasoning_chain=chain,
        )

    def _persist_ranking_match(
        self,
        *,
        pool_id: str,
        round_id: str,
        left: dict[str, object],
        right: dict[str, object],
        ranking: dict[str, object],
        transcript_id: str,
    ) -> dict[str, object]:
        left_id = str(left["candidate_id"])
        right_id = str(right["candidate_id"])
        winner_id = self._resolve_winner_id(
            raw=ranking.get("winner_candidate_id"), left_id=left_id, right_id=right_id
        )
        loser_id = right_id if winner_id == left_id else left_id
        left_before = float(left.get("elo_rating") or self._ELO_BASE)
        right_before = float(right.get("elo_rating") or self._ELO_BASE)
        left_after, right_after = self._elo(
            left_before, right_before, left_wins=(winner_id == left_id)
        )
        computed_elo_delta = {
            "left": left_after - left_before,
            "right": right_after - right_before,
        }
        self._store.update_hypothesis_candidate(
            candidate_id=left_id, elo_rating=left_after
        )
        self._store.update_hypothesis_candidate(
            candidate_id=right_id, elo_rating=right_after
        )
        self._mark_candidates_reranked(
            candidate_ids=[left_id, right_id], round_id=round_id
        )
        compare_vector = ranking.get("compare_vector")
        if not isinstance(compare_vector, dict):
            compare_vector = {}
        else:
            compare_vector = copy.deepcopy(compare_vector)
        criterion_scores = ranking.get("criterion_scores")
        if isinstance(criterion_scores, dict):
            compare_vector["criterion_scores"] = copy.deepcopy(criterion_scores)
            for key, value in criterion_scores.items():
                compare_vector.setdefault(str(key), value)
        for key in (
            "debate_transcript",
            "loser_failure_modes",
            "match_scheduling_reason",
            "confidence_in_judgment",
        ):
            compare_vector[key] = copy.deepcopy(ranking.get(key))
        compare_vector["elo_delta"] = copy.deepcopy(computed_elo_delta)

        judge_trace: dict[str, object] = {
            "ranking_agent": copy.deepcopy(ranking),
            "transcript_id": transcript_id,
            "computed_elo_delta": copy.deepcopy(computed_elo_delta),
        }
        llm_elo_delta = ranking.get("elo_delta")
        if isinstance(llm_elo_delta, dict) and llm_elo_delta != computed_elo_delta:
            judge_trace["llm_elo_delta_mismatch"] = {
                "llm_provided": copy.deepcopy(llm_elo_delta),
                "computed": copy.deepcopy(computed_elo_delta),
            }
        return self._store.create_hypothesis_match(
            pool_id=pool_id,
            round_id=round_id,
            left_candidate_id=left_id,
            right_candidate_id=right_id,
            winner_candidate_id=winner_id,
            loser_candidate_id=loser_id,
            match_reason=str(ranking.get("match_reason") or ""),
            compare_vector=compare_vector,
            left_elo_before=left_before,
            right_elo_before=right_before,
            left_elo_after=left_after,
            right_elo_after=right_after,
            judge_trace=judge_trace,
        )

    def _mark_candidates_reranked(
        self, *, candidate_ids: list[str], round_id: str
    ) -> None:
        for candidate_id in candidate_ids:
            candidate = self._store.get_hypothesis_candidate(candidate_id)
            if candidate is None:
                continue
            chain = dict(candidate.get("reasoning_chain") or {})
            chain["requires_rerank"] = False
            chain["last_ranking_round_id"] = round_id
            self._store.update_hypothesis_candidate(
                candidate_id=candidate_id, reasoning_chain=chain
            )

    def _persist_evolution_children(
        self,
        *,
        pool: dict[str, object],
        round_id: str,
        round_number: int,
        evolution: dict[str, object],
        transcript_id: str,
        parent_candidates: list[dict[str, object]],
    ) -> int:
        children = evolution.get("children")
        if not isinstance(children, list):
            return 0
        root_tree_node_id = str(
            (pool.get("reasoning_subgraph") or {}).get("root_tree_node_id") or ""
        )
        parent_ids = [str(item["candidate_id"]) for item in parent_candidates]
        created_count = 0
        for child in children:
            if not isinstance(child, dict):
                continue
            child_payload = copy.deepcopy(child)
            lineage = dict(child_payload.get("lineage") or {})
            lineage.pop("mode", None)
            lineage["parents"] = self._string_list(lineage.get("parents"))
            lineage["operator"] = str(lineage.get("operator") or "").strip()
            lineage["parent_weaknesses"] = self._evolution_parent_weaknesses(
                child_payload
            )
            child_payload["lineage"] = lineage
            agent_trace = copy.deepcopy(evolution)
            agent_trace["children"] = [copy.deepcopy(child_payload)]
            agent_trace["candidate"] = child_payload
            created = self._materialize_candidate(
                pool_id=str(pool["pool_id"]),
                generated=agent_trace,
                generation_transcript_id=transcript_id,
                origin_type="evolution",
                origin_round=round_number,
                lineage=lineage,
                parent_tree_node_id=root_tree_node_id,
                trigger_refs=list(pool.get("trigger_refs") or []),
                related_object_ids=(
                    list(parent_candidates[0].get("related_object_ids") or [])
                    if parent_candidates
                    else []
                ),
                minimum_validation_action=(
                    dict(parent_candidates[0].get("minimum_validation_action") or {})
                    if parent_candidates
                    else {}
                ),
                weakening_signal=(
                    dict(parent_candidates[0].get("weakening_signal") or {})
                    if parent_candidates
                    else {}
                ),
                novelty_typing=(
                    str(
                        parent_candidates[0].get("novelty_typing")
                        or "literature_frontier"
                    )
                    if parent_candidates
                    else "literature_frontier"
                ),
            )
            source_id = lineage["parents"][0] if lineage["parents"] else parent_ids[0]
            self._store.create_hypothesis_evolution(
                pool_id=str(pool["pool_id"]),
                round_id=round_id,
                source_candidate_id=source_id,
                new_candidate_id=str(created["candidate_id"]),
                evolution_mode=str(lineage["operator"]),
                driving_review_ids=[],
                change_summary=str(evolution.get("change_summary") or ""),
                preserved_claims=[],
                modified_claims=[],
                trace_refs={
                    "transcript_id": transcript_id,
                    "operator": lineage["operator"],
                    "parents": copy.deepcopy(lineage["parents"]),
                    "parent_weaknesses": copy.deepcopy(
                        lineage["parent_weaknesses"]
                    ),
                },
            )
            created_count += 1
        return created_count

    def _record_meta_review_in_pool(
        self,
        *,
        pool_id: str,
        meta_review_id: str,
        transcript_id: str,
        meta_review: dict[str, object],
    ) -> None:
        pool = self._require_pool(pool_id)
        reasoning_subgraph = dict(pool.get("reasoning_subgraph") or {})
        reasoning_subgraph["latest_meta_review_id"] = meta_review_id
        reasoning_subgraph["latest_meta_review_transcript_id"] = transcript_id
        summary = self._compact_meta_review_summary(meta_review)
        summary["latest_meta_review_id"] = meta_review_id
        summary["transcript_id"] = transcript_id
        reasoning_subgraph["latest_meta_review_summary"] = summary
        self._store.update_hypothesis_pool(
            pool_id=pool_id, reasoning_subgraph=reasoning_subgraph
        )

    def _latest_meta_review_context(
        self, *, pool_id: str
    ) -> dict[str, object] | None:
        pool = self._store.get_hypothesis_pool(pool_id)
        if pool is None:
            return None
        reasoning_subgraph = pool.get("reasoning_subgraph")
        if not isinstance(reasoning_subgraph, dict):
            return None
        latest_meta_review_id = str(
            reasoning_subgraph.get("latest_meta_review_id") or ""
        ).strip()
        summary = reasoning_subgraph.get("latest_meta_review_summary")
        if not latest_meta_review_id or not isinstance(summary, dict):
            return None
        summary = copy.deepcopy(summary)
        summary["latest_meta_review_id"] = latest_meta_review_id
        return {
            "latest_meta_review_id": latest_meta_review_id,
            "meta_review_summary": summary,
            "meta_review_summary_text": self._meta_review_summary_text(summary),
        }

    def _compact_meta_review_summary(
        self, meta_review: dict[str, object]
    ) -> dict[str, object]:
        return {
            "generation_feedback": copy.deepcopy(
                meta_review.get("generation_feedback") or []
            ),
            "reflection_feedback": copy.deepcopy(
                meta_review.get("reflection_feedback") or []
            ),
            "ranking_feedback": copy.deepcopy(
                meta_review.get("ranking_feedback") or []
            ),
            "research_overview": copy.deepcopy(
                meta_review.get("research_overview") or {}
            ),
            "stop_or_continue_rationale": str(
                meta_review.get("stop_or_continue_rationale") or ""
            ),
        }

    def _meta_review_summary_text(self, summary: dict[str, object]) -> str:
        parts: list[str] = []
        for field in (
            "generation_feedback",
            "reflection_feedback",
            "ranking_feedback",
        ):
            parts.extend(self._string_list(summary.get(field)))
        rationale = str(summary.get("stop_or_continue_rationale") or "").strip()
        if rationale:
            parts.append(rationale)
        return " ".join(parts)

    def _record_round_supervisor_in_pool(
        self,
        *,
        pool_id: str,
        round_id: str,
        transcript_id: str,
        supervisor: dict[str, object],
    ) -> None:
        pool = self._require_pool(pool_id)
        reasoning_subgraph = dict(pool.get("reasoning_subgraph") or {})
        history = list(reasoning_subgraph.get("round_supervisor_history") or [])
        history.append(
            {
                "round_id": round_id,
                "transcript_id": transcript_id,
                "supervisor": copy.deepcopy(supervisor),
            }
        )
        reasoning_subgraph["round_supervisor_history"] = history
        reasoning_subgraph["latest_round_supervisor"] = copy.deepcopy(supervisor)
        reasoning_subgraph["latest_supervisor_decision"] = supervisor.get("decision")
        reasoning_subgraph["latest_round_supervisor_transcript_id"] = transcript_id
        self._store.update_hypothesis_pool(
            pool_id=pool_id, reasoning_subgraph=reasoning_subgraph
        )

    def _persist_proximity(self, *, pool_id: str) -> None:
        proximity = self._proximity.build_edges(
            candidates=self._alive(pool_id), top_n=12
        )
        persisted_edges: list[dict[str, object]] = []
        for edge in proximity.get("edges", []) if isinstance(proximity, dict) else []:
            if not isinstance(edge, dict):
                continue
            record = self._store.create_hypothesis_proximity_edge(
                pool_id=pool_id,
                from_candidate_id=str(edge.get("from_candidate_id") or ""),
                to_candidate_id=str(edge.get("to_candidate_id") or ""),
                similarity_score=self._float(edge.get("similarity_score"), default=0.0),
                shared_trigger_ratio=self._float(
                    edge.get("shared_trigger_ratio"), default=0.0
                ),
                shared_object_ratio=self._float(
                    edge.get("shared_object_ratio"), default=0.0
                ),
                shared_chain_overlap=self._float(
                    edge.get("shared_chain_overlap"), default=0.0
                ),
                trace_refs=edge,
            )
            trace = copy.deepcopy(edge)
            trace["edge_id"] = str((record or {}).get("edge_id") or "")
            persisted_edges.append(trace)
        pool = self._require_pool(pool_id)
        reasoning_subgraph = dict(pool.get("reasoning_subgraph") or {})
        reasoning_subgraph["latest_proximity_trace"] = {
            "service_name": "proximity",
            "edges": persisted_edges,
        }
        self._store.update_hypothesis_pool(
            pool_id=pool_id, reasoning_subgraph=reasoning_subgraph
        )

    def _prune(self, *, pool_id: str, recommendations: object) -> None:
        wanted = {
            str(item).strip()
            for item in (recommendations if isinstance(recommendations, list) else [])
            if str(item).strip()
        }
        for candidate_id in wanted:
            if self._store.get_hypothesis_candidate(candidate_id) is not None:
                self._store.update_hypothesis_candidate(
                    candidate_id=candidate_id, status="pruned"
                )

    def _alive(self, pool_id: str) -> list[dict[str, object]]:
        return self._store.list_hypothesis_candidates(pool_id=pool_id, status="alive")

    def _pairings(
        self, candidates: list[dict[str, object]], *, max_matches: int
    ) -> list[tuple[str, str]]:
        if len(candidates) < 2:
            return []
        proximity = self._proximity.build_edges(candidates=candidates, top_n=10_000)
        candidate_ids = {str(candidate["candidate_id"]) for candidate in candidates}
        pairs: list[tuple[str, str]] = []
        used: set[str] = set()
        for edge in proximity.get("edges", []) if isinstance(proximity, dict) else []:
            left_id = str(edge.get("from_candidate_id") or "")
            right_id = str(edge.get("to_candidate_id") or "")
            if left_id not in candidate_ids or right_id not in candidate_ids:
                continue
            if left_id in used or right_id in used:
                continue
            pairs.append((left_id, right_id))
            used.update({left_id, right_id})
            if len(pairs) >= max_matches:
                break
        ordered = sorted(
            [
                candidate
                for candidate in candidates
                if str(candidate["candidate_id"]) not in used
            ],
            key=lambda c: float(c.get("elo_rating") or 0.0),
            reverse=True,
        )
        idx = 0
        while idx + 1 < len(ordered) and len(pairs) < max_matches:
            pairs.append((str(ordered[idx]["candidate_id"]), str(ordered[idx + 1]["candidate_id"])))
            idx += 2
        return pairs

    def _select_diverse_frontier(
        self, *, pool_id: str, ranked: list[dict[str, object]], top_k: int
    ) -> list[dict[str, object]]:
        selected: list[dict[str, object]] = []
        exclusions: list[dict[str, object]] = []
        for candidate in ranked:
            exclusion_reason = ""
            for kept in selected:
                edge = self._proximity.build_edge(left=kept, right=candidate)
                exclusion_reason = str(edge.get("frontier_exclusion_reason") or "")
                if exclusion_reason:
                    exclusions.append(
                        {
                            "candidate_id": str(candidate["candidate_id"]),
                            "kept_candidate_id": str(kept["candidate_id"]),
                            "reason": exclusion_reason,
                            "proximity": edge,
                        }
                    )
                    break
            if exclusion_reason:
                continue
            signature = {
                "mechanism_signature": self._proximity.mechanism_signature(candidate),
                "source_ids": self._proximity.source_ids(candidate),
                "validation_path": self._proximity.validation_path(candidate),
            }
            chain = dict(candidate.get("reasoning_chain") or {})
            chain["diversity_signature"] = signature
            self._store.update_hypothesis_candidate(
                candidate_id=str(candidate["candidate_id"]), reasoning_chain=chain
            )
            refreshed = self._store.get_hypothesis_candidate(str(candidate["candidate_id"]))
            selected.append(refreshed or candidate)
            if len(selected) >= top_k:
                break
        pool = self._require_pool(pool_id)
        reasoning_subgraph = dict(pool.get("reasoning_subgraph") or {})
        reasoning_subgraph["frontier_selection_trace"] = {
            "strategy": "quality_under_diversity_constraint",
            "selected_candidate_ids": [str(item["candidate_id"]) for item in selected],
            "exclusions": exclusions,
        }
        self._store.update_hypothesis_pool(
            pool_id=pool_id, reasoning_subgraph=reasoning_subgraph
        )
        return selected

    def _elo(
        self, left: float, right: float, *, left_wins: bool
    ) -> tuple[float, float]:
        expected_left = 1.0 / (1.0 + math.pow(10.0, (right - left) / 400.0))
        expected_right = 1.0 - expected_left
        left_score = 1.0 if left_wins else 0.0
        right_score = 0.0 if left_wins else 1.0
        return (
            left + self._ELO_K * (left_score - expected_left),
            right + self._ELO_K * (right_score - expected_right),
        )

    def _resolve_winner_id(self, *, raw: object, left_id: str, right_id: str) -> str:
        text = str(raw or "").strip()
        normalized = text.lower()
        if text == left_id or normalized in {"left", "use_left", "left_candidate"}:
            return left_id
        if text == right_id or normalized in {"right", "use_right", "right_candidate"}:
            return right_id
        raise ResearchLLMError(
            status_code=502,
            error_code="research.llm_invalid_output",
            message="ranking agent returned an unknown winner_candidate_id",
            details={
                "winner_candidate_id": text,
                "left_candidate_id": left_id,
                "right_candidate_id": right_id,
                "failure_code": "ranking_no_decision",
            },
        )

    def _require_pool(self, pool_id: str) -> dict[str, object]:
        pool = self._store.get_hypothesis_pool(pool_id)
        if pool is None:
            raise ValueError(f"pool {pool_id} not found")
        return pool

    def _require_candidate(self, candidate_id: str) -> dict[str, object]:
        candidate = self._store.get_hypothesis_candidate(candidate_id)
        if candidate is None:
            raise ValueError(f"candidate {candidate_id} not found")
        return candidate

    def _pool_public(self, pool: dict[str, object]) -> dict[str, object]:
        return copy.deepcopy(pool)

    def _candidate_public(self, candidate: dict[str, object]) -> dict[str, object]:
        public = copy.deepcopy(candidate)
        chain = public.get("reasoning_chain")
        if isinstance(chain, dict):
            public["testability_hint"] = chain.get("required_validation", "")
            agent_trace = (
                chain.get("agent_trace", {})
                if isinstance(chain.get("agent_trace"), dict)
                else {}
            )
            agent_candidate = (
                agent_trace.get("candidate", {})
                if isinstance(agent_trace.get("candidate"), dict)
                else {}
            )
            public["novelty_hint"] = str(agent_candidate.get("novelty_hint") or "")
            public["suggested_next_steps"] = chain.get("suggested_next_steps", [])
            public["confidence_hint"] = chain.get("confidence_hint", 0.5)
            public["source_refs"] = chain.get("source_refs", [])
            public["search_tree_node_id"] = chain.get("search_tree_node_id")
        return public

    def _review_verdict(self, candidate: dict[str, object]) -> str:
        chain = candidate.get("reasoning_chain")
        if isinstance(chain, dict):
            verdict = str(chain.get("review_status") or "").strip().lower()
            if verdict:
                return verdict
        return "pending"

    def _source_refs(self, payload: dict[str, object]) -> list[dict[str, object]]:
        raw = payload.get("source_refs")
        if not isinstance(raw, list):
            return []
        return [item for item in raw if isinstance(item, dict)]

    def _trigger_types(self, trigger_refs: list[dict[str, object]]) -> list[str]:
        return sorted(
            {
                str(item.get("trigger_type", "")).strip()
                for item in trigger_refs
                if str(item.get("trigger_type", "")).strip()
            }
        )

    def _string_list(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def _evolution_parent_weaknesses(self, child: dict[str, object]) -> list[str]:
        lineage = child.get("lineage")
        if isinstance(lineage, dict):
            values = self._string_list(lineage.get("parent_weaknesses"))
            if values:
                return values
        return self._string_list(child.get("parent_weaknesses"))

    def _evolution_parent_prompt_candidates(
        self, parents: list[dict[str, object]]
    ) -> list[dict[str, object]]:
        sanitized = copy.deepcopy(parents)
        for parent in sanitized:
            lineage = parent.get("lineage")
            if isinstance(lineage, dict):
                lineage.pop("mode", None)
        return sanitized

    def _float(self, value: object, *, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
