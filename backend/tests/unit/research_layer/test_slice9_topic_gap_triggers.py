from __future__ import annotations

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.services.hypothesis_trigger_detector import HypothesisTriggerDetector
from research_layer.services.source_import_service import SourceImportService


def _build_store(tmp_path) -> ResearchApiStateStore:
    return ResearchApiStateStore(db_path=str(tmp_path / "slice9_topic_gap.sqlite3"))


def test_slice9_source_import_persists_deterministic_topic_clusters(tmp_path) -> None:
    store = _build_store(tmp_path)
    service = SourceImportService(store)
    workspace_id = "ws_slice9_topic_cluster_import"

    source = service.import_source(
        workspace_id=workspace_id,
        source_type="paper",
        title="Queue Retrieval Latency Study",
        content=(
            "Queue latency in retrieval pipeline causes queue backlog. "
            "Queue scheduling and latency controls improve retrieval stability."
        ),
        metadata={},
        source_input_mode="manual_text",
        source_input=None,
        source_url=None,
        local_file=None,
        request_id="req_slice9_topic_cluster_import",
    )

    metadata = source.get("metadata", {})
    assert isinstance(metadata, dict)
    assert metadata.get("topic_cluster_version") == "deterministic_v1"
    clusters = metadata.get("topic_clusters")
    assert isinstance(clusters, list) and clusters
    first = clusters[0]
    assert isinstance(first, dict)
    assert first.get("cluster_id")
    assert isinstance(first.get("keywords"), list) and first["keywords"]


def test_slice9_trigger_detector_emits_explainable_topic_gap_cluster_triggers(
    tmp_path,
) -> None:
    store = _build_store(tmp_path)
    importer = SourceImportService(store)
    detector = HypothesisTriggerDetector(store)
    workspace_id = "ws_slice9_topic_gap_triggers"

    importer.import_source(
        workspace_id=workspace_id,
        source_type="paper",
        title="Queue Stability Notes",
        content=(
            "Queue backlog impacts retrieval latency. "
            "Queue saturation degrades retrieval quality."
        ),
        metadata={},
        source_input_mode="manual_text",
        source_input=None,
        source_url=None,
        local_file=None,
        request_id="req_slice9_gap_src_queue_1",
    )
    importer.import_source(
        workspace_id=workspace_id,
        source_type="paper",
        title="Queue Load Analysis",
        content=(
            "Queue control and queue draining strategies reduce retrieval tail latency."
        ),
        metadata={},
        source_input_mode="manual_text",
        source_input=None,
        source_url=None,
        local_file=None,
        request_id="req_slice9_gap_src_queue_2",
    )
    importer.import_source(
        workspace_id=workspace_id,
        source_type="paper",
        title="Schema Drift Monitoring",
        content=(
            "Schema drift can produce contradiction across schema versions and alerts."
        ),
        metadata={},
        source_input_mode="manual_text",
        source_input=None,
        source_url=None,
        local_file=None,
        request_id="req_slice9_gap_src_schema",
    )
    importer.import_source(
        workspace_id=workspace_id,
        source_type="paper",
        title="Bioseal Primitive Intro",
        content=(
            "Bioseal orchestration and bioseal primitive design introduce bioseal policy."
        ),
        metadata={},
        source_input_mode="manual_text",
        source_input=None,
        source_url=None,
        local_file=None,
        request_id="req_slice9_gap_src_bioseal_1",
    )
    importer.import_source(
        workspace_id=workspace_id,
        source_type="paper",
        title="Bioseal Runtime Notes",
        content="Bioseal runtime and bioseal envelope remain under active exploration.",
        metadata={},
        source_input_mode="manual_text",
        source_input=None,
        source_url=None,
        local_file=None,
        request_id="req_slice9_gap_src_bioseal_2",
    )

    store.create_route(
        workspace_id=workspace_id,
        title="Queue path route",
        summary="queue retrieval route has weak support",
        status="weakened",
        support_score=42.0,
        risk_score=63.0,
        progressability_score=39.0,
        conclusion="queue route needs more support",
        key_supports=["queue evidence limited"],
        assumptions=["queue saturation hypothesis"],
        risks=["queue regression risk"],
        next_validation_action="collect additional queue traces",
        route_node_ids=[],
        key_support_node_ids=[],
        key_assumption_node_ids=[],
        risk_node_ids=[],
        conclusion_node_id=None,
        version_id="ver_slice9_topic_gap",
    )
    store.create_graph_node(
        workspace_id=workspace_id,
        node_type="conflict",
        object_ref_type="conflict",
        object_ref_id="schema_conflict_1",
        short_label="Schema drift conflict",
        full_description="schema drift contradiction remains unresolved",
        status="active",
    )

    triggers = detector.list_triggers(workspace_id=workspace_id)
    cluster_triggers = [
        item
        for item in triggers
        if str(item.get("object_ref_type", "")) == "research_gap_cluster"
    ]
    assert cluster_triggers

    reason_to_types: dict[str, set[str]] = {}
    for trigger in cluster_triggers:
        trace_refs = trigger.get("trace_refs", {})
        assert isinstance(trace_refs, dict)
        reason = str(trace_refs.get("gap_reason", "")).strip()
        if not reason:
            continue
        reason_to_types.setdefault(reason, set()).add(str(trigger["trigger_type"]))
        assert isinstance(trace_refs.get("cluster_keywords"), list)
        assert isinstance(trace_refs.get("source_ids"), list)
        assert trigger.get("summary")

    assert "low_support" in reason_to_types
    assert "high_conflict" in reason_to_types
    assert "empty_theme" in reason_to_types
    assert "weak_support" in reason_to_types["low_support"]
    assert "conflict" in reason_to_types["high_conflict"]
    assert "gap" in reason_to_types["empty_theme"]
