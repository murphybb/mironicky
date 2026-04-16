from __future__ import annotations

import json
from dataclasses import dataclass
from json import JSONDecodeError

from core.component.llm.llm_adapter.completion import ChatCompletionResponse


@dataclass(slots=True)
class LLMParseError(Exception):
    error_code: str
    message: str
    details: dict[str, object]

    def __str__(self) -> str:
        return f"{self.error_code}: {self.message}"


class LLMResultParser:
    """Shared parser for structured LLM outputs used by research flows."""

    INVALID_OUTPUT_CODE = "research.llm_invalid_output"

    def extract_assistant_text(self, response: ChatCompletionResponse) -> str:
        if not isinstance(response, ChatCompletionResponse):
            raise LLMParseError(
                error_code=self.INVALID_OUTPUT_CODE,
                message="unsupported completion response type",
                details={"response_type": type(response).__name__},
            )

        if not response.choices:
            raise LLMParseError(
                error_code=self.INVALID_OUTPUT_CODE,
                message="empty completion choices",
                details={},
            )

        first_choice = response.choices[0]
        message_payload = first_choice.get("message", {}) if isinstance(first_choice, dict) else {}
        content = message_payload.get("content")
        if isinstance(content, list):
            content_parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    text_value = item.get("text")
                    if isinstance(text_value, str):
                        content_parts.append(text_value)
            content = "".join(content_parts)

        text = str(content or "").strip()
        if not text:
            raise LLMParseError(
                error_code=self.INVALID_OUTPUT_CODE,
                message="empty assistant content",
                details={"response_id": response.id},
            )
        return text

    def parse_json_text(
        self,
        text: str,
        *,
        expected_container: str = "any",
    ) -> dict[str, object] | list[object]:
        normalized = self._strip_code_fence(text)
        try:
            parsed = json.loads(normalized)
        except JSONDecodeError as exc:
            raise LLMParseError(
                error_code=self.INVALID_OUTPUT_CODE,
                message="invalid json from llm",
                details={
                    "json_error": str(exc),
                    "raw_preview": normalized[:200],
                },
            ) from exc

        if expected_container == "dict" and not isinstance(parsed, dict):
            raise LLMParseError(
                error_code=self.INVALID_OUTPUT_CODE,
                message="json output is not an object",
                details={"actual_type": type(parsed).__name__},
            )
        if expected_container == "list" and not isinstance(parsed, list):
            raise LLMParseError(
                error_code=self.INVALID_OUTPUT_CODE,
                message="json output is not a list",
                details={"actual_type": type(parsed).__name__},
            )
        if not isinstance(parsed, (dict, list)):
            raise LLMParseError(
                error_code=self.INVALID_OUTPUT_CODE,
                message="json output root must be object or list",
                details={"actual_type": type(parsed).__name__},
            )

        return parsed

    def _strip_code_fence(self, text: str) -> str:
        stripped = text.strip()
        if not stripped.startswith("```"):
            return stripped

        lines = stripped.splitlines()
        if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
            return "\n".join(lines[1:-1]).strip()
        return stripped
