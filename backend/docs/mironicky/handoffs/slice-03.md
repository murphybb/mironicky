---
record_type: developer_handoff
slice_id: slice_3
status: developer_complete
next_required_action: run_evaluator_for_slice_3
allowed_to_start_next_slice: false
---

# Slice 3 Developer Handoff

## Status

- Current result: `DEVELOPER_COMPLETE`
- Blocking status: `awaiting_evaluator`

## Implemented Scope (Slice 3 Only)

- source import service（真实持久化 + `source_import_started/completed`）
- source parser（含 parse failure 显式错误语义）
- extractors（`evidence/assumption/conflict/failure/validation`）
- prompt files（5 类 extractor prompt 全部落地）
- extraction worker（job lifecycle + candidate batch 回链）
- source / candidate / job / extraction result traceability 字段
- 最小 `Research Dev Console`（import -> extract -> candidate list）

## Explicitly Not Implemented in This Slice

- candidate confirm/reject 正式流扩展
- graph build / scoring / route generation
- failure recompute
- hypothesis
- package publish

## Verification Summary

- Unit: parser/extractors/prompt/fixture tests
- Integration: import/extract/job status/result_ref 回链、parse/extract failure、workspace 约束、dev console 路径
- Re-submit fix: `source_import_started` 事件现已绑定 `source_id`，新增用例校验该绑定不为空且与导入资源一致
- Fixture: `demo/research_dev/fixtures/slice3_sources.json`

## Known Risks

- 当前 extraction worker 为“接口触发后立即执行并落终态”的实现，满足统一 job 契约与终态查询，但尚未接入独立队列消费模型。
- 提取规则当前为 deterministic keyword extractor，后续若切到 LLM 抽取需要在不破坏结构化契约与可追溯字段的前提下替换。

## Async Job Note

- Slice 3 extract 使用异步 job 契约（`queued/running/succeeded|failed`）。
- `result_ref` 指向 `candidate_batch`，可回链到 `source_id`、`job_id`、`candidate_ids`。
