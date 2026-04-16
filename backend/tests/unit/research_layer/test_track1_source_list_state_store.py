from __future__ import annotations

from research_layer.api.controllers._state_store import ResearchApiStateStore


def test_state_store_list_sources_is_workspace_scoped(tmp_path) -> None:
    store = ResearchApiStateStore(db_path=str(tmp_path / "research_track1.sqlite3"))
    store.create_source(
        workspace_id="ws_track1_a",
        source_type="paper",
        title="A1",
        content="content-a1",
        metadata={},
        import_request_id="req_a1",
    )
    store.create_source(
        workspace_id="ws_track1_a",
        source_type="note",
        title="A2",
        content="content-a2",
        metadata={},
        import_request_id="req_a2",
    )
    store.create_source(
        workspace_id="ws_track1_b",
        source_type="paper",
        title="B1",
        content="content-b1",
        metadata={},
        import_request_id="req_b1",
    )

    items = store.list_sources(workspace_id="ws_track1_a")

    assert len(items) == 2
    assert all(item["workspace_id"] == "ws_track1_a" for item in items)
