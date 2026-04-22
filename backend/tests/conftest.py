from __future__ import annotations

from pathlib import Path

import pytest

from research_layer.api.controllers._state_store import STORE


@pytest.fixture(autouse=True)
def isolate_research_state_store(tmp_path):
    original_db_path = STORE.db_path
    STORE.db_path = str(tmp_path / "research_slice2_test.sqlite3")
    Path(STORE.db_path).parent.mkdir(parents=True, exist_ok=True)
    STORE._ensure_schema()
    try:
        yield
    finally:
        STORE.db_path = original_db_path
        STORE._ensure_schema()
