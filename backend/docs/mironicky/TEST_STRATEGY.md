# TEST_STRATEGY.md — Mironicky Test Strategy

## 1. 总原则

- 每个 slice 都要有单测和最小验收 demo。
- 当本 slice 已引入 service / repository / API / worker 边界时，必须补齐集成测试。
- 不允许只测 happy path。
- LLM 相关路径必须有 deterministic fixtures，避免把自由输出当成稳定契约。
- 从 Slice 2 起，每个 slice 都要有至少一个真实可点击的最小手动验收入口。

## 1.1 命令前置条件

当前仓库默认未作为可直接导入的 site package 安装。测试与验收命令必须显式写出运行前置条件：

- 在仓库根目录运行
- 显式设置 `PYTHONPATH=src`，或使用等效 editable install / 启动方式
- evaluator 在复现实验时必须照抄这些前置条件，不能自行猜测

## 2. 测试分层

### 2.1 单元测试

覆盖：

- domain model
- enums / value objects
- state transitions
- scoring logic
- graph helper
- failure impact rules

### 2.2 集成测试

覆盖：

- controller -> service -> repository
- worker -> persistence
- graph build / query
- route recompute

### 2.3 E2E 测试

至少覆盖三条主闭环：

1. import → extract → confirm → graph → score → route
2. failure → impact → recompute → diff
3. gap / conflict / failure → hypothesis candidate

### 2.4 手动验收入口

从 Slice 2 起，每个 slice 的验收除了自动化测试，还必须提供至少一个可点击的最小手动验收入口。

- Slice 2 可以先以 Swagger / OpenAPI 作为单步接口验收入口
- 凡涉及连续状态变化的 slice，必须提供最小 `Research Dev Console`
- 对于纯后端且仅单步接口验收的切片，允许使用 Swagger / OpenAPI + 内部验收脚本组合
- 手动验收入口必须只调用真实 API，不得缓存假状态、不得前端自算业务规则、不得喂硬编码示例数据冒充真实结果
- evaluator 在独立验收时必须沿这条手动路径再跑一遍，验证真 API、真持久化、真状态变化
- 若模块包含异步 job，手动验收必须覆盖：启动 job、查询 job 状态、观察终态、回链最终结果资源

## 3. 必测异常场景

- 空输入
- 非法状态
- 重复导入
- 重复确认
- 冲突对象
- 失败回流后状态变化
- 重算后的 diff

## 4. LLM 测试策略

- 使用 deterministic fixtures 固定 extractor 输入输出
- 结构化输出 schema 必须校验
- parse failure 需要单测覆盖
- 不把“看起来合理”的自然语言输出当成通过标准

## 5. Slice 0 要求

Slice 0 先建立测试目录骨架，并至少保留一个 import / bootstrap 级 smoke test，确保 Research Layer 目录接入不会破坏现有应用启动。

## 5.1 Slice 1 说明

Slice 1 是纯 domain model / enum / value object 层：

- 必须有单测
- 若尚未引入 service / repository / API / worker 边界，可不强制要求集成测试
- 不要求可点击手动验收入口
- 交付格式中的 `entrypoint` / `manual steps` / `expected observations` 可填写对象构造与测试复现实验命令，或标记为 `N/A (Slice 1)`

## 6. Slice 2+ 手动验收要求

从 Slice 2 起，每个 slice 的测试交付物除单测、集成测试、E2E 外，还必须包含：

- 一个可点击的最小手动验收入口
- `entrypoint`：入口 URL、页面路径或 OpenAPI 路由
- `startup / reset commands`：启动、重置、seed 命令
- `fixture / demo data`：对应的 deterministic fixture 或最小 demo 数据
- `manual steps`：手动点击或调用步骤
- `expected observations`：至少一个可观察的状态变化、终态或错误语义
