# ACCEPTANCE_GATES.md — Mironicky × EverMemOS 科研版深改验收门槛

> 原则：没有通过门槛，就不算完成；不算完成，就不能进入下一 Slice。

## 通用门槛

每个 Slice 都必须满足：

1. 代码完成：功能主路径可运行。
2. 类型完整：无明显类型缺口，核心对象有明确类型。
3. 单元测试通过：覆盖核心逻辑与边界输入。
4. 集成测试通过：若本 Slice 已引入服务、仓储、API 或 worker 的真实连接，则必须覆盖。
5. 无假实现：不得存在 hard-coded happy path、仅返回示例数据、无效 TODO。
6. 无静默降级：失败场景必须显式返回错误或状态。
7. 文档同步：涉及对象、API、规则、状态的变更必须同步更新文档。
8. 最小 demo 可复现：至少有一个可执行示例或测试证明 slice 主路径有效。
9. 从 Slice 2 起，必须存在至少一个可点击的最小手动验收入口，并能用真实后端、真实状态流、真实持久化完成本 slice 的关键动作。

## 命令前置条件

除非仓库已通过等效方式安装为可直接导入的 package，所有测试与验收命令都必须显式声明：

- 从仓库根目录运行
- 设置 `PYTHONPATH=src`
- 必要的启动 / reset / seed 前置条件

## 手动验收入口规则

- Slice 2 可以使用 Swagger / OpenAPI 作为单步接口验收入口
- 凡涉及连续状态变化的 slice，必须提供最小 `Research Dev Console`
- Dev Console 是内部验收工具，不是正式产品前端
- 手动验收入口只能做真实 API 的薄封装，不得使用 mock、fake path、hard-coded state 或跳过持久化
- 若模块包含异步 job，手动验收必须覆盖 job 启动、状态查询、终态与结果资源回链
- evaluator 在独立验收时必须沿手动验收入口验证主流程，不得只给出 pytest 结果

## Slice 0 门槛

- `docs/mironicky/` 文档目录存在并含核心文件
- `src/research_layer/` 与测试目录骨架完整
- 应用可启动，无 import 错误
- 未引入伪业务逻辑

## Slice 1 门槛

- 所有 domain models / enums / value objects 完成
- 字段约束、状态约束、序列化一致
- 单测覆盖合法 / 非法构造、状态流转
- Slice 1 不强制要求可点击手动验收入口
- 若尚未引入 service / repository / API / worker 边界，集成测试可不作为阻塞项

## Slice 2 门槛

- research API 出现在 OpenAPI
- 所有 schema 有明确输入校验
- controller 可注册且返回正确错误语义
- `API_SPEC.md` 与实现一致
- 至少可通过 OpenAPI 手动点击并验证一个 research API 主路径
- 若 Slice 2 引入异步接口，必须可查询 job 终态与结果资源
- 最小可观测字段必须可被追踪：`request_id`、`workspace_id`；若引入异步 job，还必须有 `job_id`、`status`、`result_ref`

## Slice 3 门槛

- 支持导入至少三类 source：paper、note、failure_record
- extractor 输出结构化 candidate，不是散文文本
- candidate 绑定 source_id 与 span
- 失败可见，不静默吞掉
- 必须通过 `Research Dev Console` 完成 import → extract → candidate 查看
- 若 extract 为异步，必须能查询 job 终态并回链到 candidate 或 source 结果
- extraction 最小事件必须可被追踪：`source_import_started`、`source_import_completed`、`candidate_extraction_started`、`candidate_extraction_completed`，并带 `source_id` 或 `candidate_batch_id`

## Slice 4 门槛

- 候选态与确认态严格隔离
- 未确认对象不会出现在主图谱
- 幂等确认通过测试
- 重复 / 冲突确认有明确信号
- 必须通过 `Research Dev Console` 完成 confirm / reject 并观察状态变化

## Slice 5 门槛

- graph nodes / edges 可持久化
- confirmed objects 能被映射进图谱
- graph query 返回局部子图
- graph update 能改变后续查询结果
- 必须通过 `Research Dev Console` 完成 graph 查询 / 更新并观察结果变化

## Slice 6 门槛

- 至少输出 3 个分数：support / risk / progressability
- 评分逻辑不依赖 LLM 的自由文字判断
- score breakdown 可返回
- 不存在只给总分不给因子的黑箱实现
- 必须通过 `Research Dev Console` 触发真实 scoring 路径，并观察 score 与 factor breakdown

## Slice 7 门槛

- 图谱能生成多条候选路线
- route ranking 由程序规则控制
- route preview 可返回：结论、关键支撑、假设、冲突 / 失败提示、下一步验证动作
- Top 3 因子能稳定输出
- 必须通过 `Research Dev Console` 触发 route generation / preview，并观察排序结果

## Slice 8 门槛

- failure 能挂到 node 或 edge
- 挂载后相关节点 / 路线状态变化可观察
- route recompute 真正发生
- version diff 记录新增 / 削弱 / 失效 / 分支变化
- 必须通过 `Research Dev Console` 提交 failure、触发 recompute 并查看 diff
- 若 recompute 为异步，必须能查询 job 终态并回链到新 version / diff
- recompute / diff 最小事件必须可被追踪：`recompute_started`、`recompute_completed`、`diff_created`，并带 `version_id` 与结果引用

## Slice 9 门槛

- hypothesis trigger 来源必须是 gap / conflict / failure / weak support
- hypothesis 输出结构化字段齐全
- 含 minimum validation action 与 weakening signal
- hypothesis 默认处于 candidate / exploratory 状态，不能直接变主路线
- 必须通过 `Research Dev Console` 生成 hypothesis 并查看状态
- 若 hypothesis generation 为异步，必须能查询 job 终态并回链到 hypothesis 结果

## Slice 10 门槛

- 每种 retrieval view 有对应 service 与测试
- 至少支持 metadata filter + hybrid retrieval
- 检索结果能回链到 source / graph
- 必须通过 `Research Dev Console` 触发 retrieval view 并回链到 source / graph

## Slice 11 门槛

- 发布是 package snapshot，不是 live sync
- 私密依赖会显式变成 public gap，而不是被省略后伪装完整
- package 可重放与可查询
- 必须通过 `Research Dev Console` 完成 create -> query
- 若支持 publish，必须通过同一入口触发 publish -> job status / result
- package build / publish 最小事件必须可被追踪：`package_build_started`、`package_build_completed`；若支持 publish，再要求 `package_publish_started`、`package_publish_completed` 与 `package_id`

## Slice 12 门槛

- 导入到路线闭环 e2e 通过
- 失败到重算闭环 e2e 通过
- gap / conflict / failure 到 hypothesis 闭环 e2e 通过
- 回归测试通过
- 无残留调试旁路
- 至少有一条 `Research Dev Console` 验收路径覆盖完整闭环

## 一票否决项

出现以下任一情况，本 Slice 直接判失败：

- 以 mock / hard-coded 数据冒充真实实现
- 以“后续接入”替代当前 slice 的核心能力
- 缺失 source traceability
- 缺失状态持久化
- 缺失失败显式语义
- LLM 越权充当评分或路由主裁判
- 文档和实现明显不一致

## 交付格式要求

每个 Slice 完成时，必须同时提交：

1. 变更文件列表
2. 该 Slice 的实现摘要
3. 测试结果摘要
4. 尚未解决但不影响本 Slice 完成的风险清单
5. 是否达到进入下一 Slice 的门槛
6. `entrypoint`：手动验收入口 URL、页面路径或 OpenAPI 路由
7. `startup / reset commands`：启动、重置、seed 命令
8. `fixture / demo data`：复现实验所需 fixture 或 demo 数据
9. `manual steps`：手动点击或调用步骤
10. `expected observations`：应看到的状态变化、终态、错误语义或结果资源
11. `slice status update`：同步更新 `docs/mironicky/slice_status.json`
12. `developer handoff`：开发完成后、等待独立 evaluator 前，同步新增或更新 `docs/mironicky/handoffs/slice-XX.md`
13. `evaluation record`：独立 evaluator 给出 PASS / FAIL 后，同步新增或更新 `docs/mironicky/evaluations/slice-XX.md`

对 `Slice 0` 与 `Slice 1`：

- `entrypoint` / `manual steps` / `expected observations` 允许填写 `N/A`，或填写对象构造 / smoke test 的复现实验命令
