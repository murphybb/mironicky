from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.services.hypothesis_service import (
    HypothesisService,
    HypothesisServiceError,
)
from research_layer.services.hypothesis_trigger_detector import (
    HypothesisTriggerDetector,
)
from research_layer.services.llm_gateway import ResearchLLMError
from research_layer.services.llm_trace import LLMCallResult


def _build_store(tmp_path) -> ResearchApiStateStore:
    return ResearchApiStateStore(
        db_path=str(tmp_path / "slice9_hypothesis_services.sqlite3")
    )


def _seed_workspace_for_triggers(
    store: ResearchApiStateStore, workspace_id: str
) -> dict[str, str]:
    conflict_node = store.create_graph_node(
        workspace_id=workspace_id,
        node_type="conflict",
        object_ref_type="conflict",
        object_ref_id="conflict_seed_1",
        short_label="Conflict Seed",
        full_description="Conflict seeded for hypothesis trigger detector",
        status="active",
    )
    gap_node = store.create_graph_node(
        workspace_id=workspace_id,
        node_type="gap",
        object_ref_type="failure_gap",
        object_ref_id="gap_seed_1",
        short_label="Gap Seed",
        full_description="Gap seeded for hypothesis trigger detector",
        status="active",
    )
    route = store.create_route(
        workspace_id=workspace_id,
        title="Weak Support Route",
        summary="route with weak support",
        status="weakened",
        support_score=41.5,
        risk_score=61.2,
        progressability_score=38.9,
        conclusion="Need new supporting evidence",
        key_supports=["support 1"],
        assumptions=["assumption 1"],
        risks=["risk 1"],
        next_validation_action="run targeted benchmark",
        route_node_ids=[str(conflict_node["node_id"]), str(gap_node["node_id"])],
        key_support_node_ids=[str(conflict_node["node_id"])],
        key_assumption_node_ids=[],
        risk_node_ids=[str(conflict_node["node_id"])],
        conclusion_node_id=str(conflict_node["node_id"]),
        version_id="ver_slice9_seed",
    )
    failure = store.create_failure(
        workspace_id=workspace_id,
        attached_targets=[
            {"target_type": "node", "target_id": str(gap_node["node_id"])}
        ],
        observed_outcome="seeded observed failure",
        expected_difference="seeded expected behavior",
        failure_reason="seeded reason",
        severity="high",
        reporter="slice9_unit",
    )
    return {
        "gap_node_id": str(gap_node["node_id"]),
        "conflict_node_id": str(conflict_node["node_id"]),
        "route_id": str(route["route_id"]),
        "failure_id": str(failure["failure_id"]),
    }


def _mock_llm_payload(
    *,
    title: str = "Queue pressure causes retrieval latency tail",
    statement: str = (
        "If queue backpressure is isolated before retrieval fan-out, then p95 latency "
        "regression should shrink while recall gain remains."
    ),
    rationale: str = (
        "Selected triggers jointly indicate weak support plus failure pressure around "
        "the same route/object neighborhood."
    ),
    testability_hint: str = "run queue-only pressure test with fixed retrieval depth",
    novelty_hint: str = "focuses on queue path not embedding quality",
    confidence_hint: float = 0.71,
    suggested_next_steps: list[str] | None = None,
) -> tuple[dict[str, str], dict[str, object], dict[str, object]]:
    return (
        {
            "title": title,
            "statement": statement,
            "rationale": rationale,
            "testability_hint": testability_hint,
            "novelty_hint": novelty_hint,
            "confidence_hint": confidence_hint,
            "suggested_next_steps": suggested_next_steps
            or ["collect queue metrics", "rerun benchmark"],
        },
        {
            "provider_backend": "openai",
            "provider_model": "gpt-4.1-mini",
            "request_id": "req_unit_slice9",
            "llm_response_id": "resp_unit_slice9",
        },
        {
            "prompt_tokens": 120,
            "completion_tokens": 48,
            "total_tokens": 168,
            "degraded": False,
            "degraded_reason": None,
        },
    )


def test_slice9_trigger_detector_detects_four_legal_trigger_types(tmp_path) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_slice9_trigger_detector"
    _seed_workspace_for_triggers(store, workspace_id)
    detector = HypothesisTriggerDetector(store)

    triggers = detector.list_triggers(workspace_id=workspace_id)

    trigger_types = {item["trigger_type"] for item in triggers}
    assert {"gap", "conflict", "failure", "weak_support"} <= trigger_types
    for trigger in triggers:
        assert trigger["workspace_id"] == workspace_id
        assert trigger["trigger_id"]
        assert trigger["object_ref_type"]
        assert trigger["object_ref_id"]
        assert isinstance(trigger["trace_refs"], dict)


@pytest.mark.asyncio
async def test_slice9_generate_rejects_invalid_trigger_ids(tmp_path) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_slice9_invalid_trigger"
    _seed_workspace_for_triggers(store, workspace_id)
    service = HypothesisService(store)

    with pytest.raises(HypothesisServiceError) as exc_info:
        await service.generate_candidate(
            workspace_id=workspace_id,
            trigger_ids=["trigger_missing"],
            request_id="req_slice9_invalid_trigger",
            generation_job_id="job_slice9_invalid_trigger",
        )
    assert exc_info.value.status_code == 400
    assert exc_info.value.error_code == "research.invalid_request"


@pytest.mark.asyncio
async def test_slice9_generate_outputs_structured_candidate_with_validation_and_signal(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_slice9_generate_structured"
    _seed_workspace_for_triggers(store, workspace_id)
    detector = HypothesisTriggerDetector(store)
    service = HypothesisService(store)
    triggers = detector.list_triggers(workspace_id=workspace_id)
    selected_trigger_ids = [item["trigger_id"] for item in triggers[:2]]

    async def _fake_generate_with_llm(**_: object):
        return _mock_llm_payload()

    monkeypatch.setattr(service, "_generate_with_llm", _fake_generate_with_llm)
    generated = await service.generate_candidate(
        workspace_id=workspace_id,
        trigger_ids=selected_trigger_ids,
        request_id="req_slice9_generate_structured",
        generation_job_id="job_slice9_generate_structured",
    )

    assert generated["status"] == "candidate"
    assert generated["stage"] == "exploratory"
    assert generated["novelty_typing"] in {
        "conservative",
        "incremental",
        "novel",
        "breakthrough",
    }
    assert isinstance(generated["trigger_refs"], list) and generated["trigger_refs"]
    assert (
        isinstance(generated["related_object_ids"], list)
        and generated["related_object_ids"]
    )
    assert isinstance(generated["minimum_validation_action"], dict)
    assert generated["minimum_validation_action"]["validation_id"]
    assert generated["minimum_validation_action"]["method"]
    assert isinstance(generated["weakening_signal"], dict)
    assert generated["weakening_signal"]["signal_type"]
    assert generated["weakening_signal"]["signal_text"]
    assert generated["provider_backend"] == "openai"
    assert generated["provider_model"] == "gpt-4.1-mini"
    assert generated["request_id"] == "req_unit_slice9"
    assert generated["llm_response_id"] == "resp_unit_slice9"
    usage = generated.get("usage") or {}
    assert usage.get("prompt_tokens") == 120
    assert usage.get("completion_tokens") == 48
    assert usage.get("total_tokens") == 168
    assert generated.get("fallback_used") is False
    assert generated.get("degraded") is False


@pytest.mark.asyncio
async def test_slice9_generate_invalid_json_uses_deterministic_fallback_when_allowed(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_slice9_generate_fallback"
    _seed_workspace_for_triggers(store, workspace_id)
    detector = HypothesisTriggerDetector(store)
    service = HypothesisService(store)
    trigger_ids = [detector.list_triggers(workspace_id=workspace_id)[0]["trigger_id"]]

    class _FailingGateway:
        async def invoke_json(self, **kwargs: object) -> object:
            assert kwargs.get("failure_mode") == "invalid_json"
            raise ResearchLLMError(
                status_code=502,
                error_code="research.llm_invalid_output",
                message="invalid json from llm",
                details={"provider_message": "injected invalid_json failure"},
            )

    monkeypatch.setattr(service, "_llm_gateway", _FailingGateway())
    monkeypatch.setattr(
        "research_layer.services.hypothesis_service.resolve_research_backend_and_model",
        lambda: ("openai", "gpt-4.1-mini"),
    )

    generated = await service.generate_candidate(
        workspace_id=workspace_id,
        trigger_ids=trigger_ids,
        request_id="req_slice9_generate_fallback",
        generation_job_id="job_slice9_generate_fallback",
        failure_mode="invalid_json",
        allow_fallback=True,
    )

    assert generated["status"] == "candidate"
    assert generated["title"]
    assert generated["statement"]
    assert generated["rationale"]
    assert generated["testability_hint"]
    assert generated["trigger_refs"][0]["trigger_id"] == trigger_ids[0]
    assert generated["provider_backend"] == "openai"
    assert generated["provider_model"] == "gpt-4.1-mini"
    assert generated["request_id"] == "req_slice9_generate_fallback"
    assert generated["llm_response_id"] in {"", None}
    assert generated.get("fallback_used") is True
    assert generated.get("degraded") is True
    assert generated.get("degraded_reason") == "research.llm_invalid_output"

    with sqlite3.connect(store.db_path) as conn:
        row = conn.execute(
            """
            SELECT metrics_json
            FROM research_events
            WHERE event_name = 'hypothesis_generation_completed'
              AND status = 'completed'
              AND request_id = ?
            ORDER BY timestamp DESC, event_id DESC
            LIMIT 1
            """,
            ("req_slice9_generate_fallback",),
        ).fetchone()
    assert row is not None
    assert '"fallback_used": true' in row[0]
    assert '"degraded": true' in row[0]
    assert "research.llm_invalid_output" in row[0]


@pytest.mark.asyncio
async def test_slice9_generate_invalid_json_fails_without_fallback(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_slice9_generate_no_fallback"
    _seed_workspace_for_triggers(store, workspace_id)
    detector = HypothesisTriggerDetector(store)
    service = HypothesisService(store)
    trigger_ids = [detector.list_triggers(workspace_id=workspace_id)[0]["trigger_id"]]

    class _FailingGateway:
        async def invoke_json(self, **_: object) -> object:
            raise ResearchLLMError(
                status_code=502,
                error_code="research.llm_invalid_output",
                message="invalid json from llm",
                details={"provider_message": "injected invalid_json failure"},
            )

    monkeypatch.setattr(service, "_llm_gateway", _FailingGateway())
    monkeypatch.setattr(
        "research_layer.services.hypothesis_service.resolve_research_backend_and_model",
        lambda: ("openai", "gpt-4.1-mini"),
    )

    with pytest.raises(HypothesisServiceError) as exc_info:
        await service.generate_candidate(
            workspace_id=workspace_id,
            trigger_ids=trigger_ids,
            request_id="req_slice9_generate_no_fallback",
            generation_job_id="job_slice9_generate_no_fallback",
            failure_mode="invalid_json",
        )

    assert exc_info.value.status_code == 502
    assert exc_info.value.error_code == "research.llm_invalid_output"
    assert store.list_hypotheses(workspace_id=workspace_id) == []


@pytest.mark.asyncio
async def test_slice9_generate_rejects_duplicate_hypothesis_candidate(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_slice9_duplicate_reject"
    _seed_workspace_for_triggers(store, workspace_id)
    detector = HypothesisTriggerDetector(store)
    service = HypothesisService(store)
    trigger_ids = [detector.list_triggers(workspace_id=workspace_id)[0]["trigger_id"]]

    async def _fake_generate_with_llm(**_: object):
        return _mock_llm_payload(
            title="Duplicate candidate title",
            statement="duplicate statement on same trigger set",
            rationale="same rationale to force duplicate contract path",
        )

    monkeypatch.setattr(service, "_generate_with_llm", _fake_generate_with_llm)
    created = await service.generate_candidate(
        workspace_id=workspace_id,
        trigger_ids=trigger_ids,
        request_id="req_slice9_duplicate_first",
        generation_job_id="job_slice9_duplicate_first",
    )
    assert created["status"] == "candidate"

    with pytest.raises(HypothesisServiceError) as exc_info:
        await service.generate_candidate(
            workspace_id=workspace_id,
            trigger_ids=trigger_ids,
            request_id="req_slice9_duplicate_second",
            generation_job_id="job_slice9_duplicate_second",
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.error_code == "research.duplicate_hypothesis_candidate"
    assert (
        exc_info.value.details.get("existing_hypothesis_id") == created["hypothesis_id"]
    )


@pytest.mark.asyncio
async def test_slice9_generate_with_llm_injects_ontology_and_tool_capability_context(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_slice9_llm_context_enriched"
    _seed_workspace_for_triggers(store, workspace_id)
    detector = HypothesisTriggerDetector(store)
    service = HypothesisService(store)
    trigger_ids = [detector.list_triggers(workspace_id=workspace_id)[0]["trigger_id"]]
    resolved_triggers = detector.resolve_trigger_ids(
        workspace_id=workspace_id, trigger_ids=trigger_ids
    )

    captured: dict[str, object] = {}

    class _CaptureGateway:
        async def invoke_json(self, **kwargs: object) -> LLMCallResult:
            captured["messages"] = kwargs.get("messages", [])
            llm_fields, _, _ = _mock_llm_payload()
            parsed = {
                "candidates": [
                    {
                        "title": llm_fields["title"],
                        "statement": llm_fields["statement"],
                        "rationale": llm_fields["rationale"],
                        "testability_hint": llm_fields["testability_hint"],
                        "novelty_hint": llm_fields["novelty_hint"],
                        "confidence_hint": llm_fields["confidence_hint"],
                        "trigger_refs": trigger_ids,
                        "suggested_next_steps": llm_fields["suggested_next_steps"],
                    }
                ]
            }
            return LLMCallResult(
                provider_backend="openai",
                provider_model="gpt-4.1-mini",
                request_id="req_slice9_llm_context_enriched",
                llm_response_id="resp_slice9_llm_context_enriched",
                usage={"prompt_tokens": 66, "completion_tokens": 21, "total_tokens": 87},
                raw_text="{}",
                parsed_json=parsed,
                fallback_used=False,
                degraded=False,
                degraded_reason=None,
            )

    monkeypatch.setattr(service, "_llm_gateway", _CaptureGateway())
    monkeypatch.setattr(
        "research_layer.services.hypothesis_service.resolve_research_backend_and_model",
        lambda: ("openai", "gpt-4.1-mini"),
    )
    fields, _, metrics = await service._generate_with_llm(
        workspace_id=workspace_id,
        request_id="req_slice9_llm_context_enriched",
        resolved_triggers=resolved_triggers,
        failure_mode=None,
    )

    messages = captured.get("messages", [])
    rendered = "\n".join(
        str(getattr(item, "content", "")) for item in messages if hasattr(item, "content")
    )
    assert "ontology_path_context_json" in rendered
    assert "tool_capability_context" in rendered
    assert metrics["tool_capability_chain_length"] >= 1
    assert "ontology_path_count" in metrics
    assert fields["title"]


def test_slice9_hypothesis_prompt_contract_contains_prg_required_constraints() -> None:
    prompt_path = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "research_layer"
        / "prompts"
        / "hypothesis_generation.txt"
    )
    prompt = prompt_path.read_text(encoding="utf-8")
    compact_lower = prompt.lower()

    # Required structured output keys.
    assert '"title"' in prompt
    assert '"statement"' in prompt
    assert '"rationale"' in prompt
    assert '"trigger_refs"' in prompt
    assert '"testability_hint"' in prompt
    assert '"novelty_hint"' in prompt
    assert '"confidence_hint"' in prompt
    assert '"suggested_next_steps"' in prompt

    # Required context placeholders.
    assert "{workspace_id}" in prompt
    assert "{request_id}" in prompt
    assert "{existing_hypotheses_summary}" in prompt
    assert "{workspace_context_summary}" in prompt
    assert "{trigger_context_json}" in prompt

    # Explicit anti-fabrication constraints.
    assert "do not fabricate" in compact_lower
    assert "do not invent trigger ids" in compact_lower


@pytest.mark.asyncio
async def test_slice9_promote_reject_defer_state_transition_and_no_direct_route_conclusion(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_slice9_state_flow"
    seeded = _seed_workspace_for_triggers(store, workspace_id)
    detector = HypothesisTriggerDetector(store)
    service = HypothesisService(store)
    trigger_ids = [detector.list_triggers(workspace_id=workspace_id)[0]["trigger_id"]]
    route_before = store.get_route(seeded["route_id"])
    assert route_before is not None

    async def _fake_generate_with_llm(**_: object):
        return _mock_llm_payload()

    monkeypatch.setattr(service, "_generate_with_llm", _fake_generate_with_llm)
    hypothesis = await service.generate_candidate(
        workspace_id=workspace_id,
        trigger_ids=trigger_ids,
        request_id="req_slice9_promote",
        generation_job_id="job_slice9_promote",
    )
    deferred = service.defer_hypothesis(
        hypothesis_id=str(hypothesis["hypothesis_id"]),
        workspace_id=workspace_id,
        note="defer for more evidence",
        decision_source_type="manual",
        decision_source_ref="unit_test",
        request_id="req_slice9_defer",
    )
    assert deferred["status"] == "deferred"
    assert deferred["decision_source_type"] == "manual"
    assert deferred["decision_source_ref"] == "unit_test"

    promoted = service.promote_hypothesis(
        hypothesis_id=str(hypothesis["hypothesis_id"]),
        workspace_id=workspace_id,
        note="promote deferred candidate for validation",
        decision_source_type="manual",
        decision_source_ref="unit_test",
        request_id="req_slice9_promote",
    )
    assert promoted["status"] == "promoted_for_validation"

    with pytest.raises(HypothesisServiceError) as duplicate_promote_exc:
        service.promote_hypothesis(
            hypothesis_id=str(hypothesis["hypothesis_id"]),
            workspace_id=workspace_id,
            note="duplicate promote",
            decision_source_type="manual",
            decision_source_ref="unit_test",
            request_id="req_slice9_promote_duplicate",
        )
    assert duplicate_promote_exc.value.status_code == 409
    assert duplicate_promote_exc.value.error_code == "research.invalid_state"

    with pytest.raises(HypothesisServiceError) as duplicate_defer_exc:
        service.defer_hypothesis(
            hypothesis_id=str(hypothesis["hypothesis_id"]),
            workspace_id=workspace_id,
            note="cannot defer after promote",
            decision_source_type="manual",
            decision_source_ref="unit_test",
            request_id="req_slice9_defer_duplicate",
        )
    assert duplicate_defer_exc.value.status_code == 409
    assert duplicate_defer_exc.value.error_code == "research.invalid_state"

    async def _fake_generate_with_llm_second(**_: object):
        return _mock_llm_payload(
            title="Second unique candidate",
            statement="second statement with non-duplicate semantics",
            rationale="second rationale",
        )

    monkeypatch.setattr(service, "_generate_with_llm", _fake_generate_with_llm_second)
    second = await service.generate_candidate(
        workspace_id=workspace_id,
        trigger_ids=trigger_ids,
        request_id="req_slice9_reject",
        generation_job_id="job_slice9_reject",
    )
    rejected = service.reject_hypothesis(
        hypothesis_id=str(second["hypothesis_id"]),
        workspace_id=workspace_id,
        note="reject hypothesis",
        decision_source_type="manual",
        decision_source_ref="unit_test",
        request_id="req_slice9_reject",
    )
    assert rejected["status"] == "rejected"

    route_after = store.get_route(seeded["route_id"])
    assert route_after is not None
    assert route_after["conclusion"] == route_before["conclusion"]
