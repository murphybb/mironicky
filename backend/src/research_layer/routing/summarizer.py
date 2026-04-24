from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.component.llm.llm_adapter.message import ChatMessage, MessageRole

if TYPE_CHECKING:
    from research_layer.services.llm_trace import LLMCallResult


_PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"
_DEFAULT_ROUTE_SUMMARY_LLM_TIMEOUT_SECONDS = 300


def _load_prompt_template(file_name: str) -> str:
    return (_PROMPT_DIR / file_name).read_text(encoding="utf-8")


def _render_prompt_template(template: str, variables: dict[str, object]) -> str:
    rendered = template
    for key, value in variables.items():
        rendered = rendered.replace("{" + key + "}", str(value))
    return rendered


def _build_messages_from_prompt(rendered_prompt: str) -> list[ChatMessage]:
    marker = "\nUSER:\n"
    if marker in rendered_prompt:
        system_part, user_part = rendered_prompt.split(marker, 1)
    else:
        system_part = rendered_prompt
        user_part = rendered_prompt
    system_text = system_part.strip()
    if system_text.startswith("SYSTEM:"):
        system_text = system_text[len("SYSTEM:") :].strip()
    user_text = user_part.strip()
    return [
        ChatMessage(role=MessageRole.SYSTEM, content=system_text),
        ChatMessage(role=MessageRole.USER, content=user_text),
    ]


class RouteSummarizer:
    def __init__(self) -> None:
        from research_layer.services.research_llm_dependencies import (
            build_research_llm_gateway,
        )

        self._gateway = build_research_llm_gateway()
        self._prompt_template = _load_prompt_template("route_summary.txt")

    async def summarize(
        self,
        *,
        candidate: dict[str, object],
        node_map: dict[str, dict[str, object]],
        top_factors: list[dict[str, object]],
        request_id: str,
        failure_mode: str | None = None,
        allow_fallback: bool = True,
    ) -> tuple[dict[str, object], "LLMCallResult"]:
        from research_layer.services.llm_gateway import ResearchLLMError
        from research_layer.services.llm_trace import LLMCallResult

        structured = self._build_structured_context(
            candidate=candidate,
            node_map=node_map,
            top_factors=top_factors,
        )
        try:
            llm_fields, trace = await self._summarize_with_llm(
                request_id=request_id,
                structured=structured,
                failure_mode=failure_mode,
            )
            return (
                {
                    **structured,
                    "summary": llm_fields["summary"],
                    "key_strengths": llm_fields["key_strengths"],
                    "key_risks": llm_fields["key_risks"],
                    "open_questions": llm_fields["open_questions"],
                    "summary_generation_mode": "llm",
                    "degraded": bool(trace.degraded),
                    "fallback_used": bool(trace.fallback_used),
                    "degraded_reason": trace.degraded_reason,
                },
                trace,
            )
        except ResearchLLMError as exc:
            if not allow_fallback:
                raise
            fallback = self._build_fallback_summary(structured=structured)
            fallback_trace = LLMCallResult(
                provider_backend=self._resolve_backend_hint(),
                provider_model="",
                request_id=request_id,
                llm_response_id="",
                usage={
                    "prompt_tokens": None,
                    "completion_tokens": None,
                    "total_tokens": None,
                },
                raw_text="",
                parsed_json=None,
                fallback_used=True,
                degraded=True,
                degraded_reason=exc.error_code,
            )
            return (
                {
                    **fallback,
                    "summary_generation_mode": "degraded_fallback",
                    "degraded": True,
                    "fallback_used": True,
                    "degraded_reason": exc.error_code,
                },
                fallback_trace,
            )

    async def _summarize_with_llm(
        self,
        *,
        request_id: str,
        structured: dict[str, object],
        failure_mode: str | None,
    ) -> tuple[dict[str, object], "LLMCallResult"]:
        from research_layer.services.llm_gateway import ResearchLLMError
        from research_layer.services.research_llm_dependencies import (
            resolve_research_backend_and_model,
        )

        backend, model = resolve_research_backend_and_model()
        rendered = _render_prompt_template(
            self._prompt_template,
            {
                "route_id": str(structured["trace_refs"].get("route_id", "")),
                "conclusion_node_json": json.dumps(
                    structured["conclusion_node"], ensure_ascii=False
                ),
                "top_factors_json": json.dumps(
                    structured["top_factors"], ensure_ascii=False
                ),
                "key_support_nodes_json": json.dumps(
                    structured["key_support_evidence"], ensure_ascii=False
                ),
                "key_assumption_nodes_json": json.dumps(
                    structured["key_assumptions"], ensure_ascii=False
                ),
                "risk_nodes_json": json.dumps(
                    structured["conflict_failure_hints"], ensure_ascii=False
                ),
                "all_route_nodes_json": json.dumps(
                    structured["all_route_nodes"], ensure_ascii=False
                ),
                "route_edge_ids_json": json.dumps(
                    structured["trace_refs"].get("route_edge_ids", []),
                    ensure_ascii=False,
                ),
            },
        )
        llm_result = await self._gateway.invoke_json(
            request_id=request_id,
            prompt_name="route_summary",
            messages=_build_messages_from_prompt(rendered),
            expected_container="dict",
            backend=backend,
            model=model,
            timeout_s=self._resolve_llm_timeout_seconds(),
            failure_mode=failure_mode,
        )
        parsed = llm_result.parsed_json
        if not isinstance(parsed, dict):
            raise ResearchLLMError(
                status_code=502,
                error_code="research.llm_invalid_output",
                message="route summary output must be object json",
                details={},
            )

        summary = str(parsed.get("summary", "")).strip()
        if not summary:
            raise ResearchLLMError(
                status_code=502,
                error_code="research.llm_invalid_output",
                message="route summary is empty",
                details={},
            )

        allowed_node_ids = {
            str(item.get("node_id", ""))
            for item in structured.get("all_route_nodes", [])
            if isinstance(item, dict)
        }
        key_strengths = self._validate_structured_items(
            parsed.get("key_strengths"),
            allowed_node_ids=allowed_node_ids,
            field_name="key_strengths",
        )
        key_risks = self._validate_structured_items(
            parsed.get("key_risks"),
            allowed_node_ids=allowed_node_ids,
            field_name="key_risks",
        )
        open_questions = self._validate_structured_items(
            parsed.get("open_questions"),
            allowed_node_ids=allowed_node_ids,
            field_name="open_questions",
        )
        return {
            "summary": summary,
            "key_strengths": key_strengths,
            "key_risks": key_risks,
            "open_questions": open_questions,
        }, llm_result

    def _build_structured_context(
        self,
        *,
        candidate: dict[str, object],
        node_map: dict[str, dict[str, object]],
        top_factors: list[dict[str, object]],
    ) -> dict[str, object]:
        conclusion_node_id = str(candidate.get("conclusion_node_id", ""))
        conclusion_node = self._node_ref(
            node_map.get(conclusion_node_id), fallback_node_id=conclusion_node_id
        )

        key_support_node_ids = [
            str(node_id) for node_id in candidate.get("key_support_node_ids", [])
        ]
        key_assumption_node_ids = [
            str(node_id) for node_id in candidate.get("key_assumption_node_ids", [])
        ]
        risk_node_ids = [str(node_id) for node_id in candidate.get("risk_node_ids", [])]
        route_node_ids = [str(node_id) for node_id in candidate.get("route_node_ids", [])]

        key_support_evidence = [
            self._node_ref(node_map.get(node_id), fallback_node_id=node_id)
            for node_id in key_support_node_ids
        ]
        key_assumptions = [
            self._node_ref(node_map.get(node_id), fallback_node_id=node_id)
            for node_id in key_assumption_node_ids
        ]
        conflict_failure_hints = []
        for node_id in risk_node_ids:
            node = self._node_ref(node_map.get(node_id), fallback_node_id=node_id)
            hint = f"Risk signal from {node['short_label'] or node['node_id']}"
            conflict_failure_hints.append({"node": node, "hint": hint})

        next_validation_action = str(candidate.get("next_validation_action", "")).strip()
        if not next_validation_action:
            next_validation_action = (
                f"Validate conclusion node {conclusion_node['node_id']} with targeted experiment"
            )

        conclusion_label_raw = (
            conclusion_node.get("short_label", "").strip() or conclusion_node["node_id"]
        )
        conclusion_label = self._compact_label(conclusion_label_raw, max_len=40)
        title = f"路线：{conclusion_label}"
        all_route_nodes = [
            self._node_ref(node_map.get(node_id), fallback_node_id=node_id)
            for node_id in route_node_ids
        ]

        trace_refs = dict(candidate.get("trace_refs", {}))
        trace_refs.setdefault("version_id", None)
        trace_refs.setdefault("conclusion_node_id", conclusion_node_id or None)
        trace_refs["route_node_ids"] = route_node_ids
        trace_refs["route_edge_ids"] = [
            str(edge_id) for edge_id in trace_refs.get("route_edge_ids", [])
        ]

        return {
            "title": title,
            "summary": "",
            "conclusion": conclusion_label,
            "key_supports": [
                item["short_label"]
                for item in key_support_evidence
                if item["short_label"]
            ],
            "assumptions": [
                item["short_label"] for item in key_assumptions if item["short_label"]
            ],
            "risks": [item["hint"] for item in conflict_failure_hints],
            "conclusion_node": conclusion_node,
            "key_support_evidence": key_support_evidence,
            "key_assumptions": key_assumptions,
            "conflict_failure_hints": conflict_failure_hints,
            "next_validation_action": next_validation_action,
            "top_factors": top_factors[:3],
            "trace_refs": trace_refs,
            "all_route_nodes": all_route_nodes,
            "key_strengths": [],
            "key_risks": [],
            "open_questions": [],
        }

    def _build_fallback_summary(self, *, structured: dict[str, object]) -> dict[str, object]:
        conclusion = str(structured["conclusion"]).strip() or "当前路线结论"
        risk_count = len(structured["conflict_failure_hints"])
        support_count = len(structured["key_support_evidence"])
        assumption_count = len(structured["key_assumptions"])
        summary = (
            f"这条路线围绕“{conclusion}”。"
            f"当前包含 {support_count} 个支撑节点、{assumption_count} 个前提节点、{risk_count} 个风险节点。"
            "该摘要为降级结果，使用前必须回到关键节点和来源材料核验。"
        )
        return {
            **structured,
            "summary": summary,
            "key_strengths": [],
            "key_risks": [],
            "open_questions": [],
        }

    def _resolve_backend_hint(self) -> str:
        from research_layer.services.research_llm_dependencies import (
            resolve_research_backend_and_model,
        )

        backend, _ = resolve_research_backend_and_model()
        return backend or "unknown"

    def _resolve_llm_timeout_seconds(self) -> float:
        import os

        raw_value = os.getenv("RESEARCH_ROUTE_SUMMARY_LLM_TIMEOUT_SECONDS", "").strip()
        if not raw_value:
            return float(_DEFAULT_ROUTE_SUMMARY_LLM_TIMEOUT_SECONDS)
        try:
            parsed = int(raw_value)
        except ValueError:
            return float(_DEFAULT_ROUTE_SUMMARY_LLM_TIMEOUT_SECONDS)
        if parsed <= 0:
            return float(_DEFAULT_ROUTE_SUMMARY_LLM_TIMEOUT_SECONDS)
        return float(parsed)

    def _compact_label(self, raw: str, *, max_len: int = 40) -> str:
        collapsed = " ".join(str(raw or "").split())
        if not collapsed:
            return ""
        if len(collapsed) <= max_len:
            return collapsed
        return f"{collapsed[:max_len].rstrip()}..."

    def _node_ref(
        self, node: dict[str, object] | None, *, fallback_node_id: str
    ) -> dict[str, str]:
        if node is None:
            return {
                "node_id": fallback_node_id,
                "node_type": "unknown",
                "object_ref_type": "unknown",
                "object_ref_id": "",
                "short_label": fallback_node_id,
                "status": "unknown",
            }
        return {
            "node_id": str(node.get("node_id", fallback_node_id)),
            "node_type": str(node.get("node_type", "unknown")),
            "object_ref_type": str(node.get("object_ref_type", "unknown")),
            "object_ref_id": str(node.get("object_ref_id", "")),
            "short_label": str(node.get("short_label", "")),
            "status": str(node.get("status", "unknown")),
        }

    def _validate_structured_items(
        self,
        raw: Any,
        *,
        allowed_node_ids: set[str],
        field_name: str,
    ) -> list[dict[str, object]]:
        from research_layer.services.llm_gateway import ResearchLLMError

        if raw is None:
            return []
        if not isinstance(raw, list):
            raise ResearchLLMError(
                status_code=502,
                error_code="research.llm_invalid_output",
                message=f"{field_name} must be an array",
                details={"field": field_name},
            )
        normalized: list[dict[str, object]] = []
        for item in raw:
            if not isinstance(item, dict):
                raise ResearchLLMError(
                    status_code=502,
                    error_code="research.llm_invalid_output",
                    message=f"{field_name} items must be objects",
                    details={"field": field_name},
                )
            text = str(item.get("text", "")).strip()
            if not text:
                raise ResearchLLMError(
                    status_code=502,
                    error_code="research.llm_invalid_output",
                    message=f"{field_name}.text is required",
                    details={"field": field_name},
                )
            node_refs_raw = item.get("node_refs")
            if isinstance(node_refs_raw, str):
                node_refs_values: list[object] = [node_refs_raw]
            elif isinstance(node_refs_raw, list):
                node_refs_values = node_refs_raw
            elif node_refs_raw is None:
                node_refs_values = []
            else:
                raise ResearchLLMError(
                    status_code=502,
                    error_code="research.llm_invalid_output",
                    message=f"{field_name}.node_refs must be array",
                    details={"field": field_name},
                )
            node_refs = [
                str(node_id)
                for node_id in node_refs_values
                if str(node_id) in allowed_node_ids
            ]
            normalized.append({"text": text, "node_refs": node_refs})
        return normalized
