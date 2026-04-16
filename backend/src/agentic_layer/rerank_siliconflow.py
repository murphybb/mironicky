"""
SiliconFlow Rerank Service Implementation

Reranking service using SiliconFlow's official rerank API.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from agentic_layer.rerank_interface import RerankError, RerankServiceInterface
from api_specs.memory_models import MemoryType

logger = logging.getLogger(__name__)


@dataclass
class SiliconFlowRerankConfig:
    """SiliconFlow rerank service configuration."""

    api_key: str = ""
    base_url: str = "https://api.siliconflow.cn/v1/rerank"
    model: str = "Qwen/Qwen3-Reranker-8B"
    timeout: int = 30
    max_retries: int = 3
    batch_size: int = 10
    max_concurrent_requests: int = 5


class SiliconFlowRerankService(RerankServiceInterface):
    """SiliconFlow reranking service implementation."""

    def __init__(self, config: Optional[SiliconFlowRerankConfig] = None):
        if config is None:
            config = SiliconFlowRerankConfig()

        self.config = config
        self.session: Optional[httpx.AsyncClient] = None
        self._semaphore = asyncio.Semaphore(config.max_concurrent_requests)
        logger.info(
            "Initialized SiliconFlowRerankService | url=%s | model=%s",
            config.base_url,
            config.model,
        )

    async def _ensure_session(self):
        """Ensure HTTP session is created."""
        if self.session is None or self.session.is_closed:
            self.session = httpx.AsyncClient(
                timeout=self.config.timeout,
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                },
            )

    async def close(self):
        """Close HTTP session."""
        if self.session and not self.session.is_closed:
            await self.session.aclose()

    async def _send_rerank_request_batch(
        self,
        query: str,
        documents: List[str],
        start_index: int,
        instruction: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send one batch rerank request to SiliconFlow."""
        await self._ensure_session()

        request_data: Dict[str, Any] = {
            "model": self.config.model,
            "query": query,
            "documents": documents,
            "return_documents": False,
        }
        if instruction:
            request_data["instruction"] = instruction

        async with self._semaphore:
            for attempt in range(self.config.max_retries):
                try:
                    response = await self.session.post(
                        self.config.base_url, json=request_data
                    )
                    if response.status_code == 200:
                        payload = response.json()
                        results = []
                        for item in payload.get("results", []):
                            local_index = item.get("index", 0)
                            results.append(
                                {
                                    "index": start_index + local_index,
                                    "relevance_score": item.get(
                                        "relevance_score", 0.0
                                    ),
                                }
                            )
                        return {"results": results}

                    error_text = response.text
                    logger.warning(
                        "SiliconFlow rerank API error (status %s, attempt %s/%s): %s",
                        response.status_code,
                        attempt + 1,
                        self.config.max_retries,
                        error_text,
                    )
                    should_retry = (
                        response.status_code >= 500 or response.status_code == 429
                    )
                    if should_retry and attempt < self.config.max_retries - 1:
                        await asyncio.sleep(2**attempt)
                        continue
                    if should_retry:
                        raise RerankError(
                            "SiliconFlow rerank request failed after "
                            f"{self.config.max_retries} attempts: "
                            f"{response.status_code} - {error_text}"
                        )
                    raise RerankError(
                        "SiliconFlow rerank request failed: "
                        f"{response.status_code} - {error_text}"
                    )
                except httpx.TimeoutException as exc:
                    if attempt < self.config.max_retries - 1:
                        await asyncio.sleep(2**attempt)
                        continue
                    raise RerankError(
                        "SiliconFlow rerank request timed out after "
                        f"{self.config.max_retries} attempts"
                    ) from exc
                except httpx.HTTPError as exc:
                    if attempt < self.config.max_retries - 1:
                        await asyncio.sleep(2**attempt)
                        continue
                    raise RerankError(
                        "SiliconFlow rerank request failed after "
                        f"{self.config.max_retries} attempts: {exc}"
                    ) from exc

    async def rerank_documents(
        self, query: str, documents: List[str], instruction: Optional[str] = None
    ) -> Dict[str, Any]:
        """Rerank raw documents using SiliconFlow."""
        if not documents:
            return {"results": []}

        batch_size = self.config.batch_size or 10
        batches = [
            documents[i : i + batch_size] for i in range(0, len(documents), batch_size)
        ]

        batch_tasks = []
        for i, batch in enumerate(batches):
            batch_tasks.append(
                self._send_rerank_request_batch(
                    query=query,
                    documents=batch,
                    start_index=i * batch_size,
                    instruction=instruction,
                )
            )

        batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)

        all_scores = [0.0] * len(documents)
        for i, result in enumerate(batch_results):
            if isinstance(result, Exception):
                logger.error("SiliconFlow rerank batch %s failed: %s", i, result)
                continue

            for item in result.get("results", []):
                index = item.get("index")
                if index is None or not 0 <= index < len(documents):
                    continue
                all_scores[index] = item.get("relevance_score", 0.0)

        indexed_scores = list(enumerate(all_scores))
        indexed_scores.sort(key=lambda pair: pair[1], reverse=True)

        results = []
        for rank, (original_index, score) in enumerate(indexed_scores):
            results.append({"index": original_index, "score": score, "rank": rank})

        return {"results": results}

    def _extract_text_from_hit(self, hit: Dict[str, Any]) -> str:
        """Extract and concatenate text based on memory type."""
        source = hit.get("_source", hit)
        memory_type = hit.get("memory_type", "")

        match memory_type:
            case MemoryType.EPISODIC_MEMORY.value:
                episode = source.get("episode", "")
                if episode:
                    return f"Episode Memory: {episode}"
            case MemoryType.FORESIGHT.value:
                foresight = source.get("foresight", "") or source.get("content", "")
                evidence = source.get("evidence", "")
                if foresight:
                    if evidence:
                        return f"Foresight: {foresight} (Evidence: {evidence})"
                    return f"Foresight: {foresight}"
            case MemoryType.EVENT_LOG.value:
                atomic_fact = source.get("atomic_fact", "")
                if atomic_fact:
                    return f"Atomic Fact: {atomic_fact}"

        if source.get("episode"):
            return source["episode"]
        if source.get("atomic_fact"):
            return source["atomic_fact"]
        if source.get("foresight"):
            return source["foresight"]
        if source.get("content"):
            return source["content"]
        if source.get("summary"):
            return source["summary"]
        if source.get("subject"):
            return source["subject"]
        return str(hit)

    async def rerank_memories(
        self,
        query: str,
        hits: List[Dict[str, Any]],
        top_k: Optional[int] = None,
        instruction: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Rerank memory hits using SiliconFlow."""
        if not hits:
            return []

        documents = [self._extract_text_from_hit(hit) for hit in hits]
        if not documents:
            return []

        try:
            rerank_result = await self.rerank_documents(query, documents, instruction)
            results_meta = rerank_result.get("results", [])

            reranked_hits = []
            for item in results_meta:
                original_idx = item.get("index", 0)
                score = item.get("score", 0.0)
                if 0 <= original_idx < len(hits):
                    hit = hits[original_idx].copy()
                    hit["score"] = score
                    reranked_hits.append(hit)

            if top_k is not None and top_k > 0:
                reranked_hits = reranked_hits[:top_k]

            if reranked_hits:
                top_scores = [f"{h.get('score', 0):.4f}" for h in reranked_hits[:3]]
                logger.info(
                    "SiliconFlow reranking completed: %s results, top scores: %s",
                    len(reranked_hits),
                    top_scores,
                )

            return reranked_hits
        except Exception as exc:
            logger.error("Error during SiliconFlow reranking: %s", exc)
            sorted_hits = sorted(hits, key=lambda item: item.get("score", 0), reverse=True)
            if top_k is not None and top_k > 0:
                sorted_hits = sorted_hits[:top_k]
            return sorted_hits

    def get_model_name(self) -> str:
        """Get the current model name."""
        return self.config.model
