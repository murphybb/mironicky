# Research Workspace Productization Track

> 用途：本文件不是替代 `SLICES.md`，而是为“正式前端接真 API”阶段建立单独的后续任务轨道。  
> 原则：保留 `slice_0 ~ slice_12` 的完成历史，不回写成新的基础 slice；所有新增工作都按“产品化补强模块”执行。

---

## 0. 适用范围

本轨道适用于以下目标：

- 将 `research-workspace-v12` 从 `defaultState() + localStorage` 的前端原型，切换为真实 `research_layer` API 驱动的正式产品前端
- 补齐当前后端与正式前端之间的缺失能力
- 保证前端不再依赖假状态、示例数据或伪交互完成主闭环

本轨道不适用于：

- 重做原 `slice_0 ~ slice_12`
- 推翻既有 Research Layer 架构
- 重新发明第二套平行主域
- 以“先前端凑合能用”为目标的降级实现

---

## 1. 与 SLICES.md 的关系

### 1.1 不是新基础 slice

本文件中的模块不是新的基础 slice，不回写到 `SLICES.md`。

原因：

1. 原 `slice_0 ~ slice_12` 解决的是 Research Layer 从无到有的主能力建设。
2. 当前工作解决的是“正式前端接真 API”的产品化补强，不是再发明一个新的主后端阶段。
3. 当前补强工作横跨多个旧 slice：
   - `Sources` 补强 Slice 3
   - `Graph Archive` 补强 Slice 5
   - `Hypothesis Inbox / Defer` 补强 Slice 9
   - `Memory Vault Controlled Actions` 补强 Slice 10
   - `Regression + Contract Sync` 补强 Slice 12

### 1.2 仍受 AGENTS 约束

虽然本轨道不是新的基础 slice，但仍严格受 `AGENTS.md` 约束：

- 禁止壳子化
- 禁止用 mock / TODO / fake path 冒充完成
- 禁止静默降级
- 对象优先于 prompt
- 可追溯优先
- 每个模块未通过验收，禁止进入下一个模块

---

## 2. 总体目标

完成以下正式产品闭环：

`Sources -> Confirm -> Graph Build -> Route Space -> Workbench Edit -> Recompute -> Package`

并在主闭环稳定后补上：

- `Hypothesis Desk` 的真实 inbox / defer
- `Memory Vault` 的 retrieval-backed read model 与受控动作

最终目标不是“前端能演示”，而是：

- 页面由真实 API 驱动
- 跨页面状态一致
- 关键动作落真实持久化
- 错误与未接通能力显式可见

---

## 3. 非妥协执行规则

### 3.1 允许做的事

- 在既有 `research_layer` 内增量补齐 controller / schema / store / service / tests / docs
- 为正式前端接真 API 补缺失接口
- 为保持可追溯和版本语义，将“删除”实现为 archive / deactivate
- 将前端页面收缩为真实后端可支撑的语义

### 3.2 不允许做的事

- 不允许把 `Memory Vault` 做成新的平行主状态源
- 不允许对 `Graph` 做物理硬删除，破坏 diff / traceability / rollback
- 不允许以前端局部假状态伪装“暂时还没接后端”
- 不允许把“前端没法接”的问题，偷换成“页面先保持现状”
- 不允许把不具备后端契约的动作默默降成 no-op

---

## 4. 执行顺序

本轨道必须严格串行执行。

### Track 0 — 前置基线确认

#### 目标

确认当前前端与后端真实边界，产出“可接 / 不可接 / 缺失能力”基线。

#### 必做

- 复核当前 `research-workspace-v12` 页面动作
- 复核当前 `research_layer` controller / schema / API_SPEC
- 记录：
  - 已存在真 API
  - 缺失真 API
  - 页面当前假状态入口

#### 输出

- 当前 API 清单
- 当前前端假状态入口清单

#### 通过标准

- 所有后续模块的依赖边界已清楚
- 不再对“后端已经有 / 没有”存在口头争议

---

### Track 1 — Sources / Materials 真列表能力

#### 目标

让 `Sources / Materials` 成为真实资料入口，而不是只有导入动作没有正式列表。

#### 必做

- 新增 `GET /api/v1/research/sources?workspace_id=...`
- 补 source list response schema
- 补 state store list 查询
- 补集成测试
- 更新 `API_SPEC.md`

#### 不允许

- 不允许继续让 `Sources` 依赖前端 `materials` 本地数组作为主数据源
- 不允许只接 import，不接 list

#### 前端接入影响

- `Sources / Materials` 页切真列表
- 首页 `Import Materials` 跳转后进入真实资料池

#### 通过标准

- `Sources` 页可读取真实资料列表
- 新导入 source 刷新后仍可见
- candidate inbox 与 materials list 不再冲突

---

### Track 2 — Graph Archive / Delete 正式能力

#### 目标

让 `Workbench` 的删除类交互有正式后端语义，同时保持可追溯与版本语义。

#### 必做

- 新增 node archive/delete endpoint
- 新增 edge archive/delete endpoint
- 定义 archive / deactivate 状态语义
- 确保 version diff / recompute / traceability 不被破坏
- 补测试与文档

#### 不允许

- 不允许物理硬删除 graph node / edge
- 不允许只在前端删掉显示对象

#### 前端接入影响

- `Workbench` 的删除边/节点动作切真 API
- 删除后的状态变化可在 route / diff / graph 里被观察到

#### 通过标准

- 删除动作真实持久化
- 旧版本和新版本差异可追踪
- 前端不再需要本地 edge remove / node remove 假逻辑

---

### Track 3 — Hypothesis Inbox / Defer

#### 目标

让 `Hypothesis Desk` 从本地候选池切到真实 workspace inbox。

#### 必做

- 新增 `GET /api/v1/research/hypotheses?workspace_id=...`
- 新增 `POST /api/v1/research/hypotheses/{hypothesis_id}/defer`
- 补 hypothesis 状态机与 defer 语义
- 补集成测试与 API 文档

#### 不允许

- 不允许前端继续本地改 hypothesis 状态冒充 defer
- 不允许把 defer 做成只是前端隐藏

#### 前端接入影响

- `Hypothesis Desk` 可读取真实 hypothesis inbox
- promote / reject / defer 都进入真实 API

#### 通过标准

- hypothesis 列表来自真实后端
- defer 后刷新仍保留真实状态
- promote / reject / defer 三者状态迁移一致

---

### Track 4 — Regression + Contract Sync

#### 目标

在前三组能力补齐后，统一收紧契约、测试和文档，防止前后端再次漂移。

#### 必做

- 更新 `API_SPEC.md`
- 更新前端真接入设计文档
- 回归：
  - sources list
  - graph archive/delete
  - hypothesis inbox/defer

#### 不允许

- 不允许“接口先改了，文档后补”
- 不允许只有 controller 通过，前端仍按旧契约接

#### 通过标准

- 文档、测试、实现一致
- 后续前端不需要靠阅读实现猜测 API 语义

---

### Track 5 — Frontend Readiness Matrix

#### 目标

形成页面到 API 的正式接入矩阵，作为前端统一切 store 前的最后真源。

#### 必做

- 列出页面：
  - Home
  - Sources
  - Workbench
  - Hypothesis
  - Memory
  - Package
- 每页标明：
  - 真实 API 数据源
  - 是否异步
  - 是否需要 job 轮询
  - 当前可写动作
  - 当前只读动作
  - 当前禁用动作
- 产出唯一真源文档：`docs/mironicky/FRONTEND_READINESS_MATRIX.md`
- 对未接通动作必须使用明确状态：`disabled` / `read-only` / `not yet connected`
- Memory 页在 Track 5 仅允许 retrieval read model，不得提前实现 Track 6 写动作

#### 通过标准

- 前端可以按矩阵切真实 store
- 不会再出现“前端以为能写，后端实际没有”的错位
- evaluator 可直接据该矩阵逐页验收按钮级接入状态

---

### Track 6 — Memory Vault Controlled Actions

#### 目标

在不发明平行主状态源的前提下，让 `Memory Vault` 获得最小可用的正式动作。

#### 必做

- 明确定义 `Memory Vault` 为 retrieval-backed read model
- 可补：
  - memory list
  - bind to current route
  - memory -> hypothesis-candidate
- `Open In Workbench` 保持前端导航语义
- 补 controller / schema / service / tests / docs

#### 不允许

- 不允许把 `Memory Vault` 变成第二套主业务存储
- 不允许通过 memory 写动作偷偷绕开 graph / hypothesis 正式状态流

#### 通过标准

- `Memory Vault` 可以读真实数据
- 受控动作真实落后端
- 不形成与 Research Graph 并行的新主域

---

## 5. 每模块开发后的固定验收流程

这是本轨道的强制规则。

### 5.1 Developer 完成不等于模块通过

每个 Track 模块完成后，只能先标记为：

- `developer_complete`

不能直接视为：

- `evaluator_pass`

### 5.2 必须单开一个 evolution / evaluator

每完成一个 Track 模块，必须单开一个独立窗口或独立 evaluator 线程，只做验收，不做实现。

evaluator 必须检查：

1. 是否真的实现了本模块目标
2. 是否跨模块偷跑
3. 是否出现 mock / fake path / hard-coded happy path
4. 是否文档同步
5. 是否测试通过
6. 本模块要求的手动验收路径是否真实可走通

### 5.3 只有 evaluator PASS 才能进入下一个模块

每个模块都必须满足：

- developer handoff 完成
- evaluator PASS
- 文档回写完成

缺一不可。

### 5.4 推荐状态流

每个 Track 模块使用以下状态流：

- `not_started`
- `in_progress`
- `developer_complete`
- `evaluator_fail`
- `evaluator_pass`

若 `evaluator_fail`：

- 必须回到当前模块修复
- 禁止进入下一个 Track 模块

---

## 6. 推荐交付物

每个 Track 模块完成后，至少要有：

1. 开发交接记录
2. evaluator 验收记录
3. 对应测试命令与结果
4. 更新后的 API / 设计文档

推荐存放位置：

- `docs/superpowers/handoffs/`
- `docs/superpowers/evaluations/`
- 或沿用当前 `mironicky/handoffs`、`mironicky/evaluations` 体系

---

## 7. 当前推荐执行顺序

按稳定性和前端收益排序，当前建议是：

1. `Track 1 — Sources / Materials 真列表能力`
2. `Track 2 — Graph Archive / Delete 正式能力`
3. `Track 3 — Hypothesis Inbox / Defer`
4. `Track 4 — Regression + Contract Sync`
5. `Track 5 — Frontend Readiness Matrix`
6. `Track 6 — Memory Vault Controlled Actions`

---

## 8. 当前下一步

当前最合理的动作不是直接做 `Memory`，而是：

1. 先开始 `Track 1 — Sources / Materials 真列表能力`
2. 开发完成后，单开一个 evaluator 检查是否通过
3. 只有 PASS 后再进 `Track 2`
