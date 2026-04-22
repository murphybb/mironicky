from __future__ import annotations

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.services.source_chunking_service import SourceChunkingService
from research_layer.services.source_parser import SourceParser


def test_chunk_plan_preserves_section_boundaries_and_hashes() -> None:
    parsed = SourceParser().parse(
        source_type="paper",
        content=(
            "1. Problem\n"
            "The first paragraph explains the problem. "
            "The second paragraph adds evidence. "
            "2. Result\n"
            "The result follows from the evidence."
        ),
    )

    plan = SourceChunkingService(max_chars=80, max_segments=2).plan(
        source_id="src_chunk", parsed=parsed
    )

    assert len(plan.chunks) >= 2
    assert all(chunk.chunk_hash for chunk in plan.chunks)
    assert all(chunk.start <= chunk.end for chunk in plan.chunks)
    assert plan.chunks[0].chunk_id == "src_chunk:chunk:0"


def test_state_store_upserts_source_chunk_cache(tmp_path) -> None:
    store = ResearchApiStateStore(db_path=str(tmp_path / "chunk_cache.sqlite3"))

    created = store.upsert_source_chunk_cache(
        workspace_id="ws_cache",
        source_id="src_cache",
        chunk_hash="hash_a",
        cache_key="candidate:argument",
        payload={"candidates": [{"candidate_id": "cand_1"}]},
    )
    updated = store.upsert_source_chunk_cache(
        workspace_id="ws_cache",
        source_id="src_cache",
        chunk_hash="hash_a",
        cache_key="candidate:argument",
        payload={"candidates": [{"candidate_id": "cand_2"}]},
    )
    loaded = store.get_source_chunk_cache(
        workspace_id="ws_cache",
        source_id="src_cache",
        chunk_hash="hash_a",
        cache_key="candidate:argument",
    )

    assert created["chunk_cache_id"] == updated["chunk_cache_id"]
    assert loaded is not None
    assert loaded["payload"]["candidates"][0]["candidate_id"] == "cand_2"
