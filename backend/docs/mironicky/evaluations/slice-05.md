---
record_type: evaluator_result
slice_id: slice_5
status: evaluator_pass
allowed_to_start_next_slice: true
blocking_status: cleared
---

# Slice 5 Evaluator Record

## Result

PASS

## Final status

- slice_5 = `evaluator_pass`
- allowed_to_start_next_slice = `true`
- blocking_status = `cleared`

## Scope

- Slice 5 only: Research Graph 基础层
- 覆盖验证项：
  - graph repository / build / node-edge CRUD / query / workspace model / graph API
  - confirmed formal objects -> graph nodes/edges 映射
  - local subgraph query
  - update 后查询结果变化
  - graph 持久化、object_ref 回链、workspace 边界、显式错误语义
  - traceability / structured events / graph 状态回读最小白盒
- Slice 6+ 越界检查：
  - 本次验收未执行 scoring/route ranking/failure recompute/hypothesis/package publish 的 Slice 6+ 验收门槛
  - `src/research_layer/scoring/`、`src/research_layer/routing/`、`src/research_layer/retrieval/` 仍为占位 `__init__.py`，未见 Slice 6+ 交付落地

## Evidence

### Automated tests (minimal required)

- `PYTHONPATH=src uv run pytest tests/unit/research_layer/test_slice5_graph_services.py tests/integration/research_api/test_slice5_graph_foundation_flow.py -q`
- Result: `6 passed in 5.75s`

### API and persistence cross-check

- Graph build result:
  - `workspace_id=ws_slice3_console`
  - `version_id=ver_a2be0016a7a0`
  - `node_count=2`
  - `edge_count=1`
- Confirmed objects ↔ graph 回链一致：
  - `research_evidences.evidence_id=evi_f7534f680f48` -> `graph_nodes.object_ref_type=evidence/object_ref_id=evi_f7534f680f48`
  - `research_assumptions.assumption_id=ass_98b7b350273b` -> `graph_nodes.object_ref_type=assumption/object_ref_id=ass_98b7b350273b`
  - `graph_edges.object_ref_type=assumption/object_ref_id=ass_98b7b350273b` 可回链
- Local subgraph query 返回局部子图（`max_hops=1`）：
  - 返回 2 nodes + 1 edge，且均带 `object_ref_type/object_ref_id`
- Update 影响后续查询：
  - node `node_bbe16a4029b9`: `short_label` 改为 `Manual Graph Node`，`status=weakened`
  - edge `edge_e1567893d8ad`: `strength` 从 `0.8` 改为 `0.3`，`status=conflicted`
  - 再次 local query 返回上述新值
- Workspace 视图与持久化一致：
  - `graph_workspaces.latest_version_id=ver_a2be0016a7a0`
  - `node_count=2`、`edge_count=1`
- 结构化事件最小白盒：
  - `research_events` 中可见 `graph_build_started/completed`、`graph_query_completed`、`graph_node_updated`、`graph_edge_updated`
  - `graph_build_completed.metrics_json` 含 `node_count/edge_count`
  - `graph_query_completed.metrics_json` 含 `max_hops`（适用时）

## Playwright manual validation evidence

基于真实 Dev Console 路径（`http://127.0.0.1:1995/api/v1/research/dev-console`）执行：

1. Import source -> Extract -> Refresh candidates，得到 5 个 pending candidates。
2. Confirm 两个 candidate（evidence + assumption）。
3. 点击 `Build Graph from Confirmed Objects`，观察 `version_id/node_count/edge_count`。
4. 点击 `Load Full Graph`，记录初始 graph（nodes/edges + object_ref）。
5. 点击 `Query Local Subgraph`，确认返回局部子图。
6. 点击 `Update Node`，修改后再次 local query，观察 node 字段变化。
7. 点击 `Update Edge`，修改后再次 local query，观察 edge 字段变化。
8. 点击 `Load Graph Workspace`，核对 `latest_version_id/node_count/edge_count`。
9. 异常路径（真实 UI 操作）：
  - `Node Status For Update=invalid_status` 后执行 update -> 返回 `400 + research.invalid_request`。

手动页面输出与 API/SQLite 回读一致，未发现“页面显示成功但后端未更新”的不一致。

## Findings (ordered by severity)

- `P3 (non-blocking)` 全量应用启动依赖 `.env`，在缺失 `.env` 时 `src/run.py` 无法直接启动；本次采用研究层最小真实 FastAPI 装配完成 Dev Console 验收。该问题不影响 Slice 5 图谱能力正确性，但影响本地复现实验便利性。

## Blocking / non-blocking judgement

- Non-blocking

## Decision

- Allowed to enter Slice 6 = YES
