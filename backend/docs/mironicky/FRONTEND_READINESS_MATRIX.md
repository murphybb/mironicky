# Frontend Readiness Matrix (Track 5)

状态：developer baseline  
日期：2026-04-02  
范围：仅 Track 5（Frontend Readiness Matrix），不包含 Track 6 Memory Vault Controlled Actions 实现

## 1. 目的与约束

本文件是 `research-workspace-v12` 切换“真实 API store”的唯一真源，明确每个正式页面：

- 哪些动作已真实接通（real connected）
- 哪些动作只能只读（read-only）
- 哪些动作必须禁用并标注未接通（disabled / not yet connected）

硬约束执行：

- 禁止 `defaultState() + localStorage` 继续承担业务主状态。
- 禁止 mock/TODO/fake path/hard-coded happy path。
- 严禁跨到 Track 6：本文件只定义 Memory 页在 Track 5 的可接边界，不新增 Memory 写 API。

## 2. 统一前端 Store 契约

前端统一 API store 必须以本矩阵为准：

- 全局主键：`workspace_id`
- 异步统一：`queued|running|succeeded|failed|cancelled`
- job 查询入口：`GET /api/v1/research/jobs/{job_id}`
- 错误结构：`error_code` + `message` + `details`

### 2.1 workspace_id 传递规则（强制）

- `GET` 列表/查询接口：默认使用 query `workspace_id=...`。
- `POST/PATCH/DELETE` 写接口：默认在 request body 传 `workspace_id`。
- path 已包含 `{workspace_id}` 的接口：仍视为显式 workspace 作用域，不允许前端省略。
- 单资源读取中若后端要求 query `workspace_id`（例如 route preview、candidate detail），前端必须显式传，不能靠资源 id 猜测。

## 3. 页面接入矩阵

### 3.1 Home（Route Space）

| 维度 | 结论 |
|---|---|
| 真实 API 数据源 | `GET /api/v1/research/routes?workspace_id=...`（query）；`GET /api/v1/research/routes/{route_id}/preview?workspace_id=...`（query）；可选刷新 `POST /api/v1/research/routes/generate`（body: `workspace_id`） |
| 是否异步 | 首页只读加载为同步；若触发 `routes/generate` 为同步写入（非 job） |
| 是否需要 job polling | 否（Home 主路径不依赖 job） |
| 当前可写动作 | `Generate/Refresh Routes` -> `POST /routes/generate`（真实写） |
| 当前只读动作 | 路线列表读取、当前路线预览读取 |
| 当前禁用动作 | 不在 Home 直接执行 recompute/failure/package publish；按钮若存在必须 disabled 并标注“not yet connected in Home” |

页面判定：

- 真接：路线列表与 preview
- 假接：任何继续从 `defaultState.routes/currentRoute` 读主数据的路径
- 不能接：Home 内跨域写动作（failure attach、package publish）

### 3.2 Sources

| 维度 | 结论 |
|---|---|
| 真实 API 数据源 | `GET /api/v1/research/sources?workspace_id=...`（query）；`GET /api/v1/research/sources/{source_id}`；`GET /api/v1/research/candidates?workspace_id=...`（query）；`GET /api/v1/research/candidates/{candidate_id}?workspace_id=...`（query）；`GET /api/v1/research/sources/{source_id}/extraction-results/{candidate_batch_id}?workspace_id=...`（query） |
| 是否异步 | `extract` 异步入口；其余读取/confirm/reject 同步 |
| 是否需要 job polling | 是（`POST /sources/{source_id}/extract` 后必须轮询 `/jobs/{job_id}` 并回链 extraction result） |
| 当前可写动作 | `Import Source` -> `POST /sources/import`（body: `workspace_id`）；`Extract` -> `POST /sources/{source_id}/extract`（body: `workspace_id`）；`Confirm` -> `POST /candidates/confirm`（body: `workspace_id`）；`Reject` -> `POST /candidates/reject`（body: `workspace_id`） |
| 当前只读动作 | sources/candidates 列表与详情查询 |
| 当前禁用动作 | 任何前端本地“直接入图/直接改 route”的捷径按钮必须 disabled（not yet connected in Sources） |

页面判定：

- 真接：import/extract/list/confirm/reject 全链路
- 假接：本地 `materials[]` 当主数据源
- 不能接：绕过 confirm 直接写 graph

### 3.3 Workbench

| 维度 | 结论 |
|---|---|
| 真实 API 数据源 | `GET /api/v1/research/graph/{workspace_id}`（path）；`GET /api/v1/research/graph/{workspace_id}/workspace`（path）；`POST /api/v1/research/graph/{workspace_id}/query`（path+body）；`GET /api/v1/research/versions?workspace_id=...`（query）；`GET /api/v1/research/versions/{version_id}/diff`；`GET /api/v1/research/routes/{route_id}/preview?workspace_id=...`（query） |
| 是否异步 | recompute 为异步入口；其余 graph CRUD / failure / validation 为同步 |
| 是否需要 job polling | 是（`POST /routes/recompute` 后必须轮询 `/jobs/{job_id}` 并按 `result_ref` 读取 `graph_version` diff 或 route） |
| 当前可写动作 | 节点/边 create/patch/archive：`POST/PATCH/DELETE /graph/...`（body 必含 `workspace_id`，graph/{workspace_id} 接口除外）；`POST /failures`（body: `workspace_id`）；`POST /validations`（body: `workspace_id`）；`POST /routes/recompute`（body: `workspace_id`）；可选 `POST /routes/{route_id}/score`（body: `workspace_id`） |
| 当前只读动作 | 图谱查询、workspace 统计、version/diff 查询、route preview |
| 当前禁用动作 | 物理删除（hard delete）必须禁用；archive 后对象“重新激活”必须禁用（invalid_state） |

页面判定：

- 真接：graph CRUD（含 archive 语义）+ failure/recompute/diff
- 假接：仅前端删除节点边不落后端
- 不能接：任何 hard delete path

### 3.4 Hypothesis

| 维度 | 结论 |
|---|---|
| 真实 API 数据源 | `GET /api/v1/research/hypotheses/triggers/list?workspace_id=...`（query）；`GET /api/v1/research/hypotheses?workspace_id=...`（query）；`GET /api/v1/research/hypotheses/{hypothesis_id}` |
| 是否异步 | generate 为异步入口；promote/reject/defer 为同步 |
| 是否需要 job polling | 是（`POST /hypotheses/generate` 后必须轮询 `/jobs/{job_id}` 并回链 hypothesis 详情） |
| 当前可写动作 | `Generate` -> `POST /hypotheses/generate`（body: `workspace_id`）；`Promote` -> `POST /hypotheses/{id}/promote`（body: `workspace_id`）；`Reject` -> `POST /hypotheses/{id}/reject`（body: `workspace_id`）；`Defer` -> `POST /hypotheses/{id}/defer`（body: `workspace_id`） |
| 当前只读动作 | trigger 列表、inbox 列表、hypothesis 详情 |
| 当前禁用动作 | 前端本地“隐藏即 defer”必须禁用；直接升为主结论按钮必须禁用（not yet connected by contract） |

页面判定：

- 真接：inbox + defer/promote/reject + async generate
- 假接：本地状态改写 hypothesis 生命周期
- 不能接：绕过状态机的直接主路线升级

### 3.5 Memory（Track 5 边界）

| 维度 | 结论 |
|---|---|
| 真实 API 数据源 | `POST /api/v1/research/retrieval/views/{view_type}`（body: `workspace_id`；`view_type` in `evidence/contradiction/failure_pattern/validation_history/hypothesis_support`） |
| 是否异步 | 否（当前 retrieval 查询同步返回） |
| 是否需要 job polling | 否 |
| 当前可写动作 | 无（Track 5 不提供 Memory 写动作） |
| 当前只读动作 | retrieval-backed 列表/过滤/查询；回链 source/graph/formal refs |
| 当前禁用动作 | `bind to route`、`memory -> hypothesis-candidate`、`memory direct edit/delete` 全部 disabled，并标注 `not yet connected (Track 6)` |

页面判定：

- 真接：retrieval read model
- 假接：任何本地 Memory 写状态
- 不能接：Track 6 才定义的 controlled actions

### 3.6 Package

| 维度 | 结论 |
|---|---|
| 真实 API 数据源 | `GET /api/v1/research/packages?workspace_id=...`（query）；`GET /api/v1/research/packages/{package_id}?workspace_id=...`（query, 推荐显式传）；`GET /api/v1/research/packages/{package_id}/replay?workspace_id=...`（query, 推荐显式传）；`GET /api/v1/research/packages/{package_id}/publish-results/{publish_result_id}?workspace_id=...`（query, 推荐显式传） |
| 是否异步 | publish 为异步入口；create/get/list/replay 为同步 |
| 是否需要 job polling | 是（`POST /packages/{package_id}/publish` 后必须轮询 `/jobs/{job_id}` 并回链 publish result） |
| 当前可写动作 | `Create Package` -> `POST /packages`（body: `workspace_id`）；`Publish Package` -> `POST /packages/{package_id}/publish`（body: `workspace_id`） |
| 当前只读动作 | list/get/replay/publish result |
| 当前禁用动作 | 前端本地“强制发布成功”分支必须 disabled；无 publish result 回链时禁止显示 published 成功态 |

页面判定：

- 真接：create/list/get/replay/publish(+job)
- 假接：前端自判 blocker 通过即成功发布
- 不能接：跳过 job/result_ref 的 publish happy path

## 4. 前端切换执行要求（Track 5）

切 store 时必须满足：

1. 页面主数据只来自本矩阵对应 API。
2. 任一未接通动作必须显式显示 `disabled` 或 `read-only` 或 `not yet connected`。
3. 不得再保留 defaultState/localStorage 作为业务主路径回退。
4. 所有异步入口必须走统一 job polling，并消费 `result_ref` 回链最终资源。

## 5. Track 边界声明

- 本文档结论：Track 5 达到 `developer_complete` 的文档与接入边界定义要求。
- 本文档不判定 `evaluator_pass`。
- Track 6 事项（Memory controlled writes）明确保持禁用，未在本 Track 实现。
