from __future__ import annotations

import copy
import math
import random
from threading import RLock

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


class HypothesisMultiAgentOrchestrator:
    _ELO_BASE = 1200.0
    _ELO_K = 24.0
    _UCT_C = 1.41

    def __init__(self, store: ResearchApiStateStore) -> None:
        self._store = store
        self._lock = RLock()
        self._rng = random.Random(20260414)
        self._supervisor = SupervisorAgent()
        self._generation = GenerationAgent()
        self._reflection = ReflectionAgent()
        self._ranking = RankingAgent()
        self._evolution = EvolutionAgent()
        self._meta_review = MetaReviewAgent()
        self._proximity = ProximityAgent()
        self._pools: dict[str, dict[str, object]] = {}
        self._candidates: dict[str, dict[str, dict[str, object]]] = {}
        self._rounds: dict[str, list[dict[str, object]]] = {}
        self._matches: dict[str, dict[str, object]] = {}
        self._nodes: dict[str, dict[str, object]] = {}
        self._children: dict[str, list[str]] = {}
        self._root_node: dict[str, str] = {}

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
        supervisor_plan = self._supervisor.build_pool_plan(
            workspace_id=workspace_id,
            research_goal=research_goal,
            trigger_refs=trigger_refs,
            top_k=top_k,
            max_rounds=max_rounds,
            candidate_count=candidate_count,
            constraints=constraints,
            preference_profile=preference_profile,
        )
        with self._lock:
            pool_id = self._store.gen_id("pool")
            now = self._store.now()
            root_id = self._create_node(
                pool_id=pool_id,
                parent_id=None,
                candidate_id=None,
                node_role="root",
                depth=0,
            )
            self._root_node[pool_id] = root_id
            self._pools[pool_id] = {
                "pool_id": pool_id,
                "workspace_id": workspace_id,
                "status": "running",
                "orchestration_mode": orchestration_mode,
                "trigger_refs": copy.deepcopy(trigger_refs),
                "top_k": top_k,
                "max_rounds": max_rounds,
                "candidate_count": candidate_count,
                "current_round_number": 0,
                "research_goal": research_goal,
                "reasoning_subgraph": {
                    "root_tree_node_id": root_id,
                    "latest_meta_review_id": None,
                    "supervisor_plan": supervisor_plan,
                    "request_id": request_id,
                },
                "constraints": dict(constraints),
                "preference_profile": dict(preference_profile),
                "created_at": now,
                "updated_at": now,
                "_novelty_typing": novelty_typing,
                "_related_object_ids": copy.deepcopy(related_object_ids),
                "_minimum_validation_action": copy.deepcopy(minimum_validation_action),
                "_weakening_signal": copy.deepcopy(weakening_signal),
            }
            self._candidates[pool_id] = {}
            self._rounds[pool_id] = []
            for seed_index in range(max(2, candidate_count)):
                generated = self._generation.propose_candidate(
                    workspace_id=workspace_id,
                    research_goal=research_goal,
                    trigger_refs=trigger_refs,
                    seed_index=seed_index,
                    supervisor_plan=supervisor_plan,
                )
                self._materialize_candidate(
                    pool_id=pool_id,
                    generated=generated,
                    origin_type="generation",
                    origin_round=0,
                    lineage={"parents": [], "mode": "seed"},
                    parent_node_id=root_id,
                )
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
        with self._lock:
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
            round_id = self._store.gen_id("round")
            round_record = {
                "round_id": round_id,
                "pool_id": pool_id,
                "round_number": round_number,
                "status": "running",
                "start_reason": start_reason,
                "stop_reason": None,
                "generation_count": 0,
                "review_count": 0,
                "match_count": 0,
                "evolution_count": 0,
                "meta_review_id": None,
                "created_at": self._store.now(),
                "completed_at": None,
            }
            self._rounds[pool_id].append(round_record)
            selected_node_id = self._select_node(pool_id)

            alive = self._alive(pool_id)
            for candidate in alive:
                reflection = self._reflection.reflect_candidate(
                    candidate=candidate,
                    round_number=round_number,
                )
                snapshot = reflection.get("reflection", {})
                candidate["last_reflection"] = snapshot if isinstance(snapshot, dict) else {}
                candidate["survival_score"] = max(
                    0.0,
                    min(
                        1.0,
                        float(candidate.get("survival_score") or 0.0)
                        + float(candidate.get("last_reflection", {}).get("score_delta") or 0.0),
                    ),
                )
                candidate["reasoning_chain"]["last_reflection"] = candidate["last_reflection"]
                candidate["updated_at"] = self._store.now()
            round_record["review_count"] = len(alive)

            matches = []
            for left_id, right_id in self._pairings(alive, max_matches=max(1, max_matches)):
                left = self._candidates[pool_id][left_id]
                right = self._candidates[pool_id][right_id]
                ranking = self._ranking.compare_pair(left_candidate=left, right_candidate=right)
                winner_id = str(ranking.get("winner_candidate_id", left_id))
                if winner_id not in {left_id, right_id}:
                    winner_id = left_id
                loser_id = right_id if winner_id == left_id else left_id
                left_before = float(left.get("elo_rating") or self._ELO_BASE)
                right_before = float(right.get("elo_rating") or self._ELO_BASE)
                left_after, right_after = self._elo(left_before, right_before, left_wins=(winner_id == left_id))
                left["elo_rating"] = left_after
                right["elo_rating"] = right_after
                match_id = self._store.gen_id("match")
                match_record = {
                    "match_id": match_id,
                    "pool_id": pool_id,
                    "round_id": round_id,
                    "left_candidate_id": left_id,
                    "right_candidate_id": right_id,
                    "winner_candidate_id": winner_id,
                    "loser_candidate_id": loser_id,
                    "match_reason": str(ranking.get("match_reason", "")),
                    "compare_vector": ranking.get("compare_vector", {}),
                    "left_elo_before": left_before,
                    "right_elo_before": right_before,
                    "left_elo_after": left_after,
                    "right_elo_after": right_after,
                    "judge_trace": {"ranking_agent": ranking, "request_id": request_id},
                    "created_at": self._store.now(),
                }
                self._matches[match_id] = match_record
                matches.append(match_record)
                self._backprop(pool_id, winner_id, reward=1.0)
                self._backprop(pool_id, loser_id, reward=-0.35)
            round_record["match_count"] = len(matches)

            ranked = sorted(self._alive(pool_id), key=lambda c: float(c.get("elo_rating") or 0.0), reverse=True)
            parents = ranked[: max(2, min(4, len(ranked)))]
            evolution = self._evolution.evolve_candidates(
                pool_id=pool_id,
                round_number=round_number,
                parent_candidates=parents,
                target_children=max(1, len(parents) // 2),
            )
            children = evolution.get("children", [])
            if isinstance(children, list):
                for child in children:
                    if not isinstance(child, dict):
                        continue
                    self._materialize_candidate(
                        pool_id=pool_id,
                        generated={"candidate": child, **evolution},
                        origin_type="evolution",
                        origin_round=round_number,
                        lineage=child.get("lineage", {}),
                        parent_node_id=selected_node_id,
                    )
            round_record["generation_count"] = len(children) if isinstance(children, list) else 0
            round_record["evolution_count"] = round_record["generation_count"]

            current_alive = self._alive(pool_id)
            meta = self._meta_review.review_round(
                pool_id=pool_id,
                round_number=round_number,
                candidates=current_alive,
                matches=matches,
                evolution_count=round_record["evolution_count"],
            )
            meta_id = self._store.gen_id("meta_review")
            round_record["meta_review_id"] = meta_id
            pool["reasoning_subgraph"]["latest_meta_review_id"] = meta_id

            self._prune(
                pool_id=pool_id,
                recommendations=meta.get("prune_recommendations", []),
            )
            self._prune_nodes(pool_id)
            proximity = self._proximity.build_edges(candidates=self._alive(pool_id), top_n=12)
            pool["reasoning_subgraph"]["proximity_edges"] = proximity.get("edges", [])

            pool["current_round_number"] = round_number
            pool["updated_at"] = self._store.now()
            if round_number >= int(pool["max_rounds"]):
                pool["status"] = "stopped"
            round_record["status"] = "completed"
            round_record["stop_reason"] = "single_round_complete"
            round_record["completed_at"] = self._store.now()
            return copy.deepcopy(round_record)

    async def finalize_pool(self, *, pool_id: str, request_id: str) -> list[dict[str, object]]:
        with self._lock:
            pool = self._require_pool(pool_id)
            ranked = sorted(self._alive(pool_id), key=lambda c: float(c.get("elo_rating") or 0.0), reverse=True)
            if not ranked:
                ranked = sorted(self._candidates[pool_id].values(), key=lambda c: float(c.get("elo_rating") or 0.0), reverse=True)
            selected = ranked[: max(1, int(pool["top_k"]))]
            now = self._store.now()
            for candidate in self._candidates[pool_id].values():
                candidate["status"] = "finalized" if candidate in selected else "pruned"
                candidate["updated_at"] = now
            pool["status"] = "finalized"
            pool["updated_at"] = now
            pool["reasoning_subgraph"]["finalize_request_id"] = request_id
            return [copy.deepcopy(item) for item in selected]

    def get_pool(self, *, pool_id: str) -> dict[str, object] | None:
        with self._lock:
            pool = self._pools.get(pool_id)
            if pool is None:
                return None
            return self._pool_public(pool)

    def get_candidate(self, *, candidate_id: str) -> dict[str, object] | None:
        with self._lock:
            for pool_candidates in self._candidates.values():
                candidate = pool_candidates.get(candidate_id)
                if candidate is not None:
                    return self._candidate_public(candidate)
            return None

    def control_pool(self, *, pool_id: str, request_id: str, action: str) -> dict[str, object]:
        with self._lock:
            pool = self._require_pool(pool_id)
            status = str(pool.get("status") or "running")
            if status in {"stopped", "finalized", "failed", "cancelled"}:
                raise ValueError(f"pool {pool_id} is terminal")

            reasoning_subgraph = pool.get("reasoning_subgraph", {})
            if not isinstance(reasoning_subgraph, dict):
                reasoning_subgraph = {}
            control = reasoning_subgraph.get("control", {})
            if not isinstance(control, dict):
                control = {}

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
            pool["reasoning_subgraph"] = reasoning_subgraph
            pool["status"] = status
            pool["updated_at"] = self._store.now()
            return self._pool_public(pool)

    def patch_candidate_reasoning_chain(
        self,
        *,
        candidate_id: str,
        reasoning_chain: dict[str, object],
        reset_review_state: bool,
    ) -> dict[str, object] | None:
        with self._lock:
            candidate: dict[str, object] | None = None
            for pool_candidates in self._candidates.values():
                if candidate_id in pool_candidates:
                    candidate = pool_candidates[candidate_id]
                    break
            if candidate is None:
                return None

            existing_chain = candidate.get("reasoning_chain", {})
            if not isinstance(existing_chain, dict):
                existing_chain = {}
            next_chain = dict(existing_chain)
            next_chain.update(reasoning_chain if isinstance(reasoning_chain, dict) else {})
            if reset_review_state:
                next_chain["review_status"] = "pending"
                next_chain["review_history"] = []
                next_chain["revise_count"] = 0
            next_chain["edited_by_user"] = True
            next_chain["edited_at"] = self._store.now().isoformat()

            candidate["reasoning_chain"] = next_chain
            candidate["status"] = "alive"
            statement = str(next_chain.get("hypothesis_statement") or "").strip()
            summary = str(next_chain.get("hypothesis_level_conclusion") or "").strip()
            if statement:
                candidate["statement"] = statement
            if summary:
                candidate["summary"] = summary
            candidate["updated_at"] = self._store.now()
            return self._candidate_public(candidate)

    def list_pool_candidates(self, *, pool_id: str) -> list[dict[str, object]]:
        with self._lock:
            candidates = list(self._candidates.get(pool_id, {}).values())
            candidates.sort(key=lambda c: float(c.get("elo_rating") or 0.0), reverse=True)
            return [self._candidate_public(item) for item in candidates]

    def list_pool_rounds(self, *, pool_id: str) -> list[dict[str, object]]:
        with self._lock:
            return [copy.deepcopy(item) for item in self._rounds.get(pool_id, [])]

    def get_match(self, *, match_id: str) -> dict[str, object] | None:
        with self._lock:
            match = self._matches.get(match_id)
            return copy.deepcopy(match) if match is not None else None

    def get_search_tree_node(self, *, tree_node_id: str) -> dict[str, object] | None:
        with self._lock:
            node = self._nodes.get(tree_node_id)
            if node is None:
                return None
            return self._node_public(node)

    def _require_pool(self, pool_id: str) -> dict[str, object]:
        pool = self._pools.get(pool_id)
        if pool is None:
            raise ValueError(f"pool {pool_id} not found")
        return pool

    def _create_node(self, *, pool_id: str, parent_id: str | None, candidate_id: str | None, node_role: str, depth: int) -> str:
        node_id = self._store.gen_id("tree")
        node = {
            "tree_node_id": node_id,
            "pool_id": pool_id,
            "parent_tree_node_id": parent_id,
            "candidate_id": candidate_id,
            "node_role": node_role,
            "depth": depth,
            "visits": 0,
            "reward_sum": 0.0,
            "mean_reward": 0.0,
            "uct_score": 0.0,
            "status": "alive",
            "created_at": self._store.now(),
            "updated_at": self._store.now(),
        }
        self._nodes[node_id] = node
        self._children.setdefault(node_id, [])
        if parent_id:
            self._children.setdefault(parent_id, []).append(node_id)
        return node_id

    def _materialize_candidate(self, *, pool_id: str, generated: dict[str, object], origin_type: str, origin_round: int, lineage: dict[str, object], parent_node_id: str) -> None:
        pool = self._pools[pool_id]
        payload = generated.get("candidate", {})
        if not isinstance(payload, dict):
            payload = {}
        candidate_id = self._store.gen_id("candidate")
        node_id = self._create_node(
            pool_id=pool_id,
            parent_id=parent_node_id,
            candidate_id=candidate_id,
            node_role="candidate",
            depth=int(self._nodes[parent_node_id]["depth"]) + 1,
        )
        self._candidates[pool_id][candidate_id] = {
            "candidate_id": candidate_id,
            "pool_id": pool_id,
            "workspace_id": pool["workspace_id"],
            "title": str(payload.get("title", "")).strip() or f"Candidate {candidate_id}",
            "statement": str(payload.get("statement", "")).strip() or "No statement",
            "summary": str(payload.get("summary", "")).strip() or "No summary",
            "rationale": str(payload.get("rationale", "")).strip() or "No rationale",
            "testability_hint": str(payload.get("testability_hint", "")).strip(),
            "novelty_hint": str(payload.get("novelty_hint", "")).strip(),
            "suggested_next_steps": [str(s).strip() for s in payload.get("suggested_next_steps", []) if str(s).strip()] if isinstance(payload.get("suggested_next_steps"), list) else [],
            "confidence_hint": float(payload.get("confidence_hint") or 0.5),
            "trigger_refs": copy.deepcopy(pool["trigger_refs"]),
            "related_object_ids": copy.deepcopy(pool["_related_object_ids"]),
            "reasoning_chain": {"agent_trace": generated},
            "minimum_validation_action": copy.deepcopy(pool["_minimum_validation_action"]),
            "weakening_signal": copy.deepcopy(pool["_weakening_signal"]),
            "novelty_typing": str(pool.get("_novelty_typing", "incremental")),
            "status": "alive",
            "origin_type": origin_type,
            "origin_round_number": origin_round,
            "elo_rating": self._ELO_BASE + self._rng.uniform(-5.0, 5.0),
            "survival_score": 0.5,
            "lineage": copy.deepcopy(lineage) if isinstance(lineage, dict) else {},
            "search_tree_node_id": node_id,
            "created_at": self._store.now(),
            "updated_at": self._store.now(),
        }

    def _alive(self, pool_id: str) -> list[dict[str, object]]:
        return [item for item in self._candidates.get(pool_id, {}).values() if str(item.get("status")) == "alive"]

    def _pairings(self, candidates: list[dict[str, object]], *, max_matches: int) -> list[tuple[str, str]]:
        ordered = sorted(candidates, key=lambda c: float(c.get("elo_rating") or 0.0), reverse=True)
        pairs: list[tuple[str, str]] = []
        idx = 0
        while idx + 1 < len(ordered) and len(pairs) < max_matches:
            pairs.append((str(ordered[idx]["candidate_id"]), str(ordered[idx + 1]["candidate_id"])))
            idx += 2
        return pairs

    def _elo(self, left: float, right: float, *, left_wins: bool) -> tuple[float, float]:
        expected_left = 1.0 / (1.0 + math.pow(10.0, (right - left) / 400.0))
        expected_right = 1.0 - expected_left
        left_score = 1.0 if left_wins else 0.0
        right_score = 0.0 if left_wins else 1.0
        return (
            left + self._ELO_K * (left_score - expected_left),
            right + self._ELO_K * (right_score - expected_right),
        )

    def _select_node(self, pool_id: str) -> str:
        current = self._root_node[pool_id]
        while True:
            children = [self._nodes[cid] for cid in self._children.get(current, []) if self._nodes[cid]["status"] == "alive"]
            if not children:
                return current
            unvisited = [node for node in children if int(node.get("visits", 0)) == 0]
            if unvisited:
                return str(unvisited[0]["tree_node_id"])
            parent_visits = max(1, int(self._nodes[current].get("visits", 1)))
            current = str(max(children, key=lambda n: self._uct(n, parent_visits))["tree_node_id"])

    def _uct(self, node: dict[str, object], parent_visits: int) -> float:
        visits = max(1, int(node.get("visits", 0)))
        mean = float(node.get("mean_reward", 0.0))
        score = mean + self._UCT_C * math.sqrt(math.log(parent_visits + 1) / visits)
        node["uct_score"] = score
        return score

    def _backprop(self, pool_id: str, candidate_id: str, *, reward: float) -> None:
        candidate = self._candidates.get(pool_id, {}).get(candidate_id)
        if candidate is None:
            return
        node_id = str(candidate.get("search_tree_node_id", ""))
        while node_id:
            node = self._nodes.get(node_id)
            if node is None:
                break
            node["visits"] = int(node.get("visits", 0)) + 1
            node["reward_sum"] = float(node.get("reward_sum", 0.0)) + reward
            node["mean_reward"] = float(node["reward_sum"]) / float(node["visits"])
            node["updated_at"] = self._store.now()
            parent_id = node.get("parent_tree_node_id")
            node_id = str(parent_id) if parent_id else ""

    def _prune(self, *, pool_id: str, recommendations: object) -> None:
        wanted = {str(item).strip() for item in (recommendations if isinstance(recommendations, list) else []) if str(item).strip()}
        alive = sorted(self._alive(pool_id), key=lambda c: float(c.get("elo_rating") or 0.0))
        for item in alive:
            cid = str(item.get("candidate_id", ""))
            prune = cid in wanted or (
                len(alive) > int(self._pools[pool_id]["top_k"]) * 2
                and float(item.get("elo_rating") or 0.0) < self._ELO_BASE - 30
            )
            if prune:
                item["status"] = "pruned"
                item["updated_at"] = self._store.now()
                node_id = str(item.get("search_tree_node_id", ""))
                if node_id in self._nodes:
                    self._nodes[node_id]["status"] = "pruned"
                    self._nodes[node_id]["updated_at"] = self._store.now()

    def _prune_nodes(self, pool_id: str) -> None:
        for node in self._nodes.values():
            if str(node.get("pool_id")) != pool_id or str(node.get("node_role")) == "root":
                continue
            if int(node.get("visits", 0)) >= 2 and float(node.get("mean_reward", 0.0)) < -0.25:
                node["status"] = "pruned"
                node["updated_at"] = self._store.now()

    def _pool_public(self, pool: dict[str, object]) -> dict[str, object]:
        return {
            "pool_id": pool["pool_id"],
            "workspace_id": pool["workspace_id"],
            "status": pool["status"],
            "orchestration_mode": pool["orchestration_mode"],
            "trigger_refs": copy.deepcopy(pool["trigger_refs"]),
            "top_k": pool["top_k"],
            "max_rounds": pool["max_rounds"],
            "candidate_count": pool["candidate_count"],
            "current_round_number": pool["current_round_number"],
            "research_goal": pool["research_goal"],
            "reasoning_subgraph": copy.deepcopy(pool["reasoning_subgraph"]),
            "constraints": copy.deepcopy(pool["constraints"]),
            "preference_profile": copy.deepcopy(pool["preference_profile"]),
            "created_at": pool["created_at"],
            "updated_at": pool["updated_at"],
        }

    def _candidate_public(self, candidate: dict[str, object]) -> dict[str, object]:
        public = copy.deepcopy(candidate)
        public.pop("search_tree_node_id", None)
        return public

    def _node_public(self, node: dict[str, object]) -> dict[str, object]:
        child_edges = []
        for child_id in self._children.get(str(node["tree_node_id"]), []):
            child = self._nodes.get(child_id)
            if child is None:
                continue
            child_edges.append(
                {
                    "child_tree_node_id": child["tree_node_id"],
                    "candidate_id": child["candidate_id"],
                    "status": child["status"],
                    "mean_reward": float(child["mean_reward"]),
                    "visits": int(child["visits"]),
                }
            )
        result = copy.deepcopy(node)
        result["child_edges"] = child_edges
        return result
