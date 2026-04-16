import os

from research_layer.bootstrap import (
    get_research_layer_scan_paths,
    get_research_layer_task_scan_paths,
)


def test_research_layer_scan_paths_are_rooted_under_src():
    base_scan_path = os.path.join("tmp", "src")

    assert get_research_layer_scan_paths(base_scan_path) == [
        os.path.join(base_scan_path, "research_layer")
    ]


def test_research_layer_task_scan_paths_are_rooted_under_workers():
    base_scan_path = os.path.join("tmp", "src")

    assert get_research_layer_task_scan_paths(base_scan_path) == [
        os.path.join(base_scan_path, "research_layer", "workers")
    ]
