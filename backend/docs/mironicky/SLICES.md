# SLICES.md — Mironicky × EverMemOS 科研版深改切片清单

> 规则：严格串行开发。每个 Slice 未通过 `docs/mironicky/ACCEPTANCE_GATES.md` 对应门槛，禁止进入下一个 Slice。
> 从 Slice 2 起，手动验收入口属于正式交付物；凡涉及连续状态变化的 slice，默认必须提供 `Research Dev Console`，而不是只给 Swagger 或脚本输出。

## Slice 0 — 文档冻结 + 仓库骨架

### 目标
把产品边界、对象模型、模块拆分、测试门槛全部冻结；创建 Research Layer 目录骨架。

### 必做
- 创建 `docs/mironicky/` 下所有核心文档并写初版内容
- 创建 `src/research_layer/` 目录骨架
- 创建 `tests/unit/research_layer/`、`tests/integration/`、`tests/e2e/research_workspace/`
- 新增 Research Layer bootstrap 注册入口
- 保证应用启动不因新增骨架报错

### 输出
- 文档骨架完整
- 代码目录完整
- 空实现只允许 schema / package init，不允许伪业务逻辑

### 通过标准
- 目录结构与蓝图一致
- 文档齐全
- lint / import / startup 不报错

---

## Slice 1 — Domain Model 冻结

### 目标
把科研对象模型和枚举彻底定死。

### 必做
- 实现并冻结：
  - `ResearchSource`
  - `ResearchEvidence`
  - `ResearchAssumption`
  - `ResearchConflict`
  - `FailureReport`
  - `ValidationAction`
  - `Route`
  - `GraphNode`
  - `GraphEdge`
  - `GraphVersion`
  - `ResearchPackage`
- 实现所有 enums / value objects
- 写 domain unit tests

### 通过标准
- 核心对象有明确字段、状态、校验
- 单测覆盖字段合法性、状态流转、边界输入
- 文档 `DOMAIN_MODEL.md` 与代码一致
- 若尚未引入 service / repository / API / worker 边界，集成测试不是本 slice 的阻塞项
- 本 slice 不要求可点击手动验收入口；可用对象构造与单测复现实验代替

---

## Slice 2 — API Schemas + Controllers 契约冻结

### 目标
先把接口契约定死，再做内部实现。

### 必做
- 新增 controllers：
  - `ResearchSourceController`
  - `ResearchRouteController`
  - `ResearchGraphController`
  - `ResearchFailureController`
  - `ResearchHypothesisController`
  - `ResearchPackageController`
- 新增 request / response schemas
- 路由注册进 FastAPI
- 生成 API 测试骨架

### 通过标准
- OpenAPI 中可见 research API
- schema 校验完整
- 非法请求有明确错误返回
- `API_SPEC.md` 冻结
- 满足手动验收入口要求；若包含异步接口，必须能查询 job 终态与结果资源

---

## Slice 3 — Research Source Import + Candidate Extraction

### 目标
让论文/笔记/反馈/失败记录能进入系统并产出候选结构化信息。

### 必做
- source import service
- source parser
- extractors：
  - evidence
  - assumption
  - conflict
  - failure
  - validation
- prompt 文件落地
- extraction worker 落地

### 通过标准
- 能从 research source 产出候选 objects
- 每个候选都能追溯到 source span
- extraction 失败不静默吞掉
- 单测 + 集成测试覆盖至少 paper / note / failure_record 三类输入
- 通过 `Research Dev Console` 完成 import → extract → candidate 查看；若 extract 为异步，必须可查询 job 终态与结果

---

## Slice 4 — Candidate Confirmation Flow

### 目标
把“模型候选”与“用户确认后的正式对象”分层。

### 必做
- candidate state model
- confirmation service
- confirm API
- confirmed object 入库逻辑
- 去重 / 冲突提示基础逻辑

### 通过标准
- 未确认对象不会进入主图谱
- 确认后能转成正式 evidence / assumption / conflict / failure / validation candidate
- 重复确认有幂等保障
- 通过 `Research Dev Console` 完成 confirm / reject 并观察状态变化

---

## Slice 5 — Research Graph 基础层

### 目标
建立研究图谱后端，不依赖前端壳子。

### 必做
- graph repository
- graph build service
- node / edge CRUD
- graph query service
- graph workspace model
- graph API

### 通过标准
- confirmed objects 能转成 graph nodes / edges
- 可查询局部子图
- 可更新节点/边
- 图谱状态持久化可回读
- 通过 `Research Dev Console` 完成 graph 查询 / 更新并观察结果变化

---

## Slice 6 — Scoring Engine

### 目标
实现“结构化 + 启发式”的判断框架。

### 必做
- scoring fields
- templates
- heuristics
- explainer
- score service
- route / node-level score breakdown

### 通过标准
- 输出至少：`support_score`、`risk_score`、`progressability_score`
- 评分过程可解释
- 非黑箱、非仅 LLM 返回文字
- `SCORING_SPEC.md` 与实现一致
- 通过 `Research Dev Console` 触发真实 scoring 路径，并观察 score 与 factor breakdown

---

## Slice 7 — Route Generation + Ranking + Preview

### 目标
从图谱生成候选研究路线并排序展示。

### 必做
- candidate builder
- route ranker
- route summarizer
- route preview API
- route list API

### 通过标准
- 图谱中至少可生成多条候选路线
- 排序由程序规则控制
- LLM 只参与摘要/解释
- 首页所需 Top 3 因子可返回
- 通过 `Research Dev Console` 触发 route generation / preview，并观察排序结果

---

## Slice 8 — Failure Loop + Recompute + Version Diff

### 目标
实现失败回流后削弱/分叉/重算/版本 diff。

### 必做
- failure attach API
- failure impact service
- branch generator
- recompute service
- version store
- diff service

### 通过标准
- failure 可挂到 node 或 edge
- 失败能影响 score 与 route status
- 可生成 gap / branch / weakened 标记
- 重算后能看到 diff
- 通过 `Research Dev Console` 完成 failure → recompute → diff；若 recompute 为异步，必须可查询 job 终态与结果

---

## Slice 9 — Hypothesis Engine

### 目标
从 gap / conflict / failure 中生成新假设候选。

### 必做
- hypothesis trigger detector
- hypothesis service
- novelty typing
- minimum validation action generation
- weakening signal generation

### 通过标准
- 只能基于局部图谱与已确认材料生成
- 输出结构化 hypothesis candidate
- 不允许直接升级成主路线结论
- 有验证路径与削弱信号
- 通过 `Research Dev Console` 生成 hypothesis 并观察状态；若为异步，必须可查询 job 终态与结果

---

## Slice 10 — Research Retrieval Views

### 目标
实现科研语义检索，而不只是通用 memory search。

### 必做
- evidence retriever
- contradiction retriever
- failure pattern retriever
- validation history retriever
- hypothesis support retriever

### 通过标准
- 每种检索视图有明确过滤条件与返回结构
- 至少支持 hybrid retrieval
- 返回结果与 graph / source 可追溯联动
- 通过 `Research Dev Console` 触发 retrieval view 并回链到 source / graph

---

## Slice 11 — Research Package 发布

### 目标
把个人研究成果按边界发布到团队。

### 必做
- research package domain
- package build service
- private dependency gap generation
- publish API

### 通过标准
- 发布不是同步，而是快照包
- 私密依赖不会被静默伪装成公开证据
- 可生成公开证据缺口
- 通过 `Research Dev Console` 完成 create -> query；若支持 publish，必须完成 publish -> job status / result

---

## Slice 12 — E2E 闭环与回归

### 目标
打通从导入到路线、从失败到重算、从 gap 到假设的闭环。

### 必做
- e2e: import → extract → confirm → graph → score → route
- e2e: failure → impact → recompute → diff
- e2e: gap / conflict / failure → hypothesis candidate
- regression suite

### 通过标准
- 三条核心闭环全部可跑通
- 回归通过
- 无 fake path / debug bypass / permanent mock
- 至少一条 `Research Dev Console` 验收路径覆盖完整闭环
