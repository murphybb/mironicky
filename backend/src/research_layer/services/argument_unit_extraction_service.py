from __future__ import annotations

import json
from typing import Any

from research_layer.services.argument_graph_types import normalize_unit_type
from research_layer.services.llm_gateway import ResearchLLMError
from research_layer.services.llm_trace import LLMCallResult
from research_layer.services.prompt_renderer import (
    build_messages_from_prompt,
    load_prompt_template,
    render_prompt_template,
)

_MAX_ARGUMENT_UNITS = 24


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
        chunk_text: str,
        anchor_refs: list[dict[str, object]],
        document_reading_memo: str,
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
                "source_title": source_title,
                "source_type": source_type,
                "chunk_id": chunk_id,
                "chunk_text": chunk_text,
                "anchor_refs_json": json.dumps(anchor_refs, ensure_ascii=False),
                "document_reading_memo": document_reading_memo,
            },
        )
        result = await self._gateway.invoke_json(
            request_id=request_id,
            prompt_name="argument_unit_extraction",
            messages=build_messages_from_prompt(prompt),
            backend=backend,
            model=model,
            max_tokens=max_tokens,
            timeout_s=timeout_s,
            allow_fallback=False,
            expected_container="dict",
            failure_mode=failure_mode,
        )
        payload = result.parsed_json if isinstance(result.parsed_json, dict) else {}
        raw_units = payload.get("units", [])
        if not isinstance(raw_units, list):
            raise ResearchLLMError(
                status_code=502,
                error_code="research.llm_invalid_output",
                message="invalid argument unit payload",
                details={},
            )

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
            units.append(
                {
                    "unit_id": str(item.get("unit_id") or f"u{index + 1}"),
                    "semantic_type": semantic_type,
                    "candidate_type": candidate_type,
                    "text": text,
                    "quote": quote or text,
                    "anchor": anchor,
                }
            )
        return units[:_MAX_ARGUMENT_UNITS], result
