# RESEARCH_PACKAGE_SPEC.md — Research Package Publishing

## 1. 目标

把个人研究成果按边界发布到团队，而不是做个人工作区到团队工作区的 live sync。

## 2. 发布对象

发布对象是 Research Package snapshot，至少包含：

- package title / summary
- included routes
- included nodes
- included validations
- private dependency flags
- public gap nodes

## 3. 私密依赖规则

如果一条个人推理链依赖私密信息，而该信息不能共享：

- 团队版绝不能伪装成链路仍然完整
- 系统必须显式标出未公开依赖
- 系统必须自动生成 public gap

## 4. 团队工作区边界

- 团队承接的是 research package，不是个人工作区全部状态
- 发布后团队看到的是可重放、可查询、带边界说明的快照

## 5. Slice 11 前必须补齐

- package schema
- snapshot / replay 规则
- private dependency -> public gap 规则
- publish API contract

## 6. Slice 11 Package Schema（冻结）

`ResearchPackage` 在 Slice 11 的最小快照字段：

- `package_id`
- `workspace_id`
- `title`
- `summary`
- `status = draft | published`
- `snapshot_type = research_package_snapshot`
- `snapshot_version = slice11.v1`
- `included_route_ids`
- `included_node_ids`
- `included_validation_ids`
- `private_dependency_flags`
- `public_gap_nodes`
- `boundary_notes`
- `traceability_refs`
- `replay_ready`（布尔）
- `build_request_id`
- `created_at`
- `updated_at`
- `published_at`（可空）

`private_dependency_flags` 每项最小字段：

- `private_node_id`
- `private_object_ref`
- `reason = private_dependency_requires_public_gap`
- `referenced_by_route_ids`
- `replacement_gap_node_id`

`public_gap_nodes` 每项最小字段：

- `node_id`
- `workspace_id`
- `node_type = gap`
- `object_ref_type = public_gap`
- `object_ref_id`
- `short_label`
- `full_description`
- `status`
- `trace_refs`

## 7. Snapshot Build 规则（冻结）

- package create 必须触发真实 `package build`，从正式状态源读取 route/node/validation。
- package 不能绑定 live workspace；create 时必须固化 snapshot payload。
- create 请求中传入的 route/node/validation 引用必须：
  - 资源存在；
  - 归属同一 `workspace_id`；
  - 非法输入显式报错，不允许静默忽略。
- create 至少要包含 route/node/validation 之一；空 package 请求返回 `research.invalid_request`。

## 8. Replay 规则（冻结）

- package 必须可 replay：通过 package replay 视图返回完整 snapshot payload。
- replay 输出必须包含：
  - `routes[]`
  - `nodes[]`
  - `validations[]`
  - `private_dependency_flags[]`
  - `public_gap_nodes[]`
  - `boundary_notes[]`
  - `traceability_refs`
- replay 输出不允许依赖前端临时推导，不允许现查 live graph 替换 snapshot 内容。

## 9. Private Dependency -> Public Gap 规则（冻结）

- `node_type=private_dependency` 的节点进入 package build 时必须被显式识别。
- 被识别的私密依赖不能“直接删除后当作完整链路”；必须同时生成：
  - 一条 `private_dependency_flag`
  - 一条 `public_gap_node`
- 默认策略：
  - private dependency 节点不进入 package public node 列表；
  - 由 `public_gap_node` 作为公开替代占位；
  - 通过 `replacement_gap_node_id` 和 `trace_refs` 保持可回链。

## 10. API Contract（Slice 11 冻结）

- `POST /api/v1/research/packages`：构建 snapshot package（create + build）。
- `GET /api/v1/research/packages`：按 workspace 查询 package 列表（query）。
- `GET /api/v1/research/packages/{package_id}`：读取 package 元信息与边界信息（get）。
- `GET /api/v1/research/packages/{package_id}/replay`：读取 snapshot replay payload。

## 11. Publish Contract（Slice 11 冻结）

- `POST /api/v1/research/packages/{package_id}/publish` 支持异步 job 契约：
  - 返回 `job_id/status_url`；
  - job 终态 `succeeded` 时，`result_ref` 必须回链 publish result 资源。
- publish result 是 package snapshot 的发布记录，不是 live sync 状态指针。
- publish 成功后 package 状态切换到 `published`，并写入 `published_at`。

## 12. 错误语义（Slice 11）

- `research.invalid_request`：
  - 缺失 `workspace_id`
  - create 输入集合为空
  - 引用字段格式非法
- `research.not_found`：
  - package / route / node / validation / publish_result 不存在
- `research.conflict`：
  - `workspace_id` 与资源归属不一致
- `research.invalid_state`：
  - package 状态不允许 publish（如重复 publish）

## 13. 可追溯与白盒要求（Slice 11）

- package build / publish 必须落结构化事件，至少：
  - `package_build_started`
  - `package_build_completed`
  - `package_publish_started`
  - `package_publish_completed`
  - `job_failed`（异步 publish 失败时）
- 事件中必须可回链：
  - `request_id`
  - `job_id`（若异步）
  - `workspace_id`
  - `package_id`
  - `refs`（route/node/validation/private/gap/publish_result）
