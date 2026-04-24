from __future__ import annotations

import json
from json import JSONDecodeError
from typing import Any

from research_layer.services.argument_graph_types import normalize_unit_type
from research_layer.services.llm_gateway import ResearchLLMError
from research_layer.services.llm_trace import LLMCallResult
from research_layer.services.prompt_renderer import (
    build_messages_from_prompt,
    load_prompt_template,
    render_prompt_template,
)

_MAX_ARGUMENT_UNITS = 12


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return stripped


def _parse_unit_payload(raw_text: str) -> dict[str, object]:
    normalized = _strip_code_fence(raw_text)
    try:
        parsed = json.loads(normalized)
    except JSONDecodeError as exc:
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
    return parsed


def _as_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


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


class ArgumentUnitExtractionService:
    prompt_file_name = "argument_unit_extractor_prompt.txt"

    def __init__(self, gateway: Any) -> None:
        self._gateway = gateway

    async def extract_units(
        self,
        *,
        request_id: str,
        workspace_id: str,
        source_id: str,
        source_title: str,
        source_type: str,
        chunk_id: str,
        chunk_section: str,
        chunk_text: str,
        anchor_refs: list[dict[str, object]],
        document_reading_memo: str,
        artifact_profile: dict[str, object],
        max_tokens: int,
        timeout_s: float,
        failure_mode: str | None,
        backend: str | None = None,
        model: str | None = None,
    ) -> tuple[list[dict[str, object]], LLMCallResult]:
        prompt_file_name = self._select_prompt_file_name(artifact_profile)
        prompt = render_prompt_template(
            load_prompt_template(prompt_file_name),
            {
                "workspace_id": workspace_id,
                "source_id": source_id,
                "source_title": source_title,
                "source_type": source_type,
                "chunk_id": chunk_id,
                "chunk_section": chunk_section,
                "chunk_text": chunk_text,
                "anchor_refs_json": json.dumps(anchor_refs, ensure_ascii=False),
                "document_reading_memo": document_reading_memo,
                "artifact_profile_json": json.dumps(
                    artifact_profile, ensure_ascii=False
                ),
            },
        )
        try:
            result = await self._invoke_unit_text(
                request_id=request_id,
                prompt_name=self._prompt_name_for_file(prompt_file_name),
                prompt=prompt,
                backend=backend,
                model=model,
                max_tokens=max_tokens,
                timeout_s=timeout_s,
                failure_mode=failure_mode,
            )
            payload = _parse_unit_payload(result.raw_text)
        except ResearchLLMError as exc:
            if exc.error_code != "research.llm_invalid_output":
                raise
            retry_prompt = (
                f"{prompt}\n\n"
                "The previous answer was rejected because it was not valid JSON. "
                "Return valid minified JSON only. Return at most 8 units. "
                "Keep text and quote under 140 characters each. "
                "If unsure, return {\"domain_profile\":[],\"units\":[]}."
            )
            result = await self._invoke_unit_text(
                request_id=request_id,
                prompt_name=f"{self._prompt_name_for_file(prompt_file_name)}_retry",
                prompt=retry_prompt,
                backend=backend,
                model=model,
                max_tokens=min(max_tokens, 4000),
                timeout_s=timeout_s,
                failure_mode=None,
            )
            payload = _parse_unit_payload(result.raw_text)
        result.parsed_json = payload
        raw_units = payload.get("units", [])
        if not isinstance(raw_units, list):
            raise ResearchLLMError(
                status_code=502,
                error_code="research.llm_invalid_output",
                message="invalid argument unit payload",
                details={},
            )
        payload_domain_profile = _as_string_list(payload.get("domain_profile"))

        units: list[dict[str, object]] = []
        for index, item in enumerate(raw_units):
            if not isinstance(item, dict):
                continue
            semantic_type = (
                str(item.get("semantic_type") or item.get("type") or "").strip().lower()
            )
            if not semantic_type:
                continue
            try:
                candidate_type = normalize_unit_type(semantic_type)
            except KeyError:
                continue
            text = str(item.get("text") or item.get("body") or "").strip()
            quote = str(item.get("quote") or item.get("evidence_quote") or "").strip()
            if not text and quote:
                text = quote
            if not text:
                continue
            anchor = item.get("anchor")
            if not isinstance(anchor, dict):
                anchor = {}
            domain_profile = (
                _as_string_list(item.get("domain_profile")) or payload_domain_profile
            )
            domain_tags = _as_string_list(item.get("domain_tags"))
            confidence_score = _as_confidence_score(item.get("confidence_score"))
            units.append(
                {
                    "unit_id": str(item.get("unit_id") or f"u{index + 1}"),
                    "semantic_type": semantic_type,
                    "candidate_type": candidate_type,
                    "text": text,
                    "normalized_label": str(item.get("normalized_label") or "").strip(),
                    "domain_profile": domain_profile,
                    "domain_tags": domain_tags,
                    "confidence_score": confidence_score,
                    "quote": quote or text,
                    "anchor": anchor,
                }
            )
        return units[:_MAX_ARGUMENT_UNITS], result

    def _select_prompt_file_name(self, artifact_profile: dict[str, object]) -> str:
        focus = str(
            artifact_profile.get("extraction_focus")
            or artifact_profile.get("dominant_artifact_type")
            or "text"
        ).strip().lower()
        if focus == "table":
            return "argument_unit_extractor_table_prompt.txt"
        if focus == "formula":
            return "argument_unit_extractor_formula_prompt.txt"
        if focus == "figure":
            return "argument_unit_extractor_figure_prompt.txt"
        if focus == "code":
            return "argument_unit_extractor_code_prompt.txt"
        return self.prompt_file_name

    def _prompt_name_for_file(self, prompt_file_name: str) -> str:
        if prompt_file_name == self.prompt_file_name:
            return "argument_unit_extraction"
        return f"argument_unit_extraction_{prompt_file_name.removesuffix('_prompt.txt')}"

    async def _invoke_unit_text(
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
