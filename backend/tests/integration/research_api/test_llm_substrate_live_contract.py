from __future__ import annotations

import os

import pytest

from core.component.llm.llm_adapter.message import ChatMessage, MessageRole
from research_layer.services.research_llm_dependencies import build_research_llm_gateway


def _live_enabled() -> bool:
    return os.getenv("MIRONICKY_LIVE_LLM", "0") == "1"


@pytest.mark.asyncio
@pytest.mark.skipif(not _live_enabled(), reason="set MIRONICKY_LIVE_LLM=1 for real provider contract test")
async def test_llm_substrate_contract_real_client_success() -> None:
    backend = os.getenv("MIRONICKY_LIVE_BACKEND", "qwen_test")
    model = os.getenv("MIRONICKY_LIVE_MODEL")

    gateway = build_research_llm_gateway(force_rebuild=True)
    result = await gateway.invoke_text(
        request_id="req_live_contract_success",
        prompt_name="llm_substrate_live_contract_success",
        messages=[
            ChatMessage(role=MessageRole.SYSTEM, content="You are a strict assistant."),
            ChatMessage(role=MessageRole.USER, content="Reply with one short sentence."),
        ],
        backend=backend,
        model=model,
        allow_fallback=False,
    )

    assert result.provider_backend == backend
    assert result.provider_model
    assert result.request_id == "req_live_contract_success"
    assert result.llm_response_id
    assert isinstance(result.raw_text, str) and result.raw_text.strip()
    assert isinstance(result.usage, dict)


@pytest.mark.asyncio
@pytest.mark.skipif(not _live_enabled(), reason="set MIRONICKY_LIVE_LLM=1 for real provider failure test")
async def test_llm_substrate_contract_real_client_failure_is_explicit() -> None:
    failure_backend = os.getenv("MIRONICKY_LIVE_FAILURE_BACKEND", "openai")

    gateway = build_research_llm_gateway(force_rebuild=True)
    with pytest.raises(Exception) as exc:
        await gateway.invoke_text(
            request_id="req_live_contract_failure",
            prompt_name="llm_substrate_live_contract_failure",
            messages=[ChatMessage(role=MessageRole.USER, content="hello")],
            backend=failure_backend,
            allow_fallback=False,
        )

    message = str(exc.value)
    assert "research.llm_" in message or getattr(exc.value, "error_code", "").startswith("research.llm_")
