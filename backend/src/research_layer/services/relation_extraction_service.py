from __future__ import annotations

import json
import re
from json import JSONDecodeError
from typing import Any

from research_layer.services.argument_graph_types import normalize_relation_type
from research_layer.services.llm_gateway import ResearchLLMError
from research_layer.services.llm_trace import LLMCallResult
from research_layer.services.prompt_renderer import (
    build_messages_from_prompt,
    load_prompt_template,
    render_prompt_template,
)

_MAX_ARGUMENT_RELATIONS = 36
_JSON_RETRY_MAX_RELATIONS = 12


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return stripped


def _parse_relation_payload(raw_text: str) -> tuple[dict[str, object], bool]:
    normalized = _strip_code_fence(raw_text)
    repaired_text = _repair_common_relation_json_typos(normalized)
    try:
        parsed = json.loads(repaired_text)
    except JSONDecodeError as exc:
        repaired_relations = _extract_valid_relation_objects(repaired_text)
        if repaired_relations:
            return {"relations": repaired_relations}, True
        raise ResearchLLMError(
            status_code=502,
            error_code="research.llm_invalid_output",
            message="invalid json from llm",
            details={"json_error": str(exc), "raw_preview": normalized[:200]},
        ) from exc
    if not isinstance(parsed, dict):
        raise ResearchLLMError(
            status_code=502,
            error_code="research.llm_invalid_output",
            message="json output is not an object",
            details={"actual_type": type(parsed).__name__},
        )
    return parsed, repaired_text != normalized


def _repair_common_relation_json_typos(raw_text: str) -> str:
    return re.sub(
        r'("confidence_score"\s*:\s*)([0-9]+(?:\.[0-9]+)?)"',
        r"\1\2",
        raw_text,
    )


def _extract_valid_relation_objects(raw_text: str) -> list[dict[str, object]]:
    relations: list[dict[str, object]] = []
    for match in re.finditer(
        r'\{[^{}]*"source_unit_id"[^{}]*"target_unit_id"[^{}]*\}',
        raw_text,
        re.DOTALL,
    ):
        try:
            item = json.loads(match.group(0))
        except JSONDecodeError:
            continue
        if isinstance(item, dict):
            relations.append(item)
    return relations[:_JSON_RETRY_MAX_RELATIONS]


def _as_confidence_label(value: object) -> str:
    normalized = str(value or "EXTRACTED").strip().upper()
    if normalized not in {"EXTRACTED", "INFERRED", "AMBIGUOUS"}:
        return "AMBIGUOUS"
    return normalized


def _as_confidence_score(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    if isinstance(value, str):
        try:
            return max(0.0, min(1.0, float(value.strip())))
        except ValueError:
            return None
    return None


class RelationExtractionService:
    prompt_file_name = "argument_relation_rebuilder_prompt.txt"

    def __init__(self, gateway: Any) -> None:
        self._gateway = gateway

    async def rebuild_relations(
        self,
        *,
        request_id: str,
        workspace_id: str,
        source_id: str,
        units: list[dict[str, object]],
        chunk_text: str,
        max_tokens: int,
        timeout_s: float,
        failure_mode: str | None,
        backend: str | None = None,
        model: str | None = None,
    ) -> tuple[list[dict[str, object]], LLMCallResult]:
        prompt = render_prompt_template(
            load_prompt_template(self.prompt_file_name),
            {
                "workspace_id": workspace_id,
                "source_id": source_id,
                "units_json": json.dumps(units, ensure_ascii=False),
                "chunk_text": chunk_text,
            },
        )
        try:
            result = await self._invoke_relation_text(
                request_id=request_id,
                prompt_name="argument_relation_rebuild",
                prompt=prompt,
                backend=backend,
                model=model,
                max_tokens=max_tokens,
                timeout_s=timeout_s,
                failure_mode=failure_mode,
            )
            payload, repaired = _parse_relation_payload(result.raw_text)
        except ResearchLLMError as exc:
            if exc.error_code != "research.llm_invalid_output":
                raise
            retry_prompt = (
                f"{prompt}\n\n"
                "The previous answer was rejected because it was not valid JSON. "
                "Return valid minified JSON only. "
                f"Return at most {_JSON_RETRY_MAX_RELATIONS} relations. "
                "Keep each quote under 120 characters. "
                "Escape every JSON string correctly. "
                "If no relation is directly supported, return {\"relations\":[]}."
            )
            result = await self._invoke_relation_text(
                request_id=request_id,
                prompt_name="argument_relation_rebuild_retry",
                prompt=retry_prompt,
                backend=backend,
                model=model,
                max_tokens=min(max_tokens, 4000),
                timeout_s=timeout_s,
                failure_mode=None,
            )
            payload, repaired = _parse_relation_payload(result.raw_text)
        result.parsed_json = payload
        if repaired:
            result.degraded = True
            result.degraded_reason = "research.llm_json_repaired"
        raw_relations = payload.get("relations", [])
        if not isinstance(raw_relations, list):
            raise ResearchLLMError(
                status_code=502,
                error_code="research.llm_invalid_output",
                message="invalid argument relation payload",
                details={},
            )

        relations: list[dict[str, object]] = []
        for item in raw_relations:
            if not isinstance(item, dict):
                continue
            semantic_relation_type = (
                str(
                    item.get("semantic_relation_type")
                    or item.get("relation_type")
                    or ""
                )
                .strip()
                .lower()
            )
            try:
                relation_type: str | None = normalize_relation_type(
                    semantic_relation_type
                )
            except KeyError:
                relation_type = None
            confidence_label = _as_confidence_label(item.get("confidence_label"))
            confidence_score = _as_confidence_score(item.get("confidence_score"))
            relation_status = (
                "resolved"
                if relation_type is not None and confidence_label == "EXTRACTED"
                else "unresolved"
            )
            relations.append(
                {
                    "source_unit_id": str(item.get("source_unit_id") or ""),
                    "target_unit_id": str(item.get("target_unit_id") or ""),
                    "semantic_relation_type": semantic_relation_type,
                    "relation_type": relation_type,
                    "relation_status": relation_status,
                    "confidence_label": confidence_label,
                    "confidence_score": confidence_score,
                    "quote": str(item.get("quote") or "").strip(),
                }
            )
        return relations[:_MAX_ARGUMENT_RELATIONS], result

    async def _invoke_relation_text(
        self,
        *,
        request_id: str,
        prompt_name: str,
        prompt: str,
        backend: str | None,
        model: str | None,
        max_tokens: int,
        timeout_s: float,
        failure_mode: str | None,
    ) -> LLMCallResult:
        return await self._gateway.invoke_text(
            request_id=request_id,
            prompt_name=prompt_name,
            messages=build_messages_from_prompt(prompt),
            backend=backend,
            model=model,
            temperature=0,
            max_tokens=max_tokens,
            timeout_s=timeout_s,
            allow_fallback=False,
            failure_mode=failure_mode,
        )
