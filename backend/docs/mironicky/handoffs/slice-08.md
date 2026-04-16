---
record_type: developer_handoff
slice_id: slice_8
status: developer_complete
next_required_action: run_evaluator_for_slice_8
allowed_to_start_next_slice: false
blocking_status: awaiting_evaluator
---

# Slice 8 Developer Handoff

## Slice 约束摘要

- 仅实现 Slice 8：`Failure Loop + Recompute + Version Diff`。
- 未进入 Slice 9+：未实现 hypothesis engine 与 package publish。
- `failure` 支持挂载到 `node/edge`，挂载后真实影响 graph/route 状态（非标签）。
- `recompute` 为真实后端重算（状态、分数、路线、版本、diff），非前端刷新。
- `version diff` 覆盖并持久化：`added/weakened/invalidated/branch_changes`，并保留 `failure/version` 回链。
- 异步 recompute 接入统一 job 契约，并可通过 `result_ref(resource_type=graph_version)` 回链到 diff。

## 变更文件列表

- `src/research_layer/services/failure_impact_service.py`
- `src/research_layer/services/recompute_service.py`
- `src/research_layer/services/version_diff_service.py`
- `src/research_layer/services/__init__.py`
- `src/research_layer/api/controllers/research_failure_controller.py`
- `src/research_layer/api/controllers/research_route_controller.py`
- `src/research_layer/api/controllers/research_source_controller.py`
- `src/research_layer/api/controllers/_state_store.py`
- `src/research_layer/api/schemas/failure.py`
- `src/research_layer/api/schemas/route.py`
- `tests/unit/research_layer/test_slice8_failure_loop_services.py`
- `tests/integration/research_api/test_slice8_failure_recompute_diff_flow.py`
- `docs/mironicky/FAILURE_LOOP_SPEC.md`
- `docs/mironicky/API_SPEC.md`
- `docs/mironicky/OBSERVABILITY.md`
- `docs/mironicky/DOMAIN_MODEL.md`
- `docs/mironicky/STORAGE_SCHEMA.md`
- `docs/mironicky/handoffs/slice-08.md`
- `docs/mironicky/slice_status.json`

## 测试命令与结果

1. `PYTHONPATH=src uv run pytest tests/unit/research_layer/test_slice8_failure_loop_services.py tests/integration/research_api/test_slice8_failure_recompute_diff_flow.py -q`
   - 结果：`ERROR`（`ModuleNotFoundError: research_layer.services.failure_impact_service`，TDD 红测基线）
2. `PYTHONPATH=src uv run pytest tests/unit/research_layer/test_slice8_failure_loop_services.py tests/integration/research_api/test_slice8_failure_recompute_diff_flow.py -q`
   - 结果：`6 passed`
3. `PYTHONPATH=src uv run pytest tests/unit/research_layer/test_slice7_route_engine.py tests/integration/research_api/test_slice7_route_generation_flow.py -q`
   - 结果：`6 passed`
4. `PYTHONPATH=src uv run pytest tests/integration/research_api/test_slice6_scoring_engine_flow.py -q`
   - 结果：`3 passed`
5. `PYTHONPATH=src uv run pytest tests/unit/research_layer tests/integration/research_api -q`
   - 结果：`88 passed`

## Dev Console 路径

- URL: `/api/v1/research/dev-console`
- Slice 8 最小能力（真实 API 薄封装）：
  - `Attach Failure`
  - `Load Failure`
  - `Recompute From Failure`
  - `Load Job Status`
  - `Load Version Diff`
  - 复用 `Load Full Graph` / `Load Routes` 观察 node/edge/route 状态变化

## startup / reset commands

- Startup（repo root）：
  - `set PYTHONPATH=src`
  - `uv run python src/run.py`
- Reset research acceptance data：
  - `set PYTHONPATH=src`
  - `uv run python -c "from research_layer.api.controllers._state_store import STORE; STORE.reset_all()"`

## fixture / demo data

- 自动化测试 fixture（deterministic）：
  - `tests/unit/research_layer/test_slice8_failure_loop_services.py`
  - `tests/integration/research_api/test_slice8_failure_recompute_diff_flow.py`
- Dev Console 可直接使用内置默认输入并通过 `Load Full Graph` 自动填充目标 node/edge id。

## manual steps

1. 打开 `/api/v1/research/dev-console`。
2. Import Source -> Trigger Extract -> Refresh Candidates -> Confirm Candidate（至少两组 source）。
3. Build Graph -> Generate Routes -> Load Routes（建立基线）。
4. Load Full Graph，选择 `Failure Target Type/ID`。
5. 点击 `Attach Failure`，记录 `failure_id`。
6. 点击 `Recompute From Failure`，记录 `job_id`。
7. 点击 `Load Job Status`，确认终态并取 `version_id`（来自 `result_ref`）。
8. 点击 `Load Version Diff`，核验 `added/weakened/invalidated/branch_changes`。
9. 再次 `Load Full Graph` 与 `Load Routes`，核验 node/edge/route 状态与分数变化。

## expected observations

- failure 可成功挂载到 node 或 edge，且非法目标/重复目标显式报错。
- recompute job 有显式终态（`succeeded` 或 `failed`），失败时可见结构化 `error`。
- 成功终态可通过 `result_ref(resource_type=graph_version)` 回链到 `/versions/{version_id}/diff`。
- diff 至少包含：
  - `added`
  - `weakened`
  - `invalidated`
  - `branch_changes`
  - `route_score_changes`
- graph / route 状态与分数可观察变化，非前端硬编码。
- `research_events` 可见：
  - `failure_attached`
  - `recompute_started`
  - `recompute_completed`
  - `diff_created`
  - 失败场景 `job_failed`

## 异步 job status / result_ref 验收步骤

1. 触发 `Recompute From Failure`，获取 `job_id`。
2. 调 `GET /api/v1/research/jobs/{job_id}`：
   - `status=succeeded` 时必须有 `result_ref={resource_type: graph_version, resource_id: <version_id>}`。
   - `status=failed` 时必须有结构化 `error`。
3. 成功路径继续调 `GET /api/v1/research/versions/{version_id}/diff`，确认回链闭环。

## 已知风险

- 当前 failure impact 传播采用确定性规则（severity 驱动 node/edge 状态），后续可在不破坏 Slice 8 契约下扩展更细粒度传播策略。
- 当前 recompute 为同步执行后返回异步 job 终态（`202 + job status`）；若后续迁移到真正后台 worker，需要保持相同 job/result_ref 契约与事件语义。
