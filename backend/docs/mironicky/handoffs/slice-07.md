---
record_type: developer_handoff
slice_id: slice_7
status: developer_complete
next_required_action: run_evaluator_for_slice_7
allowed_to_start_next_slice: false
blocking_status: awaiting_evaluator
---

# Slice 7 Developer Handoff

## Slice 约束摘要

- 仅实现 Slice 7：Route Generation + Ranking + Preview。
- 未进入 Slice 8+：未实现 failure recompute、version diff、hypothesis、package publish。
- 已落地核心模块：
  - candidate builder（真实 graph -> 多候选 route）
  - route ranker（纯程序规则比较器）
  - route summarizer（摘要/解释，不参与排序裁决）
  - route generation API
  - route list API（按 rank 输出）
  - route preview API（结构化 preview + trace refs）
- 排序规则遵循文档：`support desc -> risk asc -> progressability desc -> private_dependency_pressure asc -> route_id asc`。
- LLM 未参与 route rank 裁决；排名仅由程序规则与结构化分数驱动。
- `top_factors` 由结构化评分输出并稳定返回，preview 中固定返回 Top 3。
- route 与 graph/formal object/score breakdown 保持可追溯（`conclusion_node_id` / `route_node_ids` / `version_id` / breakdown refs）。
- Dev Console 使用真实 API 薄封装，支持输入变化后二次生成并观察排序变化。

## 变更文件列表

- `src/research_layer/routing/__init__.py`
- `src/research_layer/routing/candidate_builder.py`
- `src/research_layer/routing/ranker.py`
- `src/research_layer/routing/summarizer.py`
- `src/research_layer/services/route_generation_service.py`
- `src/research_layer/services/score_service.py`
- `src/research_layer/services/__init__.py`
- `src/research_layer/api/controllers/research_route_controller.py`
- `src/research_layer/api/controllers/research_source_controller.py`
- `src/research_layer/api/controllers/_state_store.py`
- `src/research_layer/api/schemas/route.py`
- `tests/unit/research_layer/test_slice7_route_engine.py`
- `tests/integration/research_api/test_slice7_route_generation_flow.py`
- `docs/mironicky/ROUTE_ENGINE_SPEC.md`
- `docs/mironicky/SCORING_SPEC.md`
- `docs/mironicky/API_SPEC.md`
- `docs/mironicky/OBSERVABILITY.md`
- `docs/mironicky/handoffs/slice-07.md`
- `docs/mironicky/slice_status.json`

## 测试命令与结果

1. Red（TDD 失败基线）
   - `PYTHONPATH=src uv run pytest tests/unit/research_layer/test_slice7_route_engine.py tests/integration/research_api/test_slice7_route_generation_flow.py -q`
   - 结果：`ERROR`（`ModuleNotFoundError: research_layer.routing.candidate_builder`）
2. Slice 7 新增测试
   - `PYTHONPATH=src uv run pytest tests/unit/research_layer/test_slice7_route_engine.py tests/integration/research_api/test_slice7_route_generation_flow.py -q`
   - 结果：`6 passed`
3. Slice 6 回归
   - `PYTHONPATH=src uv run pytest tests/unit/research_layer/test_slice6_scoring_service.py tests/integration/research_api/test_slice6_scoring_engine_flow.py -q`
   - 结果：`8 passed`
4. Slice 6+7 组合回归
   - `PYTHONPATH=src uv run pytest tests/unit/research_layer/test_slice7_route_engine.py tests/integration/research_api/test_slice7_route_generation_flow.py tests/unit/research_layer/test_slice6_scoring_service.py tests/integration/research_api/test_slice6_scoring_engine_flow.py -q`
   - 结果：`14 passed`
5. research layer 全量单测+集成
   - `PYTHONPATH=src uv run pytest tests/unit/research_layer tests/integration/research_api -q`
   - 结果：`82 passed`

## Dev Console 路径

- URL: `/api/v1/research/dev-console`
- Slice 7 最小能力（真实 API 薄封装）：
  - Generate Routes
  - Load Routes
  - Load Route Preview
  - 查看 Top 3 Factors（score/preview 返回）
  - 修改图节点状态后重新 Generate Routes，观察排序变化

## startup / reset commands

- Startup（repo root）：
  - `set PYTHONPATH=src`
  - `uv run python src/run.py`
- Reset research acceptance data：
  - `set PYTHONPATH=src`
  - `uv run python -c "from research_layer.api.controllers._state_store import STORE; STORE.reset_all()"`

## fixture / demo data

- 自动化测试内置 deterministic 输入：
  - `tests/unit/research_layer/test_slice7_route_engine.py`
  - `tests/integration/research_api/test_slice7_route_generation_flow.py`
- 可选已有 demo fixture：
  - `demo/research_dev/fixtures/slice3_sources.json`
  - `demo/research_dev/fixtures/slice5_graph_sources.json`

## manual steps

1. 打开 `/api/v1/research/dev-console`。
2. 导入至少两个 source（建议一个偏 validation、一个含 conflict/failure）。
3. Trigger Extract -> Refresh Candidates -> 全部 Confirm。
4. Build Graph。
5. 点击 `Generate Routes`。
6. 点击 `Load Routes`，记录排序。
7. 点击 `Load Route Preview`，检查结构化字段完整性。
8. 通过 Graph Node Update 将某个 conclusion node 标记为 `failed`。
9. 再次 `Generate Routes` + `Load Routes`，观察排序变化。

## expected observations

- route list 至少返回多条候选路线，且顺序满足 rank comparator。
- route preview 至少返回：
  - `conclusion_node`
  - `key_support_evidence`
  - `key_assumptions`
  - `conflict_failure_hints`
  - `next_validation_action`
  - `top_factors`（长度 3）
- 输入变化后二次生成会导致 route ranking 实际变化。
- `research_events` 可见：
  - `route_generation_started`
  - `route_generation_completed`（含 metrics/top_factors）

## 已知风险

- 当前 candidate builder 使用“一跳子图”策略，适合 Slice 7 最小可用实现；后续可扩展为更复杂路径搜索。
- summarizer 目前以程序模板为主，未接入外部 LLM 润色链路；但已满足“LLM 不越权裁决排序”的硬约束。
- 当前持久化仍为 research-layer SQLite 阶段态，后续迁移需保持 route/preview/traceability 契约不变。
