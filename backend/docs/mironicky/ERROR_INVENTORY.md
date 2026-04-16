# ERROR_INVENTORY.md — Mironicky Research Error Truth

## 1. Purpose
This document is the single truth for:
- research error code semantics
- HTTP mapping
- research error envelope
- execution point for translating exceptions into API responses

`API_SPEC.md` references this document and must not redefine error semantics inline.

## 2. Ownership
### Owned Scope
- error code names and meanings
- HTTP status mapping
- response envelope fields
- translation execution point
- degraded/provider/request trace error fields

### Out of Scope
- endpoint ownership
- business state machines
- controller-specific business logic

### Conflict Resolution
1. If an error code meaning conflicts with another spec, this document wins.
2. If current implementation cannot yet emit the full target envelope, the gap must be recorded as migration work, not hidden.
3. Controllers may not invent local error envelopes.
4. Async-envelope endpoints running in transitional sync execution mode must still surface failures as explicit job error payloads and compatible error envelopes.

## 3. Current Execution Point
- Core exception translation currently runs through:
  - `src/core/middleware/global_exception_handler.py`
- Current shared research error schema baseline exists in:
  - `src/research_layer/api/schemas/common.py`

## 4. Current vs Target Envelope

### Current Core Envelope
Current core middleware returns a generic body with fields such as:
- `status`
- `code`
- `message`
- `timestamp`
- `path`

### Current Research Error Schema Baseline
Current research schema baseline exposes:
- `error_code`
- `message`
- `details`

### Target Research Envelope
The target research envelope is:
```json
{
  "error_code": "research.invalid_state",
  "message": "candidate cannot be confirmed twice",
  "details": {},
  "trace_id": "trace_xxx",
  "request_id": "req_xxx",
  "provider": null,
  "degraded": false
}
```

Required fields:
- `error_code`
- `message`
- `details`
- `trace_id`
- `request_id`
- `provider`
- `degraded`

## 5. Shared Request Errors

| error_code | http_status | meaning |
|---|---|---|
| `research.invalid_request` | `400` | missing required field, invalid format, invalid enum, invalid filter |
| `research.not_found` | `404` | resource does not exist |
| `research.invalid_state` | `409` | resource exists but current state forbids the action |
| `research.conflict` | `409` | ownership, workspace, or uniqueness conflict |
| `research.client_disconnected` | `499` | client closed connection before request body was fully consumed |

Client-side async polling compatibility codes (non-HTTP terminal errors):
- `research.job_timeout`: frontend polling timeout for accepted async job; indicates unknown backend terminal state and requires follow-up via `/api/v1/research/jobs/{job_id}`.
- `research.request_timeout`: frontend request timeout before receiving backend response; does not imply backend business failure.

## 6. LLM / Provider Errors

| error_code | http_status | meaning |
|---|---|---|
| `research.llm_failed` | `502` | provider call failed without a recoverable local validation issue |
| `research.llm_timeout` | `504` | provider call timed out |
| `research.llm_rate_limited` | `429` | provider rejected due to rate limit |
| `research.llm_auth_failed` | `502` | provider auth/config failed |
| `research.llm_invalid_output` | `502` | provider returned output that fails strict parser or contract |

## 7. Authz and Visibility Errors

| error_code | http_status | meaning |
|---|---|---|
| `research.forbidden` | `403` | resource exists but caller lacks permission |
| `research.visibility_violation` | `403` | attempted access or edit violates visibility rules |
| `research.package_visibility_violation` | `403` | package operation would leak restricted content |

## 8. Failure, Recompute, and Package Errors

| error_code | http_status | meaning |
|---|---|---|
| `research.failure_attach_invalid_target` | `400` | failure target refs are malformed or unsupported |
| `research.internal_error` | `500` | unexpected internal failure without a more specific research error code |
| `research.recompute_failed` | `500` | recompute job finished unsuccessfully |
| `research.version_diff_unavailable` | `409` | version diff cannot be materialized from current persisted state |
| `research.package_publish_failed` | `500` | package publish failed after build/start |

## 9. Scholarly, Source Import, and Cold-Start Policy Errors

| error_code | http_status | meaning |
|---|---|---|
| `research.scholarly_provider_unavailable` | `503` | scholarly provider required by live flow is unavailable |
| `research.scholarly_provider_misconfigured` | `500` | required scholarly provider auth/config missing |
| `research.source_import_remote_fetch_failed` | `502` | URL mode import failed while fetching remote article/page content |
| `research.source_import_parse_failed` | `400` | import payload is present but URL/file/text parsing failed |
| `research.source_import_unsupported_format` | `400` | local file import attempted with format outside supported set (`pdf/docx`) |
| `research.bootstrap_live_llm_disabled` | `409` | bootstrap template policy forbids live LLM execution |
| `research.fixture_live_llm_not_allowed` | `409` | a fixture disallows live LLM use for active bootstrap |

## 10. Envelope Execution Rule
- The real translation execution point is `src/core/middleware/global_exception_handler.py`.
- Research-layer exceptions must be normalized into the target research envelope before response leaves the API boundary.
- Controllers may enrich `details`, `provider`, `request_id`, or `degraded`, but may not change the envelope shape.

## 11. Migration Notes
- Current implementation does not yet guarantee the full target envelope on every research path.
- The migration path is:
  1. align research exceptions with canonical error codes
  2. extend middleware/handler plumbing so `trace_id`, `request_id`, `provider`, and `degraded` can be injected
  3. update API schemas and integration tests to assert the target envelope
  4. remove transitional "sync execution + async envelope" paths for extract/recompute/hypothesis/package publish while preserving error code and envelope compatibility

## 12. Reference Rule
- `API_SPEC.md` references this document for every endpoint error family.
- `OBSERVABILITY.md` references this document for structured event error payload compatibility.
- Specialized specs may mention errors, but this document is the single semantic truth.

## 13. Unified Contract Error Sync (2026-04-08)

### 13.1 Existing Contract-Critical Errors
| error_code | http_status | contract_family | status |
|---|---|---|---|
| `research.invalid_request` | `400` | ingest/provenance/validation | existing |
| `research.not_found` | `404` | ingest/provenance/validation/package | existing |
| `research.invalid_state` | `409` | validation/package/confidence transition safety | existing |
| `research.conflict` | `409` | ownership/provenance consistency | existing |
| `research.llm_invalid_output` | `502` | ingest/confidence/hypothesis generation quality guard | existing |
| `research.internal_error` | `500` | shared internal fallback envelope | existing |
| `research.recompute_failed` | `500` | validation/recompute contract | existing |
| `research.package_publish_failed` | `500` | package publish contract | existing |

### 13.2 Planned Contract Errors (frozen vocabulary, not yet guaranteed runtime)
| error_code | http_status | contract_family | status |
|---|---|---|---|
| `research.validation_gate_failed` | `409` | validation gate hard-stop | planned |
| `research.confidence_contract_violation` | `409` | confidence explanation completeness | planned |
| `research.provenance_missing` | `409` | provenance trace completeness | planned |
| `research.asset_writeback_failed` | `500` | Q&A artifact writeback | planned |
| `research.lint_failed` | `409` | research lint gate | planned |

### 13.3 Rule
1. Planned errors may appear in truth docs and tests as future vocabulary.
2. Planned errors must not be claimed as existing runtime behavior before implementation lands.

## 14. Six Capability Error Use (existing)

The six capability additions reuse the existing error family instead of introducing new runtime error codes:

| condition | error_code | http_status | status |
|---|---|---|---|
| feature flag disabled | `research.forbidden` | `403` | existing |
| unsupported query tool, command, export format, or bootstrap payload | `research.invalid_request` | `400` | existing |
| package/version/resource not found | `research.not_found` | `404` | existing |
| workspace ownership mismatch | `research.conflict` | `409` | existing |
| command delegation reaches an invalid state in existing services | `research.invalid_state` | `409` | existing |

Rule:
1. Feature-disabled responses must include `details.feature_flag`.
2. Bootstrap partial item failures must be explicit in `failures[]`; silent drops are not allowed.
3. Query/report/export failures must not mutate canonical state as recovery behavior.
