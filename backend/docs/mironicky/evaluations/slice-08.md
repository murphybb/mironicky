---
record_type: evaluator_result
slice_id: slice_8
status: evaluator_pass
allowed_to_start_next_slice: true
blocking_status: cleared
---

# Slice 8 Evaluator Record

## Result
PASS

## Final status
- `slice_8`: `evaluator_pass`
- Allowed to enter Slice 9: `YES`

## Scope
Slice 8 only: Failure Loop + Recompute + Version Diff.
Validated surfaces:
- failure attach API
- failure impact service
- branch marker generation
- recompute service
- version store + version diff service
- async job status + `result_ref` backlink

## Preconditions
- `docs/mironicky/slice_status.json`: `slice_8=developer_complete`
- `docs/mironicky/slice_status.json`: `slice_7=evaluator_pass`
- `docs/mironicky/handoffs/slice-08.md` exists and was read

## Evidence

### Automated validation
Command:
`PYTHONPATH=src uv run pytest tests/unit/research_layer/test_slice8_failure_loop_services.py tests/integration/research_api/test_slice8_failure_recompute_diff_flow.py -q`

Result:
- `6 passed in 7.18s`

### Playwright manual validation evidence
Dev Console URL:
- `http://127.0.0.1:1995/api/v1/research/dev-console`

Manual path executed (real button flow):
1. Import/Extract/Confirm -> Build Graph -> Generate Routes -> Load Routes (baseline).
2. `Attach Failure` on node target (`node_61d8f91d939a`) and verified failure detail回读.
3. `Recompute From Failure` with async mode and captured `job_id=job_421818eaf29c`.
4. `Load Job Status` until terminal (`succeeded`) and verified `result_ref = graph_version/ver_15febfb7aeea`.
5. `Load Version Diff` and verified diff payload categories and score deltas.
6. `Load Full Graph` + `Load Routes` and verified node/route/score/version changes.
7. Additional attach on edge target (`edge_2d319f64fa0b`) to verify edge attach semantics.
8. Error path: missing `workspace_id` recompute request -> `research.invalid_request` validation failure.

Artifacts:
- `output/playwright/slice8-before-attach.png`
- `output/playwright/slice8-after-attach.png`
- `output/playwright/slice8-recompute-trigger-job.png`
- `output/playwright/slice8-job-terminal.png`
- `output/playwright/slice8-version-diff.png`
- `output/playwright/slice8-error-missing-workspace.png`

### API / job / version / diff cross-check
- `GET /api/v1/research/jobs/job_421818eaf29c`:
  - `status=succeeded`
  - `result_ref.resource_type=graph_version`
  - `result_ref.resource_id=ver_15febfb7aeea`
- `GET /api/v1/research/versions/ver_15febfb7aeea/diff`:
  - `failure_id=failure_d439a4c4e3a8`
  - contains `added/weakened/invalidated/branch_changes/route_score_changes`
- `GET /api/v1/research/routes?workspace_id=ws_slice3_console`:
  - routes moved to `status=weakened`
  - scores changed (`risk_score` up, `progressability_score` down)
  - `version_id` switched to `ver_15febfb7aeea`
- `GET /api/v1/research/graph/ws_slice3_console`:
  - target node changed to `failed`
  - branch/gap nodes and branch edges present

### Minimal white-box observability checks
SQLite (`data/research_slice2.sqlite3`) verified:
- `failures` persisted both target types:
  - node attach: `failure_d439a4c4e3a8`
  - edge attach: `failure_556f9eedf047`
- `jobs` persisted async contract:
  - `job_421818eaf29c` with `result_ref_type=graph_version`, `result_ref_id=ver_15febfb7aeea`
- `graph_versions` persisted diff payload for `ver_15febfb7aeea`
- `research_events` includes:
  - `failure_attached`
  - `recompute_started`
  - `recompute_completed`
  - `diff_created`
  - plus scoring events tied to same `request_id`

## Findings (ordered by severity)
1. No blocking findings.
2. Low: `added.nodes/added.edges` in observed recompute diff were empty while branch additions were expressed via `branch_changes`; contract satisfied but category semantics may need future clarification.

## Blocking / non-blocking judgement
- Blocking: NONE
- Non-blocking: 1 low-severity observation

## Decision
Allowed to enter Slice 9 = YES
