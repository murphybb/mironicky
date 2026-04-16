# API_SPEC.md — Mironicky Research API Truth

## 1. Purpose
This document is the active foundational truth for research API contracts in the real backend repo.

It freezes:
- canonical controller boundaries
- endpoint method/path ownership
- request/response schema references
- field-level schema contract for existing endpoints
- side effects and async behavior summaries
- error family references

It does not own business semantics such as route ranking, confidence formulas, RBAC propagation, or provider prompt content.

## 2. Ownership

### Owned Scope
- controller boundaries
- endpoint paths and methods
- request/response schema names and field-level contracts
- async job/result-ref behavior
- side-effect summaries
- error family references

### Out of Scope
- error code meanings
- domain object semantics
- persistence naming
- scoring/ranking/business algorithms

### Conflict Resolution
1. Controller names and endpoint ownership come from this document.
2. Error meanings come from `ERROR_INVENTORY.md`.
3. Persistence naming comes from `STORAGE_SCHEMA.md`.
4. If an endpoint is `planned`, it cannot be presented as `existing`.
5. Any handler/path drift must also be reflected in `WIRING_TARGET_MAP.md`.
6. An existing API schema or endpoint may be a transitional representation over current code and does not, by itself, prove that the corresponding canonical domain object in `DOMAIN_MODEL.md` is already `existing`.
7. Five contract families are remediation-aligned in this version: ingest, provenance, confidence explanation, validation, and package publish.
8. Endpoints returning `AsyncJobAcceptedResponse` must execute as real background jobs, reject `async_mode=false` with `research.invalid_request`, and expose pollable terminal status via `/api/v1/research/jobs/{job_id}`.
9. V1 scholarly provider strategy is fixed to `Crossref + Semantic Scholar` under existing source/retrieval controller boundaries.
10. Retrieval/memory endpoints in this document describe research-layer read models and controlled actions; native EverMemOS memory integration remains an additive future path.
11. `JobStatusResponse.status` is backend truth; frontend `research.job_timeout` means polling timeout only and must not be interpreted as backend terminal failure.
12. For `ValidationResultSubmitRequest(outcome=failed)`, runtime keeps auto-deriving a failure record; frontend must explain the relation through `triggered_failure_id` and `FailureResponse.derived_from_validation_*` provenance fields.

## 3. Canonical Controllers

| canonical_controller | evermemos_target_path | status | notes |
|---|---|---|---|
| `ResearchSourceController` | `src/research_layer/api/controllers/research_source_controller.py` | `existing` | source import, extraction, candidate actions, execution summary |
| `ResearchGraphController` | `src/research_layer/api/controllers/research_graph_controller.py` | `existing` | graph build/query, node-edge CRUD, version list/diff |
| `ResearchRouteController` | `src/research_layer/api/controllers/research_route_controller.py` | `existing` | route generate/list/detail/preview/score/recompute |
| `ResearchFailureController` | `src/research_layer/api/controllers/research_failure_controller.py` | `existing` | failure attach and validation create |
| `ResearchHypothesisController` | `src/research_layer/api/controllers/research_hypothesis_controller.py` | `existing` | current hypothesis generation and decisions; planned multi-agent pool/tournament actions remain inside this controller boundary until explicitly split |
| `ResearchPackageController` | `src/research_layer/api/controllers/research_package_controller.py` | `existing` | package create/list/detail/replay/publish |
| `ResearchRetrievalController` | `src/research_layer/api/controllers/research_retrieval_controller.py` | `existing` | retrieval views and memory actions |
| `ResearchJobController` | `src/research_layer/api/controllers/research_job_controller.py` | `existing` | async job status |
| `ResearchWorkspaceController` | _none_ | `planned` | cannot become canonical until real code target exists |
| `ResearchEvidenceController` | _none_ | `planned` | scholarly/evidence remains inside existing controller boundaries for V1 |

## 4. Global Rules
1. Base prefix: `/api/v1/research`.
2. Every endpoint must resolve to a `workspace_id` directly or by owned resource.
3. Async endpoints must expose `job_id`, `status`, and `result_ref` behavior.
4. Existing endpoints are frozen to field-level schema contract below.
5. Planned endpoints stay in `WIRING_TARGET_MAP.md` only and do not receive full schema expansion here.
6. All error families referenced below are defined in `ERROR_INVENTORY.md`.

## 5. Shared Schema Catalog

### 5.1 `common.py`

#### `WorkspaceScopedBody`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `workspace_id` | `string` | yes | none | regex `^[A-Za-z0-9_-]{3,64}$` | `common.py` | yes |

#### `ErrorResponse`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `error_code` | `string` | yes | none | research error code | `common.py` | yes |
| `message` | `string` | yes | none | non-empty | `common.py` | yes |
| `details` | `object` | yes | `{}` | JSON object | `common.py` | yes |

#### `ResultRef`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `resource_type` | `string` | yes | none | non-empty | `common.py` | yes |
| `resource_id` | `string` | yes | none | non-empty | `common.py` | yes |

#### `JobError`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `error_code` | `string` | yes | none | research error code | `common.py` | yes |
| `message` | `string` | yes | none | non-empty | `common.py` | yes |
| `details` | `object` | yes | `{}` | JSON object | `common.py` | yes |

#### `AsyncJobAcceptedResponse`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `job_id` | `string` | yes | none | non-empty | `common.py` | yes |
| `job_type` | `string` | yes | none | non-empty | `common.py` | yes |
| `status` | `string` | yes | none | async job enum | `common.py` | yes |
| `workspace_id` | `string` | yes | none | workspace regex | `common.py` | yes |
| `status_url` | `string` | yes | none | URL/path | `common.py` | yes |

#### `JobStatusResponse`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `job_id` | `string` | yes | none | non-empty | `common.py` | yes |
| `job_type` | `string` | yes | none | non-empty | `common.py` | yes |
| `status` | `string` | yes | none | `pending/running/completed/failed` style enum | `common.py` | yes |
| `workspace_id` | `string` | yes | none | workspace regex | `common.py` | yes |
| `request_id` | `string` | no | `null` | non-empty when present | `common.py` | yes |
| `created_at` | `datetime-string` | yes | none | ISO timestamp | `common.py` | yes |
| `started_at` | `datetime-string` | no | `null` | ISO timestamp | `common.py` | yes |
| `finished_at` | `datetime-string` | no | `null` | ISO timestamp | `common.py` | yes |
| `result_ref` | `ResultRef` | no | `null` | structured ref | `common.py` | yes |
| `error` | `JobError` | no | `null` | structured job error | `common.py` | yes |

### 5.2 `source.py`

#### `SourceImportRequest`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `workspace_id` | `string` | yes | none | workspace regex | `source.py` | yes |
| `source_type` | `enum` | yes | none | `paper/note/feedback/failure_record/dialogue` | `source.py` | yes |
| `title` | `string` | no | `null` | `<=256` chars | `source.py` | yes |
| `content` | `string` | no | `null` | non-empty when manual text mode is used | `source.py` | yes |
| `source_input_mode` | `enum` | no | `auto` | `auto/manual_text/url/local_file` | `source.py` | yes |
| `source_input` | `string` | no | `null` | URL string or manual text (depends on mode) | `source.py` | yes |
| `source_url` | `string` | no | `null` | `http/https` URL when URL mode is explicit | `source.py` | yes |
| `local_file` | `object` | no | `null` | `file_name` + (`file_content_base64` or `local_path`) | `source.py` | yes |
| `metadata` | `object` | no | `{}` | JSON object | `source.py` | yes |

#### `SourceLocalFileInput`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `file_name` | `string` | yes | none | non-empty | `source.py` | yes |
| `file_content_base64` | `string` | no | `null` | base64 payload when file bytes are sent inline | `source.py` | yes |
| `local_path` | `string` | no | `null` | absolute or relative local path | `source.py` | yes |
| `mime_type` | `string` | no | `null` | optional MIME hint | `source.py` | yes |

#### `SourceResponse`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `source_id` | `string` | yes | none | non-empty | `source.py` | yes |
| `workspace_id` | `string` | yes | none | workspace regex | `source.py` | yes |
| `source_type` | `enum` | yes | none | source type enum | `source.py` | yes |
| `title` | `string` | yes | none | non-empty | `source.py` | yes |
| `content` | `string` | yes | none | non-empty | `source.py` | yes |
| `normalized_content` | `string` | no | `null` | normalized text | `source.py` | yes |
| `status` | `string` | yes | none | source lifecycle enum | `source.py` | yes |
| `metadata` | `object` | yes | `{}` | JSON object | `source.py` | yes |
| `import_request_id` | `string` | no | `null` | non-empty when present | `source.py` | yes |
| `last_extract_job_id` | `string` | no | `null` | job id | `source.py` | yes |
| `created_at` | `datetime-string` | yes | none | ISO timestamp | `source.py` | yes |
| `updated_at` | `datetime-string` | yes | none | ISO timestamp | `source.py` | yes |

#### `SourceListResponse`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `items` | `array[SourceResponse]` | yes | `[]` | source item list | `source.py` | yes |
| `total` | `integer` | yes | none | `>= 0` | `source.py` | yes |

#### `SourceExtractRequest`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `workspace_id` | `string` | yes | none | workspace regex | `source.py` | yes |
| `async_mode` | `boolean` | no | `true` | must be `true`; `false` is rejected with `400 research.invalid_request` | `source.py` | yes |

#### `CandidateRecord`
This schema is the current API/store transitional representation for source extraction output. It must not be interpreted as proof that the canonical domain object `Candidate` already exists in `src/research_layer/domain/models/research_domain.py`.

| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `candidate_id` | `string` | yes | none | non-empty | `source.py` | yes |
| `workspace_id` | `string` | yes | none | workspace regex | `source.py` | yes |
| `source_id` | `string` | yes | none | non-empty | `source.py` | yes |
| `candidate_type` | `enum` | yes | none | `evidence/assumption/conflict/failure/validation` | `source.py` | yes |
| `text` | `string` | yes | none | non-empty | `source.py` | yes |
| `status` | `enum` | yes | none | `pending/confirmed/rejected` | `source.py` | yes |
| `source_span` | `object` | yes | none | structured span JSON | `source.py` | yes |
| `candidate_batch_id` | `string` | no | `null` | batch id | `source.py` | yes |
| `extraction_job_id` | `string` | no | `null` | job id | `source.py` | yes |
| `extractor_name` | `string` | no | `null` | non-empty when present | `source.py` | yes |
| `reject_reason` | `string` | no | `null` | non-empty when present | `source.py` | yes |

#### `CandidateDetailResponse`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `candidate_id` | `string` | yes | none | non-empty | `source.py` | yes |
| `workspace_id` | `string` | yes | none | workspace regex | `source.py` | yes |
| `source_id` | `string` | yes | none | non-empty | `source.py` | yes |
| `candidate_type` | `enum` | yes | none | `evidence/assumption/conflict/failure/validation` | `source.py` | yes |
| `text` | `string` | yes | none | non-empty | `source.py` | yes |
| `status` | `enum` | yes | none | `pending/confirmed/rejected` | `source.py` | yes |
| `source_span` | `object` | yes | none | structured span JSON | `source.py` | yes |
| `candidate_batch_id` | `string` | no | `null` | batch id | `source.py` | yes |
| `extraction_job_id` | `string` | no | `null` | job id | `source.py` | yes |
| `extractor_name` | `string` | no | `null` | non-empty when present | `source.py` | yes |
| `reject_reason` | `string` | no | `null` | non-empty when present | `source.py` | yes |

#### `CandidateListResponse`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `items` | `array[CandidateRecord]` | yes | `[]` | candidate item list | `source.py` | yes |
| `total` | `integer` | yes | none | `>= 0` | `source.py` | yes |

#### `CandidateConfirmRequest`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `workspace_id` | `string` | yes | none | workspace regex | `source.py` | yes |
| `candidate_ids` | `array[string]` | yes | none | min length 1 | `source.py` | yes |

#### `CandidateRejectRequest`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `workspace_id` | `string` | yes | none | workspace regex | `source.py` | yes |
| `candidate_ids` | `array[string]` | yes | none | min length 1 | `source.py` | yes |
| `reason` | `string` | yes | none | non-empty | `source.py` | yes |

#### `CandidateActionResponse`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `updated_ids` | `array[string]` | yes | none | non-empty list | `source.py` | yes |
| `status` | `string` | yes | none | resulting terminal or confirmed status | `source.py` | yes |

#### `ExtractionResultResponse`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `candidate_batch_id` | `string` | yes | none | non-empty | `source.py` | yes |
| `workspace_id` | `string` | yes | none | workspace regex | `source.py` | yes |
| `source_id` | `string` | yes | none | non-empty | `source.py` | yes |
| `job_id` | `string` | yes | none | job id | `source.py` | yes |
| `request_id` | `string` | no | `null` | non-empty when present | `source.py` | yes |
| `candidate_ids` | `array[string]` | yes | none | list of candidate ids | `source.py` | yes |
| `status` | `string` | yes | none | extraction status | `source.py` | yes |
| `error` | `JobError` | no | `null` | structured error | `source.py` | yes |
| `degraded` | `boolean` | yes | `false` | extraction degraded marker for partial fallback success | `source.py` | yes |
| `degraded_reason` | `string` | no | `null` | canonical degraded reason/error code | `source.py` | yes |
| `partial_failure_count` | `integer` | yes | `0` | count of extractor/provider partial failures in current batch | `source.py` | yes |
| `created_at` | `datetime-string` | yes | none | ISO timestamp | `source.py` | yes |
| `finished_at` | `datetime-string` | no | `null` | ISO timestamp | `source.py` | yes |

### 5.3 `graph.py`

#### `GraphNodeCreateRequest`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `workspace_id` | `string` | yes | none | workspace regex | `graph.py` | yes |
| `node_type` | `string` | yes | none | graph node enum | `graph.py` | yes |
| `object_ref_type` | `string` | yes | none | non-empty | `graph.py` | yes |
| `object_ref_id` | `string` | yes | none | non-empty | `graph.py` | yes |
| `short_label` | `string` | yes | none | max 128 chars | `graph.py` | yes |
| `full_description` | `string` | yes | none | non-empty | `graph.py` | yes |
| `short_tags` | `array[string]` | no | `[]` | deduped, max 3 tags | `graph.py` | yes |
| `visibility` | `string` | no | `workspace` | `private/workspace/package_public` | `graph.py` | yes |
| `source_refs` | `array[object]` | no | `[]` | source trace references | `graph.py` | yes |

#### `GraphNodePatchRequest`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `workspace_id` | `string` | yes | none | workspace regex | `graph.py` | yes |
| `short_label` | `string` | no | `null` | max 128 chars | `graph.py` | yes |
| `full_description` | `string` | no | `null` | non-empty when present | `graph.py` | yes |
| `short_tags` | `array[string]` | no | `null` | deduped, max 3 tags when provided | `graph.py` | yes |
| `visibility` | `string` | no | `null` | `private/workspace/package_public` when provided | `graph.py` | yes |
| `source_refs` | `array[object]` | no | `null` | source trace references when provided | `graph.py` | yes |
| `status` | `string` | no | `null` | graph status enum | `graph.py` | yes |

#### `GraphNodeResponse`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `node_id` | `string` | yes | none | non-empty | `graph.py` | yes |
| `workspace_id` | `string` | yes | none | workspace regex | `graph.py` | yes |
| `node_type` | `string` | yes | none | node enum | `graph.py` | yes |
| `object_ref_type` | `string` | yes | none | non-empty | `graph.py` | yes |
| `object_ref_id` | `string` | yes | none | non-empty | `graph.py` | yes |
| `short_label` | `string` | yes | none | max 128 chars | `graph.py` | yes |
| `full_description` | `string` | yes | none | non-empty | `graph.py` | yes |
| `short_tags` | `array[string]` | yes | `[]` | deduped, max 3 tags | `graph.py` | yes |
| `visibility` | `string` | yes | `workspace` | `private/workspace/package_public` | `graph.py` | yes |
| `source_refs` | `array[object]` | yes | `[]` | source trace references | `graph.py` | yes |
| `status` | `string` | yes | none | node status enum | `graph.py` | yes |
| `created_at` | `datetime-string` | no | `null` | ISO timestamp | `graph.py` | yes |
| `updated_at` | `datetime-string` | no | `null` | ISO timestamp | `graph.py` | yes |

#### `GraphEdgeCreateRequest`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `workspace_id` | `string` | yes | none | workspace regex | `graph.py` | yes |
| `source_node_id` | `string` | yes | none | non-empty | `graph.py` | yes |
| `target_node_id` | `string` | yes | none | non-empty | `graph.py` | yes |
| `edge_type` | `string` | yes | none | graph edge enum | `graph.py` | yes |
| `object_ref_type` | `string` | yes | none | non-empty | `graph.py` | yes |
| `object_ref_id` | `string` | yes | none | non-empty | `graph.py` | yes |
| `strength` | `number` | yes | none | `0 <= strength <= 1` | `graph.py` | yes |

#### `GraphEdgePatchRequest`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `workspace_id` | `string` | yes | none | workspace regex | `graph.py` | yes |
| `status` | `string` | no | `null` | edge status enum | `graph.py` | yes |
| `strength` | `number` | no | `null` | `0 <= strength <= 1` | `graph.py` | yes |

#### `GraphArchiveRequest`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `workspace_id` | `string` | yes | none | workspace regex | `graph.py` | yes |
| `reason` | `string` | no | `null` | max 512 chars | `graph.py` | yes |

#### `GraphEdgeResponse`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `edge_id` | `string` | yes | none | non-empty | `graph.py` | yes |
| `workspace_id` | `string` | yes | none | workspace regex | `graph.py` | yes |
| `source_node_id` | `string` | yes | none | non-empty | `graph.py` | yes |
| `target_node_id` | `string` | yes | none | non-empty | `graph.py` | yes |
| `edge_type` | `string` | yes | none | edge enum | `graph.py` | yes |
| `object_ref_type` | `string` | yes | none | non-empty | `graph.py` | yes |
| `object_ref_id` | `string` | yes | none | non-empty | `graph.py` | yes |
| `strength` | `number` | yes | none | `0 <= strength <= 1` | `graph.py` | yes |
| `status` | `string` | yes | none | edge status enum | `graph.py` | yes |
| `created_at` | `datetime-string` | no | `null` | ISO timestamp | `graph.py` | yes |
| `updated_at` | `datetime-string` | no | `null` | ISO timestamp | `graph.py` | yes |

#### `GraphResponse`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `workspace_id` | `string` | yes | none | workspace regex | `graph.py` | yes |
| `nodes` | `array[GraphNodeResponse]` | yes | `[]` | graph node list | `graph.py` | yes |
| `edges` | `array[GraphEdgeResponse]` | yes | `[]` | graph edge list | `graph.py` | yes |

#### `GraphBuildResponse`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `workspace_id` | `string` | yes | none | workspace regex | `graph.py` | yes |
| `version_id` | `string` | yes | none | non-empty | `graph.py` | yes |
| `node_count` | `integer` | yes | none | `>= 0` | `graph.py` | yes |
| `edge_count` | `integer` | yes | none | `>= 0` | `graph.py` | yes |

#### `GraphWorkspaceResponse`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `workspace_id` | `string` | yes | none | workspace regex | `graph.py` | yes |
| `latest_version_id` | `string` | no | `null` | version id | `graph.py` | yes |
| `status` | `string` | yes | none | workspace graph status | `graph.py` | yes |
| `node_count` | `integer` | yes | none | `>= 0` | `graph.py` | yes |
| `edge_count` | `integer` | yes | none | `>= 0` | `graph.py` | yes |
| `updated_at` | `datetime-string` | no | `null` | ISO timestamp | `graph.py` | yes |

#### `GraphQueryRequest`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `center_node_id` | `string` | no | `null` | non-empty when present | `graph.py` | yes |
| `max_hops` | `integer` | no | `1` | `1 <= max_hops <= 5` | `graph.py` | yes |

#### `GraphVersionRecord`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `version_id` | `string` | yes | none | non-empty | `graph.py` | yes |
| `workspace_id` | `string` | yes | none | workspace regex | `graph.py` | yes |
| `trigger_type` | `string` | yes | none | version trigger enum | `graph.py` | yes |
| `change_summary` | `string` | yes | none | non-empty | `graph.py` | yes |
| `created_at` | `datetime-string` | no | `null` | ISO timestamp | `graph.py` | yes |
| `request_id` | `string` | no | `null` | request id | `graph.py` | yes |

#### `GraphVersionListResponse`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `items` | `array[GraphVersionRecord]` | yes | `[]` | version list | `graph.py` | yes |
| `total` | `integer` | yes | none | `>= 0` | `graph.py` | yes |

#### `GraphVersionDiffResponse`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `version_id` | `string` | yes | none | non-empty | `graph.py` | yes |
| `workspace_id` | `string` | yes | none | workspace regex | `graph.py` | yes |
| `diff_payload` | `object` | yes | none | version diff JSON | `graph.py` | yes |

#### `GraphArchiveResponse`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `workspace_id` | `string` | yes | none | workspace regex | `graph.py` | yes |
| `target_type` | `string` | yes | none | `node/edge` | `graph.py` | yes |
| `target_id` | `string` | yes | none | non-empty | `graph.py` | yes |
| `status` | `string` | yes | none | archival outcome | `graph.py` | yes |
| `version_id` | `string` | yes | none | non-empty | `graph.py` | yes |
| `diff_payload` | `object` | yes | none | diff JSON | `graph.py` | yes |

### 5.4 `route.py`

#### Nested Route Models
| model | fields | source_schema | implemented |
|---|---|---|---|
| `FactorBreakdownRecord` | `factor_name, score_dimension, normalized_value, weight, weighted_contribution, status, reason, refs, metrics, explanation?` | `route.py` | yes |
| `ScoreDimensionBreakdown` | `normalized_score, score, factors[]` | `route.py` | yes |
| `NodeFactorContribution` | `factor_name, score_dimension, contribution` | `route.py` | yes |
| `NodeScoreBreakdownRecord` | `node_id, node_type, status, object_ref_type, object_ref_id, support_contribution, risk_contribution, progressability_contribution, total_contribution, factor_contributions[]` | `route.py` | yes |
| `RouteNodeRef` | `node_id, node_type, object_ref_type, object_ref_id, short_label, status` | `route.py` | yes |
| `RouteRiskHint` | `node, hint` | `route.py` | yes |
| `RouteTraceRefs` | `version_id?, route_node_ids[], route_edge_ids[], conclusion_node_id?` | `route.py` | yes |

#### `RouteRecord`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `route_id` | `string` | yes | none | non-empty | `route.py` | yes |
| `workspace_id` | `string` | yes | none | workspace regex | `route.py` | yes |
| `title` | `string` | yes | none | non-empty | `route.py` | yes |
| `summary` | `string` | yes | none | non-empty | `route.py` | yes |
| `status` | `string` | yes | none | route status enum | `route.py` | yes |
| `support_score` | `number` | yes | none | score value | `route.py` | yes |
| `risk_score` | `number` | yes | none | score value | `route.py` | yes |
| `progressability_score` | `number` | yes | none | score value | `route.py` | yes |
| `confidence_score` | `number` | yes | none | deterministic aggregate score | `route.py` | yes |
| `confidence_grade` | `string` | yes | none | `low/medium/high` | `route.py` | yes |
| `novelty_level` | `string` | yes | `incremental` | novelty enum | `route.py` | yes |
| `relation_tags` | `array[string]` | yes | `[]` | semantic tags: `direct_support/recombination/upstream_inspiration` | `route.py` | yes |
| `top_factors` | `array[FactorBreakdownRecord]` | yes | `[]` | factor breakdown list | `route.py` | yes |
| `score_breakdown` | `object` | yes | `{}` | dimension breakdown JSON | `route.py` | yes |
| `node_score_breakdown` | `array[NodeScoreBreakdownRecord]` | yes | `[]` | node factor detail | `route.py` | yes |
| `scoring_template_id` | `string` | no | `null` | template id | `route.py` | yes |
| `scored_at` | `datetime-string` | no | `null` | ISO timestamp | `route.py` | yes |
| `conclusion` | `string` | yes | none | non-empty | `route.py` | yes |
| `key_supports` | `array[string]` | yes | `[]` | conclusion support text | `route.py` | yes |
| `assumptions` | `array[string]` | yes | `[]` | route assumption text | `route.py` | yes |
| `risks` | `array[string]` | yes | `[]` | route risk text | `route.py` | yes |
| `next_validation_action` | `string` | yes | none | non-empty | `route.py` | yes |
| `conclusion_node_id` | `string` | no | `null` | node id | `route.py` | yes |
| `route_node_ids` | `array[string]` | yes | `[]` | node id list | `route.py` | yes |
| `route_edge_ids` | `array[string]` | yes | `[]` | edge id list persisted from canonical route replay source | `route.py` | yes |
| `key_support_node_ids` | `array[string]` | yes | `[]` | node id list | `route.py` | yes |
| `key_assumption_node_ids` | `array[string]` | yes | `[]` | node id list | `route.py` | yes |
| `risk_node_ids` | `array[string]` | yes | `[]` | node id list | `route.py` | yes |
| `next_validation_node_id` | `string` | no | `null` | node id | `route.py` | yes |
| `version_id` | `string` | no | `null` | graph version id | `route.py` | yes |
| `summary_generation_mode` | `string` | yes | `llm` | `llm \| degraded_fallback` | `route.py` | yes |
| `provider_backend` | `string` | no | `null` | provider backend for summary generation | `route.py` | yes |
| `provider_model` | `string` | no | `null` | provider model for summary generation | `route.py` | yes |
| `request_id` | `string` | no | `null` | LLM request correlation id | `route.py` | yes |
| `llm_response_id` | `string` | no | `null` | provider response id | `route.py` | yes |
| `usage` | `object` | no | `null` | token usage payload | `route.py` | yes |
| `fallback_used` | `boolean` | yes | `false` | explicit fallback marker | `route.py` | yes |
| `degraded` | `boolean` | yes | `false` | explicit degraded marker | `route.py` | yes |
| `degraded_reason` | `string` | no | `null` | canonical degraded reason/error code | `route.py` | yes |
| `key_strengths` | `array[object]` | yes | `[]` | structured summary strengths with `text/node_refs` | `route.py` | yes |
| `key_risks` | `array[object]` | yes | `[]` | structured summary risks with `text/node_refs` | `route.py` | yes |
| `open_questions` | `array[object]` | yes | `[]` | structured summary open questions with `text/node_refs` | `route.py` | yes |
| `rank` | `integer` | no | `null` | ranking position | `route.py` | yes |

#### `RouteListResponse`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `items` | `array[RouteRecord]` | yes | `[]` | route list | `route.py` | yes |
| `total` | `integer` | yes | none | `>= 0` | `route.py` | yes |

#### `RoutePreviewResponse`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `route_id` | `string` | yes | none | non-empty | `route.py` | yes |
| `workspace_id` | `string` | yes | none | workspace regex | `route.py` | yes |
| `summary` | `string` | yes | none | non-empty | `route.py` | yes |
| `summary_generation_mode` | `string` | yes | `llm` | `llm \| degraded_fallback` | `route.py` | yes |
| `degraded` | `boolean` | yes | `false` | explicit degraded marker | `route.py` | yes |
| `provider_backend` | `string` | no | `null` | provider backend for summary generation | `route.py` | yes |
| `provider_model` | `string` | no | `null` | provider model for summary generation | `route.py` | yes |
| `request_id` | `string` | no | `null` | LLM request correlation id | `route.py` | yes |
| `llm_response_id` | `string` | no | `null` | provider response id | `route.py` | yes |
| `usage` | `object` | no | `null` | token usage payload | `route.py` | yes |
| `fallback_used` | `boolean` | yes | `false` | explicit fallback marker | `route.py` | yes |
| `degraded_reason` | `string` | no | `null` | canonical degraded reason/error code | `route.py` | yes |
| `key_strengths` | `array[object]` | yes | `[]` | structured summary strengths with `text/node_refs` | `route.py` | yes |
| `key_risks` | `array[object]` | yes | `[]` | structured summary risks with `text/node_refs` | `route.py` | yes |
| `open_questions` | `array[object]` | yes | `[]` | structured summary open questions with `text/node_refs` | `route.py` | yes |
| `conclusion_node` | `RouteNodeRef` | yes | none | route node ref | `route.py` | yes |
| `key_support_evidence` | `array[RouteNodeRef]` | yes | `[]` | node refs | `route.py` | yes |
| `key_assumptions` | `array[RouteNodeRef]` | yes | `[]` | node refs | `route.py` | yes |
| `conflict_failure_hints` | `array[RouteRiskHint]` | yes | `[]` | risk hints | `route.py` | yes |
| `next_validation_action` | `string` | yes | none | non-empty | `route.py` | yes |
| `top_factors` | `array[FactorBreakdownRecord]` | yes | `[]` | top factor breakdown list | `route.py` | yes |
| `trace_refs` | `RouteTraceRefs` | yes | none | structured refs | `route.py` | yes |

#### `RouteGenerateRequest`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `workspace_id` | `string` | yes | none | workspace regex | `route.py` | yes |
| `reason` | `string` | yes | none | `1..256` chars | `route.py` | yes |
| `max_candidates` | `integer` | no | `8` | `1 <= value <= 20` | `route.py` | yes |

#### `RouteGenerateResponse`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `workspace_id` | `string` | yes | none | workspace regex | `route.py` | yes |
| `generated_count` | `integer` | yes | none | `>= 0` | `route.py` | yes |
| `ranked_route_ids` | `array[string]` | yes | `[]` | route ids | `route.py` | yes |
| `top_route_id` | `string` | no | `null` | route id | `route.py` | yes |

#### `RouteScoreRequest`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `workspace_id` | `string` | yes | none | workspace regex | `route.py` | yes |
| `template_id` | `string` | no | `null` | scoring template id | `route.py` | yes |
| `focus_node_ids` | `array[string]` | no | `[]` | node ids | `route.py` | yes |

#### `RouteScoreResponse`
- Schema alias: `RouteRecord`
- source schema: `route.py`
- implemented: yes

#### `RouteRecomputeRequest`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `workspace_id` | `string` | yes | none | workspace regex | `route.py` | yes |
| `failure_id` | `string` | no | `null` | failure id | `route.py` | yes |
| `reason` | `string` | yes | none | `1..256` chars | `route.py` | yes |
| `async_mode` | `boolean` | no | `true` | must be `true`; `false` is rejected with `400 research.invalid_request` | `route.py` | yes |

### 5.5 `failure.py`

#### `FailureTargetRef`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `target_type` | `string` | yes | none | regex `^(node|edge)$` | `failure.py` | yes |
| `target_id` | `string` | yes | none | non-empty | `failure.py` | yes |

#### `FailureCreateRequest`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `workspace_id` | `string` | yes | none | workspace regex | `failure.py` | yes |
| `attached_targets` | `array[FailureTargetRef]` | yes | none | min length 1 | `failure.py` | yes |
| `observed_outcome` | `string` | yes | none | non-empty | `failure.py` | yes |
| `expected_difference` | `string` | yes | none | non-empty | `failure.py` | yes |
| `failure_reason` | `string` | yes | none | non-empty | `failure.py` | yes |
| `severity` | `string` | yes | none | severity enum | `failure.py` | yes |
| `reporter` | `string` | yes | none | non-empty | `failure.py` | yes |

#### `FailureResponse`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `failure_id` | `string` | yes | none | non-empty | `failure.py` | yes |
| `workspace_id` | `string` | yes | none | workspace regex | `failure.py` | yes |
| `attached_targets` | `array[FailureTargetRef]` | yes | none | target list | `failure.py` | yes |
| `observed_outcome` | `string` | yes | none | non-empty | `failure.py` | yes |
| `expected_difference` | `string` | yes | none | non-empty | `failure.py` | yes |
| `failure_reason` | `string` | yes | none | non-empty | `failure.py` | yes |
| `severity` | `string` | yes | none | severity enum | `failure.py` | yes |
| `reporter` | `string` | yes | none | non-empty | `failure.py` | yes |
| `created_at` | `datetime-string` | yes | none | ISO timestamp | `failure.py` | yes |
| `impact_summary` | `object` | yes | `{}` | structured impact payload | `failure.py` | yes |
| `impact_updated_at` | `datetime-string` | no | `null` | latest persisted impact snapshot timestamp; remains `null` until attach/recompute has materialized impact | `failure.py` | yes |
| `derived_from_validation_id` | `string` | no | `null` | validation id when failure is auto-derived from validation feedback | `failure.py` | yes |
| `derived_from_validation_result_id` | `string` | no | `null` | validation result id that produced the derived failure record | `failure.py` | yes |

#### `ValidationCreateRequest`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `workspace_id` | `string` | yes | none | workspace regex | `failure.py` | yes |
| `target_object` | `string` | yes | none | non-empty | `failure.py` | yes |
| `method` | `string` | yes | none | non-empty | `failure.py` | yes |
| `success_signal` | `string` | yes | none | non-empty | `failure.py` | yes |
| `weakening_signal` | `string` | yes | none | non-empty | `failure.py` | yes |
| `status` | `string` | yes | `pending` | `pending/validated/weakened/failed` | `failure.py` | yes |
| `latest_outcome` | `string` | no | `null` | latest submitted outcome | `failure.py` | yes |
| `latest_result_id` | `string` | no | `null` | validation result id | `failure.py` | yes |
| `updated_at` | `datetime-string` | no | `null` | ISO timestamp | `failure.py` | yes |

#### `ValidationResultSubmitRequest`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `workspace_id` | `string` | yes | none | workspace regex | `failure.py` | yes |
| `outcome` | `enum` | yes | none | `validated/weakened/failed` | `failure.py` | yes |
| `note` | `string` | no | `null` | optional note | `failure.py` | yes |
| `target_type` | `string` | no | `null` | `route/node/edge` when provided with `target_id` | `failure.py` | yes |
| `target_id` | `string` | no | `null` | non-empty when provided with `target_type` | `failure.py` | yes |
| `reporter` | `string` | no | `validation_feedback` | non-empty, max 64 | `failure.py` | yes |

#### `ValidationResultResponse`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `result_id` | `string` | yes | none | non-empty | `failure.py` | yes |
| `validation_id` | `string` | yes | none | non-empty | `failure.py` | yes |
| `workspace_id` | `string` | yes | none | workspace regex | `failure.py` | yes |
| `outcome` | `string` | yes | none | `validated/weakened/failed` | `failure.py` | yes |
| `target_type` | `string` | no | `null` | `route/node/edge` | `failure.py` | yes |
| `target_id` | `string` | no | `null` | non-empty when present | `failure.py` | yes |
| `note` | `string` | no | `null` | optional note | `failure.py` | yes |
| `request_id` | `string` | no | `null` | request correlation id | `failure.py` | yes |
| `triggered_failure_id` | `string` | no | `null` | failure id when weakened/failed | `failure.py` | yes |
| `recompute_job_id` | `string` | no | `null` | job id when weakened/failed | `failure.py` | yes |
| `created_at` | `datetime-string` | yes | none | ISO timestamp | `failure.py` | yes |
| `triggered_failure` | `FailureResponse` | no | `null` | inline failure snapshot for weakened/failed outcomes; includes provenance + latest persisted impact snapshot when available | `failure.py` | yes |

Validation-to-failure semantics:
- `triggered_failure_id` must point to the same failure record returned by `triggered_failure.failure_id` when inline payload exists.
- `GET /api/v1/research/failures/{failure_id}` is the canonical detail source for persisted `impact_summary` and `impact_updated_at`.
- Frontend must not infer impact/route diffs from transient client state when `impact_summary` is available from API.

#### `ValidationResponse`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `validation_id` | `string` | yes | none | non-empty | `failure.py` | yes |
| `workspace_id` | `string` | yes | none | workspace regex | `failure.py` | yes |
| `target_object` | `string` | yes | none | non-empty | `failure.py` | yes |
| `method` | `string` | yes | none | non-empty | `failure.py` | yes |
| `success_signal` | `string` | yes | none | non-empty | `failure.py` | yes |
| `weakening_signal` | `string` | yes | none | non-empty | `failure.py` | yes |

### 5.6 `hypothesis.py`

#### `HypothesisTriggerRecord`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `trigger_id` | `string` | yes | none | non-empty | `hypothesis.py` | yes |
| `trigger_type` | `string` | yes | none | trigger enum | `hypothesis.py` | yes |
| `workspace_id` | `string` | yes | none | workspace regex | `hypothesis.py` | yes |
| `object_ref_type` | `string` | yes | none | non-empty | `hypothesis.py` | yes |
| `object_ref_id` | `string` | yes | none | non-empty | `hypothesis.py` | yes |
| `summary` | `string` | yes | none | non-empty | `hypothesis.py` | yes |
| `trace_refs` | `object` | yes | `{}` | trace refs JSON | `hypothesis.py` | yes |
| `related_object_ids` | `array[string]` | yes | `[]` | object ids | `hypothesis.py` | yes |
| `metrics` | `object` | yes | `{}` | JSON object | `hypothesis.py` | yes |

#### `HypothesisTriggerListResponse`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `items` | `array[HypothesisTriggerRecord]` | yes | `[]` | trigger list | `hypothesis.py` | yes |
| `total` | `integer` | yes | none | `>= 0` | `hypothesis.py` | yes |

#### `HypothesisListResponse`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `items` | `array[HypothesisResponse]` | yes | `[]` | hypothesis list | `hypothesis.py` | yes |
| `total` | `integer` | yes | none | `>= 0` | `hypothesis.py` | yes |

#### `HypothesisGenerateRequest`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `workspace_id` | `string` | yes | none | workspace regex | `hypothesis.py` | yes |
| `trigger_ids` | `array[string]` | yes | none | min length 1 | `hypothesis.py` | yes |
| `async_mode` | `boolean` | no | `true` | must be `true`; `false` is rejected with `400 research.invalid_request` | `hypothesis.py` | yes |

Current note:
- this is the existing transitional single-shot generation contract.
- planned multi-agent pool generation fields remain `planned` and must not be expanded here until runtime support lands.

#### `HypothesisDecisionRequest`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `workspace_id` | `string` | yes | none | workspace regex | `hypothesis.py` | yes |
| `note` | `string` | yes | none | non-empty | `hypothesis.py` | yes |
| `decision_source_type` | `string` | yes | none | non-empty | `hypothesis.py` | yes |
| `decision_source_ref` | `string` | yes | none | non-empty | `hypothesis.py` | yes |

#### Nested Hypothesis Models
| model | fields | source_schema | implemented |
|---|---|---|---|
| `HypothesisRelatedObject` | `object_type, object_id` | `hypothesis.py` | yes |
| `HypothesisValidationAction` | `validation_id, target_object, method, success_signal, weakening_signal, cost_level, time_level` | `hypothesis.py` | yes |
| `HypothesisWeakeningSignal` | `signal_type, signal_text, severity_hint, trace_refs` | `hypothesis.py` | yes |

#### `HypothesisResponse`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `hypothesis_id` | `string` | yes | none | non-empty | `hypothesis.py` | yes |
| `workspace_id` | `string` | yes | none | workspace regex | `hypothesis.py` | yes |
| `statement` | `string` | yes | `""` | text | `hypothesis.py` | yes |
| `title` | `string` | yes | none | non-empty | `hypothesis.py` | yes |
| `summary` | `string` | yes | none | non-empty | `hypothesis.py` | yes |
| `premise` | `string` | yes | none | non-empty | `hypothesis.py` | yes |
| `rationale` | `string` | yes | none | non-empty | `hypothesis.py` | yes |
| `status` | `string` | yes | none | hypothesis status enum | `hypothesis.py` | yes |
| `stage` | `string` | yes | none | stage enum | `hypothesis.py` | yes |
| `trigger_object_ids` | `array[string]` | yes | `[]` | object ids | `hypothesis.py` | yes |
| `trigger_refs` | `array[string]` | yes | `[]` | trace refs | `hypothesis.py` | yes |
| `related_object_ids` | `array[HypothesisRelatedObject]` | yes | `[]` | related objects | `hypothesis.py` | yes |
| `novelty_typing` | `string` | yes | none | novelty enum/text | `hypothesis.py` | yes |
| `minimum_validation_action` | `HypothesisValidationAction` | yes | none | structured action | `hypothesis.py` | yes |
| `weakening_signal` | `HypothesisWeakeningSignal` | yes | none | structured signal | `hypothesis.py` | yes |
| `decision_note` | `string` | no | `null` | note text | `hypothesis.py` | yes |
| `decision_source_type` | `string` | no | `null` | non-empty when present | `hypothesis.py` | yes |
| `decision_source_ref` | `string` | no | `null` | non-empty when present | `hypothesis.py` | yes |
| `decided_at` | `datetime-string` | no | `null` | ISO timestamp | `hypothesis.py` | yes |
| `decided_request_id` | `string` | no | `null` | request id | `hypothesis.py` | yes |
| `created_at` | `datetime-string` | no | `null` | ISO timestamp | `hypothesis.py` | yes |
| `updated_at` | `datetime-string` | no | `null` | ISO timestamp | `hypothesis.py` | yes |
| `generation_job_id` | `string` | no | `null` | job id | `hypothesis.py` | yes |

Current note:
- this is the existing hypothesis response contract.
- planned pool/candidate/round/match/search-tree response models remain `planned` and are tracked only through `WIRING_TARGET_MAP.md` until implemented.

### 5.7 `package.py`

#### Nested Package Models
| model | fields | source_schema | implemented |
|---|---|---|---|
| `PrivateDependencyFlagRecord` | `private_node_id, private_object_ref, reason, referenced_by_route_ids, replacement_gap_node_id` | `package.py` | yes |
| `PublicGapNodeRecord` | `node_id, workspace_id, node_type, object_ref_type, object_ref_id, short_label, full_description, status, trace_refs` | `package.py` | yes |

#### `PackageCreateRequest`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `workspace_id` | `string` | yes | none | workspace regex | `package.py` | yes |
| `title` | `string` | yes | none | max 256 chars | `package.py` | yes |
| `summary` | `string` | yes | none | non-empty | `package.py` | yes |
| `included_route_ids` | `array[string]` | yes | none | route ids | `package.py` | yes |
| `included_node_ids` | `array[string]` | yes | none | node ids | `package.py` | yes |
| `included_validation_ids` | `array[string]` | yes | none | validation ids | `package.py` | yes |

#### `PackagePublishRequest`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `workspace_id` | `string` | yes | none | workspace regex | `package.py` | yes |
| `async_mode` | `boolean` | no | `true` | must be `true`; `false` is rejected with `400 research.invalid_request` | `package.py` | yes |

#### `PackageResponse`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `package_id` | `string` | yes | none | non-empty | `package.py` | yes |
| `workspace_id` | `string` | yes | none | workspace regex | `package.py` | yes |
| `title` | `string` | yes | none | max 256 chars | `package.py` | yes |
| `summary` | `string` | yes | none | non-empty | `package.py` | yes |
| `included_route_ids` | `array[string]` | yes | `[]` | route ids | `package.py` | yes |
| `included_node_ids` | `array[string]` | yes | `[]` | node ids | `package.py` | yes |
| `included_validation_ids` | `array[string]` | yes | `[]` | validation ids | `package.py` | yes |
| `status` | `string` | yes | none | package status enum | `package.py` | yes |
| `snapshot_type` | `string` | yes | none | snapshot enum/text | `package.py` | yes |
| `snapshot_version` | `string` | yes | none | non-empty | `package.py` | yes |
| `private_dependency_flags` | `array[PrivateDependencyFlagRecord]` | yes | `[]` | private dependency list | `package.py` | yes |
| `public_gap_nodes` | `array[PublicGapNodeRecord]` | yes | `[]` | gap node list | `package.py` | yes |
| `boundary_notes` | `array[string]` | yes | `[]` | note list | `package.py` | yes |
| `traceability_refs` | `object` | yes | `{}` | trace refs JSON | `package.py` | yes |
| `replay_ready` | `boolean` | yes | none | snapshot replay flag | `package.py` | yes |
| `build_request_id` | `string` | no | `null` | request id | `package.py` | yes |
| `created_at` | `datetime-string` | no | `null` | ISO timestamp | `package.py` | yes |
| `updated_at` | `datetime-string` | no | `null` | ISO timestamp | `package.py` | yes |
| `published_at` | `datetime-string` | no | `null` | ISO timestamp | `package.py` | yes |

#### `PackageListResponse`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `items` | `array[PackageResponse]` | yes | `[]` | package list | `package.py` | yes |
| `total` | `integer` | yes | none | `>= 0` | `package.py` | yes |

#### `PackageReplayResponse`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `package_id` | `string` | yes | none | non-empty | `package.py` | yes |
| `workspace_id` | `string` | yes | none | workspace regex | `package.py` | yes |
| `snapshot` | `object` | yes | none | replay payload | `package.py` | yes |

#### `PackagePublishResultResponse`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `publish_result_id` | `string` | yes | none | non-empty | `package.py` | yes |
| `package_id` | `string` | yes | none | non-empty | `package.py` | yes |
| `workspace_id` | `string` | yes | none | workspace regex | `package.py` | yes |
| `snapshot_type` | `string` | yes | none | snapshot enum/text | `package.py` | yes |
| `snapshot_version` | `string` | yes | none | non-empty | `package.py` | yes |
| `boundary_notes` | `array[string]` | yes | `[]` | note list | `package.py` | yes |
| `snapshot_payload` | `object` | yes | none | publish payload | `package.py` | yes |
| `published_at` | `datetime-string` | yes | none | ISO timestamp | `package.py` | yes |
| `request_id` | `string` | no | `null` | request id | `package.py` | yes |

### 5.8 `retrieval.py`, `memory.py`, `observability.py`

#### `RetrievalViewRequest`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `workspace_id` | `string` | yes | none | workspace regex | `retrieval.py` | yes |
| `query` | `string` | no | `""` | free text | `retrieval.py` | yes |
| `retrieve_method` | `enum` | no | `hybrid` | `keyword/vector/hybrid/logical` | `retrieval.py` | yes |
| `top_k` | `integer` | no | `20` | `1 <= value <= 100` | `retrieval.py` | yes |
| `metadata_filters` | `object` | no | `{}` | JSON object | `retrieval.py` | yes |

#### `RetrievalResultItem`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `result_id` | `string` | yes | none | non-empty | `retrieval.py` | yes |
| `score` | `number` | yes | none | score value | `retrieval.py` | yes |
| `title` | `string` | yes | none | non-empty | `retrieval.py` | yes |
| `snippet` | `string` | yes | none | non-empty | `retrieval.py` | yes |
| `source_ref` | `object` | yes | `{}` | source refs JSON | `retrieval.py` | yes |
| `graph_refs` | `object` | yes | `{}` | graph refs JSON | `retrieval.py` | yes |
| `formal_refs` | `array` | yes | `[]` | formal object refs | `retrieval.py` | yes |
| `supporting_refs` | `object` | yes | `{}` | supporting refs JSON | `retrieval.py` | yes |
| `trace_refs` | `object` | yes | `{}` | trace refs JSON | `retrieval.py` | yes |

#### `RetrievalViewResponse`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `view_type` | `enum` | yes | none | `evidence/contradiction/failure_pattern/validation_history/hypothesis_support` | `retrieval.py` | yes |
| `workspace_id` | `string` | yes | none | workspace regex | `retrieval.py` | yes |
| `retrieve_method` | `enum` | yes | none | retrieval method enum | `retrieval.py` | yes |
| `query_ref` | `object` | yes | `{}` | query metadata | `retrieval.py` | yes |
| `metadata_filter_refs` | `object` | yes | `{}` | filter refs | `retrieval.py` | yes |
| `total` | `integer` | yes | none | `>= 0` | `retrieval.py` | yes |
| `items` | `array[RetrievalResultItem]` | yes | `[]` | retrieval results | `retrieval.py` | yes |

`logical` retrieve method additive contract:
- `query_ref.logical_subgoals[]`: role-tagged subgoals (`condition/mechanism/outcome`) with tokenized terms.
- `query_ref.logical_subgoal_count`: derived subgoal count used by retrieval traceability.
- each item `trace_refs.mutual_index`: includes `graph_to_text` and `text_to_graph` links for graph↔text mutual index replay.

#### `MemoryListRequest`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `workspace_id` | `string` | yes | none | workspace regex | `memory.py` | yes |
| `view_types` | `array[enum]` | no | all retrieval views | retrieval view enum set | `memory.py` | yes |
| `query` | `string` | no | `""` | free text | `memory.py` | yes |
| `retrieve_method` | `enum` | no | `hybrid` | retrieval method enum | `memory.py` | yes |
| `top_k_per_view` | `integer` | no | `20` | `1 <= value <= 100` | `memory.py` | yes |
| `metadata_filters_by_view` | `object` | no | `{}` | JSON object | `memory.py` | yes |

#### `MemoryListResponse`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `read_model_kind` | `string` | yes | `retrieval_backed_read_model` | fixed literal | `memory.py` | yes |
| `workspace_id` | `string` | yes | none | workspace regex | `memory.py` | yes |
| `controlled_action_semantics` | `object` | yes | `{}` | action semantics JSON | `memory.py` | yes |
| `tool_capability_refs` | `object` | yes | `{}` | selected tool-capability chain + dispatch hints | `memory.py` | yes |
| `total` | `integer` | yes | none | `>= 0` | `memory.py` | yes |
| `items` | `array[MemoryRecord]` | yes | `[]` | memory records | `memory.py` | yes |

`tool_capability_refs` contract:
- `scenario`: current orchestration scenario (`memory_assisted_reasoning`).
- `selected_chain[]`: ordered tool chain with step/category/purpose.
- `dispatch_hints[]`: operator hints and required inputs per tool step.

#### Nested Memory Models
| model | fields | source_schema | implemented |
|---|---|---|---|
| `MemoryRetrievalContext` | `view_type, retrieve_method, query_ref, metadata_filter_refs` | `memory.py` | yes |
| `MemoryRecord` | `read_model_kind, memory_id, memory_view_type, score, title, snippet, source_ref, graph_refs, formal_refs, supporting_refs, trace_refs, retrieval_context` | `memory.py` | yes |
| `MemoryValidationAction` | `validation_id, target_object, method, success_signal, weakening_signal` | `memory.py` | yes |

#### `MemoryBindToCurrentRouteRequest`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `workspace_id` | `string` | yes | none | workspace regex | `memory.py` | yes |
| `memory_id` | `string` | yes | none | non-empty | `memory.py` | yes |
| `memory_view_type` | `string` | yes | none | retrieval view enum | `memory.py` | yes |
| `note` | `string` | no | `null` | note text | `memory.py` | yes |
| `route_id` | `string` | yes | none | route id | `memory.py` | yes |

#### `MemoryBindToCurrentRouteResponse`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `action_id` | `string` | yes | none | non-empty | `memory.py` | yes |
| `action_type` | `string` | yes | none | action enum | `memory.py` | yes |
| `workspace_id` | `string` | yes | none | workspace regex | `memory.py` | yes |
| `route_id` | `string` | yes | none | route id | `memory.py` | yes |
| `memory_id` | `string` | yes | none | memory id | `memory.py` | yes |
| `memory_view_type` | `string` | yes | none | view type enum | `memory.py` | yes |
| `binding_status` | `string` | yes | none | binding status enum | `memory.py` | yes |
| `validation_action` | `MemoryValidationAction` | yes | none | validation action | `memory.py` | yes |
| `trace_refs` | `object` | yes | `{}` | trace refs | `memory.py` | yes |
| `note` | `string` | no | `null` | note text | `memory.py` | yes |
| `created_at` | `datetime-string` | yes | none | ISO timestamp | `memory.py` | yes |

#### `MemoryToHypothesisCandidateRequest`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `workspace_id` | `string` | yes | none | workspace regex | `memory.py` | yes |
| `memory_id` | `string` | yes | none | memory id | `memory.py` | yes |
| `memory_view_type` | `string` | yes | none | view type enum | `memory.py` | yes |
| `note` | `string` | no | `null` | note text | `memory.py` | yes |

#### `MemoryToHypothesisCandidateResponse`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `action_id` | `string` | yes | none | non-empty | `memory.py` | yes |
| `action_type` | `string` | yes | none | action enum | `memory.py` | yes |
| `workspace_id` | `string` | yes | none | workspace regex | `memory.py` | yes |
| `memory_id` | `string` | yes | none | memory id | `memory.py` | yes |
| `memory_view_type` | `string` | yes | none | view type enum | `memory.py` | yes |
| `hypothesis` | `HypothesisResponse` | yes | none | embedded candidate hypothesis | `memory.py` | yes |
| `trace_refs` | `object` | yes | `{}` | trace refs | `memory.py` | yes |
| `note` | `string` | no | `null` | note text | `memory.py` | yes |
| `created_at` | `datetime-string` | yes | none | ISO timestamp | `memory.py` | yes |

#### `ExecutionTimelineEvent`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `event_name` | `string` | yes | none | non-empty | `observability.py` | yes |
| `timestamp` | `datetime-string` | no | `null` | ISO timestamp | `observability.py` | yes |
| `request_id` | `string` | no | `null` | request id | `observability.py` | yes |
| `job_id` | `string` | no | `null` | job id | `observability.py` | yes |
| `workspace_id` | `string` | no | `null` | workspace regex | `observability.py` | yes |
| `source_id` | `string` | no | `null` | source id | `observability.py` | yes |
| `candidate_batch_id` | `string` | no | `null` | batch id | `observability.py` | yes |
| `component` | `string` | yes | none | emitting component | `observability.py` | yes |
| `step` | `string` | no | `null` | sub-step | `observability.py` | yes |
| `status` | `string` | yes | none | event status | `observability.py` | yes |
| `refs` | `object` | yes | `{}` | structured refs | `observability.py` | yes |
| `metrics` | `object` | yes | `{}` | metrics JSON | `observability.py` | yes |
| `error` | `object` | no | `null` | error payload | `observability.py` | yes |

#### `ExecutionSummaryResponse`
| field | type | required | default | constraints | source_schema | implemented |
|---|---|---|---|---|---|---|
| `workspace_id` | `string` | yes | none | workspace regex | `observability.py` | yes |
| `request_id` | `string` | no | `null` | request id | `observability.py` | yes |
| `job_id` | `string` | no | `null` | job id | `observability.py` | yes |
| `timeline` | `array[ExecutionTimelineEvent]` | yes | `[]` | timeline events | `observability.py` | yes |
| `business_objects` | `ExecutionBusinessObjects` | yes | none | touched objects summary | `observability.py` | yes |
| `final_outcome` | `ExecutionFinalOutcome` | yes | none | final execution outcome | `observability.py` | yes |

#### Nested Execution Summary Models
| model | fields | source_schema | implemented |
|---|---|---|---|
| `ExecutionBusinessObjects` | `source_ids, route_ids, version_ids, hypothesis_ids, package_ids, failure_ids, candidate_batch_ids, request_ids, job_ids` | `observability.py` | yes |
| `ExecutionFinalOutcome` | `status, last_event, last_status, completed_event_count, failed_event_count, result_refs` | `observability.py` | yes |

## 6. Endpoint Contracts

### 6.1 ResearchSourceController
| method | path | current_handler | evermemos_target_path | status | request_schema | response_schema | error_families | side_effects | async_contract |
|---|---|---|---|---|---|---|---|---|---|
| `POST` | `/api/v1/research/sources/import` | `import_source` | `src/research_layer/api/controllers/research_source_controller.py` | `existing` | `SourceImportRequest` | `SourceResponse` | shared request, source import parse/fetch errors, client disconnected | creates source, emits import events and import observability metrics | none |
| `POST` | `/api/v1/research/sources/{source_id}/extract` | `extract_source` | `src/research_layer/api/controllers/research_source_controller.py` | `existing` | `SourceExtractRequest` | `AsyncJobAcceptedResponse` | LLM/provider, shared request | creates extraction job and returns before terminal result; outcome resolved via job polling | job status via `/jobs/{job_id}` and extraction result ref |
| `GET` | `/api/v1/research/sources` | `list_sources` | `src/research_layer/api/controllers/research_source_controller.py` | `existing` | `query(workspace_id?)` | `SourceListResponse` | shared request | none | none |
| `GET` | `/api/v1/research/sources/{source_id}` | `get_source` | `src/research_layer/api/controllers/research_source_controller.py` | `existing` | `path(source_id)` | `SourceResponse` | shared request | none | none |
| `GET` | `/api/v1/research/sources/{source_id}/extraction-results/{candidate_batch_id}` | `get_extraction_result` | `src/research_layer/api/controllers/research_source_controller.py` | `existing` | `path(source_id,candidate_batch_id) + query(workspace_id?)` | `ExtractionResultResponse` | shared request | none | returns async batch outcome |
| `GET` | `/api/v1/research/candidates` | `list_candidates` | `src/research_layer/api/controllers/research_source_controller.py` | `existing` | `query(workspace_id?, source_id?, candidate_type?, status?)` | `CandidateListResponse` | shared request | none | none |
| `GET` | `/api/v1/research/candidates/{candidate_id}` | `get_candidate_detail` | `src/research_layer/api/controllers/research_source_controller.py` | `existing` | `path(candidate_id) + query(workspace_id?)` | `CandidateDetailResponse` | shared request | none | none |
| `POST` | `/api/v1/research/candidates/confirm` | `confirm_candidates` | `src/research_layer/api/controllers/research_source_controller.py` | `existing` | `CandidateConfirmRequest` | `CandidateActionResponse` | shared request, invalid state, conflict | candidate -> confirmed, formal object materialization, graph eligibility | none |
| `POST` | `/api/v1/research/candidates/reject` | `reject_candidates` | `src/research_layer/api/controllers/research_source_controller.py` | `existing` | `CandidateRejectRequest` | `CandidateActionResponse` | shared request, invalid state | terminal reject state update | none |
| `GET` | `/api/v1/research/executions/summary` | `get_execution_summary` | `src/research_layer/api/controllers/research_source_controller.py` | `existing` | `query(workspace_id?, request_id?, job_id?, limit=500)` | `ExecutionSummaryResponse` | shared request | read-only execution timeline | none |
| `GET` | `/api/v1/research/dev-console` | `research_dev_console` | `src/research_layer/api/controllers/research_source_controller.py` | `existing` | none | `text/html` | n/a | dev-only HTML console | none |

#### 6.1.1 Existing request parameter contracts

##### `POST /api/v1/research/sources/import`
| name | location | type | required | default | constraints | source_schema_or_handler | status |
|---|---|---|---|---|---|---|---|
| `X-Request-Id` | `header` | `string` | no | autogenerated UUID | non-empty when provided; used for client/server correlation and execution summary retrieval | `research_source_controller.import_source` + `app_logic_provider.setup_app_context` | `existing` |
| `workspace_id` | `body` | `string` | yes | none | workspace regex | `SourceImportRequest` | `existing` |
| `source_input_mode` | `body` | `enum(auto/manual_text/url/local_file)` | yes | `auto` | mode controls payload interpretation; local_file imports are expected to use extended client timeout budget | `SourceImportRequest` + `source_import_service` | `existing` |

##### `GET /api/v1/research/sources`
| name | location | type | required | default | constraints | source_schema_or_handler | status |
|---|---|---|---|---|---|---|---|
| `workspace_id` | `query` | `string` | no | `null` | workspace regex when present | `research_source_controller.list_sources` | `existing` |

##### `GET /api/v1/research/candidates`
| name | location | type | required | default | constraints | source_schema_or_handler | status |
|---|---|---|---|---|---|---|---|
| `workspace_id` | `query` | `string` | no | `null` | workspace regex when present | `research_source_controller.list_candidates` | `existing` |
| `source_id` | `query` | `string` | no | `null` | non-empty when present | `research_source_controller.list_candidates` | `existing` |
| `candidate_type` | `query` | `string` | no | `null` | member of `CANDIDATE_TYPE_VALUES` when present | `research_source_controller.list_candidates` | `existing` |
| `status` | `query` | `string` | no | `null` | member of candidate status enum when present | `research_source_controller.list_candidates` | `existing` |

##### `GET /api/v1/research/candidates/{candidate_id}`
| name | location | type | required | default | constraints | source_schema_or_handler | status |
|---|---|---|---|---|---|---|---|
| `candidate_id` | `path` | `string` | yes | none | non-empty | `research_source_controller.get_candidate_detail` | `existing` |
| `workspace_id` | `query` | `string` | no | `null` | workspace regex when present; conflict if ownership mismatches | `research_source_controller.get_candidate_detail` | `existing` |

##### `GET /api/v1/research/executions/summary`
| name | location | type | required | default | constraints | source_schema_or_handler | status |
|---|---|---|---|---|---|---|---|
| `workspace_id` | `query` | `string` | no | `null` | workspace regex when present | `research_source_controller.get_execution_summary` | `existing` |
| `request_id` | `query` | `string` | no | `null` | trimmed non-empty when present | `research_source_controller.get_execution_summary` | `existing` |
| `job_id` | `query` | `string` | no | `null` | trimmed non-empty when present | `research_source_controller.get_execution_summary` | `existing` |
| `limit` | `query` | `integer` | no | `500` | `1 <= limit <= 5000` | `research_source_controller.get_execution_summary` | `existing` |

### 6.2 ResearchGraphController
| method | path | current_handler | evermemos_target_path | status | request_schema | response_schema | error_families | side_effects | async_contract |
|---|---|---|---|---|---|---|---|---|---|
| `POST` | `/api/v1/research/graph/{workspace_id}/build` | `build_graph` | `src/research_layer/api/controllers/research_graph_controller.py` | `existing` | path `workspace_id` | `GraphBuildResponse` | shared request, conflict | formal objects -> graph projection + version update | none |
| `GET` | `/api/v1/research/graph/{workspace_id}` | `get_graph` | `src/research_layer/api/controllers/research_graph_controller.py` | `existing` | path `workspace_id` | `GraphResponse` | authz/visibility, shared request | none | none |
| `POST` | `/api/v1/research/graph/{workspace_id}/query` | `query_graph` | `src/research_layer/api/controllers/research_graph_controller.py` | `existing` | `GraphQueryRequest` + path `workspace_id` | `GraphResponse` | authz/visibility, shared request | read-only graph query | none |
| `GET` | `/api/v1/research/graph/{workspace_id}/workspace` | `get_graph_workspace` | `src/research_layer/api/controllers/research_graph_controller.py` | `existing` | path `workspace_id` | `GraphWorkspaceResponse` | authz/visibility, shared request | none | none |
| `POST` | `/api/v1/research/graph/nodes` | `create_graph_node` | `src/research_layer/api/controllers/research_graph_controller.py` | `existing` | `GraphNodeCreateRequest` | `GraphNodeResponse` | shared request, authz/visibility | projection node create | none |
| `PATCH` | `/api/v1/research/graph/nodes/{node_id}` | `patch_graph_node` | `src/research_layer/api/controllers/research_graph_controller.py` | `existing` | `GraphNodePatchRequest` + path `node_id` | `GraphNodeResponse` | authz/visibility, invalid state | limited patch/update | none |
| `DELETE` | `/api/v1/research/graph/nodes/{node_id}` | `archive_graph_node` | `src/research_layer/api/controllers/research_graph_controller.py` | `existing` | `GraphArchiveRequest` + path `node_id` | `GraphArchiveResponse` | authz/visibility, invalid state | archive node + version diff | none |
| `POST` | `/api/v1/research/graph/edges` | `create_graph_edge` | `src/research_layer/api/controllers/research_graph_controller.py` | `existing` | `GraphEdgeCreateRequest` | `GraphEdgeResponse` | shared request, authz/visibility | projection edge create | none |
| `PATCH` | `/api/v1/research/graph/edges/{edge_id}` | `patch_graph_edge` | `src/research_layer/api/controllers/research_graph_controller.py` | `existing` | `GraphEdgePatchRequest` + path `edge_id` | `GraphEdgeResponse` | authz/visibility, invalid state | limited patch/update | none |
| `DELETE` | `/api/v1/research/graph/edges/{edge_id}` | `archive_graph_edge` | `src/research_layer/api/controllers/research_graph_controller.py` | `existing` | `GraphArchiveRequest` + path `edge_id` | `GraphArchiveResponse` | authz/visibility, invalid state | archive edge + version diff | none |
| `GET` | `/api/v1/research/versions` | `list_versions` | `src/research_layer/api/controllers/research_graph_controller.py` | `existing` | `query(workspace_id?)` | `GraphVersionListResponse` | shared request | read-only version list | none |
| `GET` | `/api/v1/research/versions/{version_id}/diff` | `get_version_diff` | `src/research_layer/api/controllers/research_graph_controller.py` | `existing` | `path(version_id)` | `GraphVersionDiffResponse` | failure/recompute, shared request | read-only version diff | none |

#### 6.2.1 Existing request parameter contracts

##### `GET /api/v1/research/versions`
| name | location | type | required | default | constraints | source_schema_or_handler | status |
|---|---|---|---|---|---|---|---|
| `workspace_id` | `query` | `string` | no | `null` | workspace regex when present | `research_graph_controller.list_versions` | `existing` |

##### `GET /api/v1/research/versions/{version_id}/diff`
| name | location | type | required | default | constraints | source_schema_or_handler | status |
|---|---|---|---|---|---|---|---|
| `version_id` | `path` | `string` | yes | none | non-empty | `research_graph_controller.get_version_diff` | `existing` |

### 6.3 ResearchRouteController
| method | path | current_handler | evermemos_target_path | status | request_schema | response_schema | error_families | side_effects | async_contract |
|---|---|---|---|---|---|---|---|---|---|
| `GET` | `/api/v1/research/routes` | `list_routes` | `src/research_layer/api/controllers/research_route_controller.py` | `existing` | query params (`workspace_id`) | `RouteListResponse` | shared request | none | none |
| `GET` | `/api/v1/research/routes/{route_id}` | `get_route` | `src/research_layer/api/controllers/research_route_controller.py` | `existing` | path `route_id` + query `workspace_id` | `RouteRecord` | shared request | none | none |
| `GET` | `/api/v1/research/routes/{route_id}/preview` | `preview_route` | `src/research_layer/api/controllers/research_route_controller.py` | `existing` | path `route_id` + query `workspace_id` | `RoutePreviewResponse` | shared request | may backfill preview summary only if route spec allows | none |
| `POST` | `/api/v1/research/routes/generate` | `generate_routes` | `src/research_layer/api/controllers/research_route_controller.py` | `existing` | `RouteGenerateRequest` | `RouteGenerateResponse` | shared request, failure/recompute | graph snapshot -> ranked route persistence | none |
| `POST` | `/api/v1/research/routes/{route_id}/score` | `score_route` | `src/research_layer/api/controllers/research_route_controller.py` | `existing` | `RouteScoreRequest` + path `route_id` | `RouteScoreResponse` | shared request | rescoring and route update | none |
| `POST` | `/api/v1/research/routes/recompute` | `recompute_routes` | `src/research_layer/api/controllers/research_route_controller.py` | `existing` | `RouteRecomputeRequest` | `AsyncJobAcceptedResponse` | failure/recompute | starts recompute flow and returns queued/running job contract | job status via `/jobs/{job_id}` |

#### 6.3.1 Existing request parameter contracts

##### `GET /api/v1/research/routes/{route_id}`
| name | location | type | required | default | constraints | source_schema_or_handler | status |
|---|---|---|---|---|---|---|---|
| `route_id` | `path` | `string` | yes | none | non-empty | `research_route_controller.get_route` | `existing` |
| `workspace_id` | `query` | `string` | yes | none | workspace regex; must match route ownership or return `research.conflict` | `research_route_controller.get_route` | `existing` |

##### `GET /api/v1/research/routes/{route_id}/preview`
| name | location | type | required | default | constraints | source_schema_or_handler | status |
|---|---|---|---|---|---|---|---|
| `route_id` | `path` | `string` | yes | none | non-empty | `research_route_controller.preview_route` | `existing` |
| `workspace_id` | `query` | `string` | yes | none | workspace regex; must match route ownership or return `research.conflict` | `research_route_controller.preview_route` | `existing` |

### 6.4 ResearchFailureController
| method | path | current_handler | evermemos_target_path | status | request_schema | response_schema | error_families | side_effects | async_contract |
|---|---|---|---|---|---|---|---|---|---|
| `POST` | `/api/v1/research/failures` | `create_failure` | `src/research_layer/api/controllers/research_failure_controller.py` | `existing` | `FailureCreateRequest` | `FailureResponse` | failure/recompute, shared request | failure persisted, may trigger recompute downstream | none |
| `POST` | `/api/v1/research/validations` | `create_validation` | `src/research_layer/api/controllers/research_failure_controller.py` | `existing` | `ValidationCreateRequest` | `ValidationResponse` | shared request | validation action persisted | none |
| `POST` | `/api/v1/research/validations/{validation_id}/results` | `submit_validation_result` | `src/research_layer/api/controllers/research_failure_controller.py` | `existing` | `ValidationResultSubmitRequest` + path `validation_id` | `ValidationResultResponse` | failure/recompute, shared request | persists validation result before recompute execution; weakened/failed outcomes keep existing semantics and create a derived failure + recompute job, and the response now includes an inline `triggered_failure` snapshot for provenance | recompute job status via `/jobs/{job_id}` |
| `GET` | `/api/v1/research/failures/{failure_id}` | `get_failure` | `src/research_layer/api/controllers/research_failure_controller.py` | `existing` | `path(failure_id)` | `FailureResponse` | shared request | returns latest persisted impact snapshot fields (`impact_summary`, `impact_updated_at`) and validation provenance fields when present | none |

#### 6.4.1 Existing request parameter contracts

##### `GET /api/v1/research/failures/{failure_id}`
| name | location | type | required | default | constraints | source_schema_or_handler | status |
|---|---|---|---|---|---|---|---|
| `failure_id` | `path` | `string` | yes | none | non-empty | `research_failure_controller.get_failure` | `existing` |

### 6.5 ResearchHypothesisController
| method | path | current_handler | evermemos_target_path | status | request_schema | response_schema | error_families | side_effects | async_contract |
|---|---|---|---|---|---|---|---|---|---|
| `GET` | `/api/v1/research/hypotheses/triggers/list` | `list_hypothesis_triggers` | `src/research_layer/api/controllers/research_hypothesis_controller.py` | `existing` | query params (`workspace_id`) | `HypothesisTriggerListResponse` | shared request | none | none |
| `GET` | `/api/v1/research/hypotheses` | `list_hypotheses` | `src/research_layer/api/controllers/research_hypothesis_controller.py` | `existing` | query params (`workspace_id`) | `HypothesisListResponse` | shared request | none | none |
| `POST` | `/api/v1/research/hypotheses/generate` | `generate_hypothesis` | `src/research_layer/api/controllers/research_hypothesis_controller.py` | `existing` | `HypothesisGenerateRequest` | `AsyncJobAcceptedResponse` | LLM/provider, shared request | starts current single-shot hypothesis generation flow and returns queued/running job contract; planned target is multi-agent candidate-pool orchestration under the same controller boundary | job status via `/jobs/{job_id}` |
| `GET` | `/api/v1/research/hypotheses/{hypothesis_id}` | `get_hypothesis` | `src/research_layer/api/controllers/research_hypothesis_controller.py` | `existing` | `path(hypothesis_id)` | `HypothesisResponse` | shared request | none | none |
| `POST` | `/api/v1/research/hypotheses/{hypothesis_id}/promote` | `promote_hypothesis` | `src/research_layer/api/controllers/research_hypothesis_controller.py` | `existing` | `HypothesisDecisionRequest` + path `hypothesis_id` | `HypothesisResponse` | shared request, invalid state | status/stage transition | none |
| `POST` | `/api/v1/research/hypotheses/{hypothesis_id}/reject` | `reject_hypothesis` | `src/research_layer/api/controllers/research_hypothesis_controller.py` | `existing` | `HypothesisDecisionRequest` + path `hypothesis_id` | `HypothesisResponse` | shared request, invalid state | terminal decision transition | none |
| `POST` | `/api/v1/research/hypotheses/{hypothesis_id}/defer` | `defer_hypothesis` | `src/research_layer/api/controllers/research_hypothesis_controller.py` | `existing` | `HypothesisDecisionRequest` + path `hypothesis_id` | `HypothesisResponse` | shared request, invalid state | defer decision transition | none |

#### 6.5.1 Existing request parameter contracts

##### `GET /api/v1/research/hypotheses/{hypothesis_id}`
| name | location | type | required | default | constraints | source_schema_or_handler | status |
|---|---|---|---|---|---|---|---|
| `hypothesis_id` | `path` | `string` | yes | none | non-empty | `research_hypothesis_controller.get_hypothesis` | `existing` |

### 6.6 ResearchPackageController
| method | path | current_handler | evermemos_target_path | status | request_schema | response_schema | error_families | side_effects | async_contract |
|---|---|---|---|---|---|---|---|---|---|
| `POST` | `/api/v1/research/packages` | `create_package` | `src/research_layer/api/controllers/research_package_controller.py` | `existing` | `PackageCreateRequest` | `PackageResponse` | shared request, authz/visibility | package snapshot create | none |
| `GET` | `/api/v1/research/packages` | `list_packages` | `src/research_layer/api/controllers/research_package_controller.py` | `existing` | query params (`workspace_id`) | `PackageListResponse` | authz/visibility, shared request | none | none |
| `GET` | `/api/v1/research/packages/{package_id}` | `get_package` | `src/research_layer/api/controllers/research_package_controller.py` | `existing` | path `package_id` + query `workspace_id` | `PackageResponse` | authz/visibility, shared request | none | none |
| `GET` | `/api/v1/research/packages/{package_id}/replay` | `replay_package` | `src/research_layer/api/controllers/research_package_controller.py` | `existing` | path `package_id` + query `workspace_id` | `PackageReplayResponse` | authz/visibility, shared request | read-only replay | none |
| `POST` | `/api/v1/research/packages/{package_id}/publish` | `publish_package` | `src/research_layer/api/controllers/research_package_controller.py` | `existing` | `PackagePublishRequest` + path `package_id` | `AsyncJobAcceptedResponse` | package/publish, authz/visibility | starts package publish flow and returns queued/running job contract | canonical polling/result retrieval via `/jobs/{job_id}` and `/packages/{package_id}/publish-results/{publish_result_id}` |
| `GET` | `/api/v1/research/packages/{package_id}/publish-results/{publish_result_id}` | `get_publish_result` | `src/research_layer/api/controllers/research_package_controller.py` | `existing` | path params + query `workspace_id` | `PackagePublishResultResponse` | package/publish, shared request | read-only publish result | none |

### 6.7 ResearchRetrievalController
| method | path | current_handler | evermemos_target_path | status | request_schema | response_schema | error_families | side_effects | async_contract |
|---|---|---|---|---|---|---|---|---|---|
| `POST` | `/api/v1/research/retrieval/views/{view_type}` | `retrieve_view` | `src/research_layer/api/controllers/research_retrieval_controller.py` | `existing` | `RetrievalViewRequest` + path `view_type` | `RetrievalViewResponse` | authz/visibility, shared request | none | none |
| `POST` | `/api/v1/research/memory/list` | `list_memory` | `src/research_layer/api/controllers/research_retrieval_controller.py` | `existing` | `MemoryListRequest` | `MemoryListResponse` | authz/visibility, shared request | none | none |
| `POST` | `/api/v1/research/memory/actions/bind-to-current-route` | `bind_memory_to_current_route` | `src/research_layer/api/controllers/research_retrieval_controller.py` | `existing` | `MemoryBindToCurrentRouteRequest` | `MemoryBindToCurrentRouteResponse` | shared request, invalid state | creates memory action and optional validation ref | none |
| `POST` | `/api/v1/research/memory/actions/memory-to-hypothesis-candidate` | `memory_to_hypothesis_candidate` | `src/research_layer/api/controllers/research_retrieval_controller.py` | `existing` | `MemoryToHypothesisCandidateRequest` | `MemoryToHypothesisCandidateResponse` | shared request, invalid state | creates memory action and hypothesis candidate | none |

### 6.8 ResearchJobController
| method | path | current_handler | evermemos_target_path | status | request_schema | response_schema | error_families | side_effects | async_contract |
|---|---|---|---|---|---|---|---|---|---|
| `GET` | `/api/v1/research/jobs/{job_id}` | `get_job_status` | `src/research_layer/api/controllers/research_job_controller.py` | `existing` | `path(job_id)` | `JobStatusResponse` | shared request | read-only async job status | canonical async polling endpoint |

#### 6.8.1 Existing request parameter contracts

##### `GET /api/v1/research/jobs/{job_id}`
| name | location | type | required | default | constraints | source_schema_or_handler | status |
|---|---|---|---|---|---|---|---|
| `job_id` | `path` | `string` | yes | none | non-empty | `research_job_controller.get_job_status` | `existing` |

## 7. Planned Additions
The following remain non-canonical until explicitly mapped and implemented:
- dedicated workspace bootstrap controller boundary
- dedicated scholarly/evidence controller boundary
- graph action split controllers
- multi-agent hypothesis pool/tournament/search-tree actions under the existing `ResearchHypothesisController` boundary
- reasoning-subgraph-specific route generation actions under the existing `ResearchRouteController` boundary

These may only appear as `planned` entries in `WIRING_TARGET_MAP.md`.

## 8. Error Reference Rule
- `API_SPEC.md` references `ERROR_INVENTORY.md` for all error families.
- Existing endpoints above are the only endpoints expanded to full field-level schema in this version.
- Any new existing endpoint must update both the endpoint matrix and the schema catalog in the same change.

## 9. Unified Contract Sync (2026-04-08)

This section freezes the API-facing baseline for five contract families:
`ingest`, `provenance`, `confidence explanation`, `validation`, `package publish`.

### 9.1 Ingest Contract (existing)
Minimum API-visible fields for ingest/extract flows:
1. `workspace_id`
2. `source_type`
3. `source_input_mode`
4. `request_id` (header derived and persisted)
5. `job_id/status/status_url` for async extract

Failure requirement:
1. parse/import/extract failures must be explicit envelopes (`error_code/message/details`).

### 9.2 Provenance Contract (existing + planned)
Existing API baseline:
1. `source_id`
2. `candidate_id` (or equivalent intermediate object id)
3. `candidate_batch_id`
4. `job_id` (for async-originated artifacts)
5. `trace_refs`-style linkage in retrieval/hypothesis surfaces

Planned-only (not existing):
1. `claim_ref` / span-level provenance fields are optional future additions and must remain `planned` until runtime support lands.
2. multi-agent hypothesis lineage fields such as `hypothesis_pool_id`, `candidate_id`, `round_id`, `match_id`, `search_tree_node_id`, and `reasoning_chain_id` are optional future additions and must remain `planned` until runtime support lands.

### 9.3 Confidence Explanation Contract (existing baseline)
Route/detail/package-facing explanation fields must remain program-controlled:
1. `confidence_score`
2. `confidence_grade`
3. `top_factors`
4. `score_breakdown`
5. `main penalties` equivalent in structured factors
6. `next_validation_action` linkage when required by flow

Rule:
1. LLM may provide semantic hints only; ranking/score/state is deterministic program output.

### 9.4 Validation Contract (existing baseline, stronger gate semantics required)
Baseline objects:
1. `ValidationAction`
2. `validation_result`
3. hypothesis/package linkage to validation artifacts

Gate rule:
1. Any route/hypothesis/package transition that requires validation must either provide validation evidence or return explicit rejection.
2. `submit_validation_result(outcome=failed)` remains an append-only validation outcome plus derived failure creation flow; clients must not reinterpret it as an in-place failure mutation.
3. When validation feedback creates a derived failure, API responses must preserve linkage through `triggered_failure_id` and failure provenance fields so the frontend can explain why an extra failure record appeared.

### 9.5 Package Publish Contract (existing baseline)
Publish API invariants:
1. publish starts from persisted package snapshot
2. publish endpoint returns async accepted contract
3. terminal result retrieved by job polling + publish result endpoint
4. boundary/gap notes are explicit payload fields, not implicit text-only summaries

### 9.6 Planned Additions (must remain planned)
1. dedicated asset writeback endpoints for Q&A artifacts
2. claim/span-level provenance mutation/query endpoints
3. git-semantic branch/merge endpoints
4. multi-agent hypothesis pool/tournament/search-tree endpoints
5. weakest-step and mechanism-revision inspection endpoints

## 10. Six Capability Additions (existing, feature-flagged)

These endpoints are implemented as derived/query/export/orchestration surfaces only.
They must not mutate canonical truth except through existing source/candidate/graph/route/hypothesis/package services.
Each endpoint is independently feature-flagged and disabled by default.

| method | path | current_handler | status | request_schema | response_schema | feature_flag | side_effects |
|---|---|---|---|---|---|---|---|
| `GET` | `/api/v1/research/graph/{workspace_id}/report` | `ResearchGraphController.get_graph_report` | `existing` | path `workspace_id` | `GraphReportResponse` | `RESEARCH_FEATURE_GRAPH_REPORT_ENABLED` | emits report event only |
| `GET` | `/api/v1/research/query/tools` | `ResearchQueryController.list_query_tools` | `existing` | none | `QueryToolsResponse` | `RESEARCH_FEATURE_QUERY_API_ENABLED` | none |
| `POST` | `/api/v1/research/query/run` | `ResearchQueryController.run_query_tool` | `existing` | `QueryRunRequest` | `QueryRunResponse` | `RESEARCH_FEATURE_QUERY_API_ENABLED` | emits query event only |
| `POST` | `/api/v1/research/sources/bootstrap` | `ResearchSourceController.bootstrap_sources` | `existing` | `SourceBootstrapRequest` | `SourceBootstrapResponse` | `RESEARCH_FEATURE_RAW_BOOTSTRAP_ENABLED` | creates raw sources, pending candidates, optional extract job refs |
| `POST` | `/api/v1/research/commands/run` | `ResearchCommandController.run_commands` | `existing` | `ResearchCommandRunRequest` | `ResearchCommandRunResponse` | `RESEARCH_FEATURE_COMMANDS_ENABLED` | orchestrates existing commands only |
| `GET` | `/api/v1/research/graph/{workspace_id}/export` | `ResearchGraphController.export_graph` | `existing` | path `workspace_id` + query `format` | `ResearchExportResponse` | `RESEARCH_FEATURE_EXPORT_ENABLED` | emits success/failed export events |
| `GET` | `/api/v1/research/packages/{package_id}/export` | `ResearchPackageController.export_package` | `existing` | path `package_id` + required query `workspace_id`, `format` | `ResearchExportResponse` | `RESEARCH_FEATURE_EXPORT_ENABLED` | enforces ownership + emits success/failed export events |

Rules:
1. `query/run` tool whitelist is fixed to `graph`, `query`, `route`, `hypothesis`, `package`, `version-diff`, `report`.
2. `sources/bootstrap` leaves candidates in `pending`; it must not confirm candidates or build graph automatically.
3. `commands/run` supports only `ingest`, `confirm`, `build_graph`, `generate_routes`, `validate`, `package`; each command delegates to existing services.
4. `export` supports `json` and `markdown` only and must omit raw/private/unconfirmed prompt-response material from public payloads.
5. `packages/{package_id}/export` requires `workspace_id`; missing or mismatch must be explicit envelope errors.
6. Graph export must drop edges connected to non-exportable/private nodes.
7. Package export must sanitize `traceability_refs` and remove private dependency/replacement/prompt/raw fields.
8. Disabled feature responses use the existing `research.forbidden` envelope with `details.feature_flag`.
