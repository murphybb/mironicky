# FAILURE_LOOP_SPEC.md — 失败回路、机制修正与重算

## 1. 目标

失败不是注释，而是必须真实改变以下内容的输入：

- graph 状态
- reasoning step 状态
- weakest-step 判断
- route 分数与排序
- mechanism revision
- 版本差异

Mironicky 的 failure loop 必须让系统因为失败而改变机制判断，而不是只给路线减几分。

## 2. Failure Attach

### 2.1 原始 attach 边界

`FailureReport` 仍然只能原始 attach 到：

- `node`
- `edge`

这保持与当前 graph 真源边界一致。

### 2.2 派生影响对象

尽管原始 attach 只落在 node / edge，系统必须继续派生出对以下对象的影响：

- `ReasoningStep`
- `ReasoningChain`
- `Hypothesis`
- `Route`
- `WeakestStepAssessment`
- `MechanismRevision`

也就是说：

- 原始 attach 边界不扩散
- 影响传播边界必须扩展到推理层对象

### 2.3 Attach 最小结构

每个 failure 至少包含：

- `failure_id`
- `workspace_id`
- `attached_targets[]`
- `observed_outcome`
- `expected_difference`
- `failure_reason`
- `severity`
- `reporter`
- `trace_refs`

`attached_targets[]` 每项必须包含：

- `target_type = node | edge`
- `target_id`

若目标不存在或 workspace 不一致，必须显式报错。

## 3. Failure Impact 传播

### 3.1 Graph 级影响

对 node attach：

- 目标 node 至少迁移到 `weakened`
- 若 severity 足够高，可进入 `failed`

对 edge attach：

- 目标 edge 至少迁移到 `weakened`
- 若 severity 足够高，可进入 `invalidated`

### 3.2 推理层影响

当 failure 命中某个 node / edge 的 trace 时，系统必须派生更新：

- 命中的 `ReasoningStep.status`
- 命中的 `ReasoningChain` 健康度
- 命中的 `Hypothesis` 信心与可测试性
- 命中的 `Route.status`

### 3.3 最弱一跳刷新

当 failure 命中路线或 hypothesis 所依赖的中间步骤时，必须重新计算：

- `WeakestStepAssessment`
- `recommended_validation_action`

如果原 weakest step 已经失效，必须显式替换，不允许沿用旧 weakest step。

### 3.4 机制修正

每次有效 failure impact 后，系统必须尝试生成或更新 `MechanismRevision`，最小包含：

- `revision_id`
- `workspace_id`
- `failure_id`
- `affected_reasoning_chain_ids[]`
- `invalidated_step_ids[]`
- `replacement_hypothesis_hint`
- `status`

状态只允许：

- `suggested`
- `confirmed`
- `rejected`

## 4. Validation 反馈回路

当 validation 结果为 `weakened` 或 `failed` 时，系统必须：

1. 生成或更新 `FailureReport`
2. 挂到对应 node / edge
3. 派生更新 weakest-step
4. 派生更新 mechanism revision
5. 触发 recompute

禁止 validation 失败后只停留在一条文本说明，不进入图谱和推理层对象。

## 5. Recompute

### 5.1 Recompute 定义

recompute 是真实后端重算流程，不是页面刷新。

### 5.2 最小流程

每次 recompute 至少执行：

1. 读取并校验 `failure_id`
2. 应用 node / edge 级 failure impact
3. 刷新受影响的 `ReasoningStep` / `ReasoningChain`
4. 刷新 `WeakestStepAssessment`
5. 生成或更新 `MechanismRevision`
6. 重新计算 route score / ranking
7. 生成并持久化新 `GraphVersion`
8. 生成并持久化 version diff

### 5.3 输出要求

recompute 的结果必须可回链到：

- `failure_id`
- `base_version_id`
- `new_version_id`
- 受影响 node / edge / route
- 受影响 reasoning chain / step
- mechanism revision

## 6. Version Diff

### 6.1 最小 diff 维度

每次 failure / validation / recompute 至少要表达：

- `added`
- `weakened`
- `invalidated`
- `branch_changes`
- `route_score_changes`
- `reasoning_chain_changes`
- `mechanism_revisions`

### 6.2 reasoning_chain_changes 最小结构

每项至少包含：

- `reasoning_chain_id`
- `invalidated_step_ids[]`
- `weakened_step_ids[]`
- `new_weakest_step_id`

### 6.3 mechanism_revisions 最小结构

每项至少包含：

- `revision_id`
- `status`
- `affected_reasoning_chain_ids[]`
- `replacement_hypothesis_hint`

禁止前端临时拼装 diff。diff 必须来自后端 recompute 持久化结果。

## 7. Follow-up Trigger

当 mechanism revision 无法在当前正式 hypothesis / route 内部消化时，系统必须显式产生 follow-up trigger，用于后续 hypothesis engine：

- `trigger_type = failure | weak_support | gap`
- `source_failure_id`
- `source_revision_id`
- `workspace_id`

是否立刻自动开启新候选池，可以作为编排策略决定；但 follow-up trigger 本身必须落库可追踪。

## 8. 设计边界

- failure 不是评论，不是 badge，不是 UI 装饰
- failure loop 的产物必须影响 graph、reasoning chain、route、version
- 机制修正是正式对象，不是临时字符串建议

## 9. 错误语义

- attach target 不存在：`404 + research.not_found`
- attach target 跨 workspace：`409 + research.conflict`
- 重复 attach 同一 target：`409 + research.invalid_state`
- 对 `archived/superseded` 对象 attach：`409 + research.invalid_state`
- recompute 输入不完整：`400 + research.invalid_request`
- recompute 执行失败：同步返回结构化错误，或异步 job 进入 `failed`
