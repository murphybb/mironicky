---
record_type: developer_handoff
slice_id: slice_9
status: developer_complete
next_required_action: run_evaluator_for_slice_9
allowed_to_start_next_slice: false
blocking_status: awaiting_evaluator
---

# Slice 9 Developer Handoff

## Slice 约束摘要

- 仅实现 Slice 9：`Hypothesis Engine`；未进入 Slice 10+（未实现 retrieval views / package publish）。
- hypothesis trigger 仅允许：`gap/conflict/failure/weak_support`。
- hypothesis generate 必须由合法 trigger 驱动，非法 trigger 显式报错。
- hypothesis 输出为结构化 candidate，默认 `status=candidate` 且 `stage=exploratory`。
- novelty typing / minimum validation action / weakening signal 由程序规则生成，不依赖 LLM 自由发挥。
- promote/reject 仅允许 `candidate` 状态；重复操作返回 `409 + research.invalid_state`。
- promote/reject 持久化显式决策来源（`decision_source_type/decision_source_ref`）与决策上下文。
- hypothesis 不直接改写主路线结论；promote 仅进入 `promoted_for_validation`。
- hypothesis generation 接入统一 job 契约，并通过 `result_ref(resource_type=hypothesis)` 回链。
- 事件落盘覆盖：`hypothesis_generation_started` / `hypothesis_generation_completed` / `hypothesis_promoted` / `hypothesis_rejected` / `job_failed`。

## 变更文件列表

- `src/research_layer/services/hypothesis_trigger_detector.py`
- `src/research_layer/services/hypothesis_service.py`
- `src/research_layer/services/__init__.py`
- `src/research_layer/api/controllers/research_hypothesis_controller.py`
- `src/research_layer/api/controllers/research_source_controller.py`
- `src/research_layer/api/controllers/_state_store.py`
- `src/research_layer/api/schemas/hypothesis.py`
- `tests/unit/research_layer/test_slice9_hypothesis_services.py`
- `tests/integration/research_api/test_slice9_hypothesis_engine_flow.py`
- `docs/mironicky/HYPOTHESIS_ENGINE_SPEC.md`
- `docs/mironicky/API_SPEC.md`
- `docs/mironicky/OBSERVABILITY.md`
- `docs/mironicky/DOMAIN_MODEL.md`
- `docs/mironicky/STORAGE_SCHEMA.md`
- `docs/mironicky/handoffs/slice-09.md`
- `docs/mironicky/slice_status.json`

## 测试命令与结果

1. `$env:PYTHONPATH='src'; uv run pytest tests/unit/research_layer/test_slice9_hypothesis_services.py tests/integration/research_api/test_slice9_hypothesis_engine_flow.py -q`
   - 结果：`ERROR`（`ModuleNotFoundError: research_layer.services.hypothesis_service`，TDD 红测基线）
2. `$env:PYTHONPATH='src'; uv run pytest tests/unit/research_layer/test_slice9_hypothesis_services.py tests/integration/research_api/test_slice9_hypothesis_engine_flow.py -q`
   - 结果：`6 passed`
3. `$env:PYTHONPATH='src'; uv run pytest tests/unit/research_layer tests/integration/research_api -q`
   - 结果：`94 passed`

## Dev Console 路径

- URL: `/api/v1/research/dev-console`
- Slice 9 最小能力（真实 API 薄封装）：
  - `Load Hypothesis Triggers`
  - `Generate Hypothesis`
  - `Load Hypothesis`
  - `Promote Hypothesis`
  - `Reject Hypothesis`
  - 复用 `Load Job Status` 观察异步终态与 `result_ref`

## startup / reset commands

- Startup（repo root）：
  - `set PYTHONPATH=src`
  - `uv run python src/run.py`
- Reset research acceptance data：
  - `set PYTHONPATH=src`
  - `uv run python -c "from research_layer.api.controllers._state_store import STORE; STORE.reset_all()"`

## fixture / demo data

- 自动化测试 fixture（deterministic）：
  - `tests/unit/research_layer/test_slice9_hypothesis_services.py`
  - `tests/integration/research_api/test_slice9_hypothesis_engine_flow.py`
- Dev Console 通过已有 Import/Extract/Confirm/Graph/Route/Failure 真实流程生成 trigger 数据。

## manual steps

1. 打开 `/api/v1/research/dev-console`。
2. Import Source -> Trigger Extract -> Refresh Candidates -> Confirm Candidate（至少两组 source，包含 conflict/failure 语义）。
3. Build Graph -> Generate Routes -> Load Full Graph。
4. Attach Failure（node/edge 任一）并可选 Recompute From Failure，确保出现 gap/weakened 路由状态。
5. 点击 `Load Hypothesis Triggers`，确认返回 `gap/conflict/failure/weak_support` 合法 trigger。
6. 点击 `Generate Hypothesis`，记录 `job_id` 与 `hypothesis_id`。
7. 点击 `Load Hypothesis`，核验结构化字段：`novelty_typing/minimum_validation_action/weakening_signal/related_object_ids`。
8. 点击 `Promote Hypothesis`，观察状态变为 `promoted_for_validation`。
9. 对另一条 hypothesis 点击 `Reject Hypothesis`，观察状态变为 `rejected`。
10. 重复 promote/reject，确认返回 `409 + research.invalid_state`。

## expected observations

- trigger 列表仅包含四类合法来源：`gap/conflict/failure/weak_support`。
- hypothesis generate 成功时返回 job，job 终态 `succeeded` 且 `result_ref.resource_type=hypothesis`。
- hypothesis detail 默认 `status=candidate`、`stage=exploratory`，并含结构化字段完整输出。
- promote/reject 保留 `decision_source_type/decision_source_ref/decision_note`。
- hypothesis promote 不会直接改写 route conclusion。
- `research_events` 可见：
  - `hypothesis_generation_started`
  - `hypothesis_generation_completed`
  - `hypothesis_promoted`
  - `hypothesis_rejected`
  - 失败场景 `job_failed`

## 异步 job status / result_ref 验收步骤

1. 触发 `Generate Hypothesis`，记录 `job_id`。
2. 调 `GET /api/v1/research/jobs/{job_id}`：
   - `status=succeeded` 时必须有 `result_ref={resource_type: hypothesis, resource_id: <hypothesis_id>}`。
   - `status=failed` 时必须有结构化 `error`。
3. 成功路径继续调 `GET /api/v1/research/hypotheses/{hypothesis_id}`，确认回链闭环与结构化输出。

## 已知风险

- 当前 weak support 触发为确定性阈值规则（`support_score/status/missing_input`），后续可在不破坏契约下做更细粒度策略。
- hypothesis generation 当前以“同步执行 + job 状态落盘”实现；若后续迁移到真正后台 worker，需保持相同 job/result_ref 与事件语义契约。
