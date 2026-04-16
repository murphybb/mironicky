from __future__ import annotations

from research_layer.services.tool_capability_graph_service import (
    ToolCapabilityGraphService,
)


def test_slice9_tool_capability_graph_definition_has_nodes_and_edges() -> None:
    service = ToolCapabilityGraphService()
    graph = service.graph_definition()
    assert graph["version"] == "tool_capability_graph.v1"
    assert len(graph["nodes"]) >= 6
    assert len(graph["edges"]) >= 5


def test_slice9_tool_plan_for_hypothesis_includes_failure_impact_when_failure_triggered() -> None:
    service = ToolCapabilityGraphService()
    plan = service.plan_for_hypothesis(
        trigger_types=["failure", "weak_support"], retrieve_method="logical"
    )
    chain = [str(item["tool_id"]) for item in plan["selected_chain"]]
    assert plan["scenario"] == "hypothesis_generation"
    assert plan["retrieve_method"] == "logical"
    assert "logical_subgraph" in chain
    assert "failure_impact" in chain
    assert "hypothesis_generation" in chain
    assert "score_route" in chain
    assert plan["chain_length"] == len(chain)


def test_slice9_tool_plan_for_memory_uses_view_types_to_shape_chain() -> None:
    service = ToolCapabilityGraphService()
    plan = service.plan_for_memory(
        view_types=["evidence", "contradiction"], retrieve_method="hybrid"
    )
    chain = [str(item["tool_id"]) for item in plan["selected_chain"]]
    assert plan["scenario"] == "memory_assisted_reasoning"
    assert chain[0] == "retrieval_views"
    assert "failure_impact" in chain
    assert "validation_planner" in chain
