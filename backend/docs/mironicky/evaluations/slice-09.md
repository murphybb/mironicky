---
record_type: evaluator_result
slice_id: slice_9
status: evaluator_pass
allowed_to_start_next_slice: true
blocking_status: cleared
---

# Slice 9 Evaluator Record

## Result
PASS

## Final status
- `slice_9`: `evaluator_pass`
- Allowed to enter Slice 10: `YES`

## Scope
Slice 9 only: Hypothesis Engine.
Validated surfaces:
- hypothesis trigger detector
- hypothesis service
- novelty typing
- minimum validation action generation
- weakening signal generation
- hypothesis generate/promote/reject APIs
- async job contract (`job status` + `result_ref`)

## Preconditions
- `docs/mironicky/slice_status.json`: `slice_9=developer_complete`
- `docs/mironicky/slice_status.json`: `slice_8=evaluator_pass`
- `docs/mironicky/handoffs/slice-09.md` exists and was read

## Evidence

### Automated validation
Command:
`$env:PYTHONPATH='src'; uv run pytest tests/unit/research_layer/test_slice9_hypothesis_services.py tests/integration/research_api/test_slice9_hypothesis_engine_flow.py -q`

Result:
- `6 passed in 4.58s`

### Playwright manual validation evidence
Dev Console URL:
- `http://127.0.0.1:1995/api/v1/research/dev-console`

Manual path executed (real button flow):
1. `Load Hypothesis Triggers` and verified available trigger sources.
2. `Generate Hypothesis` and captured async job payload.
3. `Load Hypothesis` and verified candidate structure with `novelty_typing`, `minimum_validation_action`, `weakening_signal`.
4. `Promote Hypothesis` and observed status change to `promoted_for_validation` with decision source fields.
5. Regenerated hypothesis and `Reject Hypothesis`, observed status `rejected` with decision source fields.
6. `Load Job Status` and verified terminal `succeeded` + `result_ref(resource_type=hypothesis)`.
7. Error path A: duplicate `Reject Hypothesis` -> `409 research.invalid_state`.
8. Error path B: illegal trigger id generate -> `400 research.invalid_request`; backend job reached `failed`.

Artifacts:
- `output/playwright/slice9-trigger-view.png`
- `output/playwright/slice9-generate-job.png`
- `output/playwright/slice9-hypothesis-candidate.png`
- `output/playwright/slice9-promote-status.png`
- `output/playwright/slice9-reject-status.png`
- `output/playwright/slice9-job-terminal.png`
- `output/playwright/slice9-error-invalid-state.png`
- `output/playwright/slice9-error-invalid-trigger.png`

### API / job / hypothesis cross-check
- Trigger list cross-check (`workspace_id=ws_slice9_eval`) returned only legal types:
  - `conflict`, `failure`, `gap`, `weak_support`
- Successful generation jobs:
  - `job_b473dbf46e30 -> result_ref(hypothesis_fb28da4d8902)`
  - `job_191b944326df -> result_ref(hypothesis_1b91cee0affe)`
- Hypothesis status/decision:
  - `hypothesis_fb28da4d8902`: `promoted_for_validation`, source `manual/research_dev_console`
  - `hypothesis_1b91cee0affe`: `rejected`, source `manual/research_dev_console`
- Failed generation job (illegal trigger):
  - `job_ee1e5672ce9e`: `status=failed`, structured error, `result_ref=null`

### Minimal white-box observability checks
SQLite (`data/research_slice2.sqlite3`) verified:
- `hypotheses` persisted structured fields and decision provenance:
  - `trigger_refs_json`
  - `minimum_validation_action_json`
  - `weakening_signal_json`
  - `decision_source_type/decision_source_ref/decided_request_id`
- `jobs` persisted hypothesis async contract:
  - success rows with `result_ref_type=hypothesis`
  - failed row with structured `error_json`
- `research_events` includes:
  - `hypothesis_generation_started`
  - `hypothesis_generation_completed` (completed + failed)
  - `hypothesis_promoted`
  - `hypothesis_rejected`
  - `job_failed` (failed generation path)
- Route conclusion was not overwritten by hypothesis text (`route_conclusion_overlap_count=0`).

## Findings (ordered by severity)
1. No blocking findings.
2. Non-blocking observation: generate endpoint currently executes inline and returns terminal `succeeded` in accepted response, but job lifecycle and `result_ref` contract are complete and traceable.

## Blocking / non-blocking judgement
- Blocking: NONE
- Non-blocking: 1 low-severity observation

## Decision
Allowed to enter Slice 10 = YES
