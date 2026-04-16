# DOMAIN_MODEL.md — Mironicky Research Domain (Foundational Truth)

## 1. Purpose
This document is the active foundational truth for Mironicky research domain objects in the real backend repo. It freezes:
- canonical object names
- field names
- enum/state names
- invariants
- object references

It does **not** own algorithmic behavior such as scoring formulas, route ranking, visibility inheritance, or LLM prompt behavior.

## 2. Ownership
### Owned Scope
- object names
- field names
- enum and state names
- required vs optional fields
- object invariants
- object reference relationships
- naming reconciliation between current code and target model

### Out of Scope
- scoring formulas
- route ranking rules
- visibility propagation rules
- provider selection and prompt contracts
- package publishing behavior details
- failure propagation math

### Conflict Resolution
1. For object names, fields, enum values, and invariants: this document wins.
2. For algorithmic behavior: the owning specialized spec wins.
3. When current code symbol and target symbol differ, both must be recorded here and in `WIRING_TARGET_MAP.md`.
4. A `planned` object cannot be treated as already implemented.
5. An existing API/store transitional record does not upgrade a canonical domain object from `planned` to `existing` unless a matching domain symbol exists in the real backend domain model.

## 3. Naming Reconciliation Table

| canonical_name | current_code_symbol | target_symbol | evermemos_target_path | owner_spec | status |
|---|---|---|---|---|---|
| `ResearchSource` | `ResearchSource` | `ResearchSource` | `src/research_layer/domain/models/research_domain.py` | `DOMAIN_MODEL.md` | `existing` |
| `ResearchEvidence` | `ResearchEvidence` | `ResearchEvidence` | `src/research_layer/domain/models/research_domain.py` | `DOMAIN_MODEL.md` | `existing` |
| `ResearchAssumption` | `ResearchAssumption` | `ResearchAssumption` | `src/research_layer/domain/models/research_domain.py` | `DOMAIN_MODEL.md` | `existing` |
| `ResearchConflict` | `ResearchConflict` | `ResearchConflict` | `src/research_layer/domain/models/research_domain.py` | `DOMAIN_MODEL.md` | `existing` |
| `FailureReport` | `FailureReport` | `FailureReport` | `src/research_layer/domain/models/research_domain.py` | `DOMAIN_MODEL.md` | `existing` |
| `ValidationAction` | `ValidationAction` | `ValidationAction` | `src/research_layer/domain/models/research_domain.py` | `DOMAIN_MODEL.md` | `existing` |
| `Route` | `Route` | `Route` | `src/research_layer/domain/models/research_domain.py` | `DOMAIN_MODEL.md` | `existing` |
| `GraphNode` | `GraphNode` | `GraphNode` | `src/research_layer/domain/models/research_domain.py` | `DOMAIN_MODEL.md` | `existing` |
| `GraphEdge` | `GraphEdge` | `GraphEdge` | `src/research_layer/domain/models/research_domain.py` | `DOMAIN_MODEL.md` | `existing` |
| `GraphVersion` | `GraphVersion` | `GraphVersion` | `src/research_layer/domain/models/research_domain.py` | `DOMAIN_MODEL.md` | `existing` |
| `ResearchPackage` | `ResearchPackage` | `ResearchPackage` | `src/research_layer/domain/models/research_domain.py` | `DOMAIN_MODEL.md` | `existing` |
| `Hypothesis` | _none as canonical domain symbol; transitional API/store representation exists as `HypothesisResponse`/`hypotheses`_ | `Hypothesis` | `src/research_layer/domain/models/research_domain.py` | `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md` | `planned` |
| `HypothesisCandidatePool` | _none_ | `HypothesisCandidatePool` | `src/research_layer/domain/models/research_domain.py` | `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md` | `planned` |
| `HypothesisCandidate` | _none_ | `HypothesisCandidate` | `src/research_layer/domain/models/research_domain.py` | `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md` | `planned` |
| `HypothesisRound` | _none_ | `HypothesisRound` | `src/research_layer/domain/models/research_domain.py` | `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md` | `planned` |
| `HypothesisReview` | _none_ | `HypothesisReview` | `src/research_layer/domain/models/research_domain.py` | `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md` | `planned` |
| `HypothesisMatch` | _none_ | `HypothesisMatch` | `src/research_layer/domain/models/research_domain.py` | `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md` | `planned` |
| `HypothesisEvolution` | _none_ | `HypothesisEvolution` | `src/research_layer/domain/models/research_domain.py` | `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md` | `planned` |
| `HypothesisMetaReview` | _none_ | `HypothesisMetaReview` | `src/research_layer/domain/models/research_domain.py` | `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md` | `planned` |
| `HypothesisProximityEdge` | _none_ | `HypothesisProximityEdge` | `src/research_layer/domain/models/research_domain.py` | `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md` | `planned` |
| `HypothesisSearchTreeNode` | _none_ | `HypothesisSearchTreeNode` | `src/research_layer/domain/models/research_domain.py` | `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md` | `planned` |
| `HypothesisSearchTreeEdge` | _none_ | `HypothesisSearchTreeEdge` | `src/research_layer/domain/models/research_domain.py` | `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md` | `planned` |
| `ReasoningChain` | _none_ | `ReasoningChain` | `src/research_layer/domain/models/research_domain.py` | `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md` | `planned` |
| `ReasoningStep` | _none_ | `ReasoningStep` | `src/research_layer/domain/models/research_domain.py` | `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md` | `planned` |
| `ReasoningSubgraph` | _none_ | `ReasoningSubgraph` | `src/research_layer/domain/models/research_domain.py` | `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md` | `planned` |
| `MechanismRevision` | _none_ | `MechanismRevision` | `src/research_layer/domain/models/research_domain.py` | `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md` | `planned` |
| `WeakestStepAssessment` | _none_ | `WeakestStepAssessment` | `src/research_layer/domain/models/research_domain.py` | `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md` | `planned` |
| `Candidate` | _none as canonical domain symbol; transitional API/store representation exists as `CandidateRecord`/`candidates`_ | `Candidate` | `src/research_layer/domain/models/research_domain.py` | `LLM_REMEDIATION_PLAN_REVISED.md` | `planned` |
| `RouteBranch` | _none_ | `RouteBranch` | `src/research_layer/domain/models/research_domain.py` | `FAILURE_RECOMPUTE_VERSION_DIFF_SPEC.md` | `planned` |
| `EvidenceRef` | _none_ | `EvidenceRef` | `src/research_layer/domain/models/research_domain.py` | `SCHOLARLY_EVIDENCE_SPEC.md` | `planned` |
| `WorkspaceTemplate` | _none_ | `WorkspaceTemplate` | `src/research_layer/domain/models/research_domain.py` | `COLD_START_WORKSPACE_SPEC.md` | `planned` |
| `WorkspaceBootstrapJob` | _none_ | `WorkspaceBootstrapJob` | `src/research_layer/domain/models/research_domain.py` | `COLD_START_WORKSPACE_SPEC.md` | `planned` |
| `ClaimRef` | _none_ | `ClaimRef` | `src/research_layer/domain/models/research_domain.py` | `UNIFIED_CONTRACTS_SPEC.md` | `planned` |
| `ProvenanceRef` | _none_ | `ProvenanceRef` | `src/research_layer/domain/models/research_domain.py` | `UNIFIED_CONTRACTS_SPEC.md` | `planned` |
| `ValidationResult` | _none_ | `ValidationResult` | `src/research_layer/domain/models/research_domain.py` | `UNIFIED_CONTRACTS_SPEC.md` | `planned` |

## 4. Shared Invariants
- Every research object belongs to exactly one `workspace_id`.
- `workspace_id` is required for all domain objects listed here.
- Graph objects are projections over confirmed/formal objects, not the source of factual truth.
- Routes, hypotheses, packages, branches, and versions are derived objects.
- A `planned` object is part of the target domain vocabulary but not yet guaranteed to exist in code.
- A planned canonical object may still have an existing API/store transitional representation; that transitional representation does not change the canonical domain status until the domain symbol exists.
- Canonical research truth remains in research domain objects and their projections; read models do not become canonical truth by usage.
- Retrieval-backed `Memory Vault` behavior and native EverMemOS memory integration are auxiliary/derived concerns and must not override canonical domain state.
- Confidence output may include LLM-assisted hints, but final ranking/state transitions remain deterministic program-controlled domain behavior.
- Validation outcomes and package publication states are canonical domain state and cannot be sourced from auxiliary memory artifacts.
- Multi-agent hypothesis pool, tournament, search-tree, and review artifacts are derived reasoning objects; only finalized `Hypothesis` objects may participate in downstream validation/package workflows.

## 5. Existing Code Objects

### 5.1 ResearchSource
- `current_code_symbol`: `ResearchSource`
- `target_symbol`: `ResearchSource`
- `evermemos_target_path`: `src/research_layer/domain/models/research_domain.py`
- `owner_spec`: `DOMAIN_MODEL.md`
- `status`: `existing`
- Required fields:
  - `source_id`
  - `workspace_id`
  - `source_type`
  - `title`
  - `raw_content`
  - `normalized_content`
  - `metadata`
  - `status`
  - `created_at`
  - `updated_at`
- Invariants:
  - `source_id` unique within research scope
  - `source_type` must be a valid `ResearchSourceType`
  - `status` must be a valid `ResearchSourceStatus`

### 5.2 ResearchEvidence
- `current_code_symbol`: `ResearchEvidence`
- `target_symbol`: `ResearchEvidence`
- `evermemos_target_path`: `src/research_layer/domain/models/research_domain.py`
- `owner_spec`: `DOMAIN_MODEL.md`
- `status`: `existing`
- Required fields:
  - `evidence_id`
  - `workspace_id`
  - `source_id`
  - `evidence_type`
  - `span_text`
  - `normalized_text`
  - `citation_ref`
  - `relation_to_prior_work`
  - `user_confirmed`
  - `confidence_hint`
- Invariants:
  - must link back to one source
  - must remain traceable to confirmed input or source span

### 5.3 ResearchAssumption
- `current_code_symbol`: `ResearchAssumption`
- `target_symbol`: `ResearchAssumption`
- `evermemos_target_path`: `src/research_layer/domain/models/research_domain.py`
- `owner_spec`: `DOMAIN_MODEL.md`
- `status`: `existing`
- Required fields:
  - `assumption_id`
  - `workspace_id`
  - `text`
  - `assumption_type`
  - `depends_on_evidence_ids`
  - `burden_score`
  - `status`
- Invariants:
  - `status` must be one of the frozen assumption states
  - dependencies must remain within the same workspace

### 5.4 ResearchConflict
- `current_code_symbol`: `ResearchConflict`
- `target_symbol`: `ResearchConflict`
- `evermemos_target_path`: `src/research_layer/domain/models/research_domain.py`
- `owner_spec`: `DOMAIN_MODEL.md`
- `status`: `existing`
- Required fields:
  - `conflict_id`
  - `workspace_id`
  - `involved_object_ids`
  - `reason`
  - `severity`
  - `resolved`
  - `resolution_note`
- Invariants:
  - `severity` must be a valid conflict severity enum
  - involved objects must belong to the same workspace

### 5.5 FailureReport
- `current_code_symbol`: `FailureReport`
- `target_symbol`: `FailureReport`
- `evermemos_target_path`: `src/research_layer/domain/models/research_domain.py`
- `owner_spec`: `DOMAIN_MODEL.md`
- `status`: `existing`
- Required fields:
  - `failure_id`
  - `workspace_id`
  - `attached_targets`
  - `observed_outcome`
  - `expected_difference`
  - `failure_reason`
  - `severity`
  - `reporter`
  - `timestamp`
- Invariants:
  - `attached_targets` cannot be empty
  - attached targets must resolve to valid node or edge refs in the same workspace
  - `severity` must be a valid failure severity enum

### 5.6 ValidationAction
- `current_code_symbol`: `ValidationAction`
- `target_symbol`: `ValidationAction`
- `evermemos_target_path`: `src/research_layer/domain/models/research_domain.py`
- `owner_spec`: `DOMAIN_MODEL.md`
- `status`: `existing`
- Required fields:
  - `action_id`
  - `workspace_id`
  - `target_object`
  - `method`
  - `success_signal`
  - `weakening_signal`
  - `status`
  - `latest_outcome`
  - `latest_result_id`
  - `cost_level`
  - `time_level`
  - `domain_template`
- Invariants:
  - cost and time levels must use frozen enums
  - validation result outcomes update lifecycle status deterministically
  - weakened/failed validation outcomes must be traceable to failure/recompute refs
  - `failed` outcome semantics are stable: runtime may auto-create a derived failure record, and that relation must stay traceable via `triggered_failure_id` plus `derived_from_validation_id` / `derived_from_validation_result_id`

### 5.7 Route
- `current_code_symbol`: `Route`
- `target_symbol`: `Route`
- `evermemos_target_path`: `src/research_layer/domain/models/research_domain.py`
- `owner_spec`: `DOMAIN_MODEL.md`
- `status`: `existing`
- Required fields:
  - `route_id`
  - `workspace_id`
  - `title`
  - `summary`
  - `support_score`
  - `risk_score`
  - `progressability_score`
  - `confidence_score`
  - `confidence_grade`
  - `novelty_level`
  - `relation_tags`
  - `top_factors`
  - `conclusion_node_id`
  - `next_validation_action_id`
  - `status`
  - `version_id`
  - `rank`
- Invariants:
  - route status must use frozen route status values
  - derived from graph snapshot within one workspace
  - rank order is deterministic and confidence-first
  - relation tags are semantic-only (`direct_support/recombination/upstream_inspiration`)

### 5.8 GraphNode
- `current_code_symbol`: `GraphNode`
- `target_symbol`: `GraphNode`
- `evermemos_target_path`: `src/research_layer/domain/models/research_domain.py`
- `owner_spec`: `DOMAIN_MODEL.md`
- `status`: `existing`
- Required fields:
  - `node_id`
  - `workspace_id`
  - `node_type`
  - `object_ref_type`
  - `object_ref_id`
  - `short_label`
  - `full_description`
  - `short_tags`
  - `visibility`
  - `source_refs`
  - `status`
- Invariants:
  - graph node is a projection, not the fact object
  - `object_ref_type/object_ref_id` must resolve to a formal object or allowed projection target

### 5.9 GraphEdge
- `current_code_symbol`: `GraphEdge`
- `target_symbol`: `GraphEdge`
- `evermemos_target_path`: `src/research_layer/domain/models/research_domain.py`
- `owner_spec`: `DOMAIN_MODEL.md`
- `status`: `existing`
- Required fields:
  - `edge_id`
  - `workspace_id`
  - `source_node_id`
  - `target_node_id`
  - `edge_type`
  - `strength`
  - `status`
- Invariants:
  - source and target nodes must exist in same workspace
  - edge is a projection relationship, not the source factual object

### 5.10 GraphVersion
- `current_code_symbol`: `GraphVersion`
- `target_symbol`: `GraphVersion`
- `evermemos_target_path`: `src/research_layer/domain/models/research_domain.py`
- `owner_spec`: `DOMAIN_MODEL.md`
- `status`: `existing`
- Required fields:
  - `version_id`
  - `workspace_id`
  - `trigger_type`
  - `change_summary`
  - `diff_payload`
  - `created_at`
- Invariants:
  - version is immutable once persisted
  - diff payload must be attributable to a concrete before/after state

### 5.11 ResearchPackage
- `current_code_symbol`: `ResearchPackage`
- `target_symbol`: `ResearchPackage`
- `evermemos_target_path`: `src/research_layer/domain/models/research_domain.py`
- `owner_spec`: `DOMAIN_MODEL.md`
- `status`: `existing`
- Required fields:
  - `package_id`
  - `workspace_id`
  - `title`
  - `summary`
  - `included_route_ids`
  - `included_node_ids`
  - `included_validation_ids`
  - `private_dependency_flags`
  - `public_gap_node_ids`
- Invariants:
  - package is a snapshot, not a live shared view
  - visibility and redaction rules are owned by package and RBAC specs
  - when private dependency nodes are replaced by public gap nodes, replay route refs must be rewritten to replacement node ids
  - replacement mapping must remain queryable from package traceability refs

## 6. Planned Target Objects

### 6.1 Hypothesis
- `current_code_symbol`: _none as domain model_
- `target_symbol`: `Hypothesis`
- `evermemos_target_path`: `src/research_layer/domain/models/research_domain.py`
- `owner_spec`: `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md`
- `status`: `planned`
- `transitional_existing_representations`: `api.schemas.hypothesis.HypothesisResponse`, `api/controllers/_state_store.py:hypotheses`
- `status_note`: `planned` here refers only to the canonical domain object; it does not deny the existing transitional API/store record already used by current hypothesis endpoints.
- Required fields:
  - `hypothesis_id`
  - `workspace_id`
  - `title`
  - `statement`
  - `summary`
  - `premise`
  - `rationale`
  - `status`
  - `stage`
  - `trigger_refs`
  - `related_object_ids`
  - `minimum_validation_action`
  - `weakening_signal`
  - `lineage_refs`
- Invariants:
  - hypothesis is a derived reasoning object, not a source fact object
  - hypothesis promotion/reject/defer transitions remain program-controlled
  - finalized hypothesis lineage must remain queryable back to pool/candidate/round state when multi-agent flow is used

### 6.2 HypothesisCandidatePool
- `current_code_symbol`: _none_
- `target_symbol`: `HypothesisCandidatePool`
- `evermemos_target_path`: `src/research_layer/domain/models/research_domain.py`
- `owner_spec`: `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md`
- `status`: `planned`
- Required fields:
  - `pool_id`
  - `workspace_id`
  - `goal_summary`
  - `trigger_refs`
  - `generation_mode`
  - `pool_status`
  - `top_k`
  - `current_round_number`
  - `generation_job_id`
- Invariants:
  - one pool belongs to exactly one workspace
  - one pool stores one frozen trigger set snapshot
  - pool lifecycle is append-only by rounds; past rounds must remain replayable

### 6.3 HypothesisCandidate
- `current_code_symbol`: _none_
- `target_symbol`: `HypothesisCandidate`
- `evermemos_target_path`: `src/research_layer/domain/models/research_domain.py`
- `owner_spec`: `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md`
- `status`: `planned`
- Required fields:
  - `candidate_id`
  - `workspace_id`
  - `pool_id`
  - `title`
  - `statement`
  - `rationale`
  - `testability_hint`
  - `novelty_hint`
  - `candidate_status`
  - `current_elo`
  - `origin_round_number`
- Invariants:
  - every candidate belongs to exactly one pool
  - pruned/finalized terminal states must remain immutable after persistence
  - candidate identity must remain stable across review, match, and search-tree references

### 6.4 HypothesisRound
- `current_code_symbol`: _none_
- `target_symbol`: `HypothesisRound`
- `evermemos_target_path`: `src/research_layer/domain/models/research_domain.py`
- `owner_spec`: `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md`
- `status`: `planned`
- Required fields:
  - `round_id`
  - `workspace_id`
  - `pool_id`
  - `round_number`
  - `round_status`
  - `strategy_summary`
  - `started_at`
  - `completed_at`
- Invariants:
  - round numbers are unique within a pool
  - a round must preserve generation/reflection/ranking/evolution/meta-review lineage refs

### 6.5 HypothesisReview
- `current_code_symbol`: _none_
- `target_symbol`: `HypothesisReview`
- `evermemos_target_path`: `src/research_layer/domain/models/research_domain.py`
- `owner_spec`: `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md`
- `status`: `planned`
- Required fields:
  - `review_id`
  - `workspace_id`
  - `pool_id`
  - `candidate_id`
  - `round_id`
  - `review_type`
  - `review_summary`
  - `review_status`
  - `weakness_refs`
- Invariants:
  - every review targets one candidate in one round
  - review output must remain structured enough to support weakest-step and prune decisions

### 6.6 HypothesisMatch
- `current_code_symbol`: _none_
- `target_symbol`: `HypothesisMatch`
- `evermemos_target_path`: `src/research_layer/domain/models/research_domain.py`
- `owner_spec`: `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md`
- `status`: `planned`
- Required fields:
  - `match_id`
  - `workspace_id`
  - `pool_id`
  - `round_id`
  - `left_candidate_id`
  - `right_candidate_id`
  - `winner_candidate_id`
  - `loser_candidate_id`
  - `elo_before`
  - `elo_after`
  - `judge_summary`
- Invariants:
  - every match belongs to exactly one round
  - winner/loser decision must be attributable to one compare action
  - Elo change history must remain replayable

### 6.7 HypothesisEvolution
- `current_code_symbol`: _none_
- `target_symbol`: `HypothesisEvolution`
- `evermemos_target_path`: `src/research_layer/domain/models/research_domain.py`
- `owner_spec`: `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md`
- `status`: `planned`
- Required fields:
  - `evolution_id`
  - `workspace_id`
  - `pool_id`
  - `source_candidate_id`
  - `evolved_candidate_id`
  - `round_id`
  - `evolution_type`
  - `change_summary`
- Invariants:
  - every evolved candidate must preserve explicit lineage to its source candidate
  - evolution cannot silently replace an existing candidate identity

### 6.8 HypothesisMetaReview
- `current_code_symbol`: _none_
- `target_symbol`: `HypothesisMetaReview`
- `evermemos_target_path`: `src/research_layer/domain/models/research_domain.py`
- `owner_spec`: `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md`
- `status`: `planned`
- Required fields:
  - `meta_review_id`
  - `workspace_id`
  - `pool_id`
  - `round_id`
  - `summary`
  - `recurring_issues`
  - `continue_hint`
- Invariants:
  - meta-review summarizes one completed round
  - continue/stop guidance must remain attributable to recorded pool state

### 6.9 HypothesisProximityEdge
- `current_code_symbol`: _none_
- `target_symbol`: `HypothesisProximityEdge`
- `evermemos_target_path`: `src/research_layer/domain/models/research_domain.py`
- `owner_spec`: `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md`
- `status`: `planned`
- Required fields:
  - `proximity_edge_id`
  - `workspace_id`
  - `pool_id`
  - `left_candidate_id`
  - `right_candidate_id`
  - `similarity_score`
  - `pairing_priority`
- Invariants:
  - proximity edges are derived ranking aids, not canonical scientific claims
  - pairing priority must remain reproducible from stored similarity state

### 6.10 HypothesisSearchTreeNode
- `current_code_symbol`: _none_
- `target_symbol`: `HypothesisSearchTreeNode`
- `evermemos_target_path`: `src/research_layer/domain/models/research_domain.py`
- `owner_spec`: `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md`
- `status`: `planned`
- Required fields:
  - `search_node_id`
  - `workspace_id`
  - `pool_id`
  - `candidate_id`
  - `round_id`
  - `parent_node_id`
  - `visit_count`
  - `value_score`
  - `branch_status`
- Invariants:
  - tree nodes must remain replayable as search-state records
  - pruned nodes cannot be silently deleted

### 6.11 HypothesisSearchTreeEdge
- `current_code_symbol`: _none_
- `target_symbol`: `HypothesisSearchTreeEdge`
- `evermemos_target_path`: `src/research_layer/domain/models/research_domain.py`
- `owner_spec`: `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md`
- `status`: `planned`
- Required fields:
  - `search_edge_id`
  - `workspace_id`
  - `pool_id`
  - `parent_node_id`
  - `child_node_id`
  - `action_type`
  - `action_summary`
- Invariants:
  - each search edge must represent one explicit expansion or continuation action
  - search edges must not imply canonical graph edges in research graph state

### 6.12 ReasoningChain
- `current_code_symbol`: _none_
- `target_symbol`: `ReasoningChain`
- `evermemos_target_path`: `src/research_layer/domain/models/research_domain.py`
- `owner_spec`: `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md`
- `status`: `planned`
- Required fields:
  - `reasoning_chain_id`
  - `workspace_id`
  - `owner_type`
  - `owner_id`
  - `subgraph_ref`
  - `step_ids`
  - `chain_status`
- Invariants:
  - a reasoning chain must be attributable to one hypothesis or route projection
  - ordered steps are mandatory; chain cannot degrade into an unordered node bag

### 6.13 ReasoningStep
- `current_code_symbol`: _none_
- `target_symbol`: `ReasoningStep`
- `evermemos_target_path`: `src/research_layer/domain/models/research_domain.py`
- `owner_spec`: `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md`
- `status`: `planned`
- Required fields:
  - `reasoning_step_id`
  - `workspace_id`
  - `reasoning_chain_id`
  - `step_order`
  - `step_type`
  - `statement`
  - `graph_refs`
  - `evidence_refs`
- Invariants:
  - step order must be unique within a chain
  - every step must be traceable to graph/evidence context or explicitly marked as inferred

### 6.14 ReasoningSubgraph
- `current_code_symbol`: _none_
- `target_symbol`: `ReasoningSubgraph`
- `evermemos_target_path`: `src/research_layer/domain/models/research_domain.py`
- `owner_spec`: `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md`
- `status`: `planned`
- Required fields:
  - `subgraph_id`
  - `workspace_id`
  - `version_id`
  - `node_ids`
  - `edge_ids`
  - `evidence_refs`
  - `query_context`
- Invariants:
  - subgraph is a scoped reasoning view, not canonical graph truth
  - subgraph membership must remain attributable to one query/request context

### 6.15 MechanismRevision
- `current_code_symbol`: _none_
- `target_symbol`: `MechanismRevision`
- `evermemos_target_path`: `src/research_layer/domain/models/research_domain.py`
- `owner_spec`: `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md`
- `status`: `planned`
- Required fields:
  - `mechanism_revision_id`
  - `workspace_id`
  - `owner_type`
  - `owner_id`
  - `trigger_ref`
  - `revision_summary`
  - `revision_status`
- Invariants:
  - a mechanism revision must reference the validation or failure artifact that triggered it
  - revision state cannot directly overwrite canonical fact objects without explicit downstream transitions

### 6.16 WeakestStepAssessment
- `current_code_symbol`: _none_
- `target_symbol`: `WeakestStepAssessment`
- `evermemos_target_path`: `src/research_layer/domain/models/research_domain.py`
- `owner_spec`: `FIRST_TIER_PAPER_FAITHFUL_MULTI_AGENT_PLAN.md`
- `status`: `planned`
- Required fields:
  - `assessment_id`
  - `workspace_id`
  - `owner_type`
  - `owner_id`
  - `reasoning_step_id`
  - `assessment_reason`
  - `validation_priority`
- Invariants:
  - weakest-step outputs are derived assessment records, not direct graph mutations
  - one assessment must always resolve to one concrete reasoning step

### 6.17 Candidate
- `current_code_symbol`: _none as domain model_
- `target_symbol`: `Candidate`
- `evermemos_target_path`: `src/research_layer/domain/models/research_domain.py`
- `owner_spec`: `LLM_REMEDIATION_PLAN_REVISED.md`
- `status`: `planned`
- `transitional_existing_representations`: `api.schemas.source.CandidateRecord`, `api/controllers/_state_store.py:candidates`
- `status_note`: `planned` here refers only to the canonical domain object; it does not deny the existing transitional API/store record already used by current source/candidate endpoints.
- Required fields:
  - `candidate_id`
  - `workspace_id`
  - `candidate_type`
  - `status`
  - `label`
  - `body`
  - `evidence_quote`
  - `source_location`
  - `confidence_hint`
  - `candidate_batch_id`
  - `extraction_job_id`
  - `source_id`
- Invariants:
  - candidate cannot enter graph directly
  - candidate state is terminal after confirm/reject

### 6.18 RouteBranch
- `current_code_symbol`: _none_
- `target_symbol`: `RouteBranch`
- `evermemos_target_path`: `src/research_layer/domain/models/research_domain.py`
- `owner_spec`: `FAILURE_RECOMPUTE_VERSION_DIFF_SPEC.md`
- `status`: `planned`
- Required fields:
  - `branch_id`
  - `workspace_id`
  - `branch_type`
  - `version_id`
- Invariants:
  - `alternative_route` and `gap_marker` variants follow the owning failure spec

### 6.19 EvidenceRef
- `current_code_symbol`: _none_
- `target_symbol`: `EvidenceRef`
- `evermemos_target_path`: `src/research_layer/domain/models/research_domain.py`
- `owner_spec`: `SCHOLARLY_EVIDENCE_SPEC.md`
- `status`: `planned`
- Required fields:
  - `evidence_ref_id`
  - `workspace_id`
  - `ref_layer`
  - `authority_tier`
  - `locator`
- Invariants:
  - EvidenceRef is a first-class scholarly citation object

### 6.20 WorkspaceTemplate
- `current_code_symbol`: _none_
- `target_symbol`: `WorkspaceTemplate`
- `evermemos_target_path`: `src/research_layer/domain/models/research_domain.py`
- `owner_spec`: `COLD_START_WORKSPACE_SPEC.md`
- `status`: `planned`
- Required fields:
  - `template_id`
  - `template_type`
  - `research_question`
  - `bootstrap_policy`
  - `expected_outputs`
- Invariants:
  - template is not allowed to pre-write final routes, hypotheses, or packages

### 6.21 WorkspaceBootstrapJob
- `current_code_symbol`: _none_
- `target_symbol`: `WorkspaceBootstrapJob`
- `evermemos_target_path`: `src/research_layer/domain/models/research_domain.py`
- `owner_spec`: `COLD_START_WORKSPACE_SPEC.md`
- `status`: `planned`
- Required fields:
  - `job_id`
  - `workspace_id`
  - `template_id`
  - `bootstrap_status`
  - `current_phase`
- Invariants:
  - current phase must follow the frozen bootstrap phase sequence

### 6.22 ClaimRef
- `current_code_symbol`: _none_
- `target_symbol`: `ClaimRef`
- `evermemos_target_path`: `src/research_layer/domain/models/research_domain.py`
- `owner_spec`: `UNIFIED_CONTRACTS_SPEC.md`
- `status`: `planned`
- Required fields:
  - `claim_ref_id`
  - `workspace_id`
  - `source_id`
  - `candidate_batch_id`
  - `locator`
- Invariants:
  - claim/span-level provenance remains optional and must not be treated as existing runtime capability yet

### 6.23 ProvenanceRef
- `current_code_symbol`: _none_
- `target_symbol`: `ProvenanceRef`
- `evermemos_target_path`: `src/research_layer/domain/models/research_domain.py`
- `owner_spec`: `UNIFIED_CONTRACTS_SPEC.md`
- `status`: `planned`
- Required fields:
  - `provenance_ref_id`
  - `workspace_id`
  - `source_id`
  - `trace_refs`
- Invariants:
  - provenance references are lineage containers and cannot mutate canonical fact objects directly

### 6.24 ValidationResult
- `current_code_symbol`: _none_
- `target_symbol`: `ValidationResult`
- `evermemos_target_path`: `src/research_layer/domain/models/research_domain.py`
- `owner_spec`: `UNIFIED_CONTRACTS_SPEC.md`
- `status`: `planned`
- Required fields:
  - `validation_result_id`
  - `workspace_id`
  - `validation_id`
  - `outcome`
  - `recorded_at`
- Invariants:
  - result objects are append-only evidence of validation outcomes
  - route/hypothesis/package state transitions must consume structured validation result semantics

## 7. Enum Baseline
Current enum implementation lives in `src/research_layer/domain/enums/research_enums.py`.
This document freezes the canonical enum names; any expansion must update both files in one change.

Key canonical enums:
- `ResearchSourceType`
- `ResearchSourceStatus`
- `EvidenceType`
- `AssumptionType`
- `AssumptionStatus`
- `ConflictSeverity`
- `FailureSeverity`
- `ValidationLevel`
- `NoveltyLevel`
- `RouteStatus`
- `GraphNodeType`
- `VisibilityLevel`
- `GraphNodeStatus`
- `GraphEdgeType`
- `GraphEdgeStatus`

## 8. Implementation Notes
- Current code symbols must be preferred over invented replacement names.
- `planned` target objects are part of the frozen target vocabulary but require explicit code introduction later.
- Specialized specs remain the owner of behavior. This document is the owner of vocabulary and invariants.

## 9. Unified Contract Object Sync (2026-04-08)

### 9.1 Provenance Vocabulary
Existing minimum provenance-bearing references remain:
1. `source_id`
2. `candidate_batch_id`
3. `object_ref_type/object_ref_id`
4. async correlation (`job_id`, `request_id`) through API/store links

Planned-only additions (must remain `planned` until runtime exists):
1. `ClaimRef` (claim/span-level provenance handle)
2. `ProvenanceRef` aggregate type for cross-object lineage packing

### 9.2 Validation Vocabulary
Existing domain baseline:
1. `ValidationAction` (existing, canonical)

Planned canonical addition:
1. `ValidationResult` object (separate from `ValidationAction.latest_*` projection fields)

Invariant:
1. Validation-driven route/hypothesis/package transitions must remain program-controlled state transitions.

### 9.3 Confidence Vocabulary
Existing route-level confidence domain fields remain canonical:
1. `confidence_score`
2. `confidence_grade`
3. `top_factors`
4. `next_validation_action_id`

Invariant:
1. Confidence state in domain objects is deterministic program output, not LLM-authored state.

## 10. Six Capability Derived Objects (existing, non-canonical)

The six capability additions introduce no new canonical truth objects. They add derived/read/export/orchestration records at API/service boundaries:

1. `GraphReport`: derived view over graph nodes, edges, failures, validations, and versions.
2. `ResearchQueryTool`: whitelisted read tool descriptor for graph/query/route/hypothesis/package/version-diff/report.
3. `RawMaterialBootstrapItem`: import result containing `source_id`, pending `candidate_ids`, provenance, and optional job refs.
4. `ResearchCommandStep`: auditable orchestration step with resource refs and job refs.
5. `ResearchExport`: public-safe rendered payload for graph/package export.
6. `LocalFirstProviderSelection`: runtime provider resolution policy that prefers configured local backend when `RESEARCH_FEATURE_LOCAL_FIRST_ENABLED=true`.

Invariants:
1. Derived objects cannot become canonical route score, graph state, hypothesis status, or package publish state.
2. Raw bootstrap candidates stay `pending` until existing confirmation flow materializes canonical objects.
3. Query/report/export services are read-only except for structured observability events.
4. Command execution may mutate state only by invoking existing services with their existing rules.
5. Local-first changes semantic generation backend selection only; deterministic scoring and state transitions remain program controlled.
