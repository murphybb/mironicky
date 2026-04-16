---
record_type: developer_handoff
track_id: track_2_graph_archive_delete
status: developer_complete
next_required_action: run_evaluator_for_track_2
allowed_to_start_next_track: false
---

# Track 2 Developer Handoff

## Status

- Current result: `DEVELOPER_COMPLETE`
- Blocking status: `awaiting_evaluator`

## Implemented Scope (Track 2 Only)

- Added archive-backed delete endpoints:
  - `DELETE /api/v1/research/graph/nodes/{node_id}`
  - `DELETE /api/v1/research/graph/edges/{edge_id}`
- Delete semantics are soft-delete only (`status=archived`), no physical graph row deletion.
- Archive operations now create a new `GraphVersion` (`trigger_type=manual_archive`) and persist diff payload with `archived` category.
- Workspace latest version is advanced on archive operations, preserving version traceability.
- Added schema contracts: `GraphArchiveRequest`, `GraphArchiveResponse`.
- Added unit and integration tests for archive/delete semantics and OpenAPI exposure.
- Updated `docs/mironicky/API_SPEC.md` with Track 2 archive/delete contract and graph API list.

## Explicitly Not Implemented in This Track

- Track 3/4/5/6 capabilities (hypothesis defer, regression matrix, memory vault controlled actions).
- Any physical delete path for graph nodes/edges.

## Verification Summary

- Unit:
  - `tests/unit/research_layer/test_slice2_api_schemas.py`
  - `tests/unit/research_layer/test_slice8_failure_loop_services.py`
- Integration:
  - `tests/integration/research_api/test_slice2_research_api_contract.py`
  - `tests/integration/research_api/test_slice5_graph_foundation_flow.py`
  - `tests/integration/research_api/test_slice8_failure_recompute_diff_flow.py`
- All above passed with `PYTHONPATH=src`.

## Known Risks

- Current full graph query still returns archived nodes/edges with archived status. Frontend should filter by status according to workbench UX expectations.
- Archive diff payload extends schema with `archived` category; downstream consumers assuming only added/weakened/invalidated should be validated by evaluator.


## post-evaluator fixups

- Blocked PATCH mutation on archived node/edge (409 + research.invalid_state) to prevent archive reopen.
- Replaced graph rebuild hard-delete reset with status demotion (superseded) to keep historical rows.
- Rebuild now skips creating active entities for object refs that have archived node records, keeping delete semantics closed across rebuild.

