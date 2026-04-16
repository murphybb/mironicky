# HYPOTHESIS_ENGINE_SPEC.md — 假设引擎与多 Agent 推理循环

## 1. 目标

Hypothesis engine 的目标不再是“单次生成一个假设候选”，而是：

- 从合法 trigger、推理子图、最新图谱版本和验证/失败反馈中生成一组候选假设
- 通过多 Agent 审查、比较、进化和搜索，筛出更强的候选
- 以程序控制的 tournament、Elo 和搜索树状态驱动淘汰与保留
- 最终只把 top-k 候选晋级为正式 `Hypothesis`

Hypothesis engine 不是路线排序器，也不是最终裁判。它负责：

- 生成候选
- 暴露中间推理链
- 识别最弱一跳
- 生成下一轮验证建议

路线结论、最终版本、下游 package 使用的对象仍然是正式 `Hypothesis`，不是未定稿的候选。

## 2. 输入边界

### 2.1 合法输入来源

Hypothesis engine 只能消费以下真实后端输入：

- 已确认的 `gap`
- 已确认的 `conflict`
- 已确认的 `failure`
- 程序计算得到的 `weak_support`
- 由 graph/query 层生成的 `ReasoningSubgraph`
- 当前 `GraphVersion`
- 当前 workspace 内已存在的正式 `Hypothesis`
- 与 trigger 相关的 validation / failure / route / graph trace refs

禁止：

- 直接从自由文本凭空生成 hypothesis
- 绕过 workspace 边界读取外部对象
- 用未确认 candidate 反向污染正式 graph

### 2.2 Trigger 最小结构

每个 trigger 至少包含：

- `trigger_id`
- `trigger_type`，仅允许 `gap | conflict | failure | weak_support`
- `workspace_id`
- `object_ref_type`
- `object_ref_id`
- `summary`
- `trace_refs`
- `metrics`

### 2.3 Generate 入参最小集合

生成候选池至少需要：

- `workspace_id`
- `trigger_ids[]`
- `research_goal`
- `reasoning_mode`
- `top_k`

可选补充：

- `constraints`
- `preference_profile`
- `seed_hypothesis_ids`
- `max_rounds`
- `budget_hint`

若 `trigger_ids` 中任意一项不合法、跨 workspace、或不存在，必须返回显式错误。

## 3. 核心对象

### 3.1 HypothesisCandidatePool

候选池是一次多 Agent 推理任务的容器，至少包含：

- `pool_id`
- `workspace_id`
- `trigger_refs[]`
- `reasoning_subgraph_id`
- `status`
- `top_k`
- `max_rounds`
- `current_round_number`
- `orchestration_mode`
- `created_by_job_id`
- `created_at`
- `updated_at`

状态只允许：

- `queued`
- `running`
- `stopped`
- `finalized`
- `failed`
- `cancelled`

### 3.2 HypothesisCandidate

单个候选至少包含：

- `candidate_id`
- `pool_id`
- `workspace_id`
- `title`
- `statement`
- `summary`
- `rationale`
- `trigger_refs[]`
- `related_object_ids[]`
- `reasoning_chain_id`
- `minimum_validation_action`
- `weakening_signal`
- `novelty_typing`
- `status`
- `origin_type`
- `origin_round_number`
- `elo_rating`
- `survival_score`
- `created_at`
- `updated_at`

状态只允许：

- `alive`
- `pruned`
- `finalized`
- `rejected`

### 3.3 HypothesisRound

每一轮编排至少包含：

- `round_id`
- `pool_id`
- `round_number`
- `status`
- `start_reason`
- `stop_reason`
- `generation_count`
- `review_count`
- `match_count`
- `evolution_count`
- `meta_review_id`
- `created_at`
- `completed_at`

### 3.4 HypothesisReview

Reflection agent 产物至少包含：

- `review_id`
- `pool_id`
- `round_id`
- `candidate_id`
- `review_type`
- `strengths[]`
- `weaknesses[]`
- `missing_evidence[]`
- `testability_issues[]`
- `weakest_step_ref`
- `recommended_actions[]`
- `trace_refs[]`

### 3.5 HypothesisMatch

每场对局至少包含：

- `match_id`
- `pool_id`
- `round_id`
- `left_candidate_id`
- `right_candidate_id`
- `winner_candidate_id`
- `loser_candidate_id`
- `match_reason`
- `compare_vector`
- `left_elo_before`
- `right_elo_before`
- `left_elo_after`
- `right_elo_after`
- `created_at`

### 3.6 HypothesisEvolution

Evolution agent 产物至少包含：

- `evolution_id`
- `pool_id`
- `round_id`
- `source_candidate_id`
- `new_candidate_id`
- `evolution_mode`
- `driving_review_ids[]`
- `change_summary`
- `preserved_claims[]`
- `modified_claims[]`

### 3.7 HypothesisMetaReview

Meta-review 至少包含：

- `meta_review_id`
- `pool_id`
- `round_id`
- `recurring_issues[]`
- `strong_patterns[]`
- `weak_patterns[]`
- `continue_recommendation`
- `stop_recommendation`
- `diversity_assessment`

### 3.8 HypothesisProximityEdge

Proximity 关系至少包含：

- `pool_id`
- `from_candidate_id`
- `to_candidate_id`
- `similarity_score`
- `shared_trigger_ratio`
- `shared_object_ratio`
- `shared_chain_overlap`

### 3.9 HypothesisSearchTreeNode

搜索树节点至少包含：

- `tree_node_id`
- `pool_id`
- `parent_tree_node_id`
- `candidate_id`
- `node_role`
- `depth`
- `visits`
- `mean_reward`
- `uct_score`
- `status`

### 3.10 正式 Hypothesis

正式 `Hypothesis` 至少需要保留以下 lineage：

- `source_pool_id`
- `source_candidate_id`
- `source_round_id`
- `finalizing_match_id`
- `reasoning_chain_id`
- `weakest_step_ref`

只有正式 `Hypothesis` 允许进入验证、路线、package 等下游流程。

## 4. 多 Agent 角色与职责

### 4.1 Supervisor Agent

职责：

- 决定本轮是否继续
- 决定先生成、先比较还是先进化
- 决定搜索树扩展和剪枝
- 决定是否满足终止条件

来源等级：

- `reconstructed-from-paper`

### 4.2 Generation Agent

职责：

- 根据 trigger、goal、reasoning subgraph 生成候选假设
- 产出 statement、rationale、validation hint、weakening signal

来源等级：

- `published`

### 4.3 Reflection Agent

职责：

- 对单个 candidate 做结构化审查
- 标记缺证、弱点、可测试性问题
- 输出 weakest-step 候选

来源等级：

- `published`

### 4.4 Ranking Agent

职责：

- 对两个 candidate 做结构化比较
- 输出 compare vector、胜负理由、需要注意的隐藏弱点

来源等级：

- `published`

### 4.5 Evolution Agent

职责：

- 根据 review 或输掉对局的原因改写 candidate
- 生成更保守或更激进的变体

来源等级：

- `published`

### 4.6 Meta-review Agent

职责：

- 汇总当前 round 中 recurring issues
- 给 Supervisor 提供 stop/continue 建议

来源等级：

- `published`

### 4.7 Proximity Agent

职责：

- 计算 candidate 之间的相似度
- 组织 tournament pairing
- 避免无意义的远距离对打

来源等级：

- 职责定义 `published`
- 具体实现 `local-design`

## 5. Prompt 来源分级

多 Agent prompt 必须标注来源等级：

- `published`
- `code-derived`
- `reconstructed-from-paper`
- `local-design`

强制规则：

- 只有论文或附录明确公开的 prompt 结构，才能标为 `published`
- 从开源仓库读到的角色约定或模板，只能标为 `code-derived`
- 按论文职责重建但没有公开原文模板的，只能标为 `reconstructed-from-paper`
- 为 Mironicky 特有 graph/version/weakest-step 需求新增的模板，必须标为 `local-design`

## 6. 编排状态机

### 6.1 候选池主状态

- `queued`
- `running`
- `stopped`
- `finalized`
- `failed`
- `cancelled`

### 6.2 轮次内固定阶段

每轮至少按以下阶段运行：

1. `generation_running`
2. `reflection_running`
3. `proximity_running`
4. `ranking_running`
5. `evolution_running`
6. `meta_review_running`
7. `branch_selection_running`

### 6.3 终止条件

满足任一条件即可停：

- 达到 `max_rounds`
- `alive` candidate 数量小于等于 `top_k`
- 连续两轮 top candidate 稳定
- diversity 下降到阈值以下
- budget 耗尽
- Supervisor / Meta-review 同时建议停止

## 7. Tournament 与 Elo 规则

### 7.1 初始 Elo

每个新 candidate 的初始 Elo 固定为：

- `1200`

### 7.2 期望胜率

使用标准 Elo 公式：

- `expected(left) = 1 / (1 + 10 ^ ((right_elo - left_elo) / 400))`
- `expected(right) = 1 - expected(left)`

### 7.3 更新公式

本轮默认 `K = 32`：

- `new_elo = old_elo + 32 * (actual_score - expected_score)`

其中：

- 胜者 `actual_score = 1`
- 负者 `actual_score = 0`

### 7.4 对局调度优先级

优先安排以下候选参赛：

- 最近一轮新生成或新进化的 candidate
- Elo 排名前列 candidate
- 相似度较高的 candidate
- 共享同一 trigger 或同一 reasoning subgraph 的 candidate

禁止：

- 纯随机无约束对局
- 只让 Elo 高的 candidate 碾压低 Elo 候选，不给新候选出场机会

## 8. 搜索树与 MCTS 风格规则

### 8.1 搜索树节点类型

搜索树节点 `node_role` 至少支持：

- `root`
- `generated`
- `evolved`
- `expanded`
- `pruned`
- `finalized`

### 8.2 选择分数

采用 UCT 风格选择分数：

- `uct_score = mean_reward + c * sqrt(ln(parent_visits + 1) / (visits + 1))`

默认探索系数：

- `c = 1.4`

### 8.3 Expand

Expand 必须至少执行一项：

- 让 Evolution agent 生成变体
- 让 Generation agent 在同一子图上提出新机制分支
- 让 Reflection agent 指定 weakest-step 后，围绕 weakest-step 生成替代链

### 8.4 Simulation / Rollout

Mironicky 中的 rollout 不是随机模拟，而是最小多 Agent 快评：

- 一次快速 reflection
- 一次 pairwise ranking
- 一次结构化 reward 计算

### 8.5 Backprop

每次 rollout 后必须回写：

- `visits`
- `mean_reward`
- `uct_score`
- `survival_score`

### 8.6 Prune

出现以下情况可剪枝：

- 连续两轮对局失败
- weakest-step 无法被合理验证
- 与更强 candidate 高度重复
- Meta-review 判定为低价值重复分支

## 9. Reasoning Chain 与弱链评估

每个候选必须尽量输出显式 `ReasoningChain`，而不是只给一句结论。

### 9.1 ReasoningStep 最小字段

- `step_id`
- `order_index`
- `step_type`
- `claim_text`
- `input_refs[]`
- `output_refs[]`
- `support_refs[]`
- `risk_refs[]`
- `status`

### 9.2 Weakest-step 规则

每个 candidate 至少要有一个 `WeakestStepAssessment`：

- `candidate_id`
- `reasoning_chain_id`
- `step_id`
- `reason`
- `support_score`
- `risk_score`
- `observability_score`
- `recommended_validation_action`

若链上有多个明显弱点，必须显式按分值排序，而不是只写自由文本。

## 10. Finalize / Reject

### 10.1 Finalize

只有满足以下条件的 candidate 才能晋级为正式 `Hypothesis`：

- 状态为 `alive`
- 已完成至少一轮 reflection
- 已至少参与一场有效 match
- 有完整 `ReasoningChain`
- 有 `WeakestStepAssessment`
- 有 `minimum_validation_action`

### 10.2 Reject / Prune

以下行为不会直接删除 candidate，只能改状态并保留 lineage：

- `pruned`
- `rejected`

禁止静默丢弃候选。

## 11. 异步 Job 契约

若 generate / run-round 走异步 job，必须遵循统一状态：

- `queued`
- `running`
- `succeeded`
- `failed`
- `cancelled`

成功终态的 `result_ref`：

- 生成候选池时：`resource_type = hypothesis_candidate_pool`
- 跑轮次时：`resource_type = hypothesis_round`
- finalize 时：`resource_type = hypothesis`

禁止仍然沿用“generate 直接返回单个 hypothesis”的旧语义。

## 12. 可追溯性

每个正式 hypothesis 必须可回链到：

- trigger
- reasoning subgraph
- candidate pool
- round
- reviews
- matches
- evolutions
- search tree node
- weakest-step assessment
- validation recommendation

任一链路缺失都不允许静默吞掉，必须显式标记为缺失。

## 13. 错误语义

- 缺失或非法 trigger：`400 + research.invalid_request`
- 跨 workspace 引用：`409 + research.conflict`
- pool / candidate / round / match 不存在：`404 + research.not_found`
- 对非 `alive` candidate 继续 compare / evolve / finalize：`409 + research.invalid_state`
- 搜索树节点与 pool 不一致：`409 + research.conflict`
- 缺失 reasoning subgraph 且无法自动构建：`409 + research.invalid_state`
- LLM 输出不满足结构化契约：显式失败，不允许 silent fallback 到空壳 candidate
