# OBSERVABILITY.md — Mironicky Observability and Logging Truth

## 1. Purpose
This document is the active truth for Mironicky observability in the real backend repo.

It freezes:
- observability ownership
- shared vocabulary for logs, events, traces, and execution summaries
- structured logging envelope
- `research_events` persistence contract mapping
- minimum observability requirements by slice
- boundaries against `ERROR_INVENTORY.md` and `global_exception_handler.py`

It does not own business semantics such as route ranking, confidence math, RBAC rules, or package publication logic.

## 2. Ownership

### Owned Scope
- execution context vocabulary
- structured log/event envelope
- required event families
- `research_events` storage mapping
- slice-level minimum observability requirements
- relationship between logs, events, job status, and execution summary

### Out of Scope
- error code semantics themselves
- API endpoint ownership
- domain object state machines
- route scoring or hypothesis generation logic

### Conflict Resolution
1. Error meanings come from `ERROR_INVENTORY.md`.
2. API response envelopes come from `API_SPEC.md` and `ERROR_INVENTORY.md`.
3. `OBSERVABILITY.md` owns trace, logging, and event vocabulary.
4. If code emits a field that is not defined here, it must be treated as implementation-specific until documented.

## 3. Core Terms

| term | meaning |
|---|---|
| `request_id` | identifier for a synchronous request or request-derived flow |
| `job_id` | identifier for an async job tracked through `jobs` |
| `trace_id` | correlation id that ties logs, errors, and execution summaries together |
| `event` | structured execution record emitted during a research flow |
| `execution summary` | API-facing read model that summarizes a request/job timeline |
| `refs` | structured references to business objects touched by an event |
| `metrics` | structured quantitative data attached to an event |
| `debug log` | free-form or semi-structured log intended for engineering diagnosis only |

## 4. Execution Context
Every research flow must carry an execution context. The context is not a business object. It is the transport for observability fields.

### 4.1 Required Context Fields
Minimum fields when applicable:
- `trace_id`
- `request_id`
- `workspace_id`
- `job_id`
- `component`
- `step`
- `status`

Extended fields when applicable:
- `source_id`
- `candidate_batch_id`
- `route_id`
- `version_id`
- `package_id`
- `failure_id`
- `hypothesis_id`
- `actor_type`
- `actor_id`

### 4.2 Context Propagation Rule
The same logical flow must preserve compatible identifiers across:
- request handling
- async job creation
- worker execution
- structured logs
- `research_events`
- `ExecutionSummaryResponse`
- error envelopes when failure occurs

Transitional note for current implementation:
- Some async-envelope endpoints may still complete execution before the response returns.
- This transitional mode is allowed only if job/event/error surfaces remain fully compatible.
- Target state remains true background execution with the same externally visible job/result/error contracts.

## 5. Structured Logging Envelope
All research-chain structured logs and events must be representable as:

```json
{
  "trace_id": "trace_xxx",
  "request_id": "req_xxx",
  "workspace_id": "ws_xxx",
  "job_id": "job_xxx",
  "component": "research_source_controller",
  "step": "candidate_extraction_completed",
  "status": "completed",
  "refs": {},
  "metrics": {},
  "error": null
}
```

### 5.1 Required Fields in Research Logs/Events
Every structured research event must include:
- `request_id` or `job_id`
- `workspace_id`
- `component`
- `step`
- `status`
- `refs`
- `error`

### 5.2 Recommended Fields
- `trace_id`
- `metrics`
- `duration_ms`
- `provider`
- `degraded`

## 6. research_events Persistence Model
Real persistence target:
- `src/research_layer/api/controllers/_state_store.py`
- table: `research_events`

### 6.1 Table Mapping
| persisted_column | logical_field | notes |
|---|---|---|
| `event_id` | event identifier | primary key |
| `event_name` | `step` or canonical event name | persisted event family |
| `timestamp` | event timestamp | UTC string |
| `request_id` | request correlation | nullable |
| `job_id` | async correlation | nullable |
| `workspace_id` | workspace scope | nullable only for pre-workspace failures |
| `source_id` | source ref | nullable |
| `candidate_batch_id` | extraction batch ref | nullable |
| `component` | emitting component | required |
| `step` | detailed sub-step | nullable |
| `status` | lifecycle state | required |
| `refs_json` | structured business refs | JSON-encoded |
| `metrics_json` | structured metrics | JSON-encoded |
| `error_json` | structured error payload | JSON-encoded |

### 6.2 refs_json Contract
`refs_json` may contain:
- `source_id`
- `candidate_id`
- `candidate_batch_id`
- `route_id`
- `route_ids`
- `node_id`
- `edge_id`
- `version_id`
- `package_id`
- `failure_id`
- `hypothesis_id`
- `result_ref`

### 6.3 metrics_json Contract
`metrics_json` may contain:
- `duration_ms`
- `candidate_count`
- `node_count`
- `edge_count`
- `generated_route_count`
- `top_k`
- `score_count`
- `diff_size`

## 7. Schema Mapping
Primary schema mapping file:
- `src/research_layer/api/schemas/observability.py`

### 7.1 API-visible Models
- `ExecutionTimelineEvent`
- `ExecutionBusinessObjects`
- `ExecutionFinalOutcome`
- `ExecutionSummaryResponse`

### 7.2 Mapping Rule
- `ExecutionTimelineEvent` is the API/read-model projection of one structured event.
- `ExecutionSummaryResponse` is not the storage truth; it is a synthesized read model from persisted events plus job/request state.
- `OBSERVABILITY.md` owns the vocabulary. `observability.py` owns schema-level implementation shape.

## 8. Boundary with Error Handling
Current exception translation entry point:
- `src/core/middleware/global_exception_handler.py`

Boundary rule:
- `ERROR_INVENTORY.md` owns error code semantics and target error envelope.
- `OBSERVABILITY.md` owns how the same failure is surfaced in logs/events and execution summaries.
- A failed request/job should produce both:
  - a normalized API error envelope
  - a structured observability event with `error` payload

`error` payload in events should be compatible with:
- `error_code`
- `message`
- `details`
- `provider`
- `degraded`

## 9. Required Event Families

### 9.1 Preflight / Documentation Events
Hard requirement before Slice 3 implementation review:
- `doc_truth_reconciliation_completed`
- `doc_wiring_map_completed`
- `doc_foundational_truth_updated`
- `doc_gate_alignment_completed`

### 9.2 Slice 3 Hard Event Families
- `source_import_started`
- `source_import_completed`
- `candidate_extraction_started`
- `candidate_extraction_completed`
- `candidate_extraction_failed`
- `job_failed`

### 9.3 Slice 4 Hard Event Families
- `candidate_confirmed`
- `candidate_rejected`
- `candidate_confirmation_failed`

### 9.4 Future Slice Families
Required when the corresponding slice enters implementation review:
- `graph_build_started`
- `graph_build_completed`
- `graph_query_completed`
- `graph_node_created`
- `graph_node_updated`
- `graph_edge_created`
- `graph_edge_updated`
- `route_generation_started`
- `route_generation_completed`
- `score_recalculated`
- `failure_attached`
- `recompute_started`
- `recompute_completed`
- `diff_created`
- `hypothesis_generation_started`
- `hypothesis_generation_completed`
- `package_build_started`
- `package_build_completed`
- `package_publish_started`
- `package_publish_completed`

For `extract`, `recompute`, `hypothesis_generate`, and `package_publish`, observability acceptance requires:
1. `*_started` and terminal event presence even when execution path is transitional.
2. `jobs` record and `research_events` record consistency for `request_id`, `job_id`, and terminal status.
3. Failure paths must emit explicit event error payloads; silent completion is forbidden.

## 10. Output Surface Consistency
The following surfaces must agree on core identifiers and final outcome:
- structured logs
- `research_events`
- `jobs`
- `ExecutionSummaryResponse`
- evaluator/gate evidence

Consistency means:
1. `request_id` / `job_id` do not drift.
2. `workspace_id` and core refs do not disagree.
3. failed flows remain failed across all surfaces.
4. completed flows expose compatible `result_ref` or produced resource identifiers.

## 11. Debug Logs vs Structured Events

### 11.1 Structured Events
Use for:
- lifecycle state changes
- evaluator evidence
- API-facing execution summaries
- cross-service correlation

### 11.2 Debug Logs
Use for:
- local developer debugging
- provider raw payload snippets when safe
- low-level diagnostics that should not enter formal read models

Rule:
- Debug logs can be richer or noisier.
- Structured events must stay stable, typed, and evaluator-safe.

## 12. Minimum Requirements by Slice

### Slice 0.5
Required:
- documentation/preflight events can be referenced in gate evidence
- file-level target mapping for observability entry points is frozen

### Slice 1
Required:
- domain-related operations define which object refs must appear in future events
- no implementation obligation beyond truth alignment

### Slice 2
Required:
- request/job-facing APIs expose traceable identifiers
- `JobStatusResponse` and `ExecutionSummaryResponse` mapping is documented
- error envelope and event error payload boundaries are aligned

### Slice 3
Required:
- source import and extraction produce structured events
- async extraction jobs expose `job_id`, `status`, `result_ref`
- failed extract flows emit explicit error payloads and do not silently disappear

## 13. Acceptance Implication
A flow is not considered real if it cannot answer:
1. what entered the flow
2. what intermediate steps occurred
3. what resources were produced
4. where it failed, if it failed

If an implementation returns business state but cannot produce compatible logs/events/job status/execution summary, it fails observability acceptance.

## 14. Reference Rule
- `API_SPEC.md` references this document for execution-summary and async observability behavior.
- `STORAGE_SCHEMA.md` references this document for `research_events` persistence truth.
- `ERROR_INVENTORY.md` references this document for failure-surface consistency.

## 15. Unified Contract Observability Sync (2026-04-08)

### 15.1 Contract-Critical Event Minimums
For ingest/provenance/confidence/validation/package flows, each accepted implementation must emit enough events to answer:
1. what entered
2. what job or action ran
3. what resource/result was produced
4. why and where it failed (if failed)

Minimum correlation fields:
1. `workspace_id`
2. `request_id`
3. `job_id` (for async flows)
4. `event_name`
5. `status`

### 15.2 Async Contract Enforcement
For `extract`, `recompute`, `hypothesis_generate`, `package_publish`:
1. job terminal status and event terminal status must agree
2. failure must include structured error payload
3. success must include compatible `result_ref`

### 15.3 Planned Observability Additions
Status remains `planned` until runtime exists:
1. contract-level lint event family (`research_lint_started/completed/failed`)
2. asset writeback event family (`asset_writeback_started/completed/failed`)
3. claim/span provenance enrichment event family
