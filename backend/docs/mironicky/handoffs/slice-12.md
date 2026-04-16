---
record_type: developer_handoff
slice_id: slice_12
status: developer_complete
next_required_action: run_evaluator_for_slice_12
allowed_to_start_next_slice: false
blocking_status: awaiting_evaluator
---

# Slice 12 Developer Handoff

## Slice 约束摘要

- 仅实现 Slice 12（E2E 闭环与回归），未新增 Slice 12 之外产品范围。
- 三条核心闭环已通过真实 API 跑通并固化为自动化测试：
  - `import -> extract -> confirm -> graph -> score -> route`
  - `failure -> impact -> recompute -> diff`
  - `gap/conflict/failure -> hypothesis candidate`
- 落地 regression suite，覆盖跨 slice 集成点、显式错误语义、workspace/resource 约束、失败与重跑路径。
- Dev Console 新增连续闭环入口（真实 API 薄封装）与执行摘要入口，未使用 mock/fake path/hard-coded state。
- 新增 execution summary 视图用于 evaluator 白盒复盘：`timeline / business_objects / final_outcome / job result_refs`。

## 变更文件列表

- `src/research_layer/api/controllers/_state_store.py`
- `src/research_layer/api/controllers/research_source_controller.py`
- `src/research_layer/api/schemas/observability.py` (new)
- `tests/e2e/research_workspace/test_slice12_e2e_closed_loops.py` (new)
- `tests/integration/research_api/test_slice12_regression_suite.py` (new)
- `docs/mironicky/API_SPEC.md`
- `docs/mironicky/OBSERVABILITY.md`
- `docs/mironicky/handoffs/slice-12.md` (new)
- `docs/mironicky/slice_status.json`

## 测试命令与结果

1. `$env:PYTHONPATH='src'; uv run pytest tests/e2e/research_workspace/test_slice12_e2e_closed_loops.py tests/integration/research_api/test_slice12_regression_suite.py -q`
   - 结果（红测）：`3 failed, 1 passed`
   - 失败点：Dev Console 缺少 Slice 12 闭环入口；`/api/v1/research/executions/summary` 未实现。

2. `$env:PYTHONPATH='src'; uv run pytest tests/e2e/research_workspace/test_slice12_e2e_closed_loops.py tests/integration/research_api/test_slice12_regression_suite.py -q`
   - 结果（绿测）：`4 passed`

3. `$env:PYTHONPATH='src'; uv run pytest tests/unit/research_layer tests/integration/research_api tests/e2e/research_workspace -q`
   - 结果（回归）：`111 passed`

## Dev Console 路径

- URL: `/api/v1/research/dev-console`
- Slice 12 闭环入口：
  - `Run Closed Loop (Source -> Route -> Failure -> Diff -> Hypothesis)`
  - `Load Execution Summary`

## startup / reset commands

- Startup（repo root）:
  - `set PYTHONPATH=src`
  - `uv run python src/run.py`

- Reset research acceptance data:
  - `set PYTHONPATH=src`
  - `uv run python -c "from research_layer.api.controllers._state_store import STORE; STORE.reset_all()"`

## fixture / demo data

- DB 状态源：`data/research_slice2.sqlite3`
- 历史 source fixture：`demo/research_dev/fixtures/slice3_sources.json`
- Slice 12 E2E fixture/流程：`tests/e2e/research_workspace/test_slice12_e2e_closed_loops.py`
- Slice 12 regression fixture/流程：`tests/integration/research_api/test_slice12_regression_suite.py`

## manual steps

1. 打开 `/api/v1/research/dev-console`。
2. 设置 `workspace_id`（如 `ws_slice12_manual`）。
3. 点击 `Run Closed Loop (Source -> Route -> Failure -> Diff -> Hypothesis)`。
4. 观察输出中是否依次出现：
   - import/extract/candidates/confirm/graph_build/route_generate/route_preview
   - failure_attach/recompute/recompute_job/version_diff
   - hypothesis_triggers/hypothesis_generate/hypothesis_job
5. 点击 `Load Execution Summary`，确认 timeline 与 business object 回链完整。
6. 可选：填写 `Execution Request ID Filter` 后再次点击 `Load Execution Summary`，验证按请求过滤。

## expected observations

- Extract/Recompute/Hypothesis 的异步 job 均可通过 `job_id` 查终态并回链 `result_ref`。
- `version_diff` 返回 `added/weakened/invalidated/branch_changes/route_score_changes`。
- summary 输出：
  - `timeline[]` 有闭环关键事件
  - `business_objects` 包含 `source_ids/route_ids/version_ids/hypothesis_ids`
  - `final_outcome` 给出 `completed|failed|partial` 与 `result_refs[]`
- 错误路径（缺失资源/非法状态）保持显式 `research.*` 错误码，不静默降级。

## 三条闭环复现说明

1. `import -> extract -> confirm -> graph -> score -> route`
   - 通过闭环按钮自动串联（或手动逐段执行 Import/Extract/Confirm/Build Graph/Generate Routes/Load Route Preview）。
   - 验证 `source_id -> candidate_batch_id -> route_id` 回链。

2. `failure -> impact -> recompute -> diff`
   - 闭环按钮会对 evidence node attach failure 并触发 recompute。
   - 验证 `job.result_ref.resource_type=graph_version`，并用 `version_id` 拉取 diff。

3. `gap/conflict/failure -> hypothesis candidate`
   - 闭环按钮先拉取 trigger 列表，再 generate hypothesis。
   - 验证 `job.result_ref.resource_type=hypothesis` 与 hypothesis detail 的 `status=candidate`。

## 异步 job / result_ref 验收步骤

1. 从闭环输出拿到 `extract/recompute/hypothesis` 的 `job_id`。
2. 调 `GET /api/v1/research/jobs/{job_id}` 验证：
   - `status` 终态（`succeeded|failed`）
   - `workspace_id` 匹配
   - 成功时有 `result_ref`
3. 按 `result_ref` 回链资源：
   - `candidate_batch` -> `/sources/{source_id}/extraction-results/{candidate_batch_id}`
   - `graph_version` -> `/versions/{version_id}/diff`
   - `hypothesis` -> `/hypotheses/{hypothesis_id}`

## 已知风险

- `executions/summary` 目前基于 `research_events + jobs` 聚合；若后续引入跨进程异步 worker，需确保事件入库一致性不被破坏。
- `final_outcome.status` 为聚合语义（completed/failed/partial），不是业务对象状态机替代；评估时应与具体对象状态联合解读。
