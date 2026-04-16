# ROUTE_ENGINE_SPEC.md — 路线生成、推理链与排序

## 1. 目标

Route engine 的目标是：

- 从真实 graph、正式 `Hypothesis`、`ReasoningChain` 和最新版本上下文中生成候选路线
- 让每条路线都带显式中间步骤，而不是只有结论和邻居节点
- 对每条路线做确定性评分、排序和预览
- 在 failure / validation 回灌后真实重算，而不是只刷新页面

Route engine 不是自由叙事生成器。它必须始终以真实 graph、正式 hypothesis 和程序评分为准。

## 2. 输入边界

路线生成只能消费：

- 当前 `workspace_id`
- 当前 `GraphVersion`
- graph 中真实存在的 `GraphNode` / `GraphEdge`
- 已正式落库的 `Hypothesis`
- 已落库的 `ReasoningChain` / `ReasoningStep`
- 当前有效的 `MechanismRevision`
- 当前有效的 `WeakestStepAssessment`

禁止：

- 直接使用未 finalize 的 hypothesis candidate 生成正式路线
- 用 LLM 自由编造中间步骤
- 用 mock path 或静态 JSON 冒充路线结果

## 3. 核心组件与职责边界

### 3.1 Reasoning Subgraph Resolver

职责：

- 围绕目标结论、正式 hypothesis 或显式 goal 抽取局部推理子图
- 为 route generation 提供噪声受控的输入上下文

最小输出：

- `reasoning_subgraph_id`
- `focus_node_ids[]`
- `focus_edge_ids[]`
- `anchor_hypothesis_ids[]`
- `version_id`

### 3.2 Chain-aware Candidate Builder

职责：

- 从 reasoning subgraph 中组装候选路线
- 尽量沿正式 `ReasoningChain` 取中间步骤
- 让路线保持“起点 -> 机制桥 -> 结果”的显式顺序

最小输出：

- `route_id`
- `workspace_id`
- `conclusion_node_id`
- `route_node_ids[]`
- `route_edge_ids[]`
- `reasoning_chain_id`
- `reasoning_steps[]`
- `key_support_node_ids[]`
- `key_assumption_node_ids[]`
- `risk_node_ids[]`
- `weakest_step_ref`
- `next_validation_node_id`
- `trace_refs`

### 3.3 Route Ranker

职责：

- 基于程序控制的评分结果排序
- 不允许 LLM 直接改写顺序

### 3.4 Route Summarizer

职责：

- 把已存在的路线结构解释成可读摘要
- 只能润色和压缩，不得更改路线成员、分数、排序、top factors

## 4. Reasoning Subgraph 规则

### 4.1 输入模式

至少支持：

- `by_conclusion_node`
- `by_hypothesis`
- `by_goal`

### 4.2 最小覆盖

一个合法 reasoning subgraph 至少包含：

- 一个结论锚点
- 与锚点直接相关的 support / assumption / conflict / failure / validation 节点
- 如存在正式 `ReasoningChain`，优先包含链上的中间步骤节点

### 4.3 剪枝规则

必须优先裁掉：

- 与目标无 trace 关系的孤立节点
- 纯历史归档节点
- 与当前版本无关的 superseded 分支

禁止把整个 workspace 全图原样塞给 route generation。

## 5. 候选路线生成规则

### 5.1 生成原则

候选路线必须满足：

- 始终从真实子图构建
- 优先引用正式 hypothesis 的 reasoning chain
- 优先保留显式中间步骤
- 若存在 `MechanismRevision`，优先采用修正后的链

### 5.2 路线中间步骤

若图中存在可用中间机制节点，路线必须显式输出 `reasoning_steps[]`，而不是只给结论摘要。

`reasoning_steps[]` 每项至少包含：

- `step_id`
- `order_index`
- `step_type`
- `claim_text`
- `support_refs[]`
- `risk_refs[]`
- `status`

### 5.3 最弱一跳

每条路线都应尽量包含：

- `weakest_step_ref`
- `weakest_step_reason`
- `recommended_validation_action`

若 route 无法识别 weakest step，必须在预览与 breakdown 中显式标记缺失。

## 6. Route 评分与排序

### 6.1 排序输入

每条路线必须先有：

- `support_score`
- `risk_score`
- `progressability_score`
- `score_breakdown`
- `top_factors`

### 6.2 排序比较器

排序必须使用纯程序规则：

1. `support_score` 降序
2. `risk_score` 升序
3. `progressability_score` 降序
4. `private_dependency_pressure` 升序
5. `route_id` 字典序升序

必须保证：

- 同输入下排序稳定
- LLM 无权直接改写排序

### 6.3 Route 与 Hypothesis 的边界

- route 是“当前值得推进的研究路径”
- hypothesis 是“候选机制陈述”
- route 可以引用 hypothesis，但不能把未 finalize 的 hypothesis candidate 直接当 route 结论

## 7. Route Preview Schema

`GET /api/v1/research/routes/{route_id}/preview` 至少返回：

- `route_id`
- `workspace_id`
- `conclusion_node`
- `reasoning_chain_id`
- `reasoning_steps[]`
- `key_support_evidence[]`
- `key_assumptions[]`
- `conflict_failure_hints[]`
- `weakest_step`
- `next_validation_action`
- `top_factors[]`
- `trace_refs`

其中 `weakest_step` 至少包含：

- `step_id`
- `reason`
- `support_score`
- `risk_score`
- `observability_score`

## 8. 重算语义

recompute 不是简单刷新，而是：

1. 读取最新 graph/version
2. 应用 failure / validation 影响
3. 读取最新 `MechanismRevision`
4. 重新抽 reasoning subgraph
5. 重新组装候选路线
6. 重新评分与排序
7. 生成新版本和 diff

当失败打断链路时，route engine 必须能观察到：

- 路线 status 变化
- weakest step 变化
- next validation action 变化
- 排序变化

## 9. 设计边界

- 路线首页展示的是“可推进路径”，不是自动决策器
- 真核心仍然是 graph 可重写、路线可重算、diff 可回链
- 禁止 hard-coded preview、静态样例路径、虚构路线成员

## 10. 错误语义

- workspace 与 route 归属不一致：`409 + research.conflict`
- route 不存在：`404 + research.not_found`
- reasoning subgraph 构建失败：`409 + research.invalid_state`
- focus nodes 含未知 node：`400 + research.invalid_request`
- 图谱未就绪导致不可生成路线：`409 + research.invalid_state`
