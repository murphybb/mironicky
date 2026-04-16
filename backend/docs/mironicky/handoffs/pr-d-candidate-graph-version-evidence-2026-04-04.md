# PR-D Candidate Confirm + Graph + Version Evidence (2026-04-04)

## 1. Scope
This evidence package covers PR-D only:
- candidate confirm/reject real state transition
- confirmed candidate -> graph node/edge materialization
- graph version creation + diff payload + query-back
- graph/version/events persistence and traceability
- direct contract/failure/no-bypass tests for PR-D chain

## 2. Full No-Bypass Chain Evidence
Chain executed from extraction outputs (no manual candidate/graph/version seed):
`source -> extract -> candidate_batch/result_ref -> confirm -> graph -> version`

Note: the extraction call in this evidence uses timeout+fallback headers (`x-research-llm-failure-mode=timeout`, `x-research-llm-allow-fallback=true`). This is degraded extraction output, not live provider path, but still upstream extraction output (not manual seed).

### 2.1 Chain IDs
- workspace_id: `ws_prd_evidence_chain`
- source_id: `src_0fa0f5a3a4df`
- extract job_id: `job_0512bb806ceb`
- extract result_ref:
  - resource_type: `candidate_batch`
  - resource_id: `batch_989cd0a47e9d`
- candidate_batch_id: `batch_989cd0a47e9d`
- candidate_id: `cand_cd65a59685a7`
- formal_object_type/formal_object_id: `evidence` / `evi_370d370d4762`
- confirmed graph node_id: `node_69c8b2e84eb5`
- confirmed graph edge_ids: `[]`
- graph_version_id: `ver_9b2098109397`
- version diff change_type: `candidate_confirm_materialization`

### 2.2 Event Chain (request_id=`req_prd_confirm`)
Observed ordered events:
1. `candidate_confirmed`
2. `graph_materialization_completed`
3. `graph_version_created`

## 3. Failure Semantics Samples
### 3.1 Workspace mismatch
- request_id: `req_prd_fail_workspace`
- endpoint: `POST /api/v1/research/candidates/confirm`
- status_code: `409`
- error_code: `research.conflict`
- message: `workspace_id does not match candidate ownership`
- details.candidate_id: `cand_cd65a59685a7`

### 3.2 Forced graph/version persistence failure rollback
- request_id: `req_prd_persist_fail`
- endpoint: `POST /api/v1/research/candidates/confirm`
- status_code: `409`
- error_code: `research.version_diff_unavailable`
- details.reason: `forced version persistence failure`
- rollback invariants observed:
  - candidate status remains `pending`
  - confirmed formal object rows: `0`
  - graph_nodes rows (workspace): `0`
  - graph_edges rows (workspace): `0`
  - graph_versions rows (workspace): `0`
  - graph_workspaces rows (workspace): `0`
  - success events (`candidate_confirmed`/`graph_materialization_completed`/`graph_version_created`): `0`
  - failure event (`candidate_confirmation_failed`): `1`

## 4. Persistence Snapshots
### 4.1 Candidate record
- candidate_id: `cand_cd65a59685a7`
- workspace_id: `ws_prd_evidence_chain`
- source_id: `src_0fa0f5a3a4df`
- candidate_type: `evidence`
- status: `confirmed`
- candidate_batch_id: `batch_989cd0a47e9d`
- extraction_job_id: `job_0512bb806ceb`

### 4.2 Graph node/edge records
- graph_nodes:
  - node_id: `node_69c8b2e84eb5`
  - node_type: `evidence`
  - object_ref_type/object_ref_id: `evidence` / `evi_370d370d4762`
  - status: `active`
- graph_edges: `[]` for this evidence-only sample

### 4.3 Graph version + diff payload
- graph_versions:
  - version_id: `ver_9b2098109397`
  - trigger_type: `confirm_candidate`
  - change_summary: `confirm candidate cand_cd65a59685a7`
  - request_id: `req_prd_confirm`
- diff payload key fields:
  - change_type: `candidate_confirm_materialization`
  - candidate_id: `cand_cd65a59685a7`
  - formal_object_type/formal_object_id: `evidence` / `evi_370d370d4762`
  - added.nodes: [`node_69c8b2e84eb5`]
  - added.edges: `[]`

## 5. Test Commands and Results
All commands executed from repo root: `C:\Users\murphy\Desktop\EverMemOS-latest`

1. PR-D targeted suite:

```powershell
$env:PYTHONPATH='src'; uv run pytest \
  tests/unit/research_layer/test_slice4_candidate_confirmation_service.py \
  tests/integration/research_api/test_slice4_candidate_confirmation_flow.py \
  tests/unit/research_layer/test_slice5_graph_services.py \
  tests/integration/research_api/test_slice5_graph_foundation_flow.py \
  tests/e2e/research_workspace/test_slice12_e2e_closed_loops.py::test_slice12_prd_no_bypass_source_extract_confirm_graph_version_chain \
  -q
```

- result: `26 passed, 35 warnings`
- same command rerun result: `26 passed, 35 warnings`

2. Atomic failure regression checks:

```powershell
$env:PYTHONPATH='src'; uv run pytest \
  tests/unit/research_layer/test_slice4_candidate_confirmation_service.py::test_confirm_graph_version_persistence_failure_is_explicit \
  tests/integration/research_api/test_slice4_candidate_confirmation_flow.py::test_confirm_persistence_failure_returns_explicit_error_and_leaves_no_residual_state \
  -q
```

- result: `2 passed`

## 6. Boundary Statements
1. PR-D implementation does **not** call direct LLM/provider code paths in confirm/graph/version logic.
2. PR-D no-bypass evidence consumes upstream extraction outputs (`job/result_ref/candidate_batch`) before confirm.
3. No manual insertion of candidate/graph/version core business results was used as completion evidence.
4. The PR-D scope does not include route/hypothesis/package/cold-start behavior.
