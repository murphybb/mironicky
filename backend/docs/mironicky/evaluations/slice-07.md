---
record_type: evaluator_result
slice_id: slice_7
status: evaluator_pass
allowed_to_start_next_slice: true
blocking_status: cleared
---

# Slice 7 Evaluator Record

## Result

PASS

## Final status

- slice_7 = `evaluator_pass`
- allowed_to_start_next_slice = `true`
- blocking_status = `cleared`

## Scope

- Slice 7 only: Route Generation + Ranking + Preview
- 验证范围：
  - candidate builder / route ranker / route summarizer
  - route generation API / route list API / route preview API
  - 图谱生成多候选、排序规则、Top 3 因子、traceability
  - Dev Console 真实手动路径（Playwright）
  - 异常语义与结构化事件 `route_generation_*`
- Slice 8+ 越界检查：
  - 未发现 `diff_created` / `recompute_started` / `recompute_completed` 等 Slice 8 事件落地到 Slice 7 核心实现。
  - `POST /routes/recompute` 保持 Slice 6/7 兼容入口，仅委托 route generation，不承载 Slice 8 diff 语义。

## Evidence

### Automated tests (minimal required)

- `PYTHONPATH=src uv run pytest tests/unit/research_layer/test_slice7_route_engine.py tests/integration/research_api/test_slice7_route_generation_flow.py -q`
- Result: `6 passed in 9.36s`

### White-box checks

- `src/research_layer/routing/candidate_builder.py`
  - 候选构建输入直接来自 `graph_nodes/graph_edges`，输出含 `conclusion_node_id/route_node_ids/.../trace_refs`。
  - 支持一跳子图构建与多候选去重，非 hard-coded route。
- `src/research_layer/routing/ranker.py`
  - 排序键为：`support desc -> risk asc -> progressability desc -> private_dependency_pressure asc -> route_id asc`。
  - 无 LLM 参与排序裁决。
- `src/research_layer/routing/summarizer.py`
  - 负责 preview 结构组装与解释文本，不改写排序/分数。
- `src/research_layer/services/route_generation_service.py`
  - 流程：build candidates -> create route -> score_route -> rank_routes -> persist/list。
  - 结构化事件覆盖 `route_generation_started` / `route_generation_completed`（success/fail）。
  - success metrics 含 `graph_node_count/graph_edge_count/candidate_count/generated_route_count/ranked_route_ids/top_factors`。
- `src/research_layer/api/controllers/research_route_controller.py`
  - `GET /routes` 强制按 ranker 返回顺序。
  - `GET /routes/{route_id}/preview` 返回完整结构化字段并校验 workspace ownership。

### API / data cross-check

- 实际 workspace：`ws_slice7_eval`
- 图谱状态：`graph_node_count=7`, `graph_edge_count=5`
- route list：
  - `total=5`（多候选成立）
  - API 顺序与文档比较器排序完全一致（`order_matches_spec=true`）
- route preview：
  - 字段完整：`conclusion_node/key_support_evidence/key_assumptions/conflict_failure_hints/next_validation_action/top_factors/trace_refs`
  - `top_factors` 长度稳定为 `3`
  - route 与 preview 回链一致（`key_assumption_node_ids`、`risk_node_ids`、`trace_refs.route_node_ids`）
- 异常语义：
  - graph 未就绪触发 `POST /routes/generate` -> `409 + research.invalid_state`
  - Dev Console 缺失 `workspace_id` -> `research.invalid_request`
  - Dev Console 非法 `route_id` preview -> `research.not_found`

## Playwright manual validation evidence

入口：`http://127.0.0.1:1995/api/v1/research/dev-console`

执行动作与观察：

1. 在 Dev Console 点击 `Generate Routes`
   - 首次结果：`generated_count=5`，`ranked_route_ids` 返回 5 条
2. 点击 `Load Routes`
   - 排序按 rank 返回，且与后端 API 顺序一致
3. 点击 `Load Route Preview`
   - 可查看结论节点、关键支撑、关键假设、冲突/失败提示、下一步验证动作、Top 3 因子
4. 调整真实输入条件（Graph Node Update）
   - 将 `node_e4bad4e9d86a` 状态更新为 `failed`
5. 再次点击 `Generate Routes` + `Load Routes`
   - 排序结果发生变化（首轮 route ids 与二轮 route ids 不同）
6. 异常路径
   - workspace 置空后 `Load Routes`，返回 `research.invalid_request`
   - route_id 设置 `route_missing` 后 `Load Route Preview`，返回 `research.not_found`

Playwright 证据截图：

- `output/playwright/slice7_route_generation_first.png`
- `output/playwright/slice7_route_list_first.png`
- `output/playwright/slice7_route_preview_first.png`
- `output/playwright/slice7_route_list_after_input_change.png`
- `output/playwright/slice7_route_preview_with_conflicts.png`
- `output/playwright/slice7_error_missing_workspace.png`
- `output/playwright/slice7_error_invalid_route_id.png`

## Findings (ordered by severity)

- 无阻塞问题。
- `P3 (non-blocking)`：Dev Console 的 graph node update 会同时提交当前 `short_label` 输入值；本次用于输入变化复验不会破坏 Slice 7 契约，但操作时需注意该副作用。

## Blocking / non-blocking judgement

- Non-blocking

## Decision

- Allowed to enter Slice 8 = YES
