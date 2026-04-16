---
record_type: developer_handoff
slice_id: slice_6
status: developer_complete
next_required_action: run_evaluator_for_slice_6
allowed_to_start_next_slice: false
blocking_status: awaiting_evaluator
---

# Slice 6 Developer Handoff

## Slice 约束摘要

- 仅实现 Slice 6：Scoring Engine。
- 未进入 Slice 7+：未实现 route generation/ranking、failure recompute、hypothesis、package publish。
- 评分实现遵循结构化启发式：
  - `support_score`
  - `risk_score`
  - `progressability_score`
- 评分由程序控制，LLM 不参与打分裁决。
- 输出包含 route-level 与 node-level 结构化 breakdown、Top factors、模板信息与可回链 refs。
- 缺失因子/非法模板/非法 refs/非法状态均显式错误语义，不做静默补值。
- Dev Console 已接入真实评分 API 薄封装，支持输入变化后二次评分并观察结果变化。

## 变更文件列表

- `src/research_layer/scoring/__init__.py`
- `src/research_layer/scoring/templates.py`
- `src/research_layer/scoring/heuristics.py`
- `src/research_layer/scoring/explainer.py`
- `src/research_layer/services/score_service.py`
- `src/research_layer/services/__init__.py`
- `src/research_layer/api/controllers/_state_store.py`
- `src/research_layer/api/controllers/research_route_controller.py`
- `src/research_layer/api/controllers/research_source_controller.py`
- `src/research_layer/api/schemas/route.py`
- `tests/unit/research_layer/test_slice6_scoring_service.py`
- `tests/integration/research_api/test_slice6_scoring_engine_flow.py`
- `docs/mironicky/SCORING_SPEC.md`
- `docs/mironicky/API_SPEC.md`
- `docs/mironicky/OBSERVABILITY.md`
- `docs/mironicky/DOMAIN_MODEL.md`
- `docs/mironicky/STORAGE_SCHEMA.md`
- `docs/mironicky/handoffs/slice-06.md`
- `docs/mironicky/slice_status.json`

## 测试命令与结果

- `PYTHONPATH=src uv run pytest tests/unit/research_layer/test_slice6_scoring_service.py tests/integration/research_api/test_slice6_scoring_engine_flow.py -q`
  - `8 passed`
- `PYTHONPATH=src uv run pytest tests/unit/research_layer tests/integration/research_api -q`
  - `76 passed`

## Dev Console 路径

- URL: `/api/v1/research/dev-console`
- Slice 6 最小能力（真实 API 薄封装）：
  - Recompute Route
  - Score Route
  - Load Routes
  - 查看 `support/risk/progressability`
  - 查看 `score_breakdown` / `node_score_breakdown` / `top_factors`

## startup / reset commands

- Startup（repo root）：
  - `set PYTHONPATH=src`
  - `uv run python src/run.py`
- Reset research acceptance data：
  - `set PYTHONPATH=src`
  - `uv run python -c "from research_layer.api.controllers._state_store import STORE; STORE.reset_all()"`

## fixture / demo data

- `demo/research_dev/fixtures/slice3_sources.json`
- `demo/research_dev/fixtures/slice5_graph_sources.json`

## manual steps

1. 打开 `/api/v1/research/dev-console`。
2. Import Source -> Trigger Extract -> Refresh Candidates。
3. Confirm 候选对象（包含 evidence/assumption/conflict/failure/validation）。
4. Build Graph。
5. 在 Route Scoring 区域点击 `Recompute Route` 获取 `route_id`。
6. 点击 `Score Route`，观察三分数、`score_breakdown`、`node_score_breakdown`、`top_factors`。
7. 修改一个图节点状态（例如 node status -> `failed`）并提交 update。
8. 再次点击 `Score Route`，对比分数和 breakdown 变化。

## expected observations

- `POST /api/v1/research/routes/{route_id}/score` 返回三大分数与结构化 breakdown。
- `top_factors` 长度为 3，来源于结构化因子并按 tie-break 规则稳定排序。
- `node_score_breakdown` 可回链到 `node_id/object_ref`。
- 输入变化后二次评分可观察到分数变化（例如 `risk_score` 变化）。
- `research_events` 中存在 `score_recalculated`，包含 `request_id/workspace_id/route_id` 与 metrics/error。

## 已知风险

- 当前 Slice 6 为启发式规则版本，权重与公式可扩展但需保持文档与测试同步。
- 当前 route recompute 仍是最小路线壳生成 + 实时评分，不包含 Slice 7 的 route generation/ranking 能力。
- 当前持久化为 research-layer SQLite 阶段性状态源，后续迁移到长期目标存储时需保持评分契约兼容。
