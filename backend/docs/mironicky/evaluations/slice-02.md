# Slice 2 Evaluation Record

## Status

- Result: `PASS`
- Final status: `evaluator_pass`

## Scope

Slice 2 closed in this pass:

- route ownership contract alignment (`GET /routes/{route_id}`)
- malformed JSON failure semantics alignment (`research.invalid_request` / 400)
- research error envelope strictness
- Slice 2 API contract test strictness (no dual-shape tolerance)
- Candidate planned/existing two-layer clarification consistency in docs

## Verification Commands

- `PYTHONPATH=src pytest -q tests/unit/research_layer/test_slice1_domain_models.py`
- `PYTHONPATH=src pytest -q tests/unit/research_layer/test_slice2_api_schemas.py`
- `PYTHONPATH=src pytest -q tests/integration/research_api/test_slice2_research_api_contract.py`
- `PYTHONPATH=src python - <<PY ... (manual malformed-json + unhandled exception envelope sampling) ... PY`

Observed results:

- unit/domain: `30 passed`
- unit/schema: `9 passed`
- integration/contract: `11 passed`

## Failure Payload Samples

### Sample A - malformed JSON -> `research.invalid_request` / 400

Endpoint:

- `POST /api/v1/research/routes/generate`

Response sample:

```json
{
  "error_code": "research.invalid_request",
  "message": "request validation failed",
  "details": {
    "errors": [
      {
        "loc": ["body"],
        "msg": "invalid json body",
        "details": {"line": 1, "column": 17, "pos": 16}
      }
    ]
  },
  "trace_id": "trace_1dea02597664",
  "request_id": "req_2f3c92678834",
  "provider": null,
  "degraded": false
}
```

### Sample B - unhandled exception -> explicit research envelope / 500

Endpoint:

- `GET /api/v1/research/_test/unhandled`

Response sample:

```json
{
  "error_code": "research.recompute_failed",
  "message": "Internal server error",
  "details": {"exception_type": "RuntimeError"},
  "trace_id": "trace_914f228c44bb",
  "request_id": "req_b70fe23f172a",
  "provider": null,
  "degraded": false
}
```

## Alignment Diff Checklist

- [x] Restored workspace ownership contract for `GET /api/v1/research/routes/{route_id}` (400/409 semantics now explicit and tested).
- [x] Replaced controller-level `await request.json()` + `parse_model(...)` with shared `parse_request_model(...)` in route/failure/hypothesis/retrieval POST entries.
- [x] Removed dual-shape tolerance (`payload.get("detail", payload)`) in Slice 2 contract tests; tests now assert the canonical research envelope only.
- [x] Added malformed JSON contract tests for route/failure/hypothesis/retrieval.
- [x] Added route detail workspace ownership tests (`200` owner, `409` mismatch, `400` missing/invalid workspace).
- [x] Corrected async extraction contract narration: extraction success `result_ref.resource_type` is `candidate_batch` (not source).

## Async Contract Correction

For source extraction flow:

- `source import -> source extract (202) -> job status terminal`
- extraction success `result_ref.resource_type` is `candidate_batch`
- extraction result is retrieved from `/sources/{source_id}/extraction-results/{candidate_batch_id}`

## Candidate Planned/Existing Clarification

- `DOMAIN_MODEL.md`: canonical `Candidate` remains `planned`.
- `API_SPEC.md` + `STORAGE_SCHEMA.md`: existing `CandidateRecord`/`candidates` are transitional API/store representations.
- Transitional existing records do not upgrade canonical domain `Candidate` to existing.

## Explicit Statement

- This window did **not** connect live LLM.
- This window did **not** fabricate LLM behavior.
