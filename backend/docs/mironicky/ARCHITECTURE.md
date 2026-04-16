# ARCHITECTURE.md — Mironicky Research Layer on EverMemOS

## 1. 目标

Mironicky 不是对现有聊天记忆链路的小改，而是在 EverMemOS Core 旁边新增一层独立的 Research Layer。它负责研究对象建模、研究图谱、评分、路线、失败回流、假设生成和研究包发布。

## 2. 不承诺事项

- 本阶段不承诺完整前端交付，当前目标是 backend-first。
- 不把 Research Layer 塞回 assistant / group_chat message pipeline。
- 不允许用 prompt 黑箱替代结构化对象、状态机和程序控制规则。

## 3. 分层职责

### 3.1 EverMemOS Core

保留并复用：

- FastAPI app、middleware、lifespan
- MongoDB / Elasticsearch / Milvus / Redis
- DI、controller 注册、worker 基座
- 现有 memory / assistant / group_chat 能力

### 3.2 Mironicky Research Layer

新增并独立建设：

- `domain/`: 研究对象、枚举、值对象
- `api/`: research schemas 与 controllers
- `extractors/`: source parsing 与 candidate extraction
- `services/`: import、confirm、graph、score、route、package 等服务
- `graph/`: graph repository、query、diff、recompute
- `workers/`: extraction / recompute 等后台任务
- `prompts/`: extractor / summarizer / hypothesis prompts
- `bootstrap/`: 研究层 scan path / task path 注册

## 4. 代码边界

- 文档：`docs/mironicky/`
- 代码：`src/research_layer/`
- 单测：`tests/unit/research_layer/`
- 集成测试：`tests/integration/research_*`
- E2E：`tests/e2e/research_workspace/`

## 5. 与现有系统的接入方式

- 通过 `src/addon.py` 把 `research_layer` 加入 DI 扫描路径。
- 通过 `src/addon.py` 把 `research_layer/workers` 加入任务扫描路径。
- 通过 `BaseController` 机制让 research controllers 自动注册进 FastAPI。
- 不改变 `memory_layer` 的 `Conversation -> MemCell -> Episode/Foresight/EventLog/Profile` 主语义。

## 6. 顶层数据流

1. 导入 research source
2. parse / extract 成 candidate objects
3. 用户确认 candidate
4. confirmed objects 映射进 graph
5. scoring engine 计算结构化分数
6. route engine 生成与排序路线
7. failure / validation 回流图谱并触发 recompute
8. hypothesis engine 从 gap / conflict / failure 派生新候选
9. research package 以 snapshot 方式发布到团队

## 6.1 正式前端入口语义

- 当前阶段虽然是 backend-first，但正式产品前端的信息架构必须承认“导入资料”是研究闭环的真实起点。
- 默认首页仍然是“路线空间 + 当前路线链预览”，而不是把用户直接丢进图谱或导入向导。
- 但正式首页必须显式提供资料导入入口，不允许把导入能力只留在内部 `Research Dev Console`。
- 至少应存在三类前端入口：
  - 首页顶部主动作：`Import Materials`
  - 空工作区空态主按钮：导入文献 / 笔记 / 导师反馈 / 失败记录
  - 持续可达的 `Sources / Materials` 入口，用于管理已导入资料
- 这条规则的目的不是把首页改造成导入页，而是避免正式产品缺少研究起点，导致用户只能看到空路线界面。

## 7. 图谱与检索

- 初始正式方案采用 `Mongo/Beanie + igraph`。
- Mongo 保存 node / edge / version / package 等结构化对象。
- `igraph` 用于内存级图计算、子图回溯、route candidate build、failure impact、diff 辅助。
- ES / Milvus / Redis 用于 research retrieval、embedding、缓存与异步任务协同。

## 8. 设计原则

- 对象优先于 prompt
- 状态显式、错误显式
- 版本和来源可追溯
- 路线由程序规则排序，LLM 只负责抽取、摘要、解释
