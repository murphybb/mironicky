# SCORING_SPEC.md — Mironicky 确定性评分、Tournament 与弱链评估

## 1. 原则

- 评分、排序、状态迁移由程序控制，不由 LLM 直接裁决
- LLM 可以生成结构化评论、比较理由和 review 文本，但不能单独决定胜负、排名和正式状态
- 任意评分结果都必须可解释、可追溯、可回链
- Hypothesis tournament、search tree 和 route ranking 必须共享同一套“程序主导”原则

## 2. 评分对象

本规范覆盖四类评分：

- `HypothesisCandidate` 结构评分
- `HypothesisMatch` 对局判定与 Elo 更新
- `ReasoningStep` 弱链评估
- `Route` 三大主分数

## 3. HypothesisCandidate 结构评分

### 3.1 候选基础字段

每个 candidate 至少有：

- `candidate_score`
- `candidate_score_breakdown`
- `weakest_step_assessment`
- `elo_rating`
- `survival_score`

### 3.2 候选评分因子

默认模板 `hypothesis_candidate_v1`：

- `trigger_coverage`: `0.20`
- `evidence_grounding`: `0.20`
- `mechanism_specificity`: `0.15`
- `chain_completeness`: `0.15`
- `testability_clarity`: `0.15`
- `novelty_strength`: `0.10`
- `duplication_penalty`: `0.05`

说明：

- 前六项按正向贡献计算
- `duplication_penalty` 是扣分因子，归一化后按负向处理

### 3.3 结构评分公式

先把所有因子归一化到 `[0,1]`：

- `candidate_score_norm = clamp01(0.20*a + 0.20*b + 0.15*c + 0.15*d + 0.15*e + 0.10*f - 0.05*g)`
- `candidate_score = round(candidate_score_norm * 100, 1)`

其中：

- `a = trigger_coverage`
- `b = evidence_grounding`
- `c = mechanism_specificity`
- `d = chain_completeness`
- `e = testability_clarity`
- `f = novelty_strength`
- `g = duplication_penalty`

### 3.4 因子含义

- `trigger_coverage`：候选是否覆盖输入 trigger 的关键断点
- `evidence_grounding`：候选 statement / rationale / step 是否能回链到真实对象
- `mechanism_specificity`：是否提出了具体机制，而不是空泛描述
- `chain_completeness`：是否有完整中间步骤链
- `testability_clarity`：最小验证动作是否明确、可执行、可观察
- `novelty_strength`：是否提供非平凡但仍合理的新机制
- `duplication_penalty`：与现有 candidate / hypothesis 的重复程度

## 4. HypothesisMatch 与对局判定

### 4.1 对局输入

每场对局必须至少读取：

- 左右 candidate 的 `candidate_score`
- 左右 candidate 的 weakest-step 结果
- 左右 candidate 的 reasoning chain 完整度
- 左右 candidate 的去重/重复信息
- Ranking agent 返回的结构化 compare vector

### 4.2 对局比较因子

默认比较权重：

- `candidate_score`: `0.35`
- `weakest_step_strength`: `0.20`
- `chain_completeness`: `0.15`
- `testability_clarity`: `0.15`
- `novelty_strength`: `0.10`
- `duplication_penalty`: `0.05`

### 4.3 最终胜负规则

最终胜负必须由程序计算，不允许 LLM 直接裁决。

规则：

1. 先根据结构化因子计算双方 `compare_total`
2. 若差值大于阈值，程序直接判胜负
3. 若差值接近，再读取 Ranking agent 的结构化 compare vector 作为说明性补充
4. 仍然同分时，按以下固定 tie-break：
   - weakest-step 更强者优先
   - duplication_penalty 更低者优先
   - candidate_id 字典序升序

Ranking agent 的输出用于：

- 解释为何更优
- 暴露隐藏弱点

但不允许单独决定 winner。

## 5. Elo Tournament

### 5.1 初始值

- 所有 candidate 初始 Elo = `1200`

### 5.2 期望值公式

- `expected(left) = 1 / (1 + 10 ^ ((right_elo - left_elo) / 400))`
- `expected(right) = 1 - expected(left)`

### 5.3 更新公式

默认 `K = 32`：

- `new_elo = old_elo + 32 * (actual_score - expected_score)`

### 5.4 参赛优先级

对局调度优先考虑：

- 新 candidate / 新 evolution candidate
- 高 Elo candidate
- proximity 高的 candidate
- 共享相同 trigger 或 reasoning subgraph 的 candidate

## 6. ReasoningStep 弱链评估

### 6.1 Step 基础字段

每个 `ReasoningStep` 至少要有：

- `step_support_score`
- `step_risk_score`
- `step_observability_score`
- `step_traceability_score`
- `step_reliability_score`

### 6.2 Step 可靠度公式

- `step_reliability_norm = clamp01(0.35*support + 0.30*(1-risk) + 0.20*observability + 0.15*traceability)`
- `step_reliability_score = round(step_reliability_norm * 100, 1)`

### 6.3 Weakest-step 规则

一条 `ReasoningChain` 的 weakest step 定义为：

- `step_reliability_score` 最低的 step

如同分，则按以下顺序选择：

1. `step_risk_score` 更高者
2. `step_observability_score` 更低者
3. `order_index` 更靠前者

`WeakestStepAssessment` 必须落库，而不是只存在于摘要文本中。

## 7. Search Tree Reward

### 7.1 Tree Node Reward

搜索树节点 reward 使用程序公式计算：

- `reward_norm = clamp01(0.40*candidate_score_norm + 0.20*elo_norm + 0.20*weakest_step_strength + 0.20*survival_rate)`

其中：

- `elo_norm = clamp01((elo_rating - 800) / 800)`
- `weakest_step_strength = weakest_step_reliability_score / 100`
- `survival_rate = survived_matches / max(1, total_matches)`

### 7.2 UCT

- `uct_score = mean_reward + 1.4 * sqrt(ln(parent_visits + 1) / (visits + 1))`

此分数只能由程序更新。

## 8. Route 三大主分数

### 8.1 主分数

- `support_score`
- `risk_score`
- `progressability_score`

分数展示范围统一为 `0-100`。

### 8.2 路线基础字段

- `novelty_level`
- `relation_tags`
- `next_validation_action`
- `top_factors`
- `score_breakdown`
- `node_score_breakdown`
- `scoring_template_id`
- `scored_at`
- `weakest_step_ref`

### 8.3 默认模板 `general_research_v1`

`support_score`：

- `confirmed_evidence_coverage`: `0.30`
- `evidence_quality`: `0.25`
- `cross_source_consistency`: `0.20`
- `validation_backing`: `0.15`
- `traceability_completeness`: `0.10`

`risk_score`：

- `unresolved_conflict_pressure`: `0.30`
- `failure_pressure`: `0.25`
- `assumption_burden`: `0.20`
- `private_dependency_pressure`: `0.15`
- `missing_validation_pressure`: `0.10`

`progressability_score`：

- `next_action_clarity`: `0.30`
- `execution_cost_feasibility`: `0.20`
- `execution_time_feasibility`: `0.15`
- `expected_signal_strength`: `0.20`
- `dependency_readiness`: `0.15`

### 8.4 归一化规则

- `dimension_score_norm = clamp01(sum(weight * normalized_value))`
- `dimension_score = round(dimension_score_norm * 100, 1)`

缺失输入时：

- `normalized_value = 0.0`
- 必须在 breakdown 中显式标记 `status = missing_input`

### 8.5 focus_node_ids 语义

当 route scoring 提供 `focus_node_ids` 时：

- 评分输入切换为该路线诱导子图
- 因子计算只允许使用该子图内节点、边和对象
- 未知 node 必须显式报错

## 9. Top Factors

Top factors 必须来自结构化 breakdown，不允许 LLM 自由生成。

默认仍取前 `3` 个最高 `weighted_contribution` 因子。

## 10. 错误语义

- 未知模板或非法因子：`400 + research.invalid_request`
- route 或 candidate 不存在：`404 + research.not_found`
- workspace 归属不一致：`409 + research.conflict`
- focus_node_ids 含未知 node：`400 + research.invalid_request`
- 图谱未就绪导致不可评分：`409 + research.invalid_state`
