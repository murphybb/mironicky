from __future__ import annotations

import pytest

from core.component.config_provider import ConfigProvider
from core.component.llm.llm_adapter.completion import ChatCompletionResponse
from core.component.llm.llm_adapter.message import ChatMessage, MessageRole
from core.component.openai_compatible_client import OpenAICompatibleClient
from research_layer.services.llm_gateway import LLMGateway, classify_provider_failure
from research_layer.services.llm_result_parser import LLMParseError, LLMResultParser
from research_layer.services.llm_trace import LLMCallResult, build_trace_payload


def test_failure_semantics_maps_auth_failure_401() -> None:
    error = RuntimeError("OpenAI chat completion request failed: 401 Unauthorized")

    mapped = classify_provider_failure(error)

    assert mapped.error_code == "research.llm_auth_failed"
    assert mapped.status_code == 502


def test_failure_semantics_maps_rate_limit_429() -> None:
    error = RuntimeError("OpenAI chat completion request failed: 429 rate limit exceeded")

    mapped = classify_provider_failure(error)

    assert mapped.error_code == "research.llm_rate_limited"
    assert mapped.status_code == 429


def test_failure_semantics_maps_timeout() -> None:
    error = TimeoutError("request timed out while waiting provider response")

    mapped = classify_provider_failure(error)

    assert mapped.error_code == "research.llm_timeout"
    assert mapped.status_code == 504


def test_failure_semantics_invalid_json_is_explicit() -> None:
    parser = LLMResultParser()

    with pytest.raises(LLMParseError) as exc:
        parser.parse_json_text("not-a-json-payload", expected_container="dict")

    assert exc.value.error_code == "research.llm_invalid_output"


def test_trace_contains_required_llm_fields() -> None:
    result = LLMCallResult(
        provider_backend="qwen_test",
        provider_model="Qwen/Qwen3-14B-AWQ",
        request_id="req_trace_001",
        llm_response_id="resp_abc",
        usage={"prompt_tokens": 10, "completion_tokens": 7, "total_tokens": 17},
        raw_text='{"ok":true}',
        parsed_json={"ok": True},
        fallback_used=False,
        degraded=False,
        degraded_reason=None,
    )

    payload = build_trace_payload(result)

    assert payload["provider_backend"] == "qwen_test"
    assert payload["provider_model"] == "Qwen/Qwen3-14B-AWQ"
    assert payload["request_id"] == "req_trace_001"
    assert payload["llm_response_id"] == "resp_abc"
    assert payload["usage"]["total_tokens"] == 17
    assert payload["fallback_used"] is False
    assert payload["degraded"] is False


def test_no_shell_gateway_rejects_fake_client_type() -> None:
    class FakeClient:
        async def chat_completion(self, *args, **kwargs):
            raise AssertionError("should never run")

    with pytest.raises(TypeError):
        LLMGateway(FakeClient())


@pytest.mark.asyncio
async def test_gateway_resolves_non_empty_provider_backend_from_default_config() -> None:
    client = OpenAICompatibleClient(ConfigProvider())
    client._config["default_backend"] = "qwen_test"

    async def _fake_chat_completion(**_: object) -> ChatCompletionResponse:
        return ChatCompletionResponse.model_validate(
            {
                "id": "resp_test_backend",
                "object": "chat.completion",
                "created": 1,
                "model": "Qwen/Qwen3-14B-AWQ",
                "choices": [
                    {"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
        )

    client.chat_completion = _fake_chat_completion  # type: ignore[assignment]
    gateway = LLMGateway(client)
    result = await gateway.invoke_text(
        request_id="req_gateway_default_backend",
        prompt_name="unit_test",
        messages=[ChatMessage(role=MessageRole.USER, content="ping")],
        allow_fallback=False,
    )
    assert result.provider_backend == "qwen_test"
