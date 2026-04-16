from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class LLMCallResult:
    provider_backend: str
    provider_model: str
    request_id: str
    llm_response_id: str
    usage: dict[str, int | float | str | None]
    raw_text: str
    parsed_json: dict[str, object] | list[object] | None
    fallback_used: bool
    degraded: bool
    degraded_reason: str | None


def build_trace_payload(result: LLMCallResult) -> dict[str, object]:
    return {
        "provider_backend": result.provider_backend,
        "provider_model": result.provider_model,
        "request_id": result.request_id,
        "llm_response_id": result.llm_response_id,
        "usage": _normalize_usage(result.usage),
        "fallback_used": result.fallback_used,
        "degraded": result.degraded,
        "degraded_reason": result.degraded_reason,
    }


def build_event_trace_parts(result: LLMCallResult) -> tuple[dict[str, object], dict[str, object]]:
    payload = build_trace_payload(result)
    usage = payload["usage"] if isinstance(payload.get("usage"), dict) else {}
    refs = {
        "provider_backend": payload["provider_backend"],
        "provider_model": payload["provider_model"],
        "request_id": payload["request_id"],
        "llm_response_id": payload["llm_response_id"],
    }
    metrics = {
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "fallback_used": payload["fallback_used"],
        "degraded": payload["degraded"],
    }
    if payload["degraded_reason"] is not None:
        metrics["degraded_reason"] = payload["degraded_reason"]
    return refs, metrics


def _normalize_usage(raw_usage: dict[str, int | float | str | None] | None) -> dict[str, int | float | str | None]:
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
