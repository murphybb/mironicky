---
record_type: developer_handoff
slice_id: slice_5
status: developer_complete
next_required_action: run_evaluator_for_slice_5
allowed_to_start_next_slice: false
blocking_status: awaiting_evaluator
---

# Slice 5 Developer Handoff

## Slice 约束摘要

- 仅实现 Slice 5：Research Graph 基础层。
- 未进入 Slice 6+（未实现 scoring、route generation/ranking、failure recompute、hypothesis、package publish）。
- 已实现并通过测试：
  - graph repository
  - graph build service
  - node / edge CRUD
  - graph query service（局部子图）
  - graph workspace model
  - graph API
- confirmed formal objects 已映射为 graph nodes / edges，且 node/edge 均含 `object_ref_type/object_ref_id` 回链字段。
- graph 状态采用 research-layer SQLite 正式持久化并可跨请求回读，未使用 mock / 进程内 dict / fake path 充当正式状态源。
- 图谱逻辑保持在 `src/research_layer/`，未塞回 assistant/group_chat message pipeline。

## 变更文件列表

- `src/research_layer/api/controllers/_state_store.py`
- `src/research_layer/api/controllers/research_graph_controller.py`
- `src/research_layer/api/controllers/research_source_controller.py`
- `src/research_layer/api/schemas/graph.py`
- `src/research_layer/graph/__init__.py`
- `src/research_layer/graph/repository.py`
- `src/research_layer/graph/workspace_model.py`
- `src/research_layer/services/__init__.py`
- `src/research_layer/services/graph_build_service.py`
- `src/research_layer/services/graph_query_service.py`
- `tests/unit/research_layer/test_slice5_graph_services.py`
- `tests/integration/research_api/test_slice5_graph_foundation_flow.py`
- `demo/research_dev/fixtures/slice5_graph_sources.json`
- `docs/mironicky/API_SPEC.md`
- `docs/mironicky/DOMAIN_MODEL.md`
- `docs/mironicky/STORAGE_SCHEMA.md`
- `docs/mironicky/OBSERVABILITY.md`
- `docs/mironicky/handoffs/slice-05.md`
- `docs/mironicky/slice_status.json`

## 测试命令与结果

- `PYTHONPATH=src uv run pytest tests/unit/research_layer/test_slice5_graph_services.py tests/integration/research_api/test_slice5_graph_foundation_flow.py -q`
  - `6 passed`
- `PYTHONPATH=src uv run pytest tests/unit/research_layer tests/integration/research_api -q`
  - `68 passed`

## Dev Console 路径

- URL: `/api/v1/research/dev-console`
- Slice 5 最小能力（真实 API 薄封装）：
  - Graph Workspace 查看
  - Graph Build（confirmed -> graph）
  - Local Subgraph Query
  - Graph Node 创建 / 更新
  - Graph Edge 创建 / 更新
  - 更新后再次查询验证结果变化

## startup / reset commands

- Startup（repo root）:
  - `set PYTHONPATH=src`
  - `uv run python src/run.py`
- Reset research acceptance data:
  - `set PYTHONPATH=src`
  - `uv run python -c "from research_layer.api.controllers._state_store import STORE; STORE.reset_all()"`

## fixture / demo data

- `demo/research_dev/fixtures/slice3_sources.json`
- `demo/research_dev/fixtures/slice5_graph_sources.json`

## manual steps

1. 打开 `/api/v1/research/dev-console`。
2. Import Source（`workspace_id=ws_slice5_console`），Trigger Extract，刷新 Candidate List。
3. Confirm 至少两个 candidate（建议 evidence + assumption）。
4. 点击 Graph Build，记录返回 `version_id/node_count/edge_count`。
5. 点击 Load Full Graph，确认返回 nodes/edges。
6. 选择 `center_node_id` 后执行 Local Graph Query，确认返回局部子图。
7. 执行 Graph Node Update（修改 label/status），再执行 Local Graph Query，确认节点变化已可见。
8. 执行 Graph Edge Update（修改 strength/status），再执行 Local Graph Query，确认边变化已可见。
9. 点击 Graph Workspace，确认 `latest_version_id`、`node_count`、`edge_count` 与 build 结果一致。

## expected observations

- graph build 后：
  - `graph_versions` 新增版本记录，含 `request_id`
  - `graph_workspaces` 更新 `latest_version_id/node_count/edge_count`
  - `graph_nodes/graph_edges` 含 `object_ref_type/object_ref_id`
- local query 返回局部子图（非空 `nodes/edges`），且可回链 formal object。
- node/edge update 后再次 query，返回结果发生对应变化。
- 错误语义显式：
  - 非法状态更新 -> `400 + research.invalid_request`
  - workspace 归属冲突 -> `409 + research.conflict`
  - 缺失 node/edge -> `404 + research.not_found`
- 结构化事件可追踪：
  - `graph_build_started/completed`
  - `graph_query_completed`
  - `graph_node_updated`
  - `graph_edge_updated`

## 已知风险

- 当前 Slice 5 图谱仍采用 research-layer SQLite 作为阶段性正式状态源；与长期目标的 Mongo/Beanie + igraph 方案仍需在后续切片迁移并保持契约一致。
- 当前 build 的 edge 生成为基础规则（按 source 聚合 + 类型映射），后续更复杂语义（scoring/route/failure impact）应在后续切片扩展，不应回改 Slice 5 验收边界。
