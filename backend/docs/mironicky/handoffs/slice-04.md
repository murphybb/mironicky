---
record_type: developer_handoff
slice_id: slice_4
status: developer_complete
next_required_action: run_evaluator_for_slice_4
allowed_to_start_next_slice: false
blocking_status: awaiting_evaluator
---

# Slice 4 Developer Handoff

## Slice 约束摘要

- 仅实现 Slice 4 Candidate Confirmation Flow。
- 未进入 Slice 5+：未实现 graph build、scoring、route generation、failure recompute、hypothesis、package publish。
- 候选态与确认态分层：candidate 仅 `pending|confirmed|rejected`；未确认对象不进入主图谱。
- confirm/reject 显式错误语义：
  - 重复 confirm/reject：`409 + research.invalid_state`
  - 冲突确认（去重命中）：`409 + research.conflict`
  - 缺失/非法 `workspace_id`：`400 + research.invalid_request`
- 与 Slice 3 traceability 一致：confirmed 对象保留 `source_id/candidate_id/candidate_batch_id/extraction_job_id/workspace_id`。
- Dev Console 为真实 API 薄封装，支持 list/detail/confirm/reject。

## 变更文件列表

- `src/research_layer/services/candidate_confirmation_service.py`
- `src/research_layer/services/__init__.py`
- `src/research_layer/api/controllers/research_source_controller.py`
- `src/research_layer/api/controllers/_state_store.py`
- `src/research_layer/api/schemas/source.py`
- `tests/unit/research_layer/test_slice4_candidate_confirmation_service.py`
- `tests/integration/research_api/test_slice4_candidate_confirmation_flow.py`
- `docs/mironicky/API_SPEC.md`
- `docs/mironicky/DOMAIN_MODEL.md`
- `docs/mironicky/OBSERVABILITY.md`
- `docs/mironicky/STORAGE_SCHEMA.md`
- `docs/mironicky/handoffs/slice-04.md`
- `docs/mironicky/slice_status.json`

## 测试命令与结果

- `PYTHONPATH=src uv run pytest tests/unit/research_layer/test_slice4_candidate_confirmation_service.py tests/integration/research_api/test_slice4_candidate_confirmation_flow.py -q`
  - `9 passed`
- `PYTHONPATH=src uv run pytest tests/unit/research_layer/test_slice3_parser_extractors.py tests/unit/research_layer/test_slice4_candidate_confirmation_service.py tests/integration/research_api/test_slice3_source_import_extraction.py tests/integration/research_api/test_slice4_candidate_confirmation_flow.py -q`
  - `22 passed`
- `PYTHONPATH=src uv run pytest tests/unit/research_layer tests/integration/research_api -q`
  - `62 passed`

## Dev Console 路径

- URL: `/api/v1/research/dev-console`
- 最小功能：
  - candidate list
  - candidate detail
  - confirm
  - reject
  - 状态变化可见（detail/list 回读）

## startup / reset commands

- Startup (repo root):
  - `set PYTHONPATH=src`
  - `uv run python src/run.py`
- Reset research acceptance data:
  - `set PYTHONPATH=src`
  - `uv run python -c "from research_layer.api.controllers._state_store import STORE; STORE.reset_all()"`

## fixture / demo data

- `demo/research_dev/fixtures/slice3_sources.json`（导入+抽取基础 fixture）

## manual steps

1. 打开 `/api/v1/research/dev-console`。
2. Import Source（填写 `workspace_id`，导入含 claim/assumption/conflict/failure/validation 的文本）。
3. Trigger Extract，等待结果区显示 `job.status=succeeded`。
4. Candidate List 刷新并选择一个 `candidate_id`。
5. Candidate Detail 查看 `pending`。
6. 点击 Confirm 或 Reject。
7. 再次执行 Candidate Detail / Candidate List，观察状态为 `confirmed` 或 `rejected`。
8. 对同一 candidate 再次 confirm/reject，观察显式错误语义。

## expected observations

- confirm 成功后：
  - candidate 状态 `pending -> confirmed`
  - confirmed 对象入库（按 candidate_type 进入对应正式对象表）
  - `candidate_confirmed` 结构化事件可追踪 `request_id/workspace_id/candidate refs`
- reject 成功后：
  - candidate 状态 `pending -> rejected`
  - `candidate_rejected` 结构化事件可追踪 `request_id/workspace_id/candidate refs`
- 重复 confirm/reject：
  - `409 + research.invalid_state`
- 去重/冲突确认：
  - `409 + research.conflict`
- 未确认对象不会自动进入主图谱（graph 仍为空，未引入 graph build）。

## 已知风险

- Slice 4 的去重/冲突键为基础策略（`workspace_id + normalized_text`）；更复杂语义冲突规则留待后续 slice 扩展。
- 当前 persistence 仍为 research-layer SQLite 过渡方案，后续需迁移到目标存储方案时保证字段与语义一致。
