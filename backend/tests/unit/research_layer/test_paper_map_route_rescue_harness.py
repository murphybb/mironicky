from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_harness_module():
    script_path = (
        Path(__file__).resolve().parents[3]
        / "scripts"
        / "verify_real_pdf_paper_map_route_rescue.py"
    )
    spec = importlib.util.spec_from_file_location(
        "verify_real_pdf_paper_map_route_rescue", script_path
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_real_pdf_harness_rejects_dirty_workspace_before_import(monkeypatch) -> None:
    harness = _load_harness_module()

    def fake_request_json(**kwargs):
        path = kwargs["path"]
        if path == "/api/v1/research/candidates":
            return {"items": [{"candidate_id": "old_candidate"}]}
        if path.startswith("/api/v1/research/graph/"):
            return {"nodes": [], "edges": []}
        if path == "/api/v1/research/routes":
            return {"items": []}
        raise AssertionError(f"unexpected request {path}")

    monkeypatch.setattr(harness, "_request_json", fake_request_json)
    failures: list[str] = []

    is_empty = harness._preflight_workspace_is_empty(
        base_url="http://127.0.0.1:1996",
        workspace_id="ws_dirty",
        failures=failures,
    )

    assert is_empty is False
    assert failures == ["workspace_not_empty_candidates"]


def test_real_pdf_harness_allows_empty_workspace(monkeypatch) -> None:
    harness = _load_harness_module()

    def fake_request_json(**kwargs):
        path = kwargs["path"]
        if path == "/api/v1/research/candidates":
            return {"items": []}
        if path.startswith("/api/v1/research/graph/"):
            return {"nodes": [], "edges": []}
        if path == "/api/v1/research/routes":
            return {"items": []}
        raise AssertionError(f"unexpected request {path}")

    monkeypatch.setattr(harness, "_request_json", fake_request_json)
    failures: list[str] = []

    is_empty = harness._preflight_workspace_is_empty(
        base_url="http://127.0.0.1:1996",
        workspace_id="ws_empty",
        failures=failures,
    )

    assert is_empty is True
    assert failures == []
