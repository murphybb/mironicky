from __future__ import annotations

import json
from typing import Any

from research_layer.services.argument_graph_types import normalize_relation_type
from research_layer.services.llm_gateway import ResearchLLMError
from research_layer.services.llm_trace import LLMCallResult
from research_layer.services.prompt_renderer import (
    build_messages_from_prompt,
    load_prompt_template,
    render_prompt_template,
)


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
        result = await self._gateway.invoke_json(
            request_id=request_id,
            prompt_name="argument_relation_rebuild",
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
                relation_status = "resolved"
            except KeyError:
                relation_type = None
                relation_status = "unresolved"
            relations.append(
                {
                    "source_unit_id": str(item.get("source_unit_id") or ""),
                    "target_unit_id": str(item.get("target_unit_id") or ""),
                    "semantic_relation_type": semantic_relation_type,
                    "relation_type": relation_type,
                    "relation_status": relation_status,
                    "quote": str(item.get("quote") or "").strip(),
                }
            )
        return relations, result
