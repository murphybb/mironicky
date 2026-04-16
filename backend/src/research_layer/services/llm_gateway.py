from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from typing import Any

from core.component.llm.llm_adapter.completion import ChatCompletionResponse
from core.component.llm.llm_adapter.message import ChatMessage
from core.component.openai_compatible_client import OpenAICompatibleClient
from research_layer.services.llm_result_parser import LLMParseError, LLMResultParser
from research_layer.services.llm_trace import LLMCallResult


@dataclass(slots=True)
class ResearchLLMError(Exception):
    status_code: int
    error_code: str
    message: str
    details: dict[str, object]

    def __str__(self) -> str:
        return f"{self.error_code}: {self.message}"


def classify_provider_failure(exc: Exception) -> ResearchLLMError:
    if isinstance(exc, ResearchLLMError):
        return exc
    if isinstance(exc, LLMParseError):
        return ResearchLLMError(
            status_code=502,
            error_code="research.llm_invalid_output",
            message=exc.message,
            details=exc.details,
        )

    status_code = _extract_status_code(exc)
    message = _flatten_exception_message(exc)
    lowered = message.lower()

    if status_code in {401, 403} or _contains_any(
        lowered,
        (
            "unauthorized",
            "authentication",
            "auth failed",
            "invalid api key",
            "api key",
            "invalid_parameter",
            "permission denied",
        ),
    ):
        return ResearchLLMError(
            status_code=502,
            error_code="research.llm_auth_failed",
            message="llm provider authentication/config failed",
            details={"provider_message": message[:400]},
        )

    if status_code == 429 or _contains_any(
        lowered,
        ("rate limit", "too many requests", "429"),
    ):
        return ResearchLLMError(
            status_code=429,
            error_code="research.llm_rate_limited",
            message="llm provider rate limit",
            details={"provider_message": message[:400]},
        )

    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)) or _contains_any(
        lowered,
        ("timed out", "timeout", "read timeout", "connect timeout"),
    ):
        return ResearchLLMError(
            status_code=504,
            error_code="research.llm_timeout",
            message="llm provider timeout",
            details={"provider_message": message[:400]},
        )

    return ResearchLLMError(
        status_code=502,
        error_code="research.llm_failed",
        message="llm provider call failed",
        details={"provider_message": message[:400]},
    )


class LLMGateway:
    """Unified gateway for all research-layer LLM calls."""

    def __init__(self, client: OpenAICompatibleClient, parser: LLMResultParser | None = None) -> None:
        if not isinstance(client, OpenAICompatibleClient):
            raise TypeError(
                "LLMGateway requires OpenAICompatibleClient; fake adapter/stub is not allowed"
            )
        self._client = client
        self._parser = parser or LLMResultParser()

    async def invoke_text(
        self,
        *,
        request_id: str,
        prompt_name: str,
        messages: list[ChatMessage],
        backend: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
        timeout_s: float | None = 45.0,
        allow_fallback: bool = False,
        fallback_backend: str | None = None,
        fallback_model: str | None = None,
        fallback_on_error_codes: set[str] | None = None,
        failure_mode: str | None = None,
    ) -> LLMCallResult:
        del prompt_name  # prompt lifecycle is managed by callers; gateway handles transport/semantics only
        return await self._invoke(
            request_id=request_id,
            messages=messages,
            backend=backend,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            timeout_s=timeout_s,
            allow_fallback=allow_fallback,
            fallback_backend=fallback_backend,
            fallback_model=fallback_model,
            fallback_on_error_codes=fallback_on_error_codes,
            expect_json=False,
            expected_container="any",
            failure_mode=failure_mode,
        )

    async def invoke_json(
        self,
        *,
        request_id: str,
        prompt_name: str,
        messages: list[ChatMessage],
        backend: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
        timeout_s: float | None = 45.0,
        allow_fallback: bool = False,
        fallback_backend: str | None = None,
        fallback_model: str | None = None,
        expected_container: str = "dict",
        fallback_on_error_codes: set[str] | None = None,
        failure_mode: str | None = None,
    ) -> LLMCallResult:
        del prompt_name
        return await self._invoke(
            request_id=request_id,
            messages=messages,
            backend=backend,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            timeout_s=timeout_s,
            allow_fallback=allow_fallback,
            fallback_backend=fallback_backend,
            fallback_model=fallback_model,
            fallback_on_error_codes=fallback_on_error_codes,
            expect_json=True,
            expected_container=expected_container,
            failure_mode=failure_mode,
        )

    async def _invoke(
        self,
        *,
        request_id: str,
        messages: list[ChatMessage],
        backend: str | None,
        model: str | None,
        temperature: float | None,
        max_tokens: int | None,
        top_p: float | None,
        timeout_s: float | None,
        allow_fallback: bool,
        fallback_backend: str | None,
        fallback_model: str | None,
        fallback_on_error_codes: set[str] | None,
        expect_json: bool,
        expected_container: str,
        failure_mode: str | None,
    ) -> LLMCallResult:
        resolved_backend = backend or self._resolve_backend_name()
        resolved_failure_mode = (
            failure_mode or os.getenv("RESEARCH_LLM_FAILURE_MODE") or ""
        ).strip() or None
        try:
            return await self._call_once(
                request_id=request_id,
                messages=messages,
                backend=resolved_backend,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                top_p=top_p,
                timeout_s=timeout_s,
                expect_json=expect_json,
                expected_container=expected_container,
                failure_mode=resolved_failure_mode,
            )
        except Exception as exc:
            primary_error = classify_provider_failure(exc)
            if not allow_fallback or not fallback_backend:
                raise primary_error from exc
            if (
                fallback_on_error_codes is not None
                and primary_error.error_code not in fallback_on_error_codes
            ):
                raise primary_error from exc

            try:
                fallback_result = await self._call_once(
                    request_id=request_id,
                    messages=messages,
                    backend=fallback_backend,
                    model=fallback_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    top_p=top_p,
                    timeout_s=timeout_s,
                    expect_json=expect_json,
                    expected_container=expected_container,
                    failure_mode=None,
                )
            except Exception as fallback_exc:
                fallback_error = classify_provider_failure(fallback_exc)
                raise ResearchLLMError(
                    status_code=fallback_error.status_code,
                    error_code=fallback_error.error_code,
                    message=fallback_error.message,
                    details={
                        **fallback_error.details,
                        "primary_error_code": primary_error.error_code,
                        "fallback_backend": fallback_backend,
                    },
                ) from fallback_exc

            fallback_result.fallback_used = True
            fallback_result.degraded = True
            fallback_result.degraded_reason = primary_error.error_code
            return fallback_result

    async def _call_once(
        self,
        *,
        request_id: str,
        messages: list[ChatMessage],
        backend: str | None,
        model: str | None,
        temperature: float | None,
        max_tokens: int | None,
        top_p: float | None,
        timeout_s: float | None,
        expect_json: bool,
        expected_container: str,
        failure_mode: str | None,
    ) -> LLMCallResult:
        self._raise_if_injected_failure(failure_mode=failure_mode, expect_json=expect_json)
        completion_coro = self._client.chat_completion(
            messages=messages,
            backend=backend,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            stream=False,
        )
        response_any = (
            await asyncio.wait_for(completion_coro, timeout=timeout_s)
            if timeout_s is not None
            else await completion_coro
        )

        if not isinstance(response_any, ChatCompletionResponse):
            raise ResearchLLMError(
                status_code=502,
                error_code="research.llm_failed",
                message="chat completion returned unsupported response type",
                details={"response_type": type(response_any).__name__},
            )

        raw_text = self._parser.extract_assistant_text(response_any)
        parsed_json: dict[str, object] | list[object] | None = None
        if expect_json:
            parsed_json = self._parser.parse_json_text(
                raw_text,
                expected_container=expected_container,
            )

        usage = _normalize_usage(response_any.usage)
        provider_model = str(response_any.model or model or "")
        llm_response_id = str(response_any.id or "")
        if not backend:
            raise ResearchLLMError(
                status_code=502,
                error_code="research.llm_trace_missing",
                message="provider backend missing in llm result",
                details={},
            )
        return LLMCallResult(
            provider_backend=str(backend),
            provider_model=provider_model,
            request_id=request_id,
            llm_response_id=llm_response_id,
            usage=usage,
            raw_text=raw_text,
            parsed_json=parsed_json,
            fallback_used=False,
            degraded=False,
            degraded_reason=None,
        )

    def _resolve_backend_name(self) -> str:
        config = getattr(self._client, "_config", {})
        backend = ""
        if isinstance(config, dict):
            backend = str(config.get("default_backend", "")).strip()
        if backend:
            return backend
        raise ResearchLLMError(
            status_code=502,
            error_code="research.llm_trace_missing",
            message="default backend is missing",
            details={},
        )

    def _raise_if_injected_failure(self, *, failure_mode: str | None, expect_json: bool) -> None:
        if failure_mode is None:
            return
        mode = failure_mode.strip().lower()
        if not mode:
            return
        if mode == "auth_401":
            raise ResearchLLMError(
                status_code=502,
                error_code="research.llm_auth_failed",
                message="llm provider authentication/config failed",
                details={"provider_message": "injected auth_401 failure"},
            )
        if mode == "rate_limit_429":
            raise ResearchLLMError(
                status_code=429,
                error_code="research.llm_rate_limited",
                message="llm provider rate limit",
                details={"provider_message": "injected rate_limit_429 failure"},
            )
        if mode == "timeout":
            raise ResearchLLMError(
                status_code=504,
                error_code="research.llm_timeout",
                message="llm provider timeout",
                details={"provider_message": "injected timeout failure"},
            )
        if mode == "invalid_json" and expect_json:
            raise LLMParseError(
                error_code="research.llm_invalid_output",
                message="invalid json from llm",
                details={"provider_message": "injected invalid_json failure"},
            )


def _normalize_usage(raw_usage: dict[str, Any] | None) -> dict[str, int | float | str | None]:
    usage = raw_usage or {}
    return {
        "prompt_tokens": _to_number_or_none(usage.get("prompt_tokens")),
        "completion_tokens": _to_number_or_none(usage.get("completion_tokens")),
        "total_tokens": _to_number_or_none(usage.get("total_tokens")),
    }


def _to_number_or_none(value: object) -> int | float | str | None:
    if value is None:
        return None
    if isinstance(value, (int, float, str)):
        return value
    return str(value)


def _extract_status_code(exc: Exception) -> int | None:
    for attr in ("status_code", "status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    if response is not None:
        for attr in ("status_code", "status"):
            value = getattr(response, attr, None)
            if isinstance(value, int):
                return value
    message = _flatten_exception_message(exc)
    match = re.search(r"\b(401|403|429|5\d\d)\b", message)
    if match:
        return int(match.group(1))
    return None


def _flatten_exception_message(exc: Exception) -> str:
    parts = [str(exc)]
    current = exc
    for _ in range(3):
        cause = getattr(current, "__cause__", None)
        if not isinstance(cause, Exception):
            break
        parts.append(str(cause))
        current = cause
    return " | ".join(part for part in parts if part)


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)
