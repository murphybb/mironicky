# STORAGE_SCHEMA.md — Mironicky Storage Truth

## 1. Purpose
This document is the active storage truth for Mironicky persistence in the real backend repo.

It freezes:
- logical storage object names
- physical persisted names
- current store/repository mapping
- column-level contract for existing tables
- index, unique, and check-constraint state
- planned table inventory and invariant sources

## 2. Ownership

### Owned Scope
- `logical_name`
- `physical_name`
- `current_store_name`
- `storage_backend`
- `evermemos_target_path`
- `columns`
- `primary_key`
- `unique_constraints`
- `indexes`
- `check_constraints`
- `json_encoded_fields`
- `current_state`
- `target_state`
- `status(existing/planned/blocked)`

### Out of Scope
- business behavior rules
- route ranking or confidence formulas
- RBAC semantics beyond persisted field existence
- provider runtime behavior

### Conflict Resolution
1. Physical names and storage mapping come from this document.
2. Object vocabulary comes from `DOMAIN_MODEL.md`.
3. API shape comes from `API_SPEC.md`.
4. If code and documentation differ, current code shape must be recorded in `current_state`; intended migration belongs in `target_state`.
5. An existing persisted record for a transitional API/store object does not, by itself, upgrade the corresponding canonical domain object from `planned` to `existing`.
6. Job persistence records current behavior even when some async envelopes are fulfilled by transitional sync execution paths; this does not redefine target async semantics.
7. `memory_actions` is a research read-model action log and must not be interpreted as the native EverMemOS memory repository.
8. Claim-level lineage/provenance expansion remains a future migration topic; planned fields must not be fabricated as existing columns.

## 3. Storage Backends and Targets

| backend | target |
|---|---|
| `SQLite` | `src/research_layer/api/controllers/_state_store.py` |
| graph repository helper | `src/research_layer/graph/repository.py` |

## 4. Existing Table Inventory

| logical_name | physical_name | current_store_name | storage_backend | evermemos_target_path | status |
|---|---|---|---|---|---|
| `ResearchSourceRecord` | `sources` | `sources` | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `existing` |
| `CandidateRecord` | `candidates` | `candidates` | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `existing` |
| `ExtractionResultRecord` | `extraction_results` | `extraction_results` | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `existing` |
| `RouteRecord` | `routes` | `routes` | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `existing` |
| `GraphNodeRecord` | `graph_nodes` | `graph_nodes` | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `existing` |
| `GraphEdgeRecord` | `graph_edges` | `graph_edges` | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `existing` |
| `GraphVersionRecord` | `graph_versions` | `graph_versions` | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `existing` |
| `GraphWorkspaceRecord` | `graph_workspaces` | `graph_workspaces` | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `existing` |
| `ResearchEvidenceRecord` | `research_evidences` | `research_evidences` | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `existing` |
| `ResearchAssumptionRecord` | `research_assumptions` | `research_assumptions` | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `existing` |
| `ResearchConflictRecord` | `research_conflicts` | `research_conflicts` | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `existing` |
| `ResearchFailureRecord` | `research_failures` | `research_failures` | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `existing` |
| `ResearchValidationRecord` | `research_validations` | `research_validations` | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `existing` |
| `FailureRecordLegacy` | `failures` | `failures` | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `existing` |
| `ValidationRecordLegacy` | `validations` | `validations` | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `existing` |
| `MemoryActionRecord` | `memory_actions` | `memory_actions` | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `existing` |
| `HypothesisRecord` | `hypotheses` | `hypotheses` | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `existing` |
| `PackageRecord` | `packages` | `packages` | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `existing` |
| `PackagePublishResultRecord` | `package_publish_results` | `package_publish_results` | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `existing` |
| `ResearchJobRecord` | `jobs` | `jobs` | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `existing` |
| `ResearchEventRecord` | `research_events` | `research_events` | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `existing` |

## 5. Existing Table Details

### 5.1 `sources`
- `logical_name`: `ResearchSourceRecord`
- `owner_spec`: `DOMAIN_MODEL.md`, `API_SPEC.md`
- `current_state`: persisted with additive column backfills via `_ensure_column`
- `target_state`: keep as canonical source import table; add explicit indexes later if query pressure requires

**columns**
| column | type | nullability | current_state | notes |
|---|---|---|---|---|
| `source_id` | `TEXT` | not null | existing | primary key |
| `workspace_id` | `TEXT` | not null | existing | workspace scope |
| `source_type` | `TEXT` | not null | existing | source enum |
| `title` | `TEXT` | not null | existing | title text |
| `content` | `TEXT` | not null | existing | raw content |
| `normalized_content` | `TEXT` | nullable | existing | normalized text |
| `status` | `TEXT` | not null | existing | source lifecycle |
| `metadata_json` | `TEXT` | not null | existing | JSON-encoded metadata |
| `import_request_id` | `TEXT` | nullable | existing | request correlation |
| `last_extract_job_id` | `TEXT` | nullable | existing | latest extraction job |
| `created_at` | `TEXT` | not null | existing | ISO timestamp |
| `updated_at` | `TEXT` | not null | existing | ISO timestamp |

- `primary_key`: `source_id`
- `unique_constraints`: none explicit beyond PK
- `indexes`:
  - `current_state`: implicit PK index only
  - `target_state`: recommend `(workspace_id, created_at)`
- `check_constraints`:
  - `current_state`: none explicit
  - `target_state`: recommended source type / status enum checks
- `json_encoded_fields`: `metadata_json -> SourceResponse.metadata`

### 5.2 `candidates`
- `logical_name`: `CandidateRecord`
- `owner_spec`: `LLM_REMEDIATION_PLAN_REVISED.md`, `API_SPEC.md`
- `current_state`: pending/confirmed/rejected candidate persistence only
- `target_state`: may later expand richer candidate payload, but current table remains canonical existing shape
- `canonical_domain_note`: this table persists the existing transitional API/store representation `CandidateRecord`. It must not be read as proof that the planned canonical domain object `Candidate` already exists in `src/research_layer/domain/models/research_domain.py`.

**columns**
| column | type | nullability | current_state | notes |
|---|---|---|---|---|
| `candidate_id` | `TEXT` | not null | existing | primary key |
| `workspace_id` | `TEXT` | not null | existing | workspace scope |
| `source_id` | `TEXT` | not null | existing | owning source |
| `candidate_type` | `TEXT` | not null | existing | candidate enum |
| `text` | `TEXT` | not null | existing | candidate body |
| `status` | `TEXT` | not null | existing | pending/confirmed/rejected |
| `source_span_json` | `TEXT` | not null | existing | JSON span |
| `candidate_batch_id` | `TEXT` | nullable | existing | extraction batch |
| `extraction_job_id` | `TEXT` | nullable | existing | extraction job |
| `extractor_name` | `TEXT` | nullable | existing | extractor trace |
| `reject_reason` | `TEXT` | nullable | existing | reject reason |

- `primary_key`: `candidate_id`
- `unique_constraints`: none explicit beyond PK
- `indexes`:
  - `current_state`: implicit PK index only
  - `target_state`: recommend `(workspace_id, status)`, `(source_id, candidate_batch_id)`
- `check_constraints`:
  - `current_state`: none explicit
  - `target_state`: candidate type/status enum checks
- `json_encoded_fields`: `source_span_json -> CandidateRecord.source_span`

### 5.3 `extraction_results`
- `logical_name`: `ExtractionResultRecord`
- `owner_spec`: `LLM_REMEDIATION_PLAN_REVISED.md`
- `current_state`: one row per candidate batch
- `target_state`: canonical extraction batch result table

**columns**
| column | type | nullability | current_state | notes |
|---|---|---|---|---|
| `candidate_batch_id` | `TEXT` | not null | existing | primary key |
| `workspace_id` | `TEXT` | not null | existing | workspace scope |
| `source_id` | `TEXT` | not null | existing | owning source |
| `job_id` | `TEXT` | not null | existing | async job |
| `request_id` | `TEXT` | nullable | existing | request correlation |
| `candidate_ids_json` | `TEXT` | not null | existing | JSON candidate ids |
| `status` | `TEXT` | not null | existing | extraction status |
| `error_json` | `TEXT` | nullable | existing | structured error |
| `created_at` | `TEXT` | not null | existing | ISO timestamp |
| `finished_at` | `TEXT` | nullable | existing | ISO timestamp |

- `primary_key`: `candidate_batch_id`
- `unique_constraints`: none explicit beyond PK
- `indexes`:
  - `current_state`: implicit PK index only
  - `target_state`: recommend `(workspace_id, job_id)`
- `check_constraints`:
  - `current_state`: none explicit
  - `target_state`: status enum check
- `json_encoded_fields`: `candidate_ids_json -> ExtractionResultResponse.candidate_ids`, `error_json -> JobError`

### 5.4 `routes`
- `logical_name`: `RouteRecord`
- `owner_spec`: `ROUTE_GENERATION_RANKING_SPEC.md`, `API_SPEC.md`
- `migration_owner`: `research API state store route/replay alignment migration`
- `current_state`: route persistence exists with explicit canonical persisted edge refs and summary trace/degraded fields
- `target_state`: keep `routes` as canonical table; maintain `route_edge_ids_json` as replay/diff source and keep summary trace/degraded fields in sync with API contract

**columns**
| column | type | nullability | current_state | notes |
|---|---|---|---|---|
| `route_id` | `TEXT` | not null | existing | primary key |
| `workspace_id` | `TEXT` | not null | existing | workspace scope |
| `title` | `TEXT` | not null | existing | route title |
| `summary` | `TEXT` | not null | existing | route summary |
| `status` | `TEXT` | not null | existing | route status |
| `support_score` | `REAL` | not null | existing | support dimension |
| `risk_score` | `REAL` | not null | existing | risk dimension |
| `progressability_score` | `REAL` | not null | existing | progressability dimension |
| `confidence_score` | `REAL` | nullable | existing | deterministic aggregate confidence |
| `confidence_grade` | `TEXT` | nullable | existing | `low/medium/high` |
| `rank` | `INTEGER` | nullable | existing | persisted ranking position |
| `novelty_level` | `TEXT` | nullable | existing | novelty typing |
| `relation_tags_json` | `TEXT` | nullable | existing | relation tag list |
| `top_factors_json` | `TEXT` | nullable | existing | factor list |
| `score_breakdown_json` | `TEXT` | nullable | existing | dimension breakdown |
| `node_score_breakdown_json` | `TEXT` | nullable | existing | node contribution breakdown |
| `scoring_template_id` | `TEXT` | nullable | existing | template id |
| `scored_at` | `TEXT` | nullable | existing | scoring timestamp |
| `conclusion` | `TEXT` | not null | existing | route conclusion |
| `key_supports_json` | `TEXT` | not null | existing | support text list |
| `assumptions_json` | `TEXT` | not null | existing | assumption text list |
| `risks_json` | `TEXT` | not null | existing | risk text list |
| `next_validation_action` | `TEXT` | not null | existing | next action text |
| `conclusion_node_id` | `TEXT` | nullable | existing | graph node id |
| `route_node_ids_json` | `TEXT` | nullable | existing | route node ids |
| `route_edge_ids_json` | `TEXT` | nullable | existing | canonical persisted route edge refs; JSON array `["edge_id_1", "edge_id_2", ...]` |
| `key_support_node_ids_json` | `TEXT` | nullable | existing | support node ids |
| `key_assumption_node_ids_json` | `TEXT` | nullable | existing | assumption node ids |
| `risk_node_ids_json` | `TEXT` | nullable | existing | risk node ids |
| `next_validation_node_id` | `TEXT` | nullable | existing | graph node id |
| `version_id` | `TEXT` | nullable | existing | graph version ref |
| `provider_backend` | `TEXT` | nullable | existing | summary provider backend |
| `provider_model` | `TEXT` | nullable | existing | summary provider model |
| `llm_request_id` | `TEXT` | nullable | existing | summary request correlation id |
| `llm_response_id` | `TEXT` | nullable | existing | provider response id |
| `usage_json` | `TEXT` | nullable | existing | summary token usage JSON |
| `fallback_used` | `INTEGER` | nullable | existing | explicit fallback marker (0/1) |
| `degraded` | `INTEGER` | nullable | existing | explicit degraded marker (0/1) |
| `degraded_reason` | `TEXT` | nullable | existing | canonical degraded reason/error code |
| `summary_generation_mode` | `TEXT` | nullable | existing | `llm` or `degraded_fallback` |
| `key_strengths_json` | `TEXT` | nullable | existing | structured strengths JSON |
| `key_risks_json` | `TEXT` | nullable | existing | structured risks JSON |
| `open_questions_json` | `TEXT` | nullable | existing | structured open questions JSON |

- `primary_key`: `route_id`
- `unique_constraints`: none explicit beyond PK
- `indexes`:
  - `current_state`: implicit PK index only
  - `target_state`: recommend `(workspace_id, status)`, `(workspace_id, version_id)`; no additional explicit index required for `route_edge_ids_json`
- `check_constraints`:
  - `current_state`: none explicit
  - `target_state`: route status enum and score range checks; `confidence_score` must align with deterministic score function; `route_edge_ids_json` must decode to an array of edge-id strings when present
- `json_encoded_fields`:
  - `relation_tags_json -> RouteRecord.relation_tags`
  - `top_factors_json -> RouteRecord.top_factors`
  - `score_breakdown_json -> RouteRecord.score_breakdown`
  - `node_score_breakdown_json -> RouteRecord.node_score_breakdown`
  - `key_supports_json -> RouteRecord.key_supports`
  - `assumptions_json -> RouteRecord.assumptions`
  - `risks_json -> RouteRecord.risks`
  - `route_node_ids_json -> RouteRecord.route_node_ids`
  - `key_support_node_ids_json -> RouteRecord.key_support_node_ids`
  - `key_assumption_node_ids_json -> RouteRecord.key_assumption_node_ids`
  - `risk_node_ids_json -> RouteRecord.risk_node_ids`
  - `route_edge_ids_json -> RouteTraceRefs.route_edge_ids`
  - `usage_json -> RouteRecord.usage`
  - `key_strengths_json -> RouteRecord.key_strengths`
  - `key_risks_json -> RouteRecord.key_risks`
  - `open_questions_json -> RouteRecord.open_questions`
- `canonical_replay_source`: persisted `route_edge_ids_json`
- `non_canonical_echo_only`: `trace_refs.route_edge_ids`

### 5.5 `graph_nodes`
- `logical_name`: `GraphNodeRecord`
- `owner_spec`: `GRAPH_EDITING_OBJECT_BOUNDARY_SPEC.md`, `DOMAIN_MODEL.md`
- `current_state`: projection node table exists
- `target_state`: keep canonical projection table; structural edit/remap additions remain separate planned tables

**columns**
| column | type | nullability | current_state | notes |
|---|---|---|---|---|
| `node_id` | `TEXT` | not null | existing | primary key |
| `workspace_id` | `TEXT` | not null | existing | workspace scope |
| `node_type` | `TEXT` | not null | existing | node type |
| `object_ref_type` | `TEXT` | not null | existing | bound object type |
| `object_ref_id` | `TEXT` | not null | existing | bound object id |
| `short_label` | `TEXT` | not null | existing | display label |
| `full_description` | `TEXT` | not null | existing | long description |
| `short_tags_json` | `TEXT` | not null | existing | JSON array of up to 3 short tags |
| `visibility` | `TEXT` | not null | existing | `private/workspace/package_public` |
| `source_refs_json` | `TEXT` | not null | existing | JSON array of source trace refs |
| `status` | `TEXT` | not null | existing | node status |
| `created_at` | `TEXT` | not null | existing | ISO timestamp |
| `updated_at` | `TEXT` | not null | existing | ISO timestamp |

- `primary_key`: `node_id`
- `unique_constraints`: none explicit beyond PK
- `indexes`:
  - `current_state`: implicit PK index only
  - `target_state`: recommend `(workspace_id, status)`, `(workspace_id, object_ref_type, object_ref_id)`
- `check_constraints`:
  - `current_state`: none explicit
  - `target_state`: node status/type enum checks; visibility enum checks
- `json_encoded_fields`:
  - `short_tags_json -> GraphNode.short_tags`
  - `source_refs_json -> GraphNode.source_refs`

### 5.6 `graph_edges`
- `logical_name`: `GraphEdgeRecord`
- `owner_spec`: `GRAPH_EDITING_OBJECT_BOUNDARY_SPEC.md`, `DOMAIN_MODEL.md`
- `current_state`: projection edge table exists
- `target_state`: keep canonical edge table; remap-specific structures remain planned

**columns**
| column | type | nullability | current_state | notes |
|---|---|---|---|---|
| `edge_id` | `TEXT` | not null | existing | primary key |
| `workspace_id` | `TEXT` | not null | existing | workspace scope |
| `source_node_id` | `TEXT` | not null | existing | source node |
| `target_node_id` | `TEXT` | not null | existing | target node |
| `edge_type` | `TEXT` | not null | existing | edge type |
| `object_ref_type` | `TEXT` | not null | existing | bound object type |
| `object_ref_id` | `TEXT` | not null | existing | bound object id |
| `strength` | `REAL` | not null | existing | edge strength |
| `status` | `TEXT` | not null | existing | edge status |
| `created_at` | `TEXT` | not null | existing | ISO timestamp |
| `updated_at` | `TEXT` | not null | existing | ISO timestamp |

- `primary_key`: `edge_id`
- `unique_constraints`: none explicit beyond PK
- `indexes`:
  - `current_state`: implicit PK index only
  - `target_state`: recommend `(workspace_id, source_node_id)`, `(workspace_id, target_node_id)`
- `check_constraints`:
  - `current_state`: none explicit
  - `target_state`: edge status/type enum and `0<=strength<=1`
- `json_encoded_fields`: none

### 5.7 `graph_versions`
- `logical_name`: `GraphVersionRecord`
- `owner_spec`: `FAILURE_RECOMPUTE_VERSION_DIFF_SPEC.md`
- `current_state`: version summary and diff payload are persisted
- `target_state`: may later add parent/version lineage fields in migration

**columns**
| column | type | nullability | current_state | notes |
|---|---|---|---|---|
| `version_id` | `TEXT` | not null | existing | primary key |
| `workspace_id` | `TEXT` | not null | existing | workspace scope |
| `trigger_type` | `TEXT` | not null | existing | version trigger |
| `change_summary` | `TEXT` | not null | existing | deterministic summary |
| `diff_payload_json` | `TEXT` | not null | existing | diff JSON |
| `created_at` | `TEXT` | not null | existing | ISO timestamp |
| `request_id` | `TEXT` | nullable | existing | request correlation |

- `primary_key`: `version_id`
- `unique_constraints`: none explicit beyond PK
- `indexes`:
  - `current_state`: implicit PK index only
  - `target_state`: recommend `(workspace_id, created_at)`
- `check_constraints`:
  - `current_state`: none explicit
  - `target_state`: trigger type enum check
- `json_encoded_fields`: `diff_payload_json -> GraphVersionDiffResponse.diff_payload`

### 5.8 `graph_workspaces`
- `logical_name`: `GraphWorkspaceRecord`
- `owner_spec`: `GRAPH_EDITING_OBJECT_BOUNDARY_SPEC.md`

**columns**
| column | type | nullability | current_state | notes |
|---|---|---|---|---|
| `workspace_id` | `TEXT` | not null | existing | primary key |
| `latest_version_id` | `TEXT` | nullable | existing | latest graph version |
| `status` | `TEXT` | not null | existing | workspace graph status |
| `node_count` | `INTEGER` | not null | existing | denormalized count |
| `edge_count` | `INTEGER` | not null | existing | denormalized count |
| `updated_at` | `TEXT` | not null | existing | ISO timestamp |

- `primary_key`: `workspace_id`
- `unique_constraints`: none explicit beyond PK
- `indexes`:
  - `current_state`: implicit PK index only
  - `target_state`: recommend `(latest_version_id)` if version queries expand
- `check_constraints`:
  - `current_state`: none explicit
  - `target_state`: non-negative count checks
- `json_encoded_fields`: none

### 5.9 Formal Object Tables (`research_evidences`, `research_assumptions`, `research_conflicts`, `research_failures`, `research_validations`)
- `owner_spec`: `DOMAIN_MODEL.md`
- `current_state`: five parallel formal object tables with the same column family
- `target_state`: remain parallel unless a future consolidation migration is explicitly approved

#### Shared Column Family
| column | type | nullability | current_state | notes |
|---|---|---|---|---|
| object primary key (`evidence_id` / `assumption_id` / `conflict_id` / `failure_id` / `validation_id`) | `TEXT` | not null | existing | primary key |
| `workspace_id` | `TEXT` | not null | existing | workspace scope |
| `candidate_id` | `TEXT` | not null | existing | unique back-link to candidate |
| `source_id` | `TEXT` | not null | existing | source ref |
| `text` | `TEXT` | not null | existing | canonical text |
| `normalized_text` | `TEXT` | not null | existing | normalized text |
| `source_span_json` | `TEXT` | not null | existing | JSON span |
| `candidate_batch_id` | `TEXT` | nullable | existing | extraction batch |
| `extraction_job_id` | `TEXT` | nullable | existing | extraction job |
| `created_at` | `TEXT` | not null | existing | ISO timestamp |
| `created_request_id` | `TEXT` | nullable | existing | request correlation |

#### Table-specific Primary Keys
| physical_name | primary_key | unique_constraints | indexes | check_constraints | json_encoded_fields |
|---|---|---|---|---|---|
| `research_evidences` | `evidence_id` | `candidate_id UNIQUE` | implicit PK + implicit unique index | current none explicit; target enum checks not applicable | `source_span_json -> ResearchEvidence.source_span` |
| `research_assumptions` | `assumption_id` | `candidate_id UNIQUE` | implicit PK + implicit unique index | current none explicit | `source_span_json -> ResearchAssumption.source_span` |
| `research_conflicts` | `conflict_id` | `candidate_id UNIQUE` | implicit PK + implicit unique index | current none explicit | `source_span_json -> ResearchConflict.source_span` |
| `research_failures` | `failure_id` | `candidate_id UNIQUE` | implicit PK + implicit unique index | current none explicit | `source_span_json -> ResearchFailure.source_span` |
| `research_validations` | `validation_id` | `candidate_id UNIQUE` | implicit PK + implicit unique index | current none explicit | `source_span_json -> ResearchValidation.source_span` |

### 5.10 Legacy Flow Tables (`failures`, `validations`)

#### `failures`
- `logical_name`: `FailureRecordLegacy`
- `owner_spec`: `FAILURE_RECOMPUTE_VERSION_DIFF_SPEC.md`

| column | type | nullability | current_state | notes |
|---|---|---|---|---|
| `failure_id` | `TEXT` | not null | existing | primary key |
| `workspace_id` | `TEXT` | not null | existing | workspace scope |
| `attached_targets_json` | `TEXT` | not null | existing | JSON target refs |
| `observed_outcome` | `TEXT` | not null | existing | observed state |
| `expected_difference` | `TEXT` | not null | existing | intended difference |
| `failure_reason` | `TEXT` | not null | existing | reason text |
| `severity` | `TEXT` | not null | existing | severity enum |
| `reporter` | `TEXT` | not null | existing | reporter text |
| `impact_summary_json` | `TEXT` | nullable | existing | persisted latest failure attach/recompute impact summary |
| `impact_updated_at` | `TEXT` | nullable | existing | ISO timestamp for latest persisted impact snapshot |
| `derived_from_validation_id` | `TEXT` | nullable | existing | validation ref when failure is auto-derived from validation feedback |
| `derived_from_validation_result_id` | `TEXT` | nullable | existing | validation result ref that produced the derived failure |
| `created_at` | `TEXT` | not null | existing | ISO timestamp |

- `primary_key`: `failure_id`
- `unique_constraints`: none explicit beyond PK
- `indexes`: implicit PK only; target recommend `(workspace_id, created_at)`
- `check_constraints`: current none explicit; target severity enum check
- `json_encoded_fields`: `attached_targets_json -> FailureCreateRequest.attached_targets`; `impact_summary_json -> FailureResponse.impact_summary`

#### `validations`
- `logical_name`: `ValidationRecordLegacy`
- `owner_spec`: `DOMAIN_MODEL.md`

| column | type | nullability | current_state | notes |
|---|---|---|---|---|
| `validation_id` | `TEXT` | not null | existing | primary key |
| `workspace_id` | `TEXT` | not null | existing | workspace scope |
| `target_object` | `TEXT` | not null | existing | validation target |
| `method` | `TEXT` | not null | existing | validation method |
| `success_signal` | `TEXT` | not null | existing | positive signal |
| `weakening_signal` | `TEXT` | not null | existing | weakening signal |
| `status` | `TEXT` | nullable | existing | `pending/validated/weakened/failed` |
| `latest_outcome` | `TEXT` | nullable | existing | latest submitted outcome |
| `latest_result_id` | `TEXT` | nullable | existing | latest validation result id |
| `updated_at` | `TEXT` | nullable | existing | ISO timestamp |

- `primary_key`: `validation_id`
- `unique_constraints`: none explicit beyond PK
- `indexes`: implicit PK only; target recommend `(workspace_id)`
- `check_constraints`: current none explicit; target method enum if later standardized
- `json_encoded_fields`: none

#### `validation_results`
- `logical_name`: `ValidationResultRecord`
- `owner_spec`: `DOMAIN_MODEL.md`, `API_SPEC.md`

| column | type | nullability | current_state | notes |
|---|---|---|---|---|
| `result_id` | `TEXT` | not null | existing | primary key |
| `validation_id` | `TEXT` | not null | existing | validation ref |
| `workspace_id` | `TEXT` | not null | existing | workspace scope |
| `outcome` | `TEXT` | not null | existing | `validated/weakened/failed` |
| `target_type` | `TEXT` | nullable | existing | `route/node/edge` |
| `target_id` | `TEXT` | nullable | existing | target object id |
| `note` | `TEXT` | nullable | existing | note |
| `request_id` | `TEXT` | nullable | existing | request correlation |
| `triggered_failure_id` | `TEXT` | nullable | existing | failure ref when weakened/failed |
| `recompute_job_id` | `TEXT` | nullable | existing | recompute job ref when weakened/failed |
| `created_at` | `TEXT` | not null | existing | ISO timestamp |

- `primary_key`: `result_id`
- `unique_constraints`: none explicit beyond PK
- `indexes`: implicit PK only; target recommend `(validation_id, created_at)`
- `check_constraints`: current none explicit; target outcome enum checks
- `json_encoded_fields`: none

### 5.11 `memory_actions`
- `logical_name`: `MemoryActionRecord`
- `owner_spec`: `API_SPEC.md`, retrieval/productization specs
- `current_state`: action log for backend-controlled memory operations over retrieval-backed records
- `target_state`: keep action persistence stable and continue deriving memory records from retrieval views
- `canonical_domain_note`: this table is not a canonical memory truth store and is not equivalent to native EverMemOS memory extraction/storage.

| column | type | nullability | current_state | notes |
|---|---|---|---|---|
| `action_id` | `TEXT` | not null | existing | primary key |
| `workspace_id` | `TEXT` | not null | existing | workspace scope |
| `action_type` | `TEXT` | not null | existing | action enum |
| `memory_view_type` | `TEXT` | not null | existing | retrieval view type |
| `memory_result_id` | `TEXT` | not null | existing | memory result ref |
| `route_id` | `TEXT` | nullable | existing | route ref |
| `hypothesis_id` | `TEXT` | nullable | existing | hypothesis ref |
| `validation_id` | `TEXT` | nullable | existing | validation ref |
| `request_id` | `TEXT` | nullable | existing | request correlation |
| `note` | `TEXT` | nullable | existing | user note |
| `memory_ref_json` | `TEXT` | not null | existing | memory payload |
| `created_at` | `TEXT` | not null | existing | ISO timestamp |

- `primary_key`: `action_id`
- `unique_constraints`: none explicit beyond PK
- `indexes`: implicit PK only; target recommend `(workspace_id, action_type)`
- `check_constraints`: current none explicit; target action type/view type enum checks
- `json_encoded_fields`: `memory_ref_json -> retrieval-backed memory reference`

### 5.12 `hypotheses`
- `logical_name`: `HypothesisRecord`
- `owner_spec`: `LLM_REMEDIATION_PLAN_REVISED.md`, `HYPOTHESIS_ENGINE_SPEC.md`, `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md`
- `current_state`: candidate hypothesis persistence exists but planned richer semantics still live in specialized specs
- `target_state`: keep table canonical for finalized hypothesis persistence; extend through documented migration only, including explicit lineage refs back to hypothesis pool/candidate/round/match/search-tree state when multi-agent runtime lands

| column | type | nullability | current_state | notes |
|---|---|---|---|---|
| `hypothesis_id` | `TEXT` | not null | existing | primary key |
| `workspace_id` | `TEXT` | not null | existing | workspace scope |
| `statement` | `TEXT` | not null | existing | statement text |
| `status` | `TEXT` | not null | existing | hypothesis status |
| `trigger_object_ids_json` | `TEXT` | not null | existing | trigger ids |
| `title` | `TEXT` | nullable | existing | title |
| `summary` | `TEXT` | nullable | existing | summary |
| `premise` | `TEXT` | nullable | existing | premise |
| `rationale` | `TEXT` | nullable | existing | rationale |
| `stage` | `TEXT` | nullable | existing | stage |
| `trigger_refs_json` | `TEXT` | nullable | existing | trigger refs |
| `related_object_ids_json` | `TEXT` | nullable | existing | related objects |
| `novelty_typing` | `TEXT` | nullable | existing | novelty classification |
| `minimum_validation_action_json` | `TEXT` | nullable | existing | validation action payload |
| `weakening_signal_json` | `TEXT` | nullable | existing | weakening signal |
| `decision_note` | `TEXT` | nullable | existing | decision note |
| `decision_source_type` | `TEXT` | nullable | existing | decision source type |
| `decision_source_ref` | `TEXT` | nullable | existing | decision source ref |
| `decided_at` | `TEXT` | nullable | existing | ISO timestamp |
| `decided_request_id` | `TEXT` | nullable | existing | request id |
| `created_at` | `TEXT` | nullable | existing | ISO timestamp |
| `updated_at` | `TEXT` | nullable | existing | ISO timestamp |
| `generation_job_id` | `TEXT` | nullable | existing | generation job |

- `primary_key`: `hypothesis_id`
- `unique_constraints`: none explicit beyond PK
- `indexes`: implicit PK only; target recommend `(workspace_id, status)`, `(generation_job_id)`, `(workspace_id, created_at)`
- `check_constraints`: current none explicit; target status/stage enum checks
- `json_encoded_fields`:
  - `trigger_object_ids_json -> HypothesisResponse.trigger_object_ids`
  - `trigger_refs_json -> HypothesisResponse.trigger_refs`
  - `related_object_ids_json -> HypothesisResponse.related_object_ids`
  - `minimum_validation_action_json -> HypothesisResponse.minimum_validation_action`
  - `weakening_signal_json -> HypothesisResponse.weakening_signal`
- `planned_lineage_extensions`:
  - `hypothesis_pool_id`
  - `source_candidate_id`
  - `source_round_id`
  - `finalizing_match_id`
  - `search_tree_node_id`
  - `reasoning_chain_id`

### 5.13 `packages`
- `logical_name`: `PackageRecord`
- `owner_spec`: `RESEARCH_PACKAGE_SPEC.md`

| column | type | nullability | current_state | notes |
|---|---|---|---|---|
| `package_id` | `TEXT` | not null | existing | primary key |
| `workspace_id` | `TEXT` | not null | existing | workspace scope |
| `title` | `TEXT` | not null | existing | title |
| `summary` | `TEXT` | not null | existing | summary |
| `included_route_ids_json` | `TEXT` | not null | existing | route ids |
| `included_node_ids_json` | `TEXT` | not null | existing | node ids |
| `included_validation_ids_json` | `TEXT` | not null | existing | validation ids |
| `status` | `TEXT` | not null | existing | package status |
| `snapshot_type` | `TEXT` | nullable | existing | snapshot type |
| `snapshot_version` | `TEXT` | nullable | existing | snapshot version |
| `private_dependency_flags_json` | `TEXT` | nullable | existing | private dependency flags |
| `public_gap_nodes_json` | `TEXT` | nullable | existing | public gap nodes |
| `boundary_notes_json` | `TEXT` | nullable | existing | boundary notes |
| `traceability_refs_json` | `TEXT` | nullable | existing | traceability refs |
| `snapshot_payload_json` | `TEXT` | nullable | existing | snapshot payload |
| `replay_ready` | `INTEGER` | nullable | existing | boolean-like flag |
| `build_request_id` | `TEXT` | nullable | existing | request id |
| `created_at` | `TEXT` | nullable | existing | ISO timestamp |
| `updated_at` | `TEXT` | nullable | existing | ISO timestamp |
| `published_at` | `TEXT` | nullable | existing | ISO timestamp |

- `primary_key`: `package_id`
- `unique_constraints`: none explicit beyond PK
- `indexes`: implicit PK only; target recommend `(workspace_id, status)`
- `check_constraints`: current none explicit; target status enum + boolean-like replay check
- `json_encoded_fields`:
  - `included_route_ids_json`
  - `included_node_ids_json`
  - `included_validation_ids_json`
  - `private_dependency_flags_json`
  - `public_gap_nodes_json`
  - `boundary_notes_json`
  - `traceability_refs_json`
  - `snapshot_payload_json`
  - `traceability_refs_json.replacement_map -> { private_node_id: replacement_gap_node_id }`

### 5.14 `package_publish_results`
- `logical_name`: `PackagePublishResultRecord`
- `owner_spec`: `RESEARCH_PACKAGE_SPEC.md`

| column | type | nullability | current_state | notes |
|---|---|---|---|---|
| `publish_result_id` | `TEXT` | not null | existing | primary key |
| `package_id` | `TEXT` | not null | existing | package ref |
| `workspace_id` | `TEXT` | not null | existing | workspace scope |
| `snapshot_type` | `TEXT` | not null | existing | snapshot type |
| `snapshot_version` | `TEXT` | not null | existing | snapshot version |
| `boundary_notes_json` | `TEXT` | not null | existing | boundary notes |
| `published_snapshot_json` | `TEXT` | not null | existing | publish payload |
| `published_at` | `TEXT` | not null | existing | ISO timestamp |
| `request_id` | `TEXT` | nullable | existing | request id |

- `primary_key`: `publish_result_id`
- `unique_constraints`: none explicit beyond PK
- `indexes`: implicit PK only; target recommend `(package_id, published_at)`
- `check_constraints`: current none explicit
- `json_encoded_fields`: `boundary_notes_json`, `published_snapshot_json`

### 5.15 `jobs`
- `logical_name`: `ResearchJobRecord`
- `owner_spec`: `API_SPEC.md`, `OBSERVABILITY.md`

| column | type | nullability | current_state | notes |
|---|---|---|---|---|
| `job_id` | `TEXT` | not null | existing | primary key |
| `job_type` | `TEXT` | not null | existing | job type |
| `status` | `TEXT` | not null | existing | job status |
| `workspace_id` | `TEXT` | not null | existing | workspace scope |
| `request_id` | `TEXT` | nullable | existing | request correlation |
| `created_at` | `TEXT` | not null | existing | ISO timestamp |
| `started_at` | `TEXT` | nullable | existing | ISO timestamp |
| `finished_at` | `TEXT` | nullable | existing | ISO timestamp |
| `result_ref_type` | `TEXT` | nullable | existing | result ref type |
| `result_ref_id` | `TEXT` | nullable | existing | result ref id |
| `error_json` | `TEXT` | nullable | existing | structured job error |

- `primary_key`: `job_id`
- `unique_constraints`: none explicit beyond PK
- `indexes`: implicit PK only; target recommend `(workspace_id, status)`, `(request_id)`
- `check_constraints`: current none explicit; target job status/type enum checks
- `json_encoded_fields`: `error_json -> JobError`

### 5.16 `research_events`
- `logical_name`: `ResearchEventRecord`
- `owner_spec`: `OBSERVABILITY.md`
- `current_state`: canonical persisted event table
- `target_state`: keep as canonical event persistence for research flows

| column | type | nullability | current_state | notes |
|---|---|---|---|---|
| `event_id` | `TEXT` | not null | existing | primary key |
| `event_name` | `TEXT` | not null | existing | canonical event family |
| `timestamp` | `TEXT` | not null | existing | ISO timestamp |
| `request_id` | `TEXT` | nullable | existing | request correlation |
| `job_id` | `TEXT` | nullable | existing | async correlation |
| `workspace_id` | `TEXT` | nullable | existing | workspace scope |
| `source_id` | `TEXT` | nullable | existing | source ref |
| `candidate_batch_id` | `TEXT` | nullable | existing | extraction batch |
| `component` | `TEXT` | not null | existing | emitting component |
| `step` | `TEXT` | nullable | existing | detailed step |
| `status` | `TEXT` | not null | existing | event status |
| `refs_json` | `TEXT` | not null | existing | structured refs |
| `metrics_json` | `TEXT` | not null | existing | metrics |
| `error_json` | `TEXT` | nullable | existing | error payload |

- `primary_key`: `event_id`
- `unique_constraints`: none explicit beyond PK
- `indexes`: implicit PK only; target recommend `(workspace_id, timestamp)`, `(request_id)`, `(job_id)`
- `check_constraints`: current none explicit; target event status enum checks
- `json_encoded_fields`: `refs_json`, `metrics_json`, `error_json`

## 6. Planned Table Inventory

| logical_name | physical_name | current_store_name | storage_backend | evermemos_target_path | migration_owner | status | target check / invariant source |
|---|---|---|---|---|---|---|---|
| `RouteBranchRecord` | `route_branches` | _none_ | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `FAILURE_RECOMPUTE_VERSION_DIFF_SPEC.md` | `planned` | branch type invariant and route/gap exclusivity |
| `GraphProjectionRemapRecord` | `graph_projection_remaps` | _none_ | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `GRAPH_EDITING_OBJECT_BOUNDARY_SPEC.md` | `planned` | remap source action constraints |
| `WorkspaceMemberRecord` | `workspace_members` | _none_ | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `VISIBILITY_RBAC_SPEC.md` | `planned` | role enum and unique membership |
| `ResourceAclRecord` | `resource_acl` | _none_ | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `VISIBILITY_RBAC_SPEC.md` | `planned` | visibility/access scope invariants |
| `SemanticLinkRecord` | `semantic_links` | _none_ | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `LLM_REMEDIATION_PLAN_REVISED.md` | `planned` | semantic mirror uniqueness |
| `SemanticWriteJobRecord` | `semantic_write_jobs` | _none_ | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `LLM_REMEDIATION_PLAN_REVISED.md` | `planned` | unique job key, transaction/recovery invariants |
| `WorkspaceTemplateRecord` | `workspace_templates` | _none_ | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `COLD_START_WORKSPACE_SPEC.md` | `planned` | template policy invariants |
| `WorkspaceBootstrapJobRecord` | `workspace_bootstrap_jobs` | _none_ | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `COLD_START_WORKSPACE_SPEC.md` | `planned` | phase/status invariants |
| `EvidenceRefRecord` | `evidence_refs` | _none_ | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `SCHOLARLY_EVIDENCE_SPEC.md` | `planned` | work/viewpoint/fragment invariants |
| `ScholarlySourceCacheRecord` | `scholarly_source_cache` | _none_ | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `SCHOLARLY_PROVIDER_INTEGRATION_SPEC.md` | `planned` | provider cache freshness/integrity rules |
| `ClaimRefRecord` | `claim_refs` | _none_ | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `UNIFIED_CONTRACTS_SPEC.md` | `planned` | claim/span provenance locator invariants |
| `ProvenanceRefRecord` | `provenance_refs` | _none_ | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `UNIFIED_CONTRACTS_SPEC.md` | `planned` | cross-object trace lineage invariants |
| `ValidationResultRecord` | `validation_results` | _none_ | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `UNIFIED_CONTRACTS_SPEC.md` | `planned` | validation outcome append-only invariants |
| `HypothesisCandidatePoolRecord` | `hypothesis_candidate_pools` | _none_ | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md` | `planned` | one workspace + one frozen trigger set snapshot per pool |
| `HypothesisCandidateRecord` | `hypothesis_candidates` | _none_ | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md` | `planned` | candidate lineage and terminal prune/finalize invariants |
| `HypothesisRoundRecord` | `hypothesis_rounds` | _none_ | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md` | `planned` | round uniqueness within pool and replayability |
| `HypothesisReviewRecord` | `hypothesis_reviews` | _none_ | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md` | `planned` | one review targets one candidate in one round |
| `HypothesisMatchRecord` | `hypothesis_matches` | _none_ | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md` | `planned` | Elo replay and winner/loser trace invariants |
| `HypothesisEvolutionRecord` | `hypothesis_evolutions` | _none_ | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md` | `planned` | evolved candidate lineage invariants |
| `HypothesisMetaReviewRecord` | `hypothesis_meta_reviews` | _none_ | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md` | `planned` | one meta-review per completed round summary |
| `HypothesisProximityEdgeRecord` | `hypothesis_proximity_edges` | _none_ | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md` | `planned` | similarity and pairing-priority reproducibility |
| `HypothesisSearchTreeNodeRecord` | `hypothesis_search_tree_nodes` | _none_ | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md` | `planned` | search branch replayability and prune persistence |
| `HypothesisSearchTreeEdgeRecord` | `hypothesis_search_tree_edges` | _none_ | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md` | `planned` | explicit expansion/continuation action lineage |
| `ReasoningChainRecord` | `reasoning_chains` | _none_ | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md` | `planned` | ordered-step chain invariants |
| `ReasoningStepRecord` | `reasoning_steps` | _none_ | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md` | `planned` | step order uniqueness and evidence/graph trace invariants |
| `ReasoningSubgraphRecord` | `reasoning_subgraphs` | _none_ | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md` | `planned` | scoped subgraph attribution invariants |
| `MechanismRevisionRecord` | `mechanism_revisions` | _none_ | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md` | `planned` | validation/failure-triggered mechanism revision invariants |
| `WeakestStepAssessmentRecord` | `weakest_step_assessments` | _none_ | `SQLite` | `src/research_layer/api/controllers/_state_store.py` | `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md` | `planned` | one assessment resolves to one concrete reasoning step |

## 7. Current vs Target Constraint Rule
1. If the code already enforces a constraint through PK or UNIQUE, it is recorded as current.
2. If a constraint exists only in specialized specs, it must appear under `target_state` or planned invariant source.
3. Existing tables must not pretend that target checks are already live in DDL.
4. Planned tables must not be given fabricated full DDL before implementation design is frozen.

## 8. Unified Contract Storage Sync (2026-04-08)

### 8.1 Ingest Contract Storage Baseline (existing)
Required persisted correlation fields across ingest/extract paths:
1. `workspace_id`
2. `source_type`
3. `source_input_mode` (or equivalent input-mode metadata field)
4. `request_id`
5. async job correlation: `job_id`, `status`, `result_ref_*`

Primary existing tables:
1. `sources`
2. `candidates`
3. `extraction_results`
4. `jobs`
5. `research_events`

### 8.2 Provenance Storage Baseline (existing + planned)
Existing minimum linkage:
1. `source_id`
2. `candidate_batch_id`
3. `llm_request_id` / `llm_response_id` where applicable
4. `refs_json`/trace-like payload columns in event and retrieval surfaces

Planned additions:
1. `claim_refs`
2. `provenance_refs`
3. multi-agent hypothesis lineage columns and tables:
   - `hypothesis_pool_id`
   - `source_candidate_id`
   - `source_round_id`
   - `finalizing_match_id`
   - `search_tree_node_id`
   - `reasoning_chain_id`

### 8.3 Validation and Publish Storage Baseline
Existing:
1. validation action and result linkage through existing validation/publish tables
2. package publish result persistence and replay linkage

Planned:
1. canonical `validation_results` table as explicit first-class record

### 8.4 Anti-Shell Rule
Storage schema changes are accepted only when:
1. corresponding API/domain/error docs are updated in the same change set
2. status labels (`existing/planned`) remain consistent across all truth docs

## 9. Six Capability Storage Impact (existing, no migration)

The six capability additions do not require new tables or mandatory DB migration.

Existing storage reuse:
1. `sources`, `candidates`, `jobs`, `extraction_results`: used by raw material bootstrap and optional extract job refs.
2. `graph_nodes`, `graph_edges`, `graph_versions`, `graph_workspaces`: read by graph report, query API, and graph export.
3. `failures`, `validations`, `routes`, `hypotheses`, `packages`: read by report/query/export and orchestrated by command layer through existing services.
4. `research_events`: receives success/degraded/failed observability events for report/query/bootstrap/commands/export.

Storage invariants:
1. No six-capability service writes canonical graph/route/hypothesis/package tables directly except existing service delegation.
2. `sources/bootstrap` may create raw `sources`, pending `candidates`, and job refs; it must not create confirmed objects or graph objects.
3. Export payloads are derived at request time and are not persisted as canonical snapshots.
