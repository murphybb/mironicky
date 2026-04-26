from __future__ import annotations

import copy
import json

import pytest

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.services.hypothesis_multi_agent_orchestrator import (
    HypothesisMultiAgentOrchestrator,
)
from research_layer.services.hypothesis_agents import (
    EvolutionAgent,
    GenerationAgent,
    MetaReviewAgent,
    RankingAgent,
    ReflectionAgent,
    SupervisorAgent,
)
from research_layer.services.hypothesis_service import (
    HypothesisService,
    HypothesisServiceError,
)
from research_layer.services.llm_gateway import ResearchLLMError
from research_layer.services.llm_trace import LLMCallResult
from research_layer.services.retrieval_views_service import RetrievalServiceError


def _parent_candidates_from_messages(messages: object) -> list[dict[str, object]]:
    rendered_prompt = "\n".join(
        str(getattr(message, "content", message))
        for message in (messages if isinstance(messages, list) else [])
    )
    parent_candidates_json = rendered_prompt.split("parent_candidates=", 1)[1].split(
        "\ntarget_children=", 1
    )[0]
    return json.loads(parent_candidates_json)


def _build_store(tmp_path) -> ResearchApiStateStore:
    return ResearchApiStateStore(
        db_path=str(tmp_path / "hypothesis_multi_agent_real_execution.sqlite3")
    )


def _trigger_refs() -> list[dict[str, object]]:
    return [
        {
            "trigger_id": "trigger_uploaded_claim_1",
            "trigger_type": "weak_support",
            "workspace_id": "ws_real_agents",
            "object_ref_type": "source_claim",
            "object_ref_id": "claim_1",
            "summary": "Uploaded literature says brand reputation depends on alumni network strength.",
            "trace_refs": {
                "source_id": "source_1",
                "source_span": {"page": 2, "start": 40, "end": 110},
                "evidence_refs": ["claim_1"],
            },
            "related_object_ids": [{"object_type": "source", "object_id": "source_1"}],
            "metrics": {},
        },
        {
            "trigger_id": "trigger_uploaded_claim_2",
            "trigger_type": "gap",
            "workspace_id": "ws_real_agents",
            "object_ref_type": "source_claim",
            "object_ref_id": "claim_2",
            "summary": "Uploaded literature leaves a gap around public sentiment recovery mechanisms.",
            "trace_refs": {
                "source_id": "source_2",
                "source_span": {"page": 5, "start": 10, "end": 92},
                "evidence_refs": ["claim_2"],
            },
            "related_object_ids": [{"object_type": "source", "object_id": "source_2"}],
            "metrics": {},
        },
    ]


class RecordingGateway:
    def __init__(
        self, *, fail_agent: str | None = None, invalid_agent: str | None = None
    ) -> None:
        self.fail_agent = fail_agent
        self.invalid_agent = invalid_agent
        self.calls: list[dict[str, object]] = []

    async def invoke_json(self, **kwargs: object) -> LLMCallResult:
        prompt_name = str(kwargs["prompt_name"])
        agent_name = prompt_name.rsplit(".", 1)[-1]
        self.calls.append(kwargs)
        if self.fail_agent == agent_name:
            raise ResearchLLMError(
                status_code=502,
                error_code="research.llm_failed",
                message=f"{agent_name} failed",
                details={"agent_name": agent_name},
            )
        parsed = (
            {}
            if self.invalid_agent == agent_name
            else _agent_payload(agent_name, len(self.calls))
        )
        if agent_name == "evolution" and parsed.get("children"):
            parent_ids = [
                str(item["candidate_id"])
                for item in _parent_candidates_from_messages(kwargs.get("messages", []))
            ]
            child = dict(parsed["children"][0])
            lineage = dict(child.get("lineage") or {})
            lineage["parents"] = parent_ids[:2]
            child["lineage"] = lineage
            parsed = {**parsed, "children": [child]}
        return LLMCallResult(
            provider_backend="openai",
            provider_model="gpt-4.1-mini",
            request_id=str(kwargs["request_id"]),
            llm_response_id=f"resp_{agent_name}_{len(self.calls)}",
            usage={"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
            raw_text="{}",
            parsed_json=parsed,
            fallback_used=False,
            degraded=False,
            degraded_reason=None,
        )


class OverridePayloadGateway(RecordingGateway):
    def __init__(self, overrides: dict[str, dict[str, object]]) -> None:
        super().__init__()
        self.overrides = overrides

    async def invoke_json(self, **kwargs: object) -> LLMCallResult:
        prompt_name = str(kwargs["prompt_name"])
        agent_name = prompt_name.rsplit(".", 1)[-1]
        if agent_name not in self.overrides:
            return await super().invoke_json(**kwargs)
        self.calls.append(kwargs)
        return LLMCallResult(
            provider_backend="openai",
            provider_model="gpt-4.1-mini",
            request_id=str(kwargs["request_id"]),
            llm_response_id=f"resp_{agent_name}_{len(self.calls)}",
            usage={"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
            raw_text="{}",
            parsed_json=self.overrides[agent_name],
            fallback_used=False,
            degraded=False,
            degraded_reason=None,
        )


class DynamicEvolutionGateway(RecordingGateway):
    def __init__(self, payload_factory) -> None:
        super().__init__()
        self.payload_factory = payload_factory

    async def invoke_json(self, **kwargs: object) -> LLMCallResult:
        prompt_name = str(kwargs["prompt_name"])
        agent_name = prompt_name.rsplit(".", 1)[-1]
        if agent_name != "evolution":
            return await super().invoke_json(**kwargs)
        input_payload = {
            "parent_candidates": _parent_candidates_from_messages(
                kwargs.get("messages", [])
            )
        }
        kwargs["input_payload"] = input_payload
        self.calls.append(kwargs)
        return LLMCallResult(
            provider_backend="openai",
            provider_model="gpt-4.1-mini",
            request_id=str(kwargs["request_id"]),
            llm_response_id=f"resp_{agent_name}_{len(self.calls)}",
            usage={"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
            raw_text="{}",
            parsed_json=self.payload_factory(input_payload),
            fallback_used=False,
            degraded=False,
            degraded_reason=None,
        )


class SequencedReflectionGateway(RecordingGateway):
    def __init__(self, verdicts: list[str]) -> None:
        super().__init__()
        self.verdicts = verdicts
        self.reflection_calls = 0

    async def invoke_json(self, **kwargs: object) -> LLMCallResult:
        prompt_name = str(kwargs["prompt_name"])
        agent_name = prompt_name.rsplit(".", 1)[-1]
        if agent_name != "reflection":
            return await super().invoke_json(**kwargs)
        verdict = self.verdicts[self.reflection_calls % len(self.verdicts)]
        self.reflection_calls += 1
        self.calls.append(kwargs)
        return LLMCallResult(
            provider_backend="openai",
            provider_model="gpt-4.1-mini",
            request_id=str(kwargs["request_id"]),
            llm_response_id=f"resp_reflection_{len(self.calls)}",
            usage={"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
            raw_text="{}",
            parsed_json=_reflection_payload(overall_verdict=verdict),
            fallback_used=False,
            degraded=False,
            degraded_reason=None,
        )


class StopRoundGateway(RecordingGateway):
    def __init__(self) -> None:
        super().__init__()
        self.supervisor_calls = 0

    async def invoke_json(self, **kwargs: object) -> LLMCallResult:
        prompt_name = str(kwargs["prompt_name"])
        agent_name = prompt_name.rsplit(".", 1)[-1]
        if agent_name != "supervisor":
            return await super().invoke_json(**kwargs)
        self.supervisor_calls += 1
        self.calls.append(kwargs)
        parsed = (
            _agent_payload("supervisor", len(self.calls))
            if self.supervisor_calls == 1
            else _supervisor_artifact(
                decision="stop",
                next_actions=[],
                stop_reason="reviewer_test_stop",
            )
        )
        return LLMCallResult(
            provider_backend="openai",
            provider_model="gpt-4.1-mini",
            request_id=str(kwargs["request_id"]),
            llm_response_id=f"resp_supervisor_{len(self.calls)}",
            usage={"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
            raw_text="{}",
            parsed_json=parsed,
            fallback_used=False,
            degraded=False,
            degraded_reason=None,
        )


def _supervisor_artifact(
    *,
    decision: str,
    next_actions: list[str],
    stop_reason: str = "",
    user_control_state: str = "none",
    retrieval_needed: bool = False,
) -> dict[str, object]:
    return {
        "decision": decision,
        "strategy": f"{decision}_strategy",
        "decision_rationale": f"{decision} decision is supported by current evidence and controls.",
        "evidence_coverage_assessment": {
            "covered": ["uploaded source claims"],
            "gaps": ["direct retrieval gap"] if retrieval_needed else [],
            "coverage_level": "partial" if retrieval_needed else "sufficient",
        },
        "ranking_stability_assessment": {
            "stable": decision in {"pause", "stop", "finalize"},
            "reason": "round branch contract test",
        },
        "user_control_state": user_control_state,
        "retrieval_intent": {
            "needed": retrieval_needed,
            "query": "alumni activation sentiment recovery evidence"
            if retrieval_needed
            else "",
            "evidence_gap": "missing direct retrieval evidence"
            if retrieval_needed
            else "",
            "scope": "uploaded_and_supplemental" if retrieval_needed else "none",
        },
        "round_budget": 1,
        "candidate_budget": 2,
        "next_actions": next_actions,
        "stop_reason": stop_reason,
    }


class RoundSupervisorDecisionGateway(RecordingGateway):
    def __init__(self, round_supervisor_payload: dict[str, object]) -> None:
        super().__init__()
        self.round_supervisor_payload = round_supervisor_payload
        self.supervisor_calls = 0

    async def invoke_json(self, **kwargs: object) -> LLMCallResult:
        prompt_name = str(kwargs["prompt_name"])
        agent_name = prompt_name.rsplit(".", 1)[-1]
        if agent_name != "supervisor":
            return await super().invoke_json(**kwargs)
        self.supervisor_calls += 1
        self.calls.append(kwargs)
        parsed = (
            _agent_payload("supervisor", len(self.calls))
            if self.supervisor_calls == 1
            else self.round_supervisor_payload
        )
        return LLMCallResult(
            provider_backend="openai",
            provider_model="gpt-4.1-mini",
            request_id=str(kwargs["request_id"]),
            llm_response_id=f"resp_supervisor_{len(self.calls)}",
            usage={"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
            raw_text="{}",
            parsed_json=parsed,
            fallback_used=False,
            degraded=False,
            degraded_reason=None,
        )


class InitialSupervisorDecisionGateway(RecordingGateway):
    def __init__(self, initial_supervisor_payload: dict[str, object]) -> None:
        super().__init__()
        self.initial_supervisor_payload = initial_supervisor_payload
        self.supervisor_calls = 0

    async def invoke_json(self, **kwargs: object) -> LLMCallResult:
        prompt_name = str(kwargs["prompt_name"])
        agent_name = prompt_name.rsplit(".", 1)[-1]
        if agent_name != "supervisor":
            return await super().invoke_json(**kwargs)
        self.supervisor_calls += 1
        self.calls.append(kwargs)
        parsed = (
            self.initial_supervisor_payload
            if self.supervisor_calls == 1
            else _agent_payload("supervisor", len(self.calls))
        )
        return LLMCallResult(
            provider_backend="openai",
            provider_model="gpt-4.1-mini",
            request_id=str(kwargs["request_id"]),
            llm_response_id=f"resp_supervisor_{len(self.calls)}",
            usage={"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
            raw_text="{}",
            parsed_json=parsed,
            fallback_used=False,
            degraded=False,
            degraded_reason=None,
        )


class InvalidRankingGateway(RecordingGateway):
    async def invoke_json(self, **kwargs: object) -> LLMCallResult:
        prompt_name = str(kwargs["prompt_name"])
        agent_name = prompt_name.rsplit(".", 1)[-1]
        if agent_name != "ranking":
            return await super().invoke_json(**kwargs)
        self.calls.append(kwargs)
        return LLMCallResult(
            provider_backend="openai",
            provider_model="gpt-4.1-mini",
            request_id=str(kwargs["request_id"]),
            llm_response_id=f"resp_ranking_{len(self.calls)}",
            usage={"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
            raw_text="{}",
            parsed_json={
                "winner_candidate_id": "not_a_compared_candidate",
                "match_reason": "Invalid winner should fail before match persistence.",
                "compare_vector": {},
            },
            fallback_used=False,
            degraded=False,
            degraded_reason=None,
        )


class InvalidSupervisorGateway(RecordingGateway):
    async def invoke_json(self, **kwargs: object) -> LLMCallResult:
        prompt_name = str(kwargs["prompt_name"])
        agent_name = prompt_name.rsplit(".", 1)[-1]
        if agent_name != "supervisor":
            return await super().invoke_json(**kwargs)
        self.calls.append(kwargs)
        return LLMCallResult(
            provider_backend="openai",
            provider_model="gpt-4.1-mini",
            request_id=str(kwargs["request_id"]),
            llm_response_id=f"resp_supervisor_{len(self.calls)}",
            usage={"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
            raw_text="{}",
            parsed_json={
                "decision": "continue",
                "strategy": "invalid_action_plan",
                "round_budget": 1,
                "candidate_budget": 1,
                "next_actions": ["retrieve"],
                "stop_reason": "",
            },
            fallback_used=False,
            degraded=False,
            degraded_reason=None,
        )


class MissingSupervisorActionsGateway(RecordingGateway):
    async def invoke_json(self, **kwargs: object) -> LLMCallResult:
        prompt_name = str(kwargs["prompt_name"])
        agent_name = prompt_name.rsplit(".", 1)[-1]
        if agent_name != "supervisor":
            return await super().invoke_json(**kwargs)
        self.calls.append(kwargs)
        return LLMCallResult(
            provider_backend="openai",
            provider_model="gpt-4.1-mini",
            request_id=str(kwargs["request_id"]),
            llm_response_id=f"resp_supervisor_{len(self.calls)}",
            usage={"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
            raw_text="{}",
            parsed_json={
                "decision": "continue",
                "strategy": "missing_actions_plan",
                "round_budget": 1,
                "candidate_budget": 1,
                "stop_reason": "",
            },
            fallback_used=False,
            degraded=False,
            degraded_reason=None,
        )


def _debate_grade_ranking_payload() -> dict[str, object]:
    return {
        "winner_candidate_id": "USE_LEFT",
        "match_reason": "Left has stronger source grounding and a cheaper validation path.",
        "debate_transcript": [
            {
                "speaker": "left_advocate",
                "claim": "Left ties alumni activation to cited source evidence and a mediation test.",
            },
            {
                "speaker": "right_critic",
                "claim": "Right is less specific about how the mechanism would be measured.",
            },
            {
                "speaker": "judge",
                "claim": "The deciding edge is stronger evidence plus lower validation cost.",
            },
        ],
        "loser_failure_modes": [
            "Right has weaker operationalization of the mechanism.",
            "Right needs more retrieval before a fair Elo-moving comparison.",
        ],
        "criterion_scores": {
            "evidence_strength": 0.72,
            "novelty": 0.57,
            "testability": 0.68,
            "mechanism_specificity": 0.64,
            "validation_cost": 0.38,
            "contradiction_risk": 0.21,
        },
        "confidence_in_judgment": 0.74,
        "match_scheduling_reason": "Adjacent survivors share evidence but differ in validation cost.",
        "elo_delta": {
            "left": 99.0,
            "right": -99.0,
            "reason": "LLM proposal should be recorded as non-authoritative.",
        },
    }


def _flat_compare_vector_only_ranking_payload() -> dict[str, object]:
    return {
        "winner_candidate_id": "USE_LEFT",
        "match_reason": "Legacy flat compare_vector is not enough for Task6.",
        "compare_vector": {
            "evidence_strength": 0.7,
            "novelty": 0.55,
            "testability": 0.65,
            "mechanism_specificity": 0.6,
            "validation_cost": 0.45,
            "contradiction_risk": 0.25,
        },
    }


def _orchestrator_with_ranking_payload(
    tmp_path, payload: dict[str, object]
) -> tuple[
    ResearchApiStateStore,
    OverridePayloadGateway,
    HypothesisMultiAgentOrchestrator,
]:
    store = _build_store(tmp_path)
    gateway = OverridePayloadGateway({"ranking": payload})
    orchestrator = HypothesisMultiAgentOrchestrator(store, llm_gateway=gateway)
    return store, gateway, orchestrator


async def _create_default_pool(
    orchestrator: HypothesisMultiAgentOrchestrator, *, request_id: str
) -> dict[str, object]:
    return await orchestrator.create_pool(
        workspace_id="ws_real_agents",
        request_id=request_id,
        trigger_refs=_trigger_refs(),
        research_goal="Find new hypotheses from uploaded literature only.",
        top_k=2,
        max_rounds=2,
        candidate_count=4,
        constraints={},
        preference_profile={},
        novelty_typing="literature_frontier",
        related_object_ids=[{"object_type": "source", "object_id": "source_1"}],
        minimum_validation_action={"validation_id": "val_1", "method": "mediation"},
        weakening_signal={"signal_type": "missing_evidence"},
        orchestration_mode="literature_frontier",
    )


async def _run_pool_with_ranking_payload(
    tmp_path, payload: dict[str, object], *, request_id: str
) -> tuple[ResearchApiStateStore, OverridePayloadGateway, dict[str, object]]:
    store, gateway, orchestrator = _orchestrator_with_ranking_payload(tmp_path, payload)
    pool = await _create_default_pool(orchestrator, request_id=request_id)
    return store, gateway, pool


def _agent_payload(agent_name: str, call_number: int) -> dict[str, object]:
    if agent_name == "supervisor":
        return _supervisor_artifact(
            decision="continue",
            next_actions=["reflect", "rank", "evolve", "meta_review"],
        )
    if agent_name == "generation":
        return {
            "candidate": {
                "title": f"LLM generated hypothesis {call_number}",
                "statement": (
                    "Uploaded evidence implies alumni network strength may mediate "
                    "brand sentiment recovery after reputational shocks."
                ),
                "hypothesis_level_conclusion": (
                    "Brand recovery is likely mediated by alumni-network activation."
                ),
                "summary": "Evidence-grounded mediation hypothesis.",
                "rationale": "The candidate combines uploaded claims rather than trigger templates.",
                "testability_hint": "Compare sentiment recovery before and after alumni network activation.",
                "novelty_hint": "Mechanism-level recombination across uploaded source claims.",
                "confidence_hint": 0.62,
                "suggested_next_steps": [
                    "collect sentiment timeline",
                    "test mediator effect",
                ],
                "source_refs": [
                    {
                        "source_id": "source_1",
                        "source_span": {"page": 2, "start": 40, "end": 110},
                        "evidence_refs": ["claim_1"],
                    }
                ],
                "reasoning_chain": {
                    "evidence": ["claim_1"],
                    "assumption": "Alumni network strength can be externally observed.",
                    "intermediate_reasoning": [
                        "Evidence links reputation to alumni network strength.",
                        "Sentiment recovery requires a plausible activation mechanism.",
                    ],
                    "conclusion": "Alumni activation may mediate sentiment recovery.",
                    "validation_need": "Estimate mediation on sentiment time series.",
                },
            }
        }
    if agent_name == "reflection":
        return _reflection_payload()
    if agent_name == "ranking":
        return _debate_grade_ranking_payload()
    if agent_name == "evolution":
        return {
            "children": [
                {
                    "title": "LLM evolved hypothesis",
                    "statement": (
                        "Alumni activation and public communication timing jointly "
                        "shape brand sentiment recovery after reputation shocks."
                    ),
                    "hypothesis_level_conclusion": (
                        "Sentiment recovery depends on coupled alumni activation and timing."
                    ),
                    "summary": "Evolved two-mechanism recovery hypothesis.",
                    "rationale": "Repairs the mediator measurement weakness from reflection.",
                    "testability_hint": "Run interaction model for activation x timing.",
                    "novelty_hint": "Combines two surviving mechanisms.",
                    "confidence_hint": 0.66,
                    "suggested_next_steps": ["fit interaction model"],
                    "source_refs": [
                        {
                            "source_id": "source_1",
                            "source_span": {"page": 2, "start": 40, "end": 110},
                            "evidence_refs": ["claim_1"],
                        }
                    ],
                    "reasoning_chain": {
                        "evidence": ["claim_1"],
                        "assumption": "Communication timing can be measured.",
                        "intermediate_reasoning": [
                            "Timing may moderate activation effects."
                        ],
                        "conclusion": "Activation and timing jointly affect recovery.",
                        "validation_need": "Estimate interaction against sentiment recovery.",
                    },
                    "lineage": {
                        "parents": [],
                        "operator": "combination",
                        "parent_weaknesses": [
                            "needs a clear mediator measurement"
                        ],
                    },
                }
            ],
            "change_summary": "Added timing moderator to repair measurement weakness.",
        }
    if agent_name == "meta_review":
        return _task8_meta_review_payload()
    raise AssertionError(f"unexpected agent: {agent_name}")


def _legacy_only_meta_review_payload() -> dict[str, object]:
    return {
        "recurring_issues": ["mediator measurement is underspecified"],
        "strong_patterns": ["source-grounded mechanisms survived reflection"],
        "weak_patterns": ["validation needs are still observational"],
        "continue_recommendation": "continue one more round if budget remains",
        "stop_recommendation": "",
        "diversity_assessment": "frontier contains distinguishable mechanisms",
        "prune_recommendations": [],
    }


def _task8_meta_review_payload() -> dict[str, object]:
    return {
        **_legacy_only_meta_review_payload(),
        "generation_feedback": [
            "Recurring weakness: define mediator measurement before proposing more variants.",
            "Bind any alumni activation claim to source_1 spans and falsification needs.",
        ],
        "reflection_feedback": [
            "Recurring weakness: challenge mediator measurement in every staged review.",
            "Do not let survive verdicts pass without evidence refs for the mechanism.",
        ],
        "ranking_feedback": [
            "Recurring weakness: rank candidates on mechanism specificity and validation cost.",
        ],
        "research_overview": {
            "top_hypotheses": ["alumni activation mediator"],
            "unresolved_gaps": ["mediator measurement is underspecified"],
            "validation_roadmap": ["operationalize mediator", "test sentiment timeline"],
        },
        "stop_or_continue_rationale": (
            "Continue because the recurring weakness is fixable and should condition the next round."
        ),
    }


def _meta_review_compact_text(payload: dict[str, object]) -> str:
    return " ".join(
        [
            *[str(item) for item in payload["generation_feedback"]],
            *[str(item) for item in payload["reflection_feedback"]],
            *[str(item) for item in payload["ranking_feedback"]],
            str(payload["stop_or_continue_rationale"]),
        ]
    )


async def _invoke_generation_after_meta_review(
    orchestrator: HypothesisMultiAgentOrchestrator,
    *,
    pool_id: str,
    request_id: str,
) -> None:
    supervisor_plan = _supervisor_artifact(
        decision="continue",
        next_actions=["reflect", "rank", "evolve", "meta_review"],
    )
    await orchestrator._invoke_agent(
        agent=orchestrator._generation,
        pool_id=pool_id,
        round_id=None,
        request_id=request_id,
        variables={
            "workspace_id": "ws_real_agents",
            "research_goal": "Find new hypotheses from uploaded literature only.",
            "seed_index": 99,
            "trigger_context_json": json.dumps(
                _trigger_refs(), ensure_ascii=False, default=str
            ),
            "supervisor_plan_json": json.dumps(
                supervisor_plan, ensure_ascii=False, default=str
            ),
        },
        input_payload={
            "seed_index": 99,
            "research_goal": "Find new hypotheses from uploaded literature only.",
            "trigger_refs": _trigger_refs(),
            "supervisor_plan": supervisor_plan,
        },
    )


def _assert_task8_meta_review_injected(
    transcript: dict[str, object],
    *,
    latest_meta_review_id: str,
    expected_text: str,
) -> None:
    input_payload = transcript["input_payload"]
    assert input_payload["latest_meta_review_id"] == latest_meta_review_id
    summary = input_payload["meta_review_summary"]
    assert summary["latest_meta_review_id"] == latest_meta_review_id
    assert "generation_feedback" in summary
    assert "reflection_feedback" in summary
    assert "ranking_feedback" in summary
    assert "research_overview" in summary
    assert "stop_or_continue_rationale" in summary
    rendered_prompt = input_payload["rendered_prompt"]
    assert latest_meta_review_id in rendered_prompt
    assert expected_text in rendered_prompt


def _reflection_payload(*, overall_verdict: str = "survive") -> dict[str, object]:
    return {
        "overall_verdict": overall_verdict,
        "initial_review": {
            "verdict": overall_verdict,
            "strengths": ["uses uploaded source provenance"],
            "weaknesses": ["needs a clear mediator measurement"],
            "recommendation": "keep reviewing the measurable mediator",
        },
        "literature_grounding_review": {
            "verdict": overall_verdict,
            "strengths": ["source_1 supports an alumni-network mechanism"],
            "evidence_refs": ["claim_1"],
            "recommendation": "retrieve direct activation timing evidence",
        },
        "deep_assumption_verification": {
            "verdict": "revise",
            "findings": ["observability of alumni activation is the key assumption"],
            "weaknesses": ["activation metric is underspecified"],
            "recommendation": "define alumni activation metric",
        },
        "simulation_or_counterexample_review": {
            "verdict": "revise",
            "findings": ["baseline sentiment trend is a plausible counterexample"],
            "weaknesses": ["needs baseline sentiment controls"],
            "recommendation": "compare against pre-shock sentiment trend",
        },
        "targeted_node_refs": [
            {"node_type": "reasoning_chain", "node_ref": "assumption"}
        ],
        "score_delta": 0.08,
    }


def _reflection_payload_without_stage() -> dict[str, object]:
    payload = _reflection_payload()
    payload.pop("literature_grounding_review")
    return payload


def _reflection_payload_with_empty_stage() -> dict[str, object]:
    payload = _reflection_payload()
    payload["deep_assumption_verification"] = {}
    return payload


def _hollow_survive_reflection_payload() -> dict[str, object]:
    payload = _reflection_payload()
    payload["initial_review"] = {
        "verdict": "survive",
        "findings": ["plausible but not grounded"],
        "recommendation": "continue",
    }
    payload["literature_grounding_review"] = {
        "verdict": "survive",
        "findings": ["plausible but not grounded"],
        "recommendation": "continue",
    }
    return payload


def _reflection_payload_without_overall_verdict() -> dict[str, object]:
    payload = _reflection_payload()
    payload.pop("overall_verdict")
    payload["verdict"] = "survive"
    return payload


def _reflection_payload_with_verdict_only_stages() -> dict[str, object]:
    payload = _reflection_payload(overall_verdict="revise")
    for stage in [
        "initial_review",
        "literature_grounding_review",
        "deep_assumption_verification",
        "simulation_or_counterexample_review",
    ]:
        payload[stage] = {"verdict": "revise"}
    return payload


def _strengths_only_survive_reflection_payload() -> dict[str, object]:
    payload = _reflection_payload()
    for stage in [
        "initial_review",
        "literature_grounding_review",
        "deep_assumption_verification",
        "simulation_or_counterexample_review",
    ]:
        payload[stage] = {
            "verdict": "survive",
            "strengths": ["plausible but not grounded"],
            "recommendation": "continue",
        }
    return payload


def _reflection_payload_with_non_list_targeted_refs() -> dict[str, object]:
    payload = _reflection_payload()
    payload["targeted_node_refs"] = {"node_ref": "assumption"}
    return payload


def test_reflection_schema_instruction_uses_multi_stage_artifact(tmp_path) -> None:
    store = _build_store(tmp_path)
    orchestrator = HypothesisMultiAgentOrchestrator(store, llm_gateway=RecordingGateway())

    schema = json.loads(orchestrator._schema_instruction("reflection"))

    assert schema["overall_verdict"] == "survive|revise|drop"
    for stage in [
        "initial_review",
        "literature_grounding_review",
        "deep_assumption_verification",
        "simulation_or_counterexample_review",
    ]:
        assert stage in schema
        assert isinstance(schema[stage], dict)
    assert schema["targeted_node_refs"] == []


def _empty_source_generation_payload() -> dict[str, object]:
    payload = _agent_payload("generation", 1)
    candidate = dict(payload["candidate"])
    candidate["source_refs"] = []
    payload["candidate"] = candidate
    return payload


def _empty_reasoning_evidence_generation_payload() -> dict[str, object]:
    payload = _agent_payload("generation", 1)
    candidate = dict(payload["candidate"])
    reasoning_chain = dict(candidate["reasoning_chain"])
    reasoning_chain["evidence"] = []
    candidate["reasoning_chain"] = reasoning_chain
    payload["candidate"] = candidate
    return payload


def _evolution_payload_without_lineage_operator() -> dict[str, object]:
    payload = _agent_payload("evolution", 1)
    child = dict(payload["children"][0])
    child["lineage"] = {}
    payload["children"] = [child]
    return payload


def _evolution_payload_with_lineage(
    *,
    parents: list[str],
    operator: str | None = "combination",
    parent_weaknesses: list[str] | None = None,
) -> dict[str, object]:
    payload = _agent_payload("evolution", 1)
    child = dict(payload["children"][0])
    lineage: dict[str, object] = {
        "parents": parents,
        "parent_weaknesses": (
            parent_weaknesses
            if parent_weaknesses is not None
            else ["activation metric is underspecified"]
        ),
    }
    if operator is not None:
        lineage["operator"] = operator
    child["lineage"] = lineage
    child["parent_weaknesses"] = list(lineage["parent_weaknesses"])
    payload["children"] = [child]
    return payload


def _evolution_payload_from_parent_input(
    input_payload: dict[str, object], *, operator: str = "combination"
) -> dict[str, object]:
    parent_candidates = input_payload["parent_candidates"]
    parent_ids = [str(item["candidate_id"]) for item in parent_candidates]
    return _evolution_payload_with_lineage(
        parents=parent_ids[:2],
        operator=operator,
        parent_weaknesses=[
            "needs a clear mediator measurement",
            "needs baseline sentiment controls",
        ],
    )


@pytest.mark.asyncio
async def test_legacy_only_meta_review_fails_with_failed_transcript_and_no_record(
    tmp_path,
) -> None:
    store = _build_store(tmp_path)
    gateway = OverridePayloadGateway({"meta_review": _legacy_only_meta_review_payload()})
    orchestrator = HypothesisMultiAgentOrchestrator(store, llm_gateway=gateway)

    with pytest.raises(ResearchLLMError) as exc_info:
        await _create_default_pool(
            orchestrator, request_id="req_task8_legacy_meta_review"
        )

    assert exc_info.value.error_code == "research.llm_invalid_output"
    assert "generation_feedback" in exc_info.value.message
    pool = store.list_hypothesis_pools(workspace_id="ws_real_agents")[0]
    assert pool["status"] == "failed"
    assert store.list_hypothesis_meta_reviews(pool_id=str(pool["pool_id"])) == []
    transcripts = store.list_hypothesis_agent_transcripts(pool_id=str(pool["pool_id"]))
    meta_review_transcript = next(
        item for item in transcripts if item["agent_name"] == "meta_review"
    )
    assert meta_review_transcript["status"] == "failed"
    assert meta_review_transcript["error_code"] == "research.llm_invalid_output"


@pytest.mark.asyncio
async def test_prior_meta_review_feedback_injects_into_next_round_inputs_and_transcripts(
    tmp_path,
) -> None:
    store = _build_store(tmp_path)
    meta_payload = _task8_meta_review_payload()
    gateway = OverridePayloadGateway({"meta_review": meta_payload})
    orchestrator = HypothesisMultiAgentOrchestrator(store, llm_gateway=gateway)

    pool = await _create_default_pool(
        orchestrator, request_id="req_task8_meta_review_round1"
    )
    pool_id = str(pool["pool_id"])
    first_meta_review = store.list_hypothesis_meta_reviews(pool_id=pool_id)[0]
    latest_meta_review_id = str(first_meta_review["meta_review_id"])
    compact_text = _meta_review_compact_text(meta_payload)

    await _invoke_generation_after_meta_review(
        orchestrator,
        pool_id=pool_id,
        request_id="req_task8_meta_review_generation",
    )
    await orchestrator.run_round(
        pool_id=pool_id,
        request_id="req_task8_meta_review_round2",
        max_matches=2,
        start_reason="task8_injection_check",
    )

    transcripts = store.list_hypothesis_agent_transcripts(pool_id=pool_id)
    generation_transcript = [
        item
        for item in transcripts
        if item["agent_name"] == "generation"
        and item["input_payload"].get("seed_index") == 99
    ][-1]
    round2_supervisor_transcript = [
        item
        for item in transcripts
        if item["agent_name"] == "supervisor"
        and item["input_payload"].get("start_reason") == "task8_injection_check"
    ][-1]
    round2_reflection_transcript = [
        item
        for item in transcripts
        if item["agent_name"] == "reflection"
        and item["input_payload"].get("round_number") == 2
    ][0]

    for transcript in [
        generation_transcript,
        round2_supervisor_transcript,
        round2_reflection_transcript,
    ]:
        _assert_task8_meta_review_injected(
            transcript,
            latest_meta_review_id=latest_meta_review_id,
            expected_text=compact_text,
        )


@pytest.mark.asyncio
async def test_user_reasoning_node_edit_drives_next_prompt_and_blocks_finalize_until_rechecked(
    tmp_path,
) -> None:
    store = _build_store(tmp_path)
    gateway = RecordingGateway()
    orchestrator = HypothesisMultiAgentOrchestrator(store, llm_gateway=gateway)
    pool = await _create_default_pool(
        orchestrator, request_id="req_task9_editable_graph"
    )
    pool_id = str(pool["pool_id"])
    candidate = store.list_hypothesis_candidates(pool_id=pool_id, status="alive")[0]
    candidate_id = str(candidate["candidate_id"])
    original_node = next(
        node
        for node in candidate["reasoning_chain"]["reasoning_nodes"]
        if node["node_type"] == "intermediate_reasoning"
    )
    deleted_content = str(original_node["content"])
    edited_content = "USER EDITED: alumni activation is conditional on crisis timing."

    orchestrator.apply_user_intervention(
        pool_id=pool_id,
        request_id="req_task9_edit_node",
        action="edit_reasoning_node",
        candidate_id=candidate_id,
        node={
            "node_id": original_node["node_id"],
            "node_type": original_node["node_type"],
            "content": edited_content,
            "source_refs": [],
        },
        candidate_patch=None,
        user_hypothesis=None,
        control_reason="test edit",
    )
    edited = store.get_hypothesis_candidate(candidate_id)
    assert edited is not None
    edited_chain = edited["reasoning_chain"]
    assert edited_chain["review_status"] == "pending"
    assert edited_chain["review_history"] == []
    assert edited_chain["requires_recheck"] is True
    assert edited_chain["requires_rerank"] is True
    assert edited["elo_rating"] == 1200.0
    assert edited_chain["user_interventions"][-1]["action"] == "edit_reasoning_node"

    with pytest.raises(ValueError, match="require recheck or rerank"):
        await orchestrator.finalize_pool(
            pool_id=pool_id, request_id="req_task9_finalize_before_recheck"
        )

    store.update_hypothesis_pool(pool_id=pool_id, status="running")
    await orchestrator.run_round(
        pool_id=pool_id,
        request_id="req_task9_recheck_after_edit",
        max_matches=2,
        start_reason="task9_user_edit_recheck",
    )
    reflection_transcript = [
        transcript
        for transcript in store.list_hypothesis_agent_transcripts(pool_id=pool_id)
        if transcript["agent_name"] == "reflection"
        and transcript["candidate_id"] == candidate_id
    ][-1]
    rendered_prompt = str(reflection_transcript["input_payload"]["rendered_prompt"])
    assert edited_content in rendered_prompt
    assert deleted_content not in rendered_prompt

    rechecked = store.get_hypothesis_candidate(candidate_id)
    assert rechecked is not None
    assert rechecked["reasoning_chain"]["requires_recheck"] is False
    assert rechecked["reasoning_chain"]["requires_rerank"] is False


@pytest.mark.asyncio
async def test_delete_reasoning_node_excludes_node_from_next_prompt(tmp_path) -> None:
    store = _build_store(tmp_path)
    gateway = RecordingGateway()
    orchestrator = HypothesisMultiAgentOrchestrator(store, llm_gateway=gateway)
    pool = await _create_default_pool(
        orchestrator, request_id="req_task9_delete_node"
    )
    pool_id = str(pool["pool_id"])
    candidate = store.list_hypothesis_candidates(pool_id=pool_id, status="alive")[0]
    candidate_id = str(candidate["candidate_id"])
    node = next(
        node
        for node in candidate["reasoning_chain"]["reasoning_nodes"]
        if node["node_type"] == "intermediate_reasoning"
    )
    deleted_content = str(node["content"])

    orchestrator.apply_user_intervention(
        pool_id=pool_id,
        request_id="req_task9_delete_node_control",
        action="delete_reasoning_node",
        candidate_id=candidate_id,
        node=node,
        candidate_patch=None,
        user_hypothesis=None,
        control_reason="test delete",
    )
    store.update_hypothesis_pool(pool_id=pool_id, status="running")
    await orchestrator.run_round(
        pool_id=pool_id,
        request_id="req_task9_recheck_after_delete",
        max_matches=2,
        start_reason="task9_user_delete_recheck",
    )
    reflection_transcript = [
        transcript
        for transcript in store.list_hypothesis_agent_transcripts(pool_id=pool_id)
        if transcript["agent_name"] == "reflection"
        and transcript["candidate_id"] == candidate_id
    ][-1]
    rendered_prompt = str(reflection_transcript["input_payload"]["rendered_prompt"])
    assert deleted_content not in rendered_prompt


@pytest.mark.asyncio
async def test_edit_candidate_updates_conclusion_node_and_next_prompt(tmp_path) -> None:
    store = _build_store(tmp_path)
    gateway = RecordingGateway()
    orchestrator = HypothesisMultiAgentOrchestrator(store, llm_gateway=gateway)
    pool = await _create_default_pool(
        orchestrator, request_id="req_task9_edit_candidate"
    )
    pool_id = str(pool["pool_id"])
    candidate = store.list_hypothesis_candidates(pool_id=pool_id, status="alive")[0]
    candidate_id = str(candidate["candidate_id"])
    new_statement = "USER PATCHED STATEMENT: timing conditions mediate recovery."
    new_conclusion = "USER PATCHED CONCLUSION: timing-gated alumni activation matters."

    orchestrator.apply_user_intervention(
        pool_id=pool_id,
        request_id="req_task9_edit_candidate_control",
        action="edit_candidate",
        candidate_id=candidate_id,
        node=None,
        candidate_patch={
            "statement": new_statement,
            "hypothesis_level_conclusion": new_conclusion,
        },
        user_hypothesis=None,
        control_reason="test candidate patch",
    )
    edited = store.get_hypothesis_candidate(candidate_id)
    assert edited is not None
    chain = edited["reasoning_chain"]
    assert edited["statement"] == new_statement
    assert edited["summary"] == new_conclusion
    assert chain["hypothesis_statement"] == new_statement
    assert chain["reasoning_chain"]["conclusion"] == new_conclusion
    assert any(
        node["node_type"] == "conclusion" and node["content"] == new_conclusion
        for node in chain["reasoning_nodes"]
    )
    assert chain["user_interventions"][-1]["action"] == "edit_candidate"

    store.update_hypothesis_pool(pool_id=pool_id, status="running")
    await orchestrator.run_round(
        pool_id=pool_id,
        request_id="req_task9_recheck_after_candidate_edit",
        max_matches=2,
        start_reason="task9_candidate_edit_recheck",
    )
    reflection_transcript = [
        transcript
        for transcript in store.list_hypothesis_agent_transcripts(pool_id=pool_id)
        if transcript["agent_name"] == "reflection"
        and transcript["candidate_id"] == candidate_id
    ][-1]
    rendered_prompt = str(reflection_transcript["input_payload"]["rendered_prompt"])
    assert new_statement in rendered_prompt
    assert new_conclusion in rendered_prompt


def _task10_candidate(
    candidate_id: str,
    *,
    statement: str,
    source_id: str,
    validation_need: str,
    elo_rating: float,
) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "statement": statement,
        "elo_rating": elo_rating,
        "reasoning_chain": {
            "source_refs": [{"source_id": source_id}],
            "reasoning_chain": {
                "assumption": statement,
                "conclusion": statement,
                "validation_need": validation_need,
            },
            "review_status": "survive",
        },
    }


def test_proximity_low_overlap_changes_pair_order(tmp_path) -> None:
    store = _build_store(tmp_path)
    orchestrator = HypothesisMultiAgentOrchestrator(store)
    candidates = [
        _task10_candidate(
            "c1",
            statement="shared alumni activation mechanism",
            source_id="source_same",
            validation_need="same mediation test",
            elo_rating=1500,
        ),
        _task10_candidate(
            "c2",
            statement="shared alumni activation mechanism",
            source_id="source_same",
            validation_need="same mediation test",
            elo_rating=1490,
        ),
        _task10_candidate(
            "c3",
            statement="public timing disclosure pathway",
            source_id="source_distinct",
            validation_need="distinct event study",
            elo_rating=1200,
        ),
        _task10_candidate(
            "c4",
            statement="donor trust repair pathway",
            source_id="source_other",
            validation_need="different survey validation",
            elo_rating=1190,
        ),
    ]

    pairs = orchestrator._pairings(candidates, max_matches=2)
    assert ("c1", "c2") not in pairs
    assert pairs[0] in {("c1", "c3"), ("c1", "c4"), ("c2", "c3"), ("c2", "c4")}


@pytest.mark.asyncio
async def test_final_frontier_selection_rejects_same_mechanism_source_validation(
    tmp_path,
) -> None:
    store = _build_store(tmp_path)
    gateway = RecordingGateway()
    orchestrator = HypothesisMultiAgentOrchestrator(store, llm_gateway=gateway)
    pool = await _create_default_pool(
        orchestrator, request_id="req_task10_diverse_frontier"
    )
    pool_id = str(pool["pool_id"])
    proximity_edges = store.list_hypothesis_proximity_edges(pool_id=pool_id)
    assert proximity_edges
    assert proximity_edges[0]["trace_refs"]["service_name"] == "proximity"
    assert "mechanism_signature" in proximity_edges[0]["trace_refs"]
    assert "validation_path_similarity" in proximity_edges[0]["trace_refs"]
    survivors = [
        candidate
        for candidate in store.list_hypothesis_candidates(pool_id=pool_id, status="alive")
        if candidate["reasoning_chain"].get("review_status") == "survive"
    ][:3]
    assert len(survivors) == 3
    duplicate_statement = "shared alumni activation mechanism"
    duplicate_chain = {
        "source_refs": [{"source_id": "source_same"}],
        "reasoning_chain": {
            "evidence": ["same claim"],
            "assumption": duplicate_statement,
            "intermediate_reasoning": ["same mechanism"],
            "conclusion": duplicate_statement,
            "validation_need": "same mediation test",
        },
        "review_status": "survive",
        "requires_recheck": False,
        "requires_rerank": False,
    }
    distinct_chain = {
        "source_refs": [{"source_id": "source_distinct"}],
        "reasoning_chain": {
            "evidence": ["distinct claim"],
            "assumption": "public timing disclosure pathway",
            "intermediate_reasoning": ["different mechanism"],
            "conclusion": "public timing disclosure pathway",
            "validation_need": "distinct event study",
        },
        "review_status": "survive",
        "requires_recheck": False,
        "requires_rerank": False,
    }
    store.update_hypothesis_candidate(
        candidate_id=str(survivors[0]["candidate_id"]),
        statement=duplicate_statement,
        summary=duplicate_statement,
        elo_rating=1500,
        reasoning_chain=copy.deepcopy(duplicate_chain),
    )
    store.update_hypothesis_candidate(
        candidate_id=str(survivors[1]["candidate_id"]),
        statement=duplicate_statement,
        summary=duplicate_statement,
        elo_rating=1490,
        reasoning_chain=copy.deepcopy(duplicate_chain),
    )
    store.update_hypothesis_candidate(
        candidate_id=str(survivors[2]["candidate_id"]),
        statement="public timing disclosure pathway",
        summary="public timing disclosure pathway",
        elo_rating=1200,
        reasoning_chain=copy.deepcopy(distinct_chain),
    )

    selected = await orchestrator.finalize_pool(
        pool_id=pool_id, request_id="req_task10_finalize"
    )
    selected_ids = {str(item["candidate_id"]) for item in selected}
    assert str(survivors[0]["candidate_id"]) in selected_ids
    assert str(survivors[1]["candidate_id"]) not in selected_ids
    assert str(survivors[2]["candidate_id"]) in selected_ids
    pool_record = store.get_hypothesis_pool(pool_id)
    assert pool_record is not None
    trace = pool_record["reasoning_subgraph"]["frontier_selection_trace"]
    assert trace["strategy"] == "quality_under_diversity_constraint"
    assert trace["exclusions"]
    assert trace["exclusions"][0]["reason"]


@pytest.mark.asyncio
async def test_add_user_hypothesis_persists_intervention_and_requires_review_before_finalize(
    tmp_path,
) -> None:
    store = _build_store(tmp_path)
    gateway = RecordingGateway()
    orchestrator = HypothesisMultiAgentOrchestrator(store, llm_gateway=gateway)
    pool = await _create_default_pool(
        orchestrator, request_id="req_task9_add_user_hypothesis"
    )
    pool_id = str(pool["pool_id"])
    user_statement = "USER HYPOTHESIS: targeted donor briefings accelerate recovery."

    orchestrator.apply_user_intervention(
        pool_id=pool_id,
        request_id="req_task9_add_user_control",
        action="add_user_hypothesis",
        candidate_id=None,
        node=None,
        candidate_patch=None,
        user_hypothesis={
            "title": "User donor briefing hypothesis",
            "statement": user_statement,
            "hypothesis_level_conclusion": user_statement,
            "reasoning_chain": {
                "evidence": [],
                "assumption": "Donor briefings are observable in communications.",
                "intermediate_reasoning": ["Briefings may amplify trust repair."],
                "conclusion": user_statement,
                "validation_need": "Compare briefing timing with sentiment recovery.",
            },
        },
        control_reason="test add user hypothesis",
    )

    user_candidate = [
        candidate
        for candidate in store.list_hypothesis_candidates(pool_id=pool_id)
        if candidate["origin_type"] == "user_hypothesis"
    ][0]
    user_candidate_id = str(user_candidate["candidate_id"])
    assert user_candidate["reasoning_chain"]["requires_recheck"] is True
    assert user_candidate["reasoning_chain"]["requires_rerank"] is True
    assert user_candidate["reasoning_chain"]["user_interventions"][0]["action"] == (
        "add_user_hypothesis"
    )
    pool_record = store.get_hypothesis_pool(pool_id)
    assert pool_record is not None
    assert (
        pool_record["reasoning_subgraph"]["latest_user_intervention"]["action"]
        == "add_user_hypothesis"
    )

    with pytest.raises(ValueError, match="require recheck or rerank"):
        await orchestrator.finalize_pool(
            pool_id=pool_id, request_id="req_task9_finalize_user_before_recheck"
        )

    store.update_hypothesis_pool(pool_id=pool_id, status="running")
    await orchestrator.run_round(
        pool_id=pool_id,
        request_id="req_task9_recheck_user_hypothesis",
        max_matches=4,
        start_reason="task9_user_hypothesis_recheck",
    )
    reflection_transcript = [
        transcript
        for transcript in store.list_hypothesis_agent_transcripts(pool_id=pool_id)
        if transcript["agent_name"] == "reflection"
        and transcript["candidate_id"] == user_candidate_id
    ][-1]
    assert user_statement in str(reflection_transcript["input_payload"]["rendered_prompt"])
    refreshed = store.get_hypothesis_candidate(user_candidate_id)
    assert refreshed is not None
    assert refreshed["reasoning_chain"]["requires_recheck"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("agent_name", "payload", "persisted_kind"),
    [
        ("generation", _empty_source_generation_payload(), "candidates"),
        (
            "generation",
            _empty_reasoning_evidence_generation_payload(),
            "candidates",
        ),
        (
            "reflection",
            {"verdict": "survive", "strengths": ["legacy flat-only review"]},
            "reviews",
        ),
        (
            "ranking",
            {
                "winner_candidate_id": "USE_LEFT",
                "match_reason": "Winner is valid but compare vector is empty.",
                "compare_vector": {},
            },
            "matches",
        ),
        (
            "evolution",
            _evolution_payload_without_lineage_operator(),
            "evolutions",
        ),
        (
            "meta_review",
            {
                "recurring_issues": [],
                "strong_patterns": [],
                "weak_patterns": [],
                "continue_recommendation": "continue without specific feedback",
                "stop_recommendation": "",
                "diversity_assessment": "not enough detail",
                "prune_recommendations": [],
            },
            "meta_reviews",
        ),
        (
            "supervisor",
            {
                "decision": "continue",
                "round_budget": 1,
                "candidate_budget": 1,
                "next_actions": ["reflect", "meta_review"],
                "stop_reason": "",
            },
            "candidates",
        ),
        (
            "supervisor",
            {
                "decision": "stop",
                "strategy": "stop_without_reason",
                "round_budget": 0,
                "candidate_budget": 0,
                "next_actions": [],
                "stop_reason": "",
            },
            "candidates",
        ),
        (
            "supervisor",
            {
                "decision": "finalize",
                "strategy": "finalize_without_reason",
                "round_budget": 0,
                "candidate_budget": 0,
                "next_actions": [],
                "stop_reason": "",
            },
            "candidates",
        ),
    ],
)
async def test_schema_valid_but_scientifically_empty_agent_output_fails(
    tmp_path, agent_name: str, payload: dict[str, object], persisted_kind: str
) -> None:
    store = _build_store(tmp_path)
    gateway = OverridePayloadGateway({agent_name: payload})
    orchestrator = HypothesisMultiAgentOrchestrator(store, llm_gateway=gateway)

    with pytest.raises(ResearchLLMError) as exc_info:
        await orchestrator.create_pool(
            workspace_id="ws_real_agents",
            request_id=f"req_invalid_{agent_name}_{persisted_kind}",
            trigger_refs=_trigger_refs(),
            research_goal="Find new hypotheses from uploaded literature only.",
            top_k=2,
            max_rounds=2,
            candidate_count=4,
            constraints={},
            preference_profile={},
            novelty_typing="literature_frontier",
            related_object_ids=[],
            minimum_validation_action={"validation_id": "val_1"},
            weakening_signal={"signal_type": "missing_evidence"},
            orchestration_mode="literature_frontier",
        )

    assert exc_info.value.error_code == "research.llm_invalid_output"
    pool = store.list_hypothesis_pools(workspace_id="ws_real_agents")[0]
    assert pool["status"] == "failed"
    transcripts = store.list_hypothesis_agent_transcripts(pool_id=str(pool["pool_id"]))
    failed_transcript = next(
        item for item in transcripts if item["agent_name"] == agent_name
    )
    assert failed_transcript["status"] == "failed"
    assert failed_transcript["error_code"] == "research.llm_invalid_output"
    if persisted_kind == "candidates":
        assert store.list_hypothesis_candidates(pool_id=str(pool["pool_id"])) == []
    if persisted_kind == "reviews":
        assert store.list_hypothesis_reviews(pool_id=str(pool["pool_id"])) == []
    if persisted_kind == "matches":
        assert store.list_hypothesis_matches(pool_id=str(pool["pool_id"])) == []
    if persisted_kind == "evolutions":
        assert store.list_hypothesis_evolutions(pool_id=str(pool["pool_id"])) == []
    if persisted_kind == "meta_reviews":
        assert store.list_hypothesis_meta_reviews(pool_id=str(pool["pool_id"])) == []


@pytest.mark.asyncio
async def test_evidence_empty_failure_code_is_persisted_in_failed_transcript(
    tmp_path,
) -> None:
    store = _build_store(tmp_path)
    invalid_payload = _agent_payload("generation", 1)
    candidate = dict(invalid_payload["candidate"])
    reasoning_chain = dict(candidate["reasoning_chain"])
    reasoning_chain["evidence"] = []
    candidate["reasoning_chain"] = reasoning_chain
    invalid_payload["candidate"] = candidate
    gateway = OverridePayloadGateway({"generation": invalid_payload})
    orchestrator = HypothesisMultiAgentOrchestrator(store, llm_gateway=gateway)

    with pytest.raises(ResearchLLMError) as exc_info:
        await orchestrator.create_pool(
            workspace_id="ws_real_agents",
            request_id="req_evidence_empty_failure_code",
            trigger_refs=_trigger_refs(),
            research_goal="Find new hypotheses from uploaded literature only.",
            top_k=2,
            max_rounds=1,
            candidate_count=2,
            constraints={},
            preference_profile={},
            novelty_typing="literature_frontier",
            related_object_ids=[],
            minimum_validation_action={"validation_id": "val_1"},
            weakening_signal={"signal_type": "missing_evidence"},
            orchestration_mode="literature_frontier",
        )

    assert exc_info.value.details["failure_code"] == "evidence_empty"
    pool = store.list_hypothesis_pools(workspace_id="ws_real_agents")[0]
    failed_generation = next(
        item
        for item in store.list_hypothesis_agent_transcripts(pool_id=str(pool["pool_id"]))
        if item["agent_role"] == "generation" and item["status"] == "failed"
    )
    assert failed_generation["output_payload"]["failure_code"] == "evidence_empty"
    assert gateway.calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case_name", "payload_factory", "message_fragment"),
    [
        (
            "legacy_mode_without_operator",
            lambda input_payload: _evolution_payload_with_lineage(
                parents=[
                    str(item["candidate_id"])
                    for item in input_payload["parent_candidates"]
                ][:2],
                operator=None,
            ),
            "operator",
        ),
        (
            "illegal_operator",
            lambda input_payload: _evolution_payload_from_parent_input(
                input_payload, operator="random"
            ),
            "operator",
        ),
        (
            "empty_parents",
            lambda input_payload: _evolution_payload_with_lineage(
                parents=[], operator="grounding"
            ),
            "parents",
        ),
        (
            "non_parent_id",
            lambda input_payload: _evolution_payload_with_lineage(
                parents=["hyp_cand_not_a_parent"], operator="feasibility"
            ),
            "parents",
        ),
    ],
)
async def test_invalid_evolution_lineage_fails_without_child_or_record(
    tmp_path, case_name: str, payload_factory, message_fragment: str
) -> None:
    store = _build_store(tmp_path)
    gateway = DynamicEvolutionGateway(payload_factory)
    orchestrator = HypothesisMultiAgentOrchestrator(store, llm_gateway=gateway)

    with pytest.raises(ResearchLLMError) as exc_info:
        await _create_default_pool(
            orchestrator, request_id=f"req_invalid_evolution_{case_name}"
        )

    assert exc_info.value.error_code == "research.llm_invalid_output"
    assert message_fragment in exc_info.value.message
    pool = store.list_hypothesis_pools(workspace_id="ws_real_agents")[0]
    assert pool["status"] == "failed"
    transcripts = store.list_hypothesis_agent_transcripts(pool_id=str(pool["pool_id"]))
    evolution_transcript = next(
        item for item in transcripts if item["agent_name"] == "evolution"
    )
    assert evolution_transcript["status"] == "failed"
    assert evolution_transcript["error_code"] == "research.llm_invalid_output"
    assert store.list_hypothesis_evolutions(pool_id=str(pool["pool_id"])) == []
    assert [
        candidate
        for candidate in store.list_hypothesis_candidates(pool_id=str(pool["pool_id"]))
        if candidate["origin_type"] == "evolution"
    ] == []


@pytest.mark.asyncio
async def test_valid_evolution_persists_operator_lineage_and_stays_unfinalized(
    tmp_path,
) -> None:
    store = _build_store(tmp_path)
    gateway = DynamicEvolutionGateway(_evolution_payload_from_parent_input)
    orchestrator = HypothesisMultiAgentOrchestrator(store, llm_gateway=gateway)

    pool = await _create_default_pool(
        orchestrator, request_id="req_valid_evolution_lineage"
    )

    pool_id = str(pool["pool_id"])
    evolution_calls = [
        call
        for call in gateway.calls
        if str(call["prompt_name"]).rsplit(".", 1)[-1] == "evolution"
    ]
    assert evolution_calls
    rendered_evolution_prompt = "\n".join(
        str(getattr(message, "content", message))
        for message in evolution_calls[-1]["messages"]
    )
    assert '"mode"' not in rendered_evolution_prompt
    assert "llm_evolution" not in rendered_evolution_prompt
    assert all(
        "mode" not in dict(parent.get("lineage") or {})
        for parent in evolution_calls[-1]["input_payload"]["parent_candidates"]
    )
    parent_ids = {
        str(item["candidate_id"])
        for item in evolution_calls[-1]["input_payload"]["parent_candidates"]
    }
    children = [
        candidate
        for candidate in store.list_hypothesis_candidates(pool_id=pool_id)
        if candidate["origin_type"] == "evolution"
    ]
    assert len(children) == 1
    child = children[0]
    assert child["lineage"]["operator"] == "combination"
    assert "mode" not in child["lineage"]
    assert set(child["lineage"]["parents"]).issubset(parent_ids)
    assert child["lineage"]["parents"]
    assert child["lineage"]["parent_weaknesses"] == [
        "needs a clear mediator measurement",
        "needs baseline sentiment controls",
    ]
    assert child["reasoning_chain"]["review_status"] == "pending"
    assert child["elo_rating"] == 1200.0

    evolutions = store.list_hypothesis_evolutions(pool_id=pool_id)
    assert len(evolutions) == 1
    evolution = evolutions[0]
    assert evolution["new_candidate_id"] == child["candidate_id"]
    assert evolution["evolution_mode"] == "combination"
    assert evolution["trace_refs"]["operator"] == "combination"
    assert evolution["trace_refs"]["parent_weaknesses"] == [
        "needs a clear mediator measurement",
        "needs baseline sentiment controls",
    ]
    assert set(evolution["trace_refs"]["parents"]).issubset(parent_ids)

    matches = store.list_hypothesis_matches(pool_id=pool_id)
    assert matches
    assert all(
        child["candidate_id"]
        not in {match["left_candidate_id"], match["right_candidate_id"]}
        for match in matches
    )

    finalized = await orchestrator.finalize_pool(
        pool_id=pool_id, request_id="req_valid_evolution_finalize"
    )
    assert all(item["candidate_id"] != child["candidate_id"] for item in finalized)
    refreshed_child = store.get_hypothesis_candidate(str(child["candidate_id"]))
    assert refreshed_child is not None
    assert refreshed_child["status"] != "finalized"


@pytest.mark.asyncio
async def test_evolved_child_reenters_reflection_and_ranking_next_round(
    tmp_path,
) -> None:
    store = _build_store(tmp_path)
    gateway = DynamicEvolutionGateway(_evolution_payload_from_parent_input)
    orchestrator = HypothesisMultiAgentOrchestrator(store, llm_gateway=gateway)

    pool = await _create_default_pool(
        orchestrator, request_id="req_evolved_child_next_round"
    )
    pool_id = str(pool["pool_id"])
    child = next(
        candidate
        for candidate in store.list_hypothesis_candidates(pool_id=pool_id)
        if candidate["origin_type"] == "evolution"
    )
    child_id = str(child["candidate_id"])
    assert child["reasoning_chain"]["review_status"] == "pending"

    await orchestrator.run_round(
        pool_id=pool_id,
        request_id="req_evolved_child_next_round_2",
        max_matches=12,
        start_reason="review_evolved_child",
    )

    reviewed_child = store.get_hypothesis_candidate(child_id)
    assert reviewed_child is not None
    assert reviewed_child["reasoning_chain"]["review_status"] == "survive"
    assert reviewed_child["reasoning_chain"]["review_history"]
    matches = store.list_hypothesis_matches(pool_id=pool_id)
    assert any(
        child_id in {str(match["left_candidate_id"]), str(match["right_candidate_id"])}
        for match in matches
    )


@pytest.mark.asyncio
async def test_terminal_round_skips_evolution_instead_of_leaving_pending_child(
    tmp_path,
) -> None:
    store = _build_store(tmp_path)
    gateway = DynamicEvolutionGateway(_evolution_payload_from_parent_input)
    orchestrator = HypothesisMultiAgentOrchestrator(store, llm_gateway=gateway)

    pool = await orchestrator.create_pool(
        workspace_id="ws_real_agents",
        request_id="req_terminal_round_no_orphan_child",
        trigger_refs=_trigger_refs(),
        research_goal="Find new hypotheses from uploaded literature only.",
        top_k=2,
        max_rounds=1,
        candidate_count=4,
        constraints={},
        preference_profile={},
        novelty_typing="literature_frontier",
        related_object_ids=[{"object_type": "source", "object_id": "source_1"}],
        minimum_validation_action={"validation_id": "val_1", "method": "mediation"},
        weakening_signal={"signal_type": "missing_evidence"},
        orchestration_mode="literature_frontier",
    )

    pool_id = str(pool["pool_id"])
    assert store.get_hypothesis_pool(pool_id)["status"] == "stopped"
    assert [
        candidate
        for candidate in store.list_hypothesis_candidates(pool_id=pool_id)
        if candidate["origin_type"] == "evolution"
    ] == []
    assert store.list_hypothesis_evolutions(pool_id=pool_id) == []
    assert all(
        str(call["prompt_name"]).rsplit(".", 1)[-1] != "evolution"
        for call in gateway.calls
    )
    terminal_round = store.list_hypothesis_rounds(pool_id=pool_id)[-1]
    assert terminal_round["evolution_count"] == 0
    assert terminal_round["stop_reason"] == "terminal_round_evolution_skipped"


def test_evolution_schema_is_operator_only_without_legacy_mode(tmp_path) -> None:
    orchestrator = HypothesisMultiAgentOrchestrator(
        _build_store(tmp_path), llm_gateway=RecordingGateway()
    )

    schema = json.loads(orchestrator._schema_instruction("evolution"))
    lineage_schema = schema["children"][0]["lineage"]

    assert "operator" in lineage_schema
    assert "mode" not in lineage_schema


def test_direct_agent_rule_methods_are_disabled_in_production_path() -> None:
    with pytest.raises(RuntimeError, match="LLMGateway"):
        GenerationAgent().propose_candidate(
            workspace_id="ws",
            research_goal="goal",
            trigger_refs=_trigger_refs(),
            seed_index=0,
            supervisor_plan={},
        )
    with pytest.raises(RuntimeError, match="LLMGateway"):
        ReflectionAgent().reflect_candidate(candidate={}, round_number=1)
    with pytest.raises(RuntimeError, match="LLMGateway"):
        RankingAgent().compare_pair(left_candidate={}, right_candidate={})
    with pytest.raises(RuntimeError, match="LLMGateway"):
        EvolutionAgent().evolve_candidates(
            pool_id="pool", round_number=1, parent_candidates=[], target_children=1
        )
    with pytest.raises(RuntimeError, match="LLMGateway"):
        MetaReviewAgent().review_round(
            pool_id="pool", round_number=1, candidates=[], matches=[], evolution_count=0
        )
    with pytest.raises(RuntimeError, match="LLMGateway"):
        SupervisorAgent().should_stop(
            round_number=1, max_rounds=2, alive_count=4, top_k=2
        )


@pytest.mark.asyncio
async def test_multi_agent_invalid_generation_output_fails_without_local_defaults(
    tmp_path,
) -> None:
    store = _build_store(tmp_path)
    gateway = RecordingGateway(invalid_agent="generation")
    orchestrator = HypothesisMultiAgentOrchestrator(store, llm_gateway=gateway)

    with pytest.raises(ResearchLLMError) as exc_info:
        await orchestrator.create_pool(
            workspace_id="ws_real_agents",
            request_id="req_invalid_generation",
            trigger_refs=_trigger_refs(),
            research_goal="Find new hypotheses from uploaded literature only.",
            top_k=2,
            max_rounds=2,
            candidate_count=4,
            constraints={},
            preference_profile={},
            novelty_typing="literature_frontier",
            related_object_ids=[],
            minimum_validation_action={"validation_id": "val_1"},
            weakening_signal={"signal_type": "missing_evidence"},
            orchestration_mode="literature_frontier",
        )

    assert exc_info.value.error_code == "research.llm_invalid_output"
    pool = store.list_hypothesis_pools(workspace_id="ws_real_agents")[0]
    assert pool["status"] == "failed"
    assert store.list_hypothesis_candidates(pool_id=str(pool["pool_id"])) == []
    transcripts = store.list_hypothesis_agent_transcripts(pool_id=str(pool["pool_id"]))
    generation_transcript = next(
        item for item in transcripts if item["agent_name"] == "generation"
    )
    assert generation_transcript["status"] == "failed"
    assert generation_transcript["error_code"] == "research.llm_invalid_output"


@pytest.mark.asyncio
async def test_multi_agent_pool_calls_llm_roles_and_persists_transcripts(
    tmp_path,
) -> None:
    store = _build_store(tmp_path)
    gateway = RecordingGateway()
    orchestrator = HypothesisMultiAgentOrchestrator(store, llm_gateway=gateway)

    pool = await orchestrator.create_pool(
        workspace_id="ws_real_agents",
        request_id="req_real_agents",
        trigger_refs=_trigger_refs(),
        research_goal="Find new hypotheses from uploaded literature only.",
        top_k=2,
        max_rounds=2,
        candidate_count=4,
        constraints={},
        preference_profile={},
        novelty_typing="literature_frontier",
        related_object_ids=[{"object_type": "source", "object_id": "source_1"}],
        minimum_validation_action={"validation_id": "val_1", "method": "mediation"},
        weakening_signal={"signal_type": "missing_evidence"},
        orchestration_mode="literature_frontier",
    )

    called_roles = {
        str(call["prompt_name"]).rsplit(".", 1)[-1] for call in gateway.calls
    }
    assert {
        "supervisor",
        "generation",
        "reflection",
        "ranking",
        "evolution",
        "meta_review",
    } <= called_roles

    transcripts = store.list_hypothesis_agent_transcripts(pool_id=str(pool["pool_id"]))
    transcript_roles = {item["agent_name"] for item in transcripts}
    assert called_roles <= transcript_roles
    assert all(item["status"] == "completed" for item in transcripts)
    assert all(item["prompt_template"] for item in transcripts)
    assert all(item["input_payload"] for item in transcripts)
    assert all(item["output_payload"] for item in transcripts)
    assert all(item["provider"] == "openai" for item in transcripts)
    assert all(item["model"] == "gpt-4.1-mini" for item in transcripts)

    persisted_candidates = store.list_hypothesis_candidates(
        pool_id=str(pool["pool_id"])
    )
    assert persisted_candidates
    for candidate in persisted_candidates:
        chain = candidate["reasoning_chain"]
        assert chain["reasoning_chain"]["evidence"]
        assert chain["reasoning_chain"]["assumption"]
        assert chain["reasoning_chain"]["intermediate_reasoning"]
        assert chain["reasoning_chain"]["conclusion"]
        assert chain["reasoning_chain"]["validation_need"]
        assert chain["source_refs"][0]["source_id"] == "source_1"

    matches = store.list_hypothesis_matches(pool_id=str(pool["pool_id"]))
    assert matches
    assert matches[0]["judge_trace"]["transcript_id"]
    reviews = store.list_hypothesis_reviews(pool_id=str(pool["pool_id"]))
    assert reviews
    assert all(review["trace_refs"]["transcript_id"] for review in reviews)
    evolutions = store.list_hypothesis_evolutions(pool_id=str(pool["pool_id"]))
    assert evolutions
    assert all(evolution["trace_refs"]["transcript_id"] for evolution in evolutions)
    meta_reviews = store.list_hypothesis_meta_reviews(pool_id=str(pool["pool_id"]))
    assert meta_reviews
    assert all(review["trace_refs"]["transcript_id"] for review in meta_reviews)
    refreshed_candidates = store.list_hypothesis_candidates(
        pool_id=str(pool["pool_id"])
    )
    assert any(candidate["elo_rating"] != 1200.0 for candidate in refreshed_candidates)
    round_supervisor = [
        item
        for item in transcripts
        if item["agent_name"] == "supervisor" and item["round_id"]
    ]
    assert round_supervisor


@pytest.mark.asyncio
async def test_multi_stage_reflection_persists_full_payload(tmp_path) -> None:
    store = _build_store(tmp_path)
    gateway = RecordingGateway()
    orchestrator = HypothesisMultiAgentOrchestrator(store, llm_gateway=gateway)

    pool = await orchestrator.create_pool(
        workspace_id="ws_real_agents",
        request_id="req_multi_stage_reflection",
        trigger_refs=_trigger_refs(),
        research_goal="Find new hypotheses from uploaded literature only.",
        top_k=2,
        max_rounds=2,
        candidate_count=4,
        constraints={},
        preference_profile={},
        novelty_typing="literature_frontier",
        related_object_ids=[{"object_type": "source", "object_id": "source_1"}],
        minimum_validation_action={"validation_id": "val_1", "method": "mediation"},
        weakening_signal={"signal_type": "missing_evidence"},
        orchestration_mode="literature_frontier",
    )

    candidates = store.list_hypothesis_candidates(pool_id=str(pool["pool_id"]))
    reviewed = [
        candidate
        for candidate in candidates
        if (candidate["reasoning_chain"] or {}).get("review_history")
    ]
    assert reviewed
    for candidate in reviewed:
        chain = candidate["reasoning_chain"]
        reflection = chain["last_reflection"]
        assert reflection["overall_verdict"] == "survive"
        assert reflection["literature_grounding_review"]["evidence_refs"] == [
            "claim_1"
        ]
        assert reflection["targeted_node_refs"] == [
            {"node_type": "reasoning_chain", "node_ref": "assumption"}
        ]
        history_reflection = chain["review_history"][-1]["reflection"]
        assert history_reflection == reflection
        assert chain["review_status"] == "survive"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        _reflection_payload_without_stage(),
        _reflection_payload_with_empty_stage(),
        _hollow_survive_reflection_payload(),
        _reflection_payload_without_overall_verdict(),
        _reflection_payload_with_verdict_only_stages(),
        _strengths_only_survive_reflection_payload(),
        _reflection_payload_with_non_list_targeted_refs(),
    ],
)
async def test_invalid_multi_stage_reflection_fails_with_failed_transcript(
    tmp_path, payload: dict[str, object]
) -> None:
    store = _build_store(tmp_path)
    gateway = OverridePayloadGateway({"reflection": payload})
    orchestrator = HypothesisMultiAgentOrchestrator(store, llm_gateway=gateway)

    with pytest.raises(ResearchLLMError) as exc_info:
        await orchestrator.create_pool(
            workspace_id="ws_real_agents",
            request_id="req_invalid_multi_stage_reflection",
            trigger_refs=_trigger_refs(),
            research_goal="Find new hypotheses from uploaded literature only.",
            top_k=2,
            max_rounds=2,
            candidate_count=4,
            constraints={},
            preference_profile={},
            novelty_typing="literature_frontier",
            related_object_ids=[],
            minimum_validation_action={"validation_id": "val_1"},
            weakening_signal={"signal_type": "missing_evidence"},
            orchestration_mode="literature_frontier",
        )

    assert exc_info.value.error_code == "research.llm_invalid_output"
    pool = store.list_hypothesis_pools(workspace_id="ws_real_agents")[0]
    assert pool["status"] == "failed"
    transcripts = store.list_hypothesis_agent_transcripts(pool_id=str(pool["pool_id"]))
    failed_reflection = next(
        item for item in transcripts if item["agent_name"] == "reflection"
    )
    assert failed_reflection["status"] == "failed"
    assert failed_reflection["error_code"] == "research.llm_invalid_output"
    assert store.list_hypothesis_reviews(pool_id=str(pool["pool_id"])) == []


@pytest.mark.asyncio
async def test_ranking_only_receives_multi_stage_survivors(tmp_path) -> None:
    store = _build_store(tmp_path)
    gateway = SequencedReflectionGateway(["survive", "drop", "survive", "revise"])
    orchestrator = HypothesisMultiAgentOrchestrator(store, llm_gateway=gateway)

    pool = await orchestrator.create_pool(
        workspace_id="ws_real_agents",
        request_id="req_multi_stage_survivor_ranking_gate",
        trigger_refs=_trigger_refs(),
        research_goal="Find new hypotheses from uploaded literature only.",
        top_k=2,
        max_rounds=2,
        candidate_count=4,
        constraints={},
        preference_profile={},
        novelty_typing="literature_frontier",
        related_object_ids=[{"object_type": "source", "object_id": "source_1"}],
        minimum_validation_action={"validation_id": "val_1", "method": "mediation"},
        weakening_signal={"signal_type": "missing_evidence"},
        orchestration_mode="literature_frontier",
    )

    ranking_transcripts = [
        transcript
        for transcript in store.list_hypothesis_agent_transcripts(
            pool_id=str(pool["pool_id"])
        )
        if transcript["agent_name"] == "ranking"
    ]
    assert ranking_transcripts
    ranked_candidate_ids = {
        str(transcript["input_payload"][side]["candidate_id"])
        for transcript in ranking_transcripts
        for side in ("left_candidate", "right_candidate")
    }
    candidates = store.list_hypothesis_candidates(pool_id=str(pool["pool_id"]))
    survive_ids = {
        str(candidate["candidate_id"])
        for candidate in candidates
        if (candidate["reasoning_chain"] or {}).get("review_status") == "survive"
    }
    non_survive_ids = {
        str(candidate["candidate_id"])
        for candidate in candidates
        if (candidate["reasoning_chain"] or {}).get("review_status") != "survive"
    }
    assert ranked_candidate_ids == survive_ids
    assert ranked_candidate_ids.isdisjoint(non_survive_ids)


async def _create_pool_with_round_supervisor(
    tmp_path, payload: dict[str, object]
) -> tuple[ResearchApiStateStore, RoundSupervisorDecisionGateway, dict[str, object]]:
    store = _build_store(tmp_path)
    gateway = RoundSupervisorDecisionGateway(payload)
    orchestrator = HypothesisMultiAgentOrchestrator(store, llm_gateway=gateway)
    pool = await orchestrator.create_pool(
        workspace_id="ws_real_agents",
        request_id=f"req_round_{payload['decision']}",
        trigger_refs=_trigger_refs(),
        research_goal="Find new hypotheses from uploaded literature only.",
        top_k=2,
        max_rounds=2,
        candidate_count=4,
        constraints={},
        preference_profile={},
        novelty_typing="literature_frontier",
        related_object_ids=[{"object_type": "source", "object_id": "source_1"}],
        minimum_validation_action={"validation_id": "val_1", "method": "mediation"},
        weakening_signal={"signal_type": "missing_evidence"},
        orchestration_mode="literature_frontier",
    )
    return store, gateway, pool


def _round_agent_calls_after_supervisor(
    gateway: RecordingGateway,
) -> list[str]:
    supervisor_count = 0
    roles: list[str] = []
    for call in gateway.calls:
        role = str(call["prompt_name"]).rsplit(".", 1)[-1]
        if role == "supervisor":
            supervisor_count += 1
            continue
        if supervisor_count >= 2:
            roles.append(role)
    return roles


def _latest_supervisor_artifact(
    store: ResearchApiStateStore, pool_id: str
) -> dict[str, object]:
    pool = store.get_hypothesis_pool(pool_id)
    assert pool is not None
    artifact = (pool["reasoning_subgraph"] or {}).get("latest_round_supervisor")
    assert isinstance(artifact, dict)
    return artifact


@pytest.mark.asyncio
async def test_retrieve_supervisor_decision_pauses_round_and_persists_artifact(
    tmp_path,
) -> None:
    payload = _supervisor_artifact(
        decision="retrieve",
        next_actions=["retrieve"],
        stop_reason="retrieve_missing_direct_evidence",
        retrieval_needed=True,
    )
    store, gateway, pool = await _create_pool_with_round_supervisor(tmp_path, payload)

    persisted = store.get_hypothesis_pool(str(pool["pool_id"]))
    assert persisted is not None
    assert persisted["status"] == "paused"
    rounds = store.list_hypothesis_rounds(pool_id=str(pool["pool_id"]))
    assert rounds[-1]["status"] == "completed"
    assert rounds[-1]["stop_reason"] == "retrieve_missing_direct_evidence"
    artifact = _latest_supervisor_artifact(store, str(pool["pool_id"]))
    assert artifact["decision"] == "retrieve"
    assert artifact["retrieval_intent"]["needed"] is True
    assert artifact["evidence_coverage_assessment"]["gaps"]
    assert _round_agent_calls_after_supervisor(gateway) == []


@pytest.mark.asyncio
async def test_initial_retrieve_supervisor_decision_pauses_without_generation(
    tmp_path,
) -> None:
    payload = _supervisor_artifact(
        decision="retrieve",
        next_actions=["retrieve"],
        stop_reason="initial_retrieve_missing_evidence",
        retrieval_needed=True,
    )
    store = _build_store(tmp_path)
    gateway = InitialSupervisorDecisionGateway(payload)
    orchestrator = HypothesisMultiAgentOrchestrator(store, llm_gateway=gateway)

    pool = await orchestrator.create_pool(
        workspace_id="ws_real_agents",
        request_id="req_initial_retrieve_supervisor",
        trigger_refs=_trigger_refs(),
        research_goal="Find new hypotheses from uploaded literature only.",
        top_k=2,
        max_rounds=2,
        candidate_count=4,
        constraints={},
        preference_profile={},
        novelty_typing="literature_frontier",
        related_object_ids=[],
        minimum_validation_action={"validation_id": "val_1"},
        weakening_signal={"signal_type": "missing_evidence"},
        orchestration_mode="literature_frontier",
    )

    persisted = store.get_hypothesis_pool(str(pool["pool_id"]))
    assert persisted is not None
    assert persisted["status"] == "paused"
    assert store.list_hypothesis_candidates(pool_id=str(pool["pool_id"])) == []
    assert store.list_hypothesis_rounds(pool_id=str(pool["pool_id"])) == []
    assert [str(call["prompt_name"]).rsplit(".", 1)[-1] for call in gateway.calls] == [
        "supervisor"
    ]
    supervisor_plan = persisted["reasoning_subgraph"]["supervisor_plan"]
    assert supervisor_plan["decision"] == "retrieve"
    assert supervisor_plan["retrieval_intent"]["needed"] is True


@pytest.mark.asyncio
async def test_evolve_supervisor_decision_runs_evolution_and_meta_review_only(
    tmp_path,
) -> None:
    payload = _supervisor_artifact(
        decision="evolve",
        next_actions=["evolve", "meta_review"],
    )
    store, gateway, pool = await _create_pool_with_round_supervisor(tmp_path, payload)

    persisted = store.get_hypothesis_pool(str(pool["pool_id"]))
    assert persisted is not None
    assert persisted["status"] == "running"
    rounds = store.list_hypothesis_rounds(pool_id=str(pool["pool_id"]))
    assert rounds[-1]["status"] == "completed"
    assert rounds[-1]["evolution_count"] > 0
    assert rounds[-1]["meta_review_id"]
    assert _latest_supervisor_artifact(store, str(pool["pool_id"]))["decision"] == "evolve"
    assert _round_agent_calls_after_supervisor(gateway) == ["evolution", "meta_review"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("decision", "status", "user_control_state", "stop_reason"),
    [
        ("pause", "paused", "pause_requested", "user_requested_pause"),
        ("stop", "stopped", "stop_requested", "user_requested_stop"),
        (
            "finalize",
            "finalizing",
            "force_finalize_requested",
            "user_requested_finalize",
        ),
    ],
)
async def test_terminal_supervisor_decisions_complete_round_and_persist_artifact(
    tmp_path,
    decision: str,
    status: str,
    user_control_state: str,
    stop_reason: str,
) -> None:
    payload = _supervisor_artifact(
        decision=decision,
        next_actions=[],
        stop_reason=stop_reason,
        user_control_state=user_control_state,
    )
    store, gateway, pool = await _create_pool_with_round_supervisor(tmp_path, payload)

    persisted = store.get_hypothesis_pool(str(pool["pool_id"]))
    assert persisted is not None
    assert persisted["status"] == status
    rounds = store.list_hypothesis_rounds(pool_id=str(pool["pool_id"]))
    assert rounds[-1]["status"] == "completed"
    assert rounds[-1]["stop_reason"] == stop_reason
    artifact = _latest_supervisor_artifact(store, str(pool["pool_id"]))
    assert artifact["decision"] == decision
    assert artifact["user_control_state"] == user_control_state
    assert artifact["stop_reason"] == stop_reason
    assert _round_agent_calls_after_supervisor(gateway) == []


@pytest.mark.asyncio
async def test_retrieve_supervisor_decision_requires_retrieval_intent_needed_true(
    tmp_path,
) -> None:
    payload = _supervisor_artifact(
        decision="retrieve",
        next_actions=["retrieve"],
        stop_reason="retrieve_missing_direct_evidence",
        retrieval_needed=False,
    )
    store = _build_store(tmp_path)
    gateway = RoundSupervisorDecisionGateway(payload)
    orchestrator = HypothesisMultiAgentOrchestrator(store, llm_gateway=gateway)

    with pytest.raises(ResearchLLMError) as exc_info:
        await orchestrator.create_pool(
            workspace_id="ws_real_agents",
            request_id="req_invalid_retrieve_intent",
            trigger_refs=_trigger_refs(),
            research_goal="Find new hypotheses from uploaded literature only.",
            top_k=2,
            max_rounds=2,
            candidate_count=4,
            constraints={},
            preference_profile={},
            novelty_typing="literature_frontier",
            related_object_ids=[],
            minimum_validation_action={"validation_id": "val_1"},
            weakening_signal={"signal_type": "missing_evidence"},
            orchestration_mode="literature_frontier",
        )

    assert exc_info.value.error_code == "research.llm_invalid_output"
    assert "retrieval_intent.needed" in exc_info.value.message
    pool = store.list_hypothesis_pools(workspace_id="ws_real_agents")[0]
    assert pool["status"] == "failed"
    transcripts = store.list_hypothesis_agent_transcripts(pool_id=str(pool["pool_id"]))
    failed_round_supervisor = [
        item
        for item in transcripts
        if item["agent_name"] == "supervisor" and item["round_id"]
    ][-1]
    assert failed_round_supervisor["status"] == "failed"
    assert failed_round_supervisor["error_code"] == "research.llm_invalid_output"


@pytest.mark.asyncio
async def test_invalid_pairwise_judge_winner_fails_before_completed_transcript(
    tmp_path,
) -> None:
    store = _build_store(tmp_path)
    gateway = InvalidRankingGateway()
    orchestrator = HypothesisMultiAgentOrchestrator(store, llm_gateway=gateway)

    with pytest.raises(ResearchLLMError) as exc_info:
        await orchestrator.create_pool(
            workspace_id="ws_real_agents",
            request_id="req_invalid_ranking",
            trigger_refs=_trigger_refs(),
            research_goal="Find new hypotheses from uploaded literature only.",
            top_k=2,
            max_rounds=2,
            candidate_count=4,
            constraints={},
            preference_profile={},
            novelty_typing="literature_frontier",
            related_object_ids=[],
            minimum_validation_action={"validation_id": "val_1"},
            weakening_signal={"signal_type": "missing_evidence"},
            orchestration_mode="literature_frontier",
        )

    assert exc_info.value.error_code == "research.llm_invalid_output"
    pool = store.list_hypothesis_pools(workspace_id="ws_real_agents")[0]
    assert pool["status"] == "failed"
    transcripts = store.list_hypothesis_agent_transcripts(pool_id=str(pool["pool_id"]))
    ranking_transcript = next(
        item for item in transcripts if item["agent_name"] == "ranking"
    )
    assert ranking_transcript["status"] == "failed"
    assert ranking_transcript["error_code"] == "research.llm_invalid_output"
    assert store.list_hypothesis_matches(pool_id=str(pool["pool_id"])) == []
    candidates = store.list_hypothesis_candidates(pool_id=str(pool["pool_id"]))
    assert candidates
    assert {candidate["elo_rating"] for candidate in candidates} == {1200.0}


@pytest.mark.asyncio
async def test_flat_compare_vector_only_ranking_payload_fails_without_elo_or_match(
    tmp_path,
) -> None:
    store, _, orchestrator = _orchestrator_with_ranking_payload(
        tmp_path, _flat_compare_vector_only_ranking_payload()
    )
    with pytest.raises(ResearchLLMError) as exc_info:
        await _create_default_pool(
            orchestrator, request_id="req_flat_ranking_rejected"
        )

    assert exc_info.value.error_code == "research.llm_invalid_output"
    pool = store.list_hypothesis_pools(workspace_id="ws_real_agents")[0]
    assert pool["status"] == "failed"
    transcripts = store.list_hypothesis_agent_transcripts(pool_id=str(pool["pool_id"]))
    ranking_transcript = next(
        item for item in transcripts if item["agent_name"] == "ranking"
    )
    assert ranking_transcript["status"] == "failed"
    assert store.list_hypothesis_matches(pool_id=str(pool["pool_id"])) == []
    candidates = store.list_hypothesis_candidates(pool_id=str(pool["pool_id"]))
    assert candidates
    assert {candidate["elo_rating"] for candidate in candidates} == {1200.0}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("invalid_field", "mutate_payload"),
    [
        ("debate_transcript", lambda payload: payload.pop("debate_transcript")),
        ("loser_failure_modes", lambda payload: payload.pop("loser_failure_modes")),
        (
            "match_scheduling_reason",
            lambda payload: payload.pop("match_scheduling_reason"),
        ),
        ("criterion_scores", lambda payload: payload.pop("criterion_scores")),
        (
            "criterion_scores",
            lambda payload: payload["criterion_scores"].__setitem__(
                "bonus_axis", 0.99
            ),
        ),
        (
            "confidence_in_judgment",
            lambda payload: payload.pop("confidence_in_judgment"),
        ),
        ("elo_delta", lambda payload: payload.pop("elo_delta")),
    ],
)
async def test_invalid_debate_grade_ranking_field_fails_and_writes_failed_transcript(
    tmp_path, invalid_field: str, mutate_payload
) -> None:
    payload = _debate_grade_ranking_payload()
    mutate_payload(payload)
    payload["compare_vector"] = _flat_compare_vector_only_ranking_payload()[
        "compare_vector"
    ]
    store, _, orchestrator = _orchestrator_with_ranking_payload(tmp_path, payload)

    with pytest.raises(ResearchLLMError) as exc_info:
        await _create_default_pool(
            orchestrator, request_id=f"req_invalid_ranking_{invalid_field}"
        )

    assert exc_info.value.error_code == "research.llm_invalid_output"
    assert invalid_field in exc_info.value.message
    pool = store.list_hypothesis_pools(workspace_id="ws_real_agents")[0]
    assert pool["status"] == "failed"
    transcripts = store.list_hypothesis_agent_transcripts(pool_id=str(pool["pool_id"]))
    ranking_transcript = next(
        item for item in transcripts if item["agent_name"] == "ranking"
    )
    assert ranking_transcript["status"] == "failed"
    assert ranking_transcript["error_code"] == "research.llm_invalid_output"
    assert store.list_hypothesis_matches(pool_id=str(pool["pool_id"])) == []
    candidates = store.list_hypothesis_candidates(pool_id=str(pool["pool_id"]))
    assert candidates
    assert {candidate["elo_rating"] for candidate in candidates} == {1200.0}


@pytest.mark.asyncio
@pytest.mark.parametrize("winner_candidate_id", ["no_decision", "unknown_candidate"])
async def test_no_decision_or_unknown_winner_does_not_update_elo(
    tmp_path, winner_candidate_id: str
) -> None:
    payload = _debate_grade_ranking_payload()
    payload["winner_candidate_id"] = winner_candidate_id
    store, _, orchestrator = _orchestrator_with_ranking_payload(tmp_path, payload)

    with pytest.raises(ResearchLLMError):
        await _create_default_pool(
            orchestrator, request_id=f"req_bad_winner_{winner_candidate_id}"
        )

    pool = store.list_hypothesis_pools(workspace_id="ws_real_agents")[0]
    assert pool["status"] == "failed"
    assert store.list_hypothesis_matches(pool_id=str(pool["pool_id"])) == []
    candidates = store.list_hypothesis_candidates(pool_id=str(pool["pool_id"]))
    assert candidates
    assert {candidate["elo_rating"] for candidate in candidates} == {1200.0}


@pytest.mark.asyncio
async def test_debate_grade_match_persists_judge_artifact_and_computed_elo_delta(
    tmp_path,
) -> None:
    store, _, pool = await _run_pool_with_ranking_payload(
        tmp_path,
        _debate_grade_ranking_payload(),
        request_id="req_debate_grade_ranking",
    )
    assert pool is not None

    matches = store.list_hypothesis_matches(pool_id=str(pool["pool_id"]))
    assert matches
    match = matches[0]
    judge_trace = match["judge_trace"]
    compare_vector = match["compare_vector"]
    computed_delta = {
        "left": match["left_elo_after"] - match["left_elo_before"],
        "right": match["right_elo_after"] - match["right_elo_before"],
    }

    assert judge_trace["ranking_agent"]["debate_transcript"]
    assert judge_trace["ranking_agent"]["loser_failure_modes"]
    assert judge_trace["ranking_agent"]["match_scheduling_reason"]
    assert judge_trace["computed_elo_delta"] == computed_delta
    assert judge_trace["llm_elo_delta_mismatch"]["llm_provided"] == {
        "left": 99.0,
        "right": -99.0,
        "reason": "LLM proposal should be recorded as non-authoritative.",
    }
    assert judge_trace["llm_elo_delta_mismatch"]["computed"] == computed_delta
    assert compare_vector["debate_transcript"] == judge_trace["ranking_agent"][
        "debate_transcript"
    ]
    assert compare_vector["loser_failure_modes"] == judge_trace["ranking_agent"][
        "loser_failure_modes"
    ]
    assert compare_vector["match_scheduling_reason"] == judge_trace["ranking_agent"][
        "match_scheduling_reason"
    ]
    assert compare_vector["elo_delta"] == computed_delta

    left = store.get_hypothesis_candidate(str(match["left_candidate_id"]))
    right = store.get_hypothesis_candidate(str(match["right_candidate_id"]))
    assert left is not None
    assert right is not None
    assert left["elo_rating"] == match["left_elo_after"]
    assert right["elo_rating"] == match["right_elo_after"]


@pytest.mark.asyncio
async def test_invalid_supervisor_action_fails_without_local_retrieve_fallback(
    tmp_path,
) -> None:
    store = _build_store(tmp_path)
    gateway = InvalidSupervisorGateway()
    orchestrator = HypothesisMultiAgentOrchestrator(store, llm_gateway=gateway)

    with pytest.raises(ResearchLLMError) as exc_info:
        await orchestrator.create_pool(
            workspace_id="ws_real_agents",
            request_id="req_invalid_supervisor",
            trigger_refs=_trigger_refs(),
            research_goal="Find new hypotheses from uploaded literature only.",
            top_k=2,
            max_rounds=2,
            candidate_count=4,
            constraints={},
            preference_profile={},
            novelty_typing="literature_frontier",
            related_object_ids=[],
            minimum_validation_action={"validation_id": "val_1"},
            weakening_signal={"signal_type": "missing_evidence"},
            orchestration_mode="literature_frontier",
        )

    assert exc_info.value.error_code == "research.llm_invalid_output"
    pool = store.list_hypothesis_pools(workspace_id="ws_real_agents")[0]
    assert pool["status"] == "failed"
    transcripts = store.list_hypothesis_agent_transcripts(pool_id=str(pool["pool_id"]))
    supervisor_transcript = next(
        item for item in transcripts if item["agent_name"] == "supervisor"
    )
    assert supervisor_transcript["status"] == "failed"
    assert supervisor_transcript["error_code"] == "research.llm_invalid_output"


@pytest.mark.asyncio
async def test_missing_supervisor_actions_fails_without_local_default_actions(
    tmp_path,
) -> None:
    store = _build_store(tmp_path)
    gateway = MissingSupervisorActionsGateway()
    orchestrator = HypothesisMultiAgentOrchestrator(store, llm_gateway=gateway)

    with pytest.raises(ResearchLLMError) as exc_info:
        await orchestrator.create_pool(
            workspace_id="ws_real_agents",
            request_id="req_missing_supervisor_actions",
            trigger_refs=_trigger_refs(),
            research_goal="Find new hypotheses from uploaded literature only.",
            top_k=2,
            max_rounds=2,
            candidate_count=4,
            constraints={},
            preference_profile={},
            novelty_typing="literature_frontier",
            related_object_ids=[],
            minimum_validation_action={"validation_id": "val_1"},
            weakening_signal={"signal_type": "missing_evidence"},
            orchestration_mode="literature_frontier",
        )

    assert exc_info.value.error_code == "research.llm_invalid_output"
    pool = store.list_hypothesis_pools(workspace_id="ws_real_agents")[0]
    transcripts = store.list_hypothesis_agent_transcripts(pool_id=str(pool["pool_id"]))
    supervisor_transcript = next(
        item for item in transcripts if item["agent_name"] == "supervisor"
    )
    assert supervisor_transcript["status"] == "failed"
    assert supervisor_transcript["error_code"] == "research.llm_invalid_output"


@pytest.mark.asyncio
async def test_multi_agent_generation_failure_marks_pool_failed_without_rule_candidate(
    tmp_path,
) -> None:
    store = _build_store(tmp_path)
    gateway = RecordingGateway(fail_agent="generation")
    orchestrator = HypothesisMultiAgentOrchestrator(store, llm_gateway=gateway)

    with pytest.raises(ResearchLLMError):
        await orchestrator.create_pool(
            workspace_id="ws_real_agents",
            request_id="req_generation_failure",
            trigger_refs=_trigger_refs(),
            research_goal="Find new hypotheses from uploaded literature only.",
            top_k=2,
            max_rounds=2,
            candidate_count=4,
            constraints={},
            preference_profile={},
            novelty_typing="literature_frontier",
            related_object_ids=[],
            minimum_validation_action={"validation_id": "val_1"},
            weakening_signal={"signal_type": "missing_evidence"},
            orchestration_mode="literature_frontier",
        )

    pools = store.list_hypothesis_pools(workspace_id="ws_real_agents")
    assert len(pools) == 1
    assert pools[0]["status"] == "failed"
    assert store.list_hypothesis_candidates(pool_id=str(pools[0]["pool_id"])) == []
    transcripts = store.list_hypothesis_agent_transcripts(
        pool_id=str(pools[0]["pool_id"])
    )
    assert any(
        item["agent_name"] == "generation"
        and item["status"] == "failed"
        and item["error_code"] == "research.llm_failed"
        for item in transcripts
    )


@pytest.mark.asyncio
async def test_initial_elo_stays_base_until_pairwise_judge_runs(tmp_path) -> None:
    store = _build_store(tmp_path)
    gateway = StopRoundGateway()
    orchestrator = HypothesisMultiAgentOrchestrator(store, llm_gateway=gateway)

    pool = await orchestrator.create_pool(
        workspace_id="ws_real_agents",
        request_id="req_initial_elo",
        trigger_refs=_trigger_refs(),
        research_goal="Find new hypotheses from uploaded literature only.",
        top_k=2,
        max_rounds=2,
        candidate_count=4,
        constraints={},
        preference_profile={},
        novelty_typing="literature_frontier",
        related_object_ids=[],
        minimum_validation_action={"validation_id": "val_1"},
        weakening_signal={"signal_type": "missing_evidence"},
        orchestration_mode="literature_frontier",
    )

    candidates = store.list_hypothesis_candidates(pool_id=str(pool["pool_id"]))
    assert candidates
    assert {candidate["elo_rating"] for candidate in candidates} == {1200.0}
    assert store.list_hypothesis_matches(pool_id=str(pool["pool_id"])) == []
    with pytest.raises(ValueError, match="LLM pairwise judge match"):
        await orchestrator.finalize_pool(
            pool_id=str(pool["pool_id"]), request_id="req_initial_elo_finalize"
        )


@pytest.mark.asyncio
async def test_multi_agent_pool_recovers_from_persisted_state_after_rebuild(
    tmp_path,
) -> None:
    store = _build_store(tmp_path)
    first_gateway = RecordingGateway()
    first = HypothesisMultiAgentOrchestrator(store, llm_gateway=first_gateway)
    pool = await first.create_pool(
        workspace_id="ws_real_agents",
        request_id="req_recover_first",
        trigger_refs=_trigger_refs(),
        research_goal="Find new hypotheses from uploaded literature only.",
        top_k=2,
        max_rounds=2,
        candidate_count=4,
        constraints={},
        preference_profile={},
        novelty_typing="literature_frontier",
        related_object_ids=[],
        minimum_validation_action={"validation_id": "val_1"},
        weakening_signal={"signal_type": "missing_evidence"},
        orchestration_mode="literature_frontier",
    )

    rebuilt = HypothesisMultiAgentOrchestrator(store, llm_gateway=RecordingGateway())
    pool_id = str(pool["pool_id"])
    assert rebuilt.get_pool(pool_id=pool_id) is not None
    assert len(rebuilt.list_pool_candidates(pool_id=pool_id)) >= 2
    assert rebuilt.list_pool_rounds(pool_id=pool_id)
    assert store.list_hypothesis_agent_transcripts(pool_id=pool_id)


@pytest.mark.asyncio
async def test_literature_frontier_active_retrieval_calls_service_and_persists_trace(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _build_store(tmp_path)
    gateway = RecordingGateway()
    service = HypothesisService(store)
    service._multi_orchestrator = HypothesisMultiAgentOrchestrator(
        store, llm_gateway=gateway
    )

    monkeypatch.setattr(
        service,
        "_build_literature_trigger_refs",
        lambda *, workspace_id, source_ids: _trigger_refs(),
    )
    calls: list[dict[str, object]] = []

    class _Retrieval:
        def __init__(self, store: ResearchApiStateStore) -> None:
            self._store = store

        def retrieve(self, **kwargs: object) -> dict[str, object]:
            calls.append(kwargs)
            return {
                "view_type": kwargs["view_type"],
                "workspace_id": kwargs["workspace_id"],
                "retrieve_method": kwargs["retrieve_method"],
                "query_ref": {"hash": "query_hash"},
                "total": 1,
                "items": [
                    {
                        "result_id": "evidence:claim_1",
                        "score": 0.91,
                        "title": "Supplemental reputation paper",
                        "snippet": "brand reputation depends on alumni network strength",
                        "source_ref": {
                            "source_id": "source_supplemental",
                            "title": "Supplemental reputation paper",
                        },
                        "citation_verification_status": "verified",
                    }
                ],
            }

    monkeypatch.setattr(
        "research_layer.services.hypothesis_service.ResearchRetrievalService",
        _Retrieval,
    )

    pool = await service.generate_literature_frontier_pool(
        workspace_id="ws_real_agents",
        source_ids=["source_1"],
        request_id="req_active_retrieval",
        generation_job_id=None,
        research_goal="Find mechanisms for reputation recovery.",
        frontier_size=3,
        max_rounds=1,
        constraints={},
        preference_profile={},
        active_retrieval={"enabled": True, "max_papers_per_burst": 3, "max_bursts": 2},
    )

    assert calls
    assert calls[0]["view_type"] == "evidence"
    assert calls[0]["query"] == "Find mechanisms for reputation recovery."
    persisted = store.get_hypothesis_pool(str(pool["pool_id"]))
    assert persisted is not None
    trace = persisted["preference_profile"]["active_retrieval_trace"]
    assert trace["status"] == "completed"
    assert trace["service"] == "ResearchRetrievalService"
    assert trace["items"][0]["result_id"] == "evidence:claim_1"
    assert trace["evidence_packets"][0]["retrieval_origin"] == "supplemental"
    assert trace["evidence_packets"][0]["rerank_score"] == 0.91
    assert trace["evidence_packets"][0]["citation_verification_status"] == "verified"
    generation_transcripts = [
        transcript
        for transcript in store.list_hypothesis_agent_transcripts(pool_id=str(pool["pool_id"]))
        if transcript["agent_role"] == "generation"
    ]
    assert generation_transcripts
    assert (
        generation_transcripts[0]["input_payload"]["evidence_packets"][0]["packet_id"]
        == "evidence_packet:evidence:claim_1"
    )
    assert "evidence_packet:evidence:claim_1" in generation_transcripts[0]["input_payload"]["rendered_prompt"]
    supervisor_transcript = next(
        transcript
        for transcript in store.list_hypothesis_agent_transcripts(pool_id=str(pool["pool_id"]))
        if transcript["agent_role"] == "supervisor"
    )
    assert "evidence_packet:evidence:claim_1" in supervisor_transcript["input_payload"]["rendered_prompt"]


@pytest.mark.asyncio
async def test_multi_agent_pool_active_retrieval_calls_service_and_persists_trace(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _build_store(tmp_path)
    gateway = RecordingGateway()
    service = HypothesisService(store)
    service._multi_orchestrator = HypothesisMultiAgentOrchestrator(
        store, llm_gateway=gateway
    )

    class _TriggerDetector:
        def resolve_trigger_ids(
            self, *, workspace_id: str, trigger_ids: list[str]
        ) -> list[dict[str, object]]:
            return _trigger_refs()[: len(trigger_ids)]

    service._trigger_detector = _TriggerDetector()
    calls: list[dict[str, object]] = []

    class _Retrieval:
        def __init__(self, store: ResearchApiStateStore) -> None:
            self._store = store

        def retrieve(self, **kwargs: object) -> dict[str, object]:
            calls.append(kwargs)
            return {
                "view_type": kwargs["view_type"],
                "workspace_id": kwargs["workspace_id"],
                "retrieve_method": kwargs["retrieve_method"],
                "query_ref": {"hash": "pool_query_hash"},
                "total": 1,
                "items": [
                    {
                        "result_id": "evidence:trigger_pool",
                        "source_ref": {"source_id": "source_1"},
                        "evidence_refs": [{"ref_id": "claim_1"}],
                    }
                ],
            }

    monkeypatch.setattr(
        "research_layer.services.hypothesis_service.ResearchRetrievalService",
        _Retrieval,
    )

    pool = await service.generate_multi_agent_pool(
        workspace_id="ws_real_agents",
        trigger_ids=["trigger_uploaded_claim_1"],
        request_id="req_pool_active_retrieval",
        generation_job_id=None,
        research_goal="Find mechanisms for reputation recovery.",
        top_k=2,
        max_rounds=1,
        candidate_count=4,
        constraints={},
        preference_profile={},
        failure_mode=None,
        allow_fallback=False,
        active_retrieval={"enabled": True, "max_papers_per_burst": 3, "max_bursts": 2},
    )

    assert calls
    assert calls[0]["view_type"] == "evidence"
    assert calls[0]["query"] == "Find mechanisms for reputation recovery."
    persisted = store.get_hypothesis_pool(str(pool["pool_id"]))
    assert persisted is not None
    trace = persisted["preference_profile"]["active_retrieval_trace"]
    assert trace["status"] == "completed"
    assert trace["items"][0]["result_id"] == "evidence:trigger_pool"
    assert trace["evidence_packets"][0]["retrieval_origin"] == "uploaded"
    assert trace["evidence_packets"][0]["citation_verification_status"] == "verified"


@pytest.mark.asyncio
async def test_literature_frontier_active_retrieval_failure_fails_explicitly(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _build_store(tmp_path)
    service = HypothesisService(store)

    monkeypatch.setattr(
        service,
        "_build_literature_trigger_refs",
        lambda *, workspace_id, source_ids: _trigger_refs(),
    )
    calls: list[dict[str, object]] = []

    class _Retrieval:
        def __init__(self, store: ResearchApiStateStore) -> None:
            self._store = store

        def retrieve(self, **kwargs: object) -> dict[str, object]:
            calls.append(kwargs)
            raise RetrievalServiceError(
                status_code=503,
                error_code="research.retrieval_unavailable",
                message="retrieval unavailable",
                details={},
            )

    monkeypatch.setattr(
        "research_layer.services.hypothesis_service.ResearchRetrievalService",
        _Retrieval,
    )

    with pytest.raises(HypothesisServiceError) as exc_info:
        await service.generate_literature_frontier_pool(
            workspace_id="ws_real_agents",
            source_ids=["source_1"],
            request_id="req_active_retrieval_failure",
            generation_job_id=None,
            research_goal="Find mechanisms for reputation recovery.",
            frontier_size=3,
            max_rounds=1,
            constraints={},
            preference_profile={},
            active_retrieval={
                "enabled": True,
                "max_papers_per_burst": 3,
                "max_bursts": 2,
            },
        )

    assert calls
    assert getattr(exc_info.value, "error_code") == "research.retrieval_unavailable"
    assert store.list_hypothesis_pools(workspace_id="ws_real_agents") == []


@pytest.mark.asyncio
async def test_unverified_supplemental_citation_blocks_finalization(tmp_path) -> None:
    store = _build_store(tmp_path)
    gateway = RecordingGateway()
    orchestrator = HypothesisMultiAgentOrchestrator(store, llm_gateway=gateway)
    pool = await _create_default_pool(
        orchestrator, request_id="req_unverified_supplemental_finalize"
    )
    pool_id = str(pool["pool_id"])
    survivor = next(
        candidate
        for candidate in store.list_hypothesis_candidates(pool_id=pool_id, status="alive")
        if candidate["reasoning_chain"].get("review_status") == "survive"
    )
    chain = copy.deepcopy(survivor["reasoning_chain"])
    chain["source_refs"] = [
        {
            "source_id": "source_supplemental",
            "packet_id": "evidence_packet:unverified",
            "retrieval_origin": "supplemental",
            "citation_verification_status": "unverified",
        }
    ]
    store.update_hypothesis_candidate(
        candidate_id=str(survivor["candidate_id"]),
        elo_rating=2000,
        reasoning_chain=chain,
    )

    with pytest.raises(ValueError, match="unverified supplemental citations"):
        await orchestrator.finalize_pool(
            pool_id=pool_id, request_id="req_unverified_supplemental_finalize"
        )
    blocked = store.get_hypothesis_pool(pool_id)
    assert blocked is not None
    blocker = blocked["reasoning_subgraph"]["finalization_blocker"]
    assert blocker["failure_code"] == "citation_unverified"
    assert blocker["invalid_refs"][0]["packet_id"] == "evidence_packet:unverified"


@pytest.mark.asyncio
async def test_missing_supplemental_citation_status_blocks_finalization(tmp_path) -> None:
    store = _build_store(tmp_path)
    orchestrator = HypothesisMultiAgentOrchestrator(
        store, llm_gateway=RecordingGateway()
    )
    pool = await _create_default_pool(
        orchestrator, request_id="req_missing_supplemental_status_finalize"
    )
    pool_id = str(pool["pool_id"])
    survivor = next(
        candidate
        for candidate in store.list_hypothesis_candidates(pool_id=pool_id, status="alive")
        if candidate["reasoning_chain"].get("review_status") == "survive"
    )
    chain = copy.deepcopy(survivor["reasoning_chain"])
    chain["source_refs"] = [
        {
            "source_id": "source_not_uploaded",
            "packet_id": "evidence_packet:missing_status",
            "source_span": {"page": 1},
        }
    ]
    store.update_hypothesis_candidate(
        candidate_id=str(survivor["candidate_id"]),
        elo_rating=2000,
        reasoning_chain=chain,
    )

    with pytest.raises(ValueError, match="unverified supplemental citations"):
        await orchestrator.finalize_pool(
            pool_id=pool_id, request_id="req_missing_supplemental_status_finalize"
        )


@pytest.mark.asyncio
async def test_workspace_source_retrieval_item_is_marked_uploaded_without_trigger_trace(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _build_store(tmp_path)
    store.create_source(
        source_id="source_workspace_uploaded",
        workspace_id="ws_real_agents",
        source_type="pdf",
        title="Uploaded source",
        content="uploaded evidence",
        metadata={},
        import_request_id="req_import",
    )
    service = HypothesisService(store)
    service._multi_orchestrator = HypothesisMultiAgentOrchestrator(
        store, llm_gateway=RecordingGateway()
    )

    monkeypatch.setattr(
        service,
        "_build_literature_trigger_refs",
        lambda *, workspace_id, source_ids: [
                {
                    "trigger_id": "trigger_without_source_trace",
                    "trigger_type": "gap",
                    "workspace_id": workspace_id,
                    "object_ref_type": "source_claim",
                    "object_ref_id": "claim_without_trace",
                    "summary": "trigger without source trace but workspace has uploaded source",
                    "description": "trigger without trace_refs source_id",
                    "trace_refs": {},
                "related_object_ids": [],
                "metrics": {},
            }
        ],
    )

    class _Retrieval:
        def __init__(self, store: ResearchApiStateStore) -> None:
            self._store = store

        def retrieve(self, **kwargs: object) -> dict[str, object]:
            return {
                "view_type": kwargs["view_type"],
                "workspace_id": kwargs["workspace_id"],
                "retrieve_method": kwargs["retrieve_method"],
                "query_ref": {"hash": "uploaded_query_hash"},
                "total": 1,
                "items": [
                    {
                        "result_id": "evidence:uploaded_source",
                        "source_ref": {"source_id": "source_workspace_uploaded"},
                        "snippet": "uploaded workspace evidence",
                    }
                ],
            }

    monkeypatch.setattr(
        "research_layer.services.hypothesis_service.ResearchRetrievalService",
        _Retrieval,
    )

    pool = await service.generate_literature_frontier_pool(
        workspace_id="ws_real_agents",
        source_ids=["source_workspace_uploaded"],
        request_id="req_workspace_uploaded_packet",
        generation_job_id=None,
        research_goal="Find uploaded-source mechanism.",
        frontier_size=3,
        max_rounds=1,
        constraints={},
        preference_profile={},
        active_retrieval={"enabled": True, "max_papers_per_burst": 3, "max_bursts": 2},
    )

    trace = pool["preference_profile"]["active_retrieval_trace"]
    assert trace["evidence_packets"][0]["retrieval_origin"] == "uploaded"


@pytest.mark.asyncio
async def test_pool_trajectory_rebuilds_timeline_and_lineage_after_restart(
    tmp_path,
) -> None:
    store = _build_store(tmp_path)
    first = HypothesisMultiAgentOrchestrator(store, llm_gateway=RecordingGateway())
    pool = await _create_default_pool(first, request_id="req_trajectory_rebuild")
    pool_id = str(pool["pool_id"])
    rebuilt_service = HypothesisService(store)
    rebuilt_service._multi_orchestrator = HypothesisMultiAgentOrchestrator(
        store, llm_gateway=RecordingGateway()
    )

    trajectory = rebuilt_service.get_pool_trajectory(pool_id=pool_id)

    assert trajectory is not None
    event_types = {
        str(event["event_type"]) for event in trajectory["chronological_events"]
    }
    assert "pool_created" in event_types
    assert any(event_type.startswith("agent:") for event_type in event_types)
    assert "ranking_match" in event_types
    assert "service:proximity" in event_types
    assert trajectory["candidate_lineage"]
    assert trajectory["service_traces"]["proximity"]["edges"]
