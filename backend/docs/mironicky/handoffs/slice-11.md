---
record_type: developer_handoff
slice_id: slice_11
status: developer_complete
next_required_action: run_evaluator_for_slice_11
allowed_to_start_next_slice: false
blocking_status: awaiting_evaluator
---

# Slice 11 Developer Handoff

## Slice 约束摘要

- 仅实现 Slice 11：Research Package 发布；未进入 Slice 12。
- package create 走真实 snapshot build，不绑定 live workspace。
- package 支持 create / list(query) / get / replay。
- private dependency 节点在 build 时显式转换为 public gap（保留 private_dependency_flags + replacement_gap_node_id）。
- package replay 返回 snapshot payload，包含 routes / nodes / validations / private_dependency_flags / public_gap_nodes / boundary_notes / traceability_refs。
- publish 使用统一异步 job 契约：`POST /packages/{package_id}/publish -> job_id`，`GET /jobs/{job_id}` 返回终态与 `result_ref`。
- publish result 资源可回链：`GET /packages/{package_id}/publish-results/{publish_result_id}`。
- 可观测性落地事件：`package_build_started/completed`、`package_publish_started/completed`，失败时 `job_failed`。
- Dev Console 已补 Slice 11 薄封装操作（真实 API，不含 mock/fake path/hard-coded state）。

## 变更文件列表

- `src/research_layer/services/package_build_service.py` (new)
- `src/research_layer/api/controllers/research_package_controller.py`
- `src/research_layer/api/controllers/_state_store.py`
- `src/research_layer/api/controllers/research_source_controller.py`
- `src/research_layer/api/schemas/package.py`
- `src/research_layer/services/__init__.py`
- `src/research_layer/domain/models/research_domain.py`
- `tests/unit/research_layer/test_slice11_package_services.py` (new)
- `tests/integration/research_api/test_slice11_research_package_flow.py` (new)
- `tests/unit/research_layer/test_slice1_domain_models.py`
- `docs/mironicky/RESEARCH_PACKAGE_SPEC.md`
- `docs/mironicky/API_SPEC.md`
- `docs/mironicky/OBSERVABILITY.md`
- `docs/mironicky/DOMAIN_MODEL.md`
- `docs/mironicky/STORAGE_SCHEMA.md`
- `docs/mironicky/handoffs/slice-11.md` (new)
- `docs/mironicky/slice_status.json`

## 测试命令与结果

1. `$env:PYTHONPATH='src'; uv run pytest tests/unit/research_layer/test_slice11_package_services.py tests/integration/research_api/test_slice11_research_package_flow.py -q`
   - 结果：`ERROR collecting ... ModuleNotFoundError: research_layer.services.package_build_service`（红测）

2. `$env:PYTHONPATH='src'; uv run pytest tests/unit/research_layer/test_slice11_package_services.py tests/integration/research_api/test_slice11_research_package_flow.py -q`
   - 结果：`4 failed, 2 passed`（中间实现后，定位 SQL 占位符错误）

3. `$env:PYTHONPATH='src'; uv run pytest tests/unit/research_layer/test_slice11_package_services.py tests/integration/research_api/test_slice11_research_package_flow.py -q`
   - 结果：`6 passed in 5.35s`（Slice 11 定向测试转绿）

4. `$env:PYTHONPATH='src'; uv run pytest tests/unit/research_layer tests/integration/research_api -q`
   - 结果：`107 passed in 81.05s`（research layer 回归通过）

## Dev Console 路径

- URL: `/api/v1/research/dev-console`
- Slice 11 新增最小能力：
  - `Create Package Snapshot`
  - `Query Packages`
  - `Load Package`
  - `Load Package Replay`
  - `Publish Package`
  - `Load Publish Result`

## startup / reset commands

- Startup（repo root）：
  - `set PYTHONPATH=src`
  - `uv run python src/run.py`

- Reset research acceptance data：
  - `set PYTHONPATH=src`
  - `uv run python -c "from research_layer.api.controllers._state_store import STORE; STORE.reset_all()"`

## fixture / demo data

- unit fixtures：`tests/unit/research_layer/test_slice11_package_services.py`
- integration fixtures：`tests/integration/research_api/test_slice11_research_package_flow.py`
- 持久化文件：`data/research_slice2.sqlite3`

## manual steps

1. 打开 `/api/v1/research/dev-console`。
2. 准备 route/node/validation（可走已有 import->extract->confirm->build graph->generate route 流程，或使用既有数据）。
3. 在 Research Package 区点击 `Create Package Snapshot`。
4. 点击 `Query Packages`，确认列表出现新 package。
5. 点击 `Load Package`，检查 `included_route_ids / included_node_ids / included_validation_ids`。
6. 点击 `Load Package Replay`，检查 snapshot 中含 `private_dependency_flags/public_gap_nodes/boundary_notes/traceability_refs`。
7. 点击 `Publish Package`，记录 `job_id`。
8. 用 `Load Job Status` 查看 job 终态与 `result_ref`。
9. 将 `result_ref.resource_id` 填入 `Publish Result ID`，点击 `Load Publish Result`。

## expected observations

- package create 返回 `snapshot_type=research_package_snapshot`、`snapshot_version=slice11.v1`、`replay_ready=true`。
- 若 route/node 中包含 `private_dependency`，create 返回：
  - 非空 `private_dependency_flags`
  - 非空 `public_gap_nodes`
  - 私密节点不进入公开 included nodes。
- replay 响应可回放 snapshot，并保留 route/node/validation/private/gap 的 traceability。
- publish 返回异步 job；`GET /jobs/{job_id}` 终态 `succeeded` 且 `result_ref.resource_type=package_publish_result`。
- publish result API 可回链 package 与 snapshot 边界信息。
- `research_events` 可看到 `package_build_started/completed`、`package_publish_started/completed`；失败路径可见 `job_failed`。

## 已知风险

- 当前 package build 默认从 route 及显式传入 node/validation 组装快照；若调用方漏传且 route 未携带相关引用，快照不会自动补全额外上下游对象。
- publish 当前为“同步执行 + 异步契约返回已终态”模式（job 仍完整可查）；后续若接入真实队列 worker，需要保持同一 result_ref/错误语义。
- private dependency 判定目前以 `node_type=private_dependency` 为主；若后续引入 visibility 字段落库，应扩展判定并保持向后兼容。

## 异步 publish 验收步骤（job/status/result_ref）

1. `POST /api/v1/research/packages/{package_id}/publish`，获取 `job_id`。
2. `GET /api/v1/research/jobs/{job_id}`，确认：
   - `status=succeeded`
   - `result_ref.resource_type=package_publish_result`
   - `result_ref.resource_id=<publish_result_id>`
3. `GET /api/v1/research/packages/{package_id}/publish-results/{publish_result_id}?workspace_id=...`，确认回链成功。
