from __future__ import annotations


class ToolCapabilityGraphService:
    _NODES: list[dict[str, object]] = [
        {
            "tool_id": "retrieval_views",
            "category": "retrieval",
            "purpose": "collect evidence, contradiction, failure, validation and hypothesis support views",
            "inputs": ["workspace_id", "query", "view_types"],
            "outputs": ["retrieval_items", "trace_refs"],
        },
        {
            "tool_id": "logical_subgraph",
            "category": "graph_reasoning",
            "purpose": "expand graph neighborhood from formal refs and seed nodes",
            "inputs": ["formal_refs", "seed_node_ids"],
            "outputs": ["subgraph_nodes", "subgraph_edges", "trace_refs"],
        },
        {
            "tool_id": "hypothesis_generation",
            "category": "reasoning",
            "purpose": "generate candidate hypothesis from triggers and graph context",
            "inputs": ["trigger_refs", "workspace_context"],
            "outputs": ["hypothesis_candidate", "minimum_validation_action"],
        },
        {
            "tool_id": "failure_impact",
            "category": "failure_loop",
            "purpose": "project impact of failures onto routes and graph",
            "inputs": ["failure_ids", "route_ids", "graph_version"],
            "outputs": ["impact_map", "weakened_targets"],
        },
        {
            "tool_id": "score_route",
            "category": "evaluation",
            "purpose": "score route support/risk/progressability and produce critique",
            "inputs": ["route_id", "scoring_factors"],
            "outputs": ["score_breakdown", "reviewer_critique"],
        },
        {
            "tool_id": "validation_planner",
            "category": "validation",
            "purpose": "materialize minimum validation action for the hypothesis or route",
            "inputs": ["target_object", "weakening_signal"],
            "outputs": ["validation_action"],
        },
        {
            "tool_id": "package_build",
            "category": "publication",
            "purpose": "build replay-ready package snapshot with publish review",
            "inputs": ["included_routes", "included_nodes", "included_validations"],
            "outputs": ["snapshot_payload", "pre_publish_review"],
        },
    ]

    _EDGES: list[dict[str, str]] = [
        {"from": "retrieval_views", "to": "logical_subgraph", "relation": "grounds"},
        {"from": "logical_subgraph", "to": "hypothesis_generation", "relation": "context"},
        {"from": "hypothesis_generation", "to": "validation_planner", "relation": "requires"},
        {"from": "hypothesis_generation", "to": "score_route", "relation": "evaluated_by"},
        {"from": "failure_impact", "to": "hypothesis_generation", "relation": "steers"},
        {"from": "score_route", "to": "package_build", "relation": "feeds_publish"},
        {"from": "validation_planner", "to": "package_build", "relation": "feeds_publish"},
    ]

    def graph_definition(self) -> dict[str, object]:
        return {
            "version": "tool_capability_graph.v1",
            "nodes": [dict(item) for item in self._NODES],
            "edges": [dict(item) for item in self._EDGES],
        }

    def plan_for_hypothesis(
        self,
        *,
        trigger_types: list[str],
        retrieve_method: str = "hybrid",
    ) -> dict[str, object]:
        normalized_types = sorted(
            {str(item).strip() for item in trigger_types if str(item).strip()}
        )
        chain = ["retrieval_views"]
        if retrieve_method == "logical":
            chain.append("logical_subgraph")
        if {"failure", "conflict"} & set(normalized_types):
            chain.append("failure_impact")
        chain.extend(["hypothesis_generation", "score_route", "validation_planner"])
        return self._build_plan(
            chain=chain,
            scenario="hypothesis_generation",
            trigger_types=normalized_types,
            retrieve_method=retrieve_method,
        )

    def plan_for_memory(
        self,
        *,
        view_types: list[str],
        retrieve_method: str,
    ) -> dict[str, object]:
        normalized_views = sorted(
            {str(item).strip() for item in view_types if str(item).strip()}
        )
        chain = ["retrieval_views"]
        if retrieve_method == "logical":
            chain.append("logical_subgraph")
        if {"failure_pattern", "contradiction"} & set(normalized_views):
            chain.append("failure_impact")
        chain.extend(["hypothesis_generation", "validation_planner"])
        return self._build_plan(
            chain=chain,
            scenario="memory_assisted_reasoning",
            trigger_types=normalized_views,
            retrieve_method=retrieve_method,
        )

    def _build_plan(
        self,
        *,
        chain: list[str],
        scenario: str,
        trigger_types: list[str],
        retrieve_method: str,
    ) -> dict[str, object]:
        node_map = {str(item["tool_id"]): item for item in self._NODES}
        selected_chain = [
            {
                "step": index + 1,
                "tool_id": tool_id,
                "category": str(node_map.get(tool_id, {}).get("category", "unknown")),
                "purpose": str(node_map.get(tool_id, {}).get("purpose", "")),
            }
            for index, tool_id in enumerate(chain)
        ]
        dispatch_hints = []
        for item in selected_chain:
            tool_id = str(item["tool_id"])
            if tool_id == "retrieval_views":
                hint = "先把可用证据和冲突读模型拉齐，避免空推理。"
            elif tool_id == "logical_subgraph":
                hint = "把 formal_refs 映射到图，再沿邻接边扩展，减少上下文漂移。"
            elif tool_id == "failure_impact":
                hint = "把失败信号先投影到路线和节点，避免忽略反例。"
            elif tool_id == "hypothesis_generation":
                hint = "在结构化上下文里生成候选，不直接裸 prompt。"
            elif tool_id == "score_route":
                hint = "用评分与审稿式挑刺过滤低质量候选。"
            elif tool_id == "validation_planner":
                hint = "把猜想变成最小验证动作，确保可执行。"
            else:
                hint = "按能力图约束输入输出，保持可追溯。"
            dispatch_hints.append(
                {"tool_id": tool_id, "hint": hint, "required_inputs": node_map.get(tool_id, {}).get("inputs", [])}
            )
        return {
            "scenario": scenario,
            "retrieve_method": retrieve_method,
            "trigger_types": trigger_types,
            "chain_length": len(selected_chain),
            "selected_chain": selected_chain,
            "dispatch_hints": dispatch_hints,
            "graph_ref": {"version": "tool_capability_graph.v1"},
        }
