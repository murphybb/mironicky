from __future__ import annotations

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.services.candidate_confirmation_service import normalize_candidate_text
from research_layer.services.graphrag_service import GraphRAGService


def _build_store(tmp_path) -> ResearchApiStateStore:
    return ResearchApiStateStore(db_path=str(tmp_path / "graphrag.sqlite3"))


def _seed_claim(store: ResearchApiStateStore, workspace_id: str) -> dict[str, object]:
    source = store.create_source(
        workspace_id=workspace_id,
        source_type="paper",
        title="Grounded latency study",
        content="Claim: shard imbalance increases timeout latency.",
        metadata={},
        import_request_id="req_graphrag_seed",
    )
    batch = store.create_candidate_batch(
        workspace_id=workspace_id,
        source_id=str(source["source_id"]),
        job_id="job_graphrag_seed",
        request_id="req_graphrag_seed",
    )
    candidate = store.add_candidates_to_batch(
        candidate_batch_id=str(batch["candidate_batch_id"]),
        workspace_id=workspace_id,
        source_id=str(source["source_id"]),
        job_id="job_graphrag_seed",
        candidates=[
            {
                "candidate_type": "evidence",
                "text": "shard imbalance increases timeout latency",
                "source_span": {"start": 7, "end": 49},
                "extractor_name": "test_graphrag",
            }
        ],
    )[0]
    object_ref = store.create_confirmed_object_from_candidate(
        candidate=candidate,
        normalized_text=normalize_candidate_text(str(candidate["text"])),
        request_id="req_graphrag_confirm",
    )
    claim = store.create_claim_from_candidate(
        candidate=candidate,
        normalized_text=normalize_candidate_text(str(candidate["text"])),
    )
    node = store.create_graph_node(
        workspace_id=workspace_id,
        node_type="evidence",
        object_ref_type=str(object_ref["object_type"]),
        object_ref_id=str(object_ref["object_id"]),
        short_label="Latency evidence",
        full_description="Evidence node for timeout latency",
        claim_id=str(claim["claim_id"]),
        source_ref={"source_id": str(source["source_id"])},
    )
    return {
        "source": source,
        "object_ref": object_ref,
        "claim": claim,
        "node": node,
    }


class FakeRetrievalService:
    def __init__(self, item: dict[str, object] | None) -> None:
        self.item = item
        self.calls: list[dict[str, object]] = []

    def retrieve(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        items = [self.item] if self.item and kwargs["view_type"] == "evidence" else []
        return {
            "view_type": kwargs["view_type"],
            "workspace_id": kwargs["workspace_id"],
            "retrieve_method": kwargs["retrieve_method"],
            "total": len(items),
            "items": items,
            "memory_recall": None,
        }


class FakeRecallService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def recall(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        return {
            "status": "completed",
            "requested_method": kwargs["requested_method"],
            "applied_method": kwargs["requested_method"],
            "reason": None,
            "query_text": kwargs["query_text"],
            "total": 1,
            "items": [
                {
                    "memory_type": "event_log",
                    "memory_id": "mem_graph_1",
                    "score": 0.8,
                    "title": "prior shard memory",
                    "snippet": "previous shard imbalance incident",
                    "timestamp": None,
                    "linked_claim_refs": [{"claim_id": kwargs["scope_claim_ids"][0]}],
                    "trace_refs": {},
                }
            ],
            "trace_refs": {"from": "fake"},
        }


def test_graphrag_answer_returns_citations_and_scoped_memory_recall(tmp_path) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_graphrag_citations"
    seeded = _seed_claim(store, workspace_id)
    claim_id = str(seeded["claim"]["claim_id"])
    source_id = str(seeded["source"]["source_id"])
    node_id = str(seeded["node"]["node_id"])
    item = {
        "result_id": f"evidence:{seeded['object_ref']['object_id']}",
        "score": 0.91,
        "title": "Grounded latency study",
        "snippet": "shard imbalance increases timeout latency",
        "source_ref": {"source_id": source_id, "title": "Grounded latency study"},
        "graph_refs": {"node_ids": [node_id], "edge_ids": [], "version_id": "v1"},
        "formal_refs": [seeded["object_ref"]],
        "trace_refs": {"graph_refs": {"node_ids": [node_id]}},
        "evidence_refs": [{"ref_id": "eref_1", "source_id": source_id}],
    }
    retrieval = FakeRetrievalService(item)
    recall = FakeRecallService()
    service = GraphRAGService(store, retrieval_service=retrieval, recall_service=recall)

    result = service.answer(
        workspace_id=workspace_id,
        question="What increases timeout latency?",
        request_id="req_graphrag_query",
        limit=8,
    )

    assert result["answer"].startswith("Based on 1 grounded claim")
    assert result["citations"][0]["claim_id"] == claim_id
    assert result["citations"][0]["text"] == "shard imbalance increases timeout latency"
    assert result["citations"][0]["source_ref"]["source_id"] == source_id
    assert result["citations"][0]["score"] == 0.91
    assert result["citations"][0]["graph_refs"]["node_ids"] == [node_id]
    assert result["memory_recall"]["items"][0]["memory_id"] == "mem_graph_1"
    assert recall.calls[0]["scope_claim_ids"] == [claim_id]
    assert recall.calls[0]["reason"] == "graphrag_query"
    assert recall.calls[0]["trace_refs"]["reason"] == "graphrag_query"
    assert recall.calls[0]["trace_refs"]["request_id"] == "req_graphrag_query"
    assert result["trace_refs"]["request_id"] == "req_graphrag_query"


def test_graphrag_answer_without_citations_does_not_fabricate_answer(tmp_path) -> None:
    store = _build_store(tmp_path)
    retrieval = FakeRetrievalService(None)
    recall = FakeRecallService()
    service = GraphRAGService(store, retrieval_service=retrieval, recall_service=recall)

    result = service.answer(
        workspace_id="ws_graphrag_empty",
        question="What causes latency?",
        request_id="req_graphrag_empty",
        limit=8,
    )

    assert result["citations"] == []
    assert "not enough claim evidence" in result["answer"]
    assert result["memory_recall"]["status"] == "skipped"
    assert result["memory_recall"]["reason"] == "no_claim_citations"
    assert recall.calls == []
