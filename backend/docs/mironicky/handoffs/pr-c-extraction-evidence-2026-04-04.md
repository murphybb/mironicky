# PR-C Extraction Evidence (2026-04-04)

## 1. Scope
This evidence package covers PR-C only (`Slice 3 extraction real provider`):
- source -> extract -> async job/result_ref -> extraction-results/candidate_batch
- extraction failure semantics and degraded semantics
- extraction prompt ownership and no-bypass assertions

## 2. Real Provider Evidence (Success Sample)
- workspace_id: `ws_prc_success_1`
- source_id: `src_e532c5daff09`
- job_id: `job_3704b75b20ec`
- result_ref:
  - resource_type: `candidate_batch`
  - resource_id: `batch_90824cdd5f0b`
- request_id: `req_prc_success_1`
- provider_backend: `openai`
- provider_model: `MiniMax-M2.5`
- llm_response_id: `chatcmpl-00c68b8a2e72d40aff92e2459e5e370e`
- token usage:
  - prompt_tokens: `446`
  - completion_tokens: `572`
  - total_tokens: `1018`
- extraction result status: `succeeded`
- degraded: `false`
- fallback_used: `false`
- candidate_batch_id: `batch_90824cdd5f0b`
- candidate_count: `6`

Execution event slice (`candidate_extraction_completed`):
- refs: `provider_backend/provider_model/request_id/llm_response_id` all present
- metrics: `prompt_tokens/completion_tokens/total_tokens/fallback_used/degraded` all present

## 3. Explicit Failure Evidence (Forbidden Fallback Case)
- workspace_id: `ws_prc_failure_auth`
- source_id: `src_d164bc996c0b`
- job_id: `job_58758607cdda`
- request_id: `req_prc_failure_auth`
- status: `failed`
- error_code: `research.llm_auth_failed`
- message: `llm provider authentication/config failed`
- details.provider_message: `injected auth_401 failure`
- result_ref: `null`

Event slice:
- `job_failed` emitted with explicit error payload
- final_outcome.status: `failed`

## 4. Degraded / Fallback Evidence (Allowed Fallback Case)
- workspace_id: `ws_prc_degraded_timeout`
- source_id: `src_88b8e813ee27`
- job_id: `job_4da13d2ccb84`
- result_ref:
  - resource_type: `candidate_batch`
  - resource_id: `batch_d0ec025eb127`
- request_id: `req_prc_degraded_timeout`
- extraction result status: `succeeded`
- degraded: `true`
- fallback_used: `true`
- degraded_reason: `research.llm_timeout`
- partial_failure_count: `5`
- candidate_batch_id: `batch_d0ec025eb127`

Event slice (`candidate_extraction_completed`):
- metrics include `fallback_used=true`, `degraded=true`, `degraded_reason=research.llm_timeout`

## 5. Job / ResultRef / Extraction-Results Chain Proof
1. `POST /api/v1/research/sources/import` -> `source_id`
2. `POST /api/v1/research/sources/{source_id}/extract` -> `job_id`
3. `GET /api/v1/research/jobs/{job_id}` -> `result_ref(resource_type=candidate_batch, resource_id=...)`
4. `GET /api/v1/research/sources/{source_id}/extraction-results/{candidate_batch_id}` -> extraction result payload

Verified on all three evidence samples above.

## 6. Tests Executed
All commands run from repo root with `PYTHONPATH=src`.

1. `uv run pytest tests/integration/research_llm/test_live_provider_flows.py tests/integration/research_llm/test_failure_semantics.py tests/integration/research_llm/test_no_bypass_e2e.py tests/integration/research_llm/test_prompt_contracts.py tests/integration/research_api/test_slice3_source_import_extraction.py -q`
- result: `28 passed, 10 warnings`

2. Targeted reruns during iteration:
- `uv run pytest tests/integration/research_llm/test_failure_semantics.py -q` -> `8 passed`
- `uv run pytest tests/integration/research_llm/test_live_provider_flows.py -q` -> `2 passed`
- `uv run pytest tests/integration/research_llm/test_no_bypass_e2e.py::test_no_bypass_full_chain_requires_real_provider_evidence -q` -> `1 passed`
- `uv run pytest tests/integration/research_api/test_slice3_source_import_extraction.py -q` -> `9 passed`

## 7. Ownership / Boundary Statement
1. Extraction prompt ownership has been moved to PR-C scope for:
   - `evidence_extractor_prompt.txt`
   - `assumption_extractor_prompt.txt`
   - `conflict_extractor_prompt.txt`
   - `failure_extractor_prompt.txt`
   - `validation_extractor_prompt.txt`
2. Hypothesis/route prompts were not modified by PR-C:
   - `hypothesis_generation.txt`
   - `route_summary.txt`
3. Extraction mainline was not bypassed:
   - no manual seeding used as completion evidence for candidate/candidate_batch/extraction_results
   - evidence chain is from real source import and real extract execution
