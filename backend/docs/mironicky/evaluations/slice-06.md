---
record_type: evaluator_result
slice_id: slice_6
status: evaluator_pass
allowed_to_start_next_slice: true
blocking_status: cleared
---

# Slice 6 Evaluator Record

## Result

PASS

## Final status

- slice_6 = `evaluator_pass`
- allowed_to_start_next_slice = `true`
- blocking_status = `cleared`

## Scope

- Slice 6 only: Scoring Engine（未验收 Slice 7+ 功能）
- 覆盖验证项：
  - scoring fields / templates / heuristics / explainer / score service
  - `support_score` / `risk_score` / `progressability_score` 真实计算
  - route-level `score_breakdown` + node-level `node_score_breakdown`
  - `top_factors` 结构化输出与 tie-break 稳定性
  - 缺失因子语义、显式错误语义、workspace 边界
  - 程序规则主导评分（非 LLM 黑箱）
  - Dev Console 真实路径 + API/持久化交叉核对 + `score_recalculated` 事件白盒
- Slice 7+ 越界检查：
  - handoff 变更清单仅落在 Slice 6 相关文件（`scoring/*`, `score_service`, `route score API`, Slice 6 docs）
  - 未发现 route generation/ranking/failure recompute/hypothesis/package publish 的 Slice 7+ 验收目标偷跑实现

## Evidence

### Automated tests (minimal required)

- `PYTHONPATH=src uv run pytest tests/unit/research_layer/test_slice6_scoring_service.py tests/integration/research_api/test_slice6_scoring_engine_flow.py -q`
- Result: `8 passed in 11.35s`

### White-box code and contract checks

- `src/research_layer/scoring/templates.py`
  - 两个模板权重与 `SCORING_SPEC.md` 一致，维度权重和校验 `== 1.0`
  - `TOP_FACTOR_TIE_BREAK_ORDER` 与文档顺序一致
- `src/research_layer/scoring/heuristics.py`
  - 15 个因子按结构化公式计算并 `clamp01`
  - 缺失输入显式标记 `status=missing_input`，`normalized_value=0.0`
- `src/research_layer/scoring/explainer.py`
  - `select_top_factors()` 先按 `weighted_contribution`，再按 tie-break，最后因子名稳定排序
- `src/research_layer/services/score_service.py`
  - route/workspace/focus-node/template 错误语义均为显式 `research.*`
  - 评分结果持久化到 route（scores + breakdown + top_factors + template + scored_at）
  - 成功/失败均写入 `research_events(event_name=score_recalculated)`
- `src/research_layer/api/schemas/route.py`
  - 返回结构含三大分数、`top_factors`、`score_breakdown`、`node_score_breakdown`、`scoring_template_id`、`scored_at`
- LLM 越权检查
  - 对 scoring 核心文件检索 `llm/openai/prompt/langchain`，未发现评分裁决依赖

### API and persistence cross-check

- 页面有效评分与后端 API 交叉核对一致（同一路由）：
  - UI: `support=50.2 / risk=28.7 / progressability=66.3`
  - API: `support=50.2 / risk=28.7 / progressability=66.3`
  - `top_factor_names` 一致：`next_action_clarity, execution_cost_feasibility, assumption_burden`
- SQLite `routes` 回读：
  - `route_id=route_29684c7094ec`
  - `scoring_template_id=general_research_v1`
  - `top_factor_len=3`
  - `breakdown_keys=[support_score, risk_score, progressability_score]`
  - `node_breakdown_len=5`
- SQLite `research_events` 回读（`workspace_id=ws_slice6_playwright`）：
  - 成功事件 `score_recalculated(status=completed)` 含
    `metrics.support_score/risk_score/progressability_score/factor_count`
  - 失败事件 `score_recalculated(status=failed)` 含
    `error.error_code/error.message/error.details`
  - `refs.route_id` 与 `refs.node_ids` 可回链

## Playwright manual validation evidence

真实 Dev Console 路径：`http://127.0.0.1:2995/api/v1/research/dev-console`

执行动作与观察：

1. `Import` -> `Extract` -> `Refresh Candidates`
   - 得到 5 类候选（evidence/assumption/conflict/failure/validation）
2. 逐个 `Confirm` 后 `Build Graph from Confirmed Objects`
   - `node_count=5`, `edge_count=4`
3. `Recompute Route`
   - 产出 `route_id=route_29684c7094ec`
4. 第一次 `Score Route`
   - 三分数：`support=50.2 / risk=26.2 / progressability=70.9`
   - 返回完整 `score_breakdown`（3 维度）
   - 返回 `node_score_breakdown`（含 `node_id/object_ref_type/object_ref_id`）
   - `top_factors` 前三：`next_action_clarity`, `execution_cost_feasibility`, `assumption_burden`
5. 输入变化后再次评分（真实状态变化）
   - `Load Full Graph` 后将首个节点状态改为 `failed`，再 `Score Route`
   - 分数变化：`risk 26.2 -> 28.7`，`progressability 70.9 -> 66.3`
   - `risk.failure_pressure` 的 `normalized_value` 变为 `0.3`
6. 异常路径（真实 UI）
   - `focus_node_ids=node_missing` 后 `Score Route`
   - 返回 `400 + research.invalid_request`
   - 错误体：`focus_node_ids contain unknown node references`
7. 额外错误语义抽查（API）
   - 请求体缺失 `workspace_id` -> `400 + research.invalid_request`

证据截图（Playwright）:
- `.playwright-cli/page-2026-03-30T16-49-50-613Z.png`（有效评分）
- `.playwright-cli/page-2026-03-30T16-50-17-491Z.png`（错误态）

## Findings (ordered by severity)

- 无阻塞问题。
- `P3 (non-blocking)`：全量 `src/run.py` 启动仍依赖基础设施生命周期（Mongo 等），本次手动验收使用与集成测试同源的 research controllers 装配服务完成 Dev Console 真 API 路径验证；不影响 Slice 6 评分契约与实现正确性。

## Blocking / non-blocking judgement

- Non-blocking

## Decision

- Allowed to enter Slice 7 = YES
