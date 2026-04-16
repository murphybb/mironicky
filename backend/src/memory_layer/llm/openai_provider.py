"""
OpenAI-compatible LLM provider implementation.

This provider supports OpenRouter-specific routing hints when configured,
while remaining compatible with standard OpenAI-style chat/completions APIs.
"""

import asyncio
import json
import os
import random
import time
from typing import Optional

import httpx

from core.observation.logger import get_logger
from memory_layer.llm.protocol import LLMError, LLMProvider

logger = get_logger(__name__)


class OpenAIProvider(LLMProvider):
    """
    OpenAI-compatible LLM provider.

    This provider can talk to OpenRouter or any OpenAI-compatible endpoint
    through the same chat/completions interface.
    """

    def __init__(
        self,
        model: str = "MiniMax-M2.5",
        api_key: str | None = None,
        base_url: str | None = None,
        temperature: float = 0.3,
        max_tokens: int | None = 100 * 1024,
        enable_stats: bool = False,
        **kwargs,
    ):
        del kwargs
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.enable_stats = enable_stats

        self.api_key = (
            api_key
            or os.getenv("LLM_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("OPENROUTER_API_KEY")
        )
        self.base_url = (
            base_url
            or os.getenv("LLM_BASE_URL")
            or os.getenv("OPENAI_BASE_URL")
            or "https://api.scnet.cn/api/llm/v1"
        )

        if self.enable_stats:
            self.current_call_stats = None

    async def generate(
        self,
        prompt: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        extra_body: dict | None = None,
        response_format: dict | None = None,
    ) -> str:
        start_time = time.perf_counter()

        if os.getenv("LLM_OPENROUTER_PROVIDER", "default") != "default":
            provider_str = os.getenv("LLM_OPENROUTER_PROVIDER")
            provider_list = [p.strip() for p in provider_str.split(",")]
            openrouter_provider = {
                "order": provider_list,
                "allow_fallbacks": False,
            }
        else:
            openrouter_provider = None

        data = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature if temperature is not None else self.temperature,
        }
        if openrouter_provider is not None:
            data["provider"] = openrouter_provider
        if response_format is not None:
            data["response_format"] = response_format
        if extra_body:
            data.update(extra_body)

        if max_tokens is not None:
            data["max_tokens"] = max_tokens
        elif self.max_tokens is not None:
            data["max_tokens"] = self.max_tokens

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        max_retries = 5
        for retry_num in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=600.0) as client:
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        json=data,
                        headers=headers,
                    )

                try:
                    response_data = response.json()
                except json.JSONDecodeError:
                    response_data = {}

                if response.status_code != 200:
                    error_msg = response_data.get("error", {}).get(
                        "message", response.text or f"HTTP {response.status_code}"
                    )
                    logger.error(
                        f"鉂?[OpenAI-{self.model}] HTTP error {response.status_code}:"
                    )
                    logger.error(f"   馃挰 Error message: {error_msg}")
                    if response.status_code == 429:
                        logger.warning("429 Too Many Requests, waiting before retry")
                        await asyncio.sleep(random.randint(5, 20))
                    raise LLMError(
                        f"HTTP Error {response.status_code}: {error_msg}"
                    )

                end_time = time.perf_counter()
                finish_reason = response_data.get("choices", [{}])[0].get(
                    "finish_reason", ""
                )
                if finish_reason == "stop":
                    logger.debug(
                        f"[OpenAI-{self.model}] Finish reason: {finish_reason}"
                    )
                else:
                    logger.warning(
                        f"[OpenAI-{self.model}] Finish reason: {finish_reason}"
                    )

                usage = response_data.get("usage", {})
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)
                total_tokens = usage.get("total_tokens", 0)

                logger.debug(f"[OpenAI-{self.model}] API call completed:")
                logger.debug(
                    f"[OpenAI-{self.model}] Duration: {end_time - start_time:.2f}s"
                )
                if end_time - start_time > 30:
                    logger.warning(
                        f"[OpenAI-{self.model}] Duration too long: {end_time - start_time:.2f}s"
                    )
                logger.debug(
                    f"[OpenAI-{self.model}] Prompt Tokens: {prompt_tokens:,}"
                )
                logger.debug(
                    f"[OpenAI-{self.model}] Completion Tokens: {completion_tokens:,}"
                )
                logger.debug(f"[OpenAI-{self.model}] Total Tokens: {total_tokens:,}")

                if self.enable_stats:
                    self.current_call_stats = {
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": total_tokens,
                        "duration": end_time - start_time,
                        "timestamp": time.time(),
                    }

                return response_data["choices"][0]["message"]["content"]

            except httpx.HTTPError as e:
                error_time = time.perf_counter()
                logger.error("httpx.HTTPError: %s", e)
                logger.error(f"   鈴憋笍  Duration: {error_time - start_time:.2f}s")
                logger.error(f"   馃挰 Error message: {str(e)}")
                logger.error(f"retry_num: {retry_num}")
                if retry_num == max_retries - 1:
                    raise LLMError(f"Request failed: {str(e)}")
            except Exception as e:
                error_time = time.perf_counter()
                logger.error("Exception: %s", e)
                logger.error(f"   鈴憋笍  Duration: {error_time - start_time:.2f}s")
                logger.error(f"   馃挰 Error message: {str(e)}")
                logger.error(f"retry_num: {retry_num}")
                if retry_num == max_retries - 1:
                    raise LLMError(f"Request failed: {str(e)}")

    async def test_connection(self) -> bool:
        """
        Test the connection to the configured API endpoint.
        """
        try:
            logger.info(f"馃敆 [OpenAI-{self.model}] Testing API connection...")
            test_response = await self.generate("Hello", temperature=0.1)
            success = len(test_response) > 0
            if success:
                logger.info(f"鉁?[OpenAI-{self.model}] API connection test succeeded")
            else:
                logger.error(
                    f"鉂?[OpenAI-{self.model}] API connection test failed: Empty response"
                )
            return success
        except Exception as e:
            logger.error(f"鉂?[OpenAI-{self.model}] API connection test failed: {e}")
            return False

    def get_current_call_stats(self) -> Optional[dict]:
        if self.enable_stats:
            return self.current_call_stats
        return None

    def __repr__(self) -> str:
        return f"OpenAIProvider(model={self.model}, base_url={self.base_url})"
