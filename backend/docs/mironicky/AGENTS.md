# AGENTS.md — Mironicky × EverMemOS 科研版深改执行宪法

> 本文件约束 Mironicky Research Layer 在 EverMemOS-latest 仓库中的实现方式。执行者不是产品经理，不是架构裁判，不是需求简化器，只负责严格执行既定方案。

## 0. 核心使命

将 EverMemOS 从通用对话记忆系统扩展为 Mironicky 科研推理底座，构建完整的 Research Layer，实现：

- 科研材料导入
- 结构化候选抽取
- 用户确认后入图
- 研究路线生成与排序
- 结构化启发式评分
- 图谱编辑
- 失败回流与重算
- 新假设候选生成
- 研究包发布

禁止将目标偷换为 demo、接口壳子、静态前端、单 prompt 黑箱。

## 1. 执行边界

### 1.1 允许做的事

- 严格按文档实现模块
- 在模块边界内做代码组织优化
- 为满足验收标准补充必要测试、类型、迁移、脚本
- 在不改变产品语义的前提下修复 bug 和技术阻塞

### 1.2 不允许做的事

- 修改产品目标
- 自行删除模块
- 把完整功能偷换成降级版
- 把复杂流程缩成单 prompt 黑箱
- 用 mock、TODO、占位逻辑冒充完成
- 用“后续再接”“先留接口”替代真实实现
- 用硬编码示例数据伪装真实状态流
- 静默吞掉失败、冲突、未支持场景

## 2. 非妥协原则

1. 禁止壳子化：没有真实后端行为的 UI、假的状态流、写死示例数据，一律不算完成。
2. 禁止临时补丁常驻化：temp hack、mock bypass、TODO 占位不得进入主路径。
3. 禁止静默降级：能力不可用时必须显式报错或显式状态。
4. 禁止跨模块偷耦合：Research Graph、Scoring、Routing、Failure Loop 通过明确接口交互。
5. 先测后并：每个 slice 通过单测、按边界要求的集成测试、最小验收 demo 后才能进入下一个。
6. 不允许自改产品边界：遇阻时报告阻塞点和技术方案，不准自行改方向。
7. 对象优先于 prompt：先定义数据结构与状态流，再定义 LLM 调用。
8. LLM 不是裁判：LLM 只负责抽取、压缩、解释、候选生成；评分、状态、版本、路由排序由程序控制。
9. 可追溯优先：任何路线、节点、假设、失败都必须能追到来源与版本。
10. 模块必须达标：未达完成标准，禁止进入下个 slice。
11. 从 Slice 2 起必须提供至少一个真实可点击的手动验收入口；该入口必须由真实后端、真实状态流、真实持久化驱动，不得使用 mock、fake path 或 hard-coded state。

## 3. 总体架构

采用双层架构：

### 3.1 EverMemOS Core

负责：

- FastAPI 服务基座
- MongoDB / Elasticsearch / Milvus / Redis
- 通用 ingestion / retrieval / worker
- 现有 assistant / group_chat 能力

### 3.2 Mironicky Research Layer

负责：

- 科研对象模型
- 研究图谱
- 候选抽取确认流
- 结构化启发式评分
- 路线生成与排序
- 失败回流与重算
- 新假设候选生成
- 研究包发布

严禁把 Research Layer 粗暴塞回 assistant/group_chat message pipeline。

## 4. 目录边界

Research 相关代码统一放入：

- `src/research_layer/`
- `tests/unit/research_layer/`
- `tests/integration/research_*`
- `tests/e2e/research_workspace/`
- `docs/mironicky/`

禁止把科研核心对象散落到无关目录。

## 5. 实现顺序规则

必须严格遵守 `docs/mironicky/SLICES.md`：

- 先 Slice 0 文档与骨架冻结
- 再 Domain Model
- 再 API Schema
- 再 Research Source Import + Candidate Extraction
- 再 Candidate Confirmation Flow
- 再 Graph
- 再 Scoring
- 再 Route Generation + Ranking + Preview
- 再 Failure Loop + Recompute + Version Diff
- 再 Hypothesis Engine
- 再 Research Retrieval Views
- 再 Research Package
- 最后端到端闭环与回归

禁止跨 slice 偷跑。

## 6. 测试规则

每个 slice 必须至少提供：

- 单元测试：对象与核心逻辑
- 集成测试：当本 slice 已引入 service / repository / API / worker 边界时必须提供
- 最小验收 demo：覆盖本 slice 主流程；Slice 1 允许用可复现实验命令替代可点击入口

从 Slice 2 起还必须提供至少一个可点击的最小手动验收入口，规则如下：

- 单步接口验收允许使用 Swagger / OpenAPI
- 凡涉及连续状态变化的 slice，必须提供最小 `Research Dev Console`
- `Research Dev Console` 允许作为真实 API 驱动的内部验收面存在
- Research Dev Console 是内部验收工具，不是正式产品前端
- 手动验收入口只能做薄封装，只调用真实 API，不在前端重复实现业务规则
- 多步状态流不得只靠 Swagger、脚本输出或薄按钮页混过验收
- evaluator 在独立验收时也必须使用同一条手动验收路径，而不只跑 pytest

测试不允许只测 happy path。必须覆盖：

- 空输入
- 非法状态
- 冲突
- 重复导入
- 用户未确认
- 失败回流后状态变化
- 重算后的 diff

当前仓库的最小测试命令默认应显式声明运行前置条件：

- 从仓库根目录运行
- 显式设置 `PYTHONPATH=src`，或使用等效 editable install / 启动方式
- 在提交验收结果时，不得省略这些前置条件

## 7. 文档同步规则

任何影响以下内容的改动，必须同步更新文档：

- 对象模型
- API 契约
- 存储结构
- 评分因子
- 路线生成规则
- 失败影响规则
- 假设生成规则
- 验收门槛
- slice 状态文件与验收记录
- 可观测性约定（如涉及 request / job / recompute / publish 生命周期）

如代码与文档冲突，以文档为准；若文档不充分，先补文档再实现。

每个 Slice 完成或验收后，还必须同步：

- `docs/mironicky/slice_status.json`
- `docs/mironicky/handoffs/slice-XX.md`（开发完成、等待独立 evaluator 时）
- `docs/mironicky/evaluations/slice-XX.md`（独立 evaluator 给出 PASS / FAIL 后）

## 8. 完成定义

一个模块只有同时满足以下条件才算完成：

- 代码实现完成
- 类型完整
- 测试通过
- 无 TODO / fake implementation / hard-coded happy path
- 有日志与错误语义
- 有模块文档
- 有最小可复现实验或 demo

## 9. 出现阻塞时的处理方式

必须输出：

1. 阻塞点是什么
2. 阻塞发生在哪个模块边界
3. 哪些既定约束导致当前无法继续
4. 2–3 个可选技术方案
5. 每个方案的代价与影响

不得在未获批准的情况下自行改产品语义。
