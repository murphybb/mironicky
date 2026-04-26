from __future__ import annotations

import re

from research_layer.services.prompt_renderer import (
    load_prompt_template,
    render_prompt_template,
)


PROMPT_SOURCE_VALUES = {
    "published",
    "reconstructed-from-paper",
    "code-derived",
    "local-design",
}


class HypothesisAgentBase:
    role_name: str = "base"
    prompt_file: str = ""
    prompt_source: str = "local-design"
    schema_version: str = "v1"

    def __init__(self) -> None:
        if self.prompt_source not in PROMPT_SOURCE_VALUES:
            raise ValueError(f"unsupported prompt source: {self.prompt_source}")
        if not self.prompt_file:
            raise ValueError(f"{self.__class__.__name__} must set prompt_file")
        self._prompt_template = load_prompt_template(
            f"hypothesis_multi_agent/{self.prompt_file}"
        )

    def _render_prompt(self, variables: dict[str, object]) -> str:
        return render_prompt_template(self._prompt_template, variables)

    def _base_output(self, *, rendered_prompt: str) -> dict[str, object]:
        return {
            "agent_role": self.role_name,
            "schema_version": self.schema_version,
            "prompt_source": self.prompt_source,
            "prompt_template": self.prompt_file,
            "prompt_chars": len(rendered_prompt),
        }

    def _raise_llm_gateway_only(self) -> None:
        raise RuntimeError(
            f"{self.__class__.__name__} cannot produce production output locally; "
            "invoke it through HypothesisMultiAgentOrchestrator and LLMGateway."
        )

    def _tokenize(self, text: str) -> set[str]:
        return {item for item in re.findall(r"[a-z0-9]+", text.lower()) if item}

    def _jaccard_similarity(self, left: str, right: str) -> float:
        left_tokens = self._tokenize(left)
        right_tokens = self._tokenize(right)
        if not left_tokens or not right_tokens:
            return 0.0
        intersection = left_tokens.intersection(right_tokens)
        union = left_tokens.union(right_tokens)
        if not union:
            return 0.0
        return len(intersection) / len(union)
