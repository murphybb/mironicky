---
record_type: developer_handoff
track_id: track_3_hypothesis_inbox_defer
status: developer_complete
next_required_action: run_evaluator_for_track_3
allowed_to_start_next_track: false
---

# Track 3 Developer Handoff

## Status

- Current result: `DEVELOPER_COMPLETE`
- Blocking status: `awaiting_evaluator`

## Implemented Scope (Track 3 Only)

- Added workspace inbox API:
  - `GET /api/v1/research/hypotheses?workspace_id=...`
- Added defer API:
  - `POST /api/v1/research/hypotheses/{hypothesis_id}/defer`
- Unified hypothesis state machine semantics in service layer:
  - Allowed transitions:
    - `candidate -> promoted_for_validation | rejected | deferred`
    - `deferred -> promoted_for_validation | rejected`
  - Disallowed transitions:
    - `deferred -> deferred`
    - any transition from `promoted_for_validation` / `rejected`
- Defer is persisted in SQLite hypothesis store (`status=deferred`) and survives refresh/read.
- Updated API schemas and OpenAPI exposure for hypothesis inbox/defer.
- Updated `docs/mironicky/API_SPEC.md` for Track 3 contract sync.

## Explicitly Not Implemented in This Track

- Track 4/5/6 capabilities (regression contract sync bundle, frontend readiness matrix, memory vault controlled actions).
- Any frontend local-state fallback path.

## Verification Summary

- Unit:
  - `tests/unit/research_layer/test_slice2_api_schemas.py`
  - `tests/unit/research_layer/test_slice9_hypothesis_services.py`
- Integration:
  - `tests/integration/research_api/test_slice2_research_api_contract.py`
  - `tests/integration/research_api/test_slice9_hypothesis_engine_flow.py`
- All above executed with `PYTHONPATH=src`.

## Known Risks

- `GET /api/v1/research/hypotheses` currently returns full hypothesis payload for inbox items; if frontend later requires lightweight list DTO, contract evolution should use non-breaking additive fields.
