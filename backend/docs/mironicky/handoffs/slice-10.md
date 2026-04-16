---
record_type: developer_handoff
slice_id: slice_10
status: developer_complete
next_required_action: run_evaluator_for_slice_10
allowed_to_start_next_slice: false
blocking_status: awaiting_evaluator
---

# Slice 10 Developer Handoff

## Slice 约束摘要

- 仅实现 Slice 10：`Research Retrieval Views`；未进入 Slice 11+，未实现 package publish。
- 已实现 5 个科研语义检索视图：`evidence`、`contradiction`、`failure_pattern`、`validation_history`、`hypothesis_support`。
- 每个 view 均由独立 service 负责，统一由 retrieval facade 编排。
- 检索支持 `metadata filter + hybrid retrieval`（`keyword + vector` 组合评分），并支持 `keyword/vector/hybrid` 显式选择。
- 检索结果返回 `source_ref / graph_refs / formal_refs / supporting_refs / trace_refs`，可回链 source/graph/formal objects。
- 严格按 `workspace_id` 作用域检索，跨 workspace 不泄露数据。
- 非法 view / 非法 filter / 缺失参数均返回显式 `research.invalid_request`。
- 空结果显式返回 `200 + items=[] + total=0`，不静默失败。
- Dev Console 新增 Slice 10 最小能力：五类检索触发、结果回链查看、改查询后二次检索。
- 可观测性新增 retrieval 事件：`retrieval_view_started` / `retrieval_view_completed`（成功/失败）。
- 已修复 evaluator 阻塞项：
  - `validation_history` 在 `target_object=node:*` 路径下补全 `source_ref` 与 `graph_refs.node_ids` 回链。
  - 非法 filter / 非法 metadata 请求会写入 `retrieval_view_completed(status=failed, error=...)` 结构化事件。

## 变更文件列表

- `src/research_layer/services/retrieval_views_service.py`
- `src/research_layer/api/controllers/research_retrieval_controller.py`
- `src/research_layer/api/schemas/retrieval.py`
- `src/research_layer/api/controllers/_state_store.py`
- `src/research_layer/services/__init__.py`
- `src/research_layer/api/controllers/__init__.py`
- `src/research_layer/api/controllers/research_source_controller.py`
- `tests/unit/research_layer/test_slice10_retrieval_services.py`
- `tests/integration/research_api/test_slice10_retrieval_views_flow.py`
- `docs/mironicky/API_SPEC.md`
- `docs/mironicky/DOMAIN_MODEL.md`
- `docs/mironicky/STORAGE_SCHEMA.md`
- `docs/mironicky/OBSERVABILITY.md`
- `docs/mironicky/handoffs/slice-10.md`
- `docs/mironicky/slice_status.json`

## 测试命令与结果

1. `$env:PYTHONPATH='src'; uv run pytest tests/unit/research_layer/test_slice10_retrieval_services.py tests/integration/research_api/test_slice10_retrieval_views_flow.py -q`
   - 结果：`4 failed, 3 passed in 8.93s`（红测，复现 evaluator 两个阻塞问题）
2. `$env:PYTHONPATH='src'; uv run pytest tests/unit/research_layer/test_slice10_retrieval_services.py tests/integration/research_api/test_slice10_retrieval_views_flow.py -q`
   - 结果：`7 passed in 6.90s`（修复后绿测）
3. `$env:PYTHONPATH='src'; uv run pytest tests/unit/research_layer tests/integration/research_api -q`
   - 结果：`101 passed in 40.60s`（回归通过）

## Dev Console 路径

- URL: `/api/v1/research/dev-console`
- Slice 10 最小能力（真实 API 薄封装）：
  - `Retrieve Evidence View`
  - `Retrieve Contradiction View`
  - `Retrieve Failure Pattern View`
  - `Retrieve Validation History View`
  - `Retrieve Hypothesis Support View`
  - `Run Retrieval Query Change`（同一 view 改查询后二次检索）

## startup / reset commands

- Startup（repo root）：
  - `set PYTHONPATH=src`
  - `uv run python src/run.py`
- Reset research acceptance data：
  - `set PYTHONPATH=src`
  - `uv run python -c "from research_layer.api.controllers._state_store import STORE; STORE.reset_all()"`

## fixture / demo data

- 自动化测试 fixture：
  - `tests/unit/research_layer/test_slice10_retrieval_services.py`
  - `tests/integration/research_api/test_slice10_retrieval_views_flow.py`
- 持久化文件：
  - `data/research_slice2.sqlite3`（由当前 research layer SQLite store 使用）

## manual steps

1. 打开 `/api/v1/research/dev-console`。
2. Import Source -> Trigger Extract -> Refresh Candidates -> Confirm Candidate（至少两条 source，含 claim/conflict/failure/validation 语义）。
3. Build Graph -> Generate Routes。
4. Attach Failure 并创建至少一次 Validation Action 与 Hypothesis（保证五个 view 都有可检索对象）。
5. 在 Retrieval 区输入 query 与 filter（JSON），依次点击五个 `Retrieve * View` 按钮。
6. 检查每次返回是否包含 `source_ref / graph_refs / formal_refs / trace_refs`。
7. 点击 `Run Retrieval Query Change`，观察 evidence view 两次查询返回排序或 top result 变化。
8. 构造错误输入：
   - 非法 view path
   - 非法 filter key
   - 缺失 `workspace_id`
   验证显式错误语义。

## expected observations

- 五个 retrieval view 都可通过真实 API 返回科研语义结果。
- `retrieve_method=hybrid` 返回稳定分数排序，不是写死顺序。
- metadata filter 会真实影响结果集。
- 每条结果可回链到 source / graph / formal/supporting refs。
- query 改变后，至少一类 view（evidence）top result 或排序可观察变化。
- `research_events` 可见 `retrieval_view_started` 与 `retrieval_view_completed`（成功/失败可区分）。

## 已知风险

- 当前 `vector` 分量采用轻量 token-cosine（deterministic）实现，满足 Slice 10 hybrid 契约；后续若接入 Milvus embeddings，需要保持同一 API/traceability/error 语义。
- failure pattern 与 hypothesis support 的 source 回链在“仅 failure report、无 formal source 映射”的边界场景下可能为空，但 graph/formal refs 仍可追溯。
