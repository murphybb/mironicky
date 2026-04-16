"""Scan-path helpers for registering the Mironicky research layer."""

from __future__ import annotations

import os


def get_research_layer_scan_paths(base_scan_path: str) -> list[str]:
    """Return dependency-injection scan roots for the research layer."""

    return [os.path.join(base_scan_path, "research_layer")]


def get_research_layer_task_scan_paths(base_scan_path: str) -> list[str]:
    """Return async-task scan roots for the research layer."""

    return [os.path.join(base_scan_path, "research_layer", "workers")]
