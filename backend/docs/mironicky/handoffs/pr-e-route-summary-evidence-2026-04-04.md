# PR-E Route Generation + Route Summary Evidence (2026-04-04)

## 1. Scope
This evidence package covers PR-E only:
1. confirmed graph/version -> route generation -> route persistence -> route preview/list -> route summary
2. route summary real LLM call via PR-B substrate
3. degraded fallback semantics for route summary
4. `route_edge_ids_json` persisted canonical source wiring
5. route prompt ownership and route-focused test evidence

## 2. Real LLM Success Sample
Request/chain:
- workspace_id: `ws_pre_success`
- request_id: `req_pre_success_1`
- route_id: `route_257264f30153`
- version_id: `ver_855a29b728fc`

Route sample:
- summary_generation_mode: `llm`
- provider_backend: `openai`
- provider_model: `MiniMax-M2.5`
- llm_response_id: `chatcmpl-9c15914019cb6de0fe9abc46af3b5722`
- usage:
  - prompt_tokens: `1138`
  - completion_tokens: `721`
  - total_tokens: `1859`
- summary: present (non-empty)
- route_edge_ids_json snapshot: `[]`

Execution summary excerpt (`route_generation_completed`):
- refs.request_id: `req_pre_success_1`
- refs.llm_response_id: `chatcmpl-b9b87ada99197f97e94e843a56f855ca`
- refs.provider_backend/provider_model: `openai` / `MiniMax-M2.5`
- metrics.prompt_tokens/completion_tokens/total_tokens: `2270 / 1381 / 3651`
- metrics.fallback_used/degraded: `false / false`

## 3. Degraded Fallback Sample
Request/chain:
- workspace_id: `ws_pre_degraded`
- request_id: `req_pre_degraded`
- route_id: `route_3c3d3fa2de51`
- version_id: `ver_ec94d5526095`

Route sample:
- summary_generation_mode: `degraded_fallback`
- degraded: `true`
- fallback_used: `true`
- degraded_reason: `research.llm_timeout`
- summary: present (non-empty fallback summary)
- route_edge_ids_json snapshot: `[]`

Execution summary excerpt (`route_generation_completed`):
- refs.request_id: `req_pre_degraded`
- refs.provider_backend/provider_model: `unknown` / ``
- refs.llm_response_id: ``
- metrics.prompt_tokens/completion_tokens/total_tokens: `0 / 0 / 0`
- metrics.fallback_used/degraded/degraded_reason: `true / true / research.llm_timeout`

## 4. `route_edge_ids_json` Canonical Wiring Evidence
1. Storage schema and store methods now persist/read `routes.route_edge_ids_json`.
2. Route preview `trace_refs.route_edge_ids` is read from persisted route record.
3. Unit contract test verifies persistence/readback:
   - `tests/unit/research_layer/test_slice7_route_engine.py::test_route_edge_ids_json_is_persisted_as_canonical_source`
4. Current live sample routes are atomic (no route edge traversal), so persisted value is `[]`; this is explicit persisted canonical state, not trace-only echo.

## 5. Route Prompt Ownership (PR-E)
Owned prompt file:
- `src/research_layer/prompts/route_summary.txt`

PR-E changes:
1. strict structured JSON schema (`summary`, `key_strengths`, `key_risks`, `open_questions`, `node_refs`)
2. explicit input context placeholders
3. anti-fabrication constraints for nodes/edges/evidence
4. parser/schema/preview alignment with route summary contract
5. strict parser guard: unknown `node_refs` now fail with `research.llm_invalid_output` (no silent filtering)

## 6. Test Commands and Results
Run from repo root `C:\Users\murphy\Desktop\EverMemOS-latest`.

1. Unit + API contract tests:
```powershell
$env:PYTHONPATH='src'; uv run pytest \
  tests/unit/research_layer/test_slice7_route_engine.py \
  tests/integration/research_api/test_slice7_route_generation_flow.py -q
```
- result: `9 passed`

2. Route failure semantics tests:
```powershell
$env:PYTHONPATH='src'; uv run pytest \
  tests/integration/research_llm/test_failure_semantics.py -k "route_summary" -q
```
- result: `3 passed, 12 deselected`

3. Live route summary tests:
```powershell
$env:PYTHONPATH='src'; uv run pytest \
  tests/integration/research_llm/test_live_route_summary.py -q
```
- result: `2 passed`

4. Route no-bypass integration/e2e test:
```powershell
$env:PYTHONPATH='src'; uv run pytest \
  tests/integration/research_llm/test_no_bypass_e2e.py::test_no_bypass_full_chain_requires_real_provider_evidence -q
```
- result: `1 passed`

## 7. Required Declarations
1. route summary prompt ownership has moved to PR-E (`route_summary.txt`).
2. route generation/ranking/persistence remain program-controlled; LLM is used only for route summary.
3. provider failures are explicit (error or explicit degraded fallback), no silent pseudo-success.

## 8. PR-E Change Boundary (Verifiable)
This PR-E delivery touched only route-focused implementation/tests/contracts/evidence files:
1. `src/research_layer/routing/summarizer.py`
2. `src/research_layer/services/route_generation_service.py`
3. `src/research_layer/api/controllers/research_route_controller.py`
4. `src/research_layer/api/schemas/route.py`
5. `src/research_layer/api/controllers/_state_store.py` (route-related columns/methods only)
6. `src/research_layer/prompts/route_summary.txt`
7. `tests/unit/research_layer/test_slice7_route_engine.py`
8. `tests/integration/research_api/test_slice7_route_generation_flow.py`
9. `tests/integration/research_llm/test_failure_semantics.py` (route-summary cases only)
10. `tests/integration/research_llm/test_no_bypass_e2e.py` (route chain assertions)
11. `tests/integration/research_llm/test_live_route_summary.py` (new)
12. `docs/mironicky/API_SPEC.md`
13. `docs/mironicky/STORAGE_SCHEMA.md`
14. `docs/mironicky/handoffs/pr-e-route-summary-evidence-2026-04-04.md`

Explicit non-ownership reminder:
1. extraction prompt ownership is not PR-E.
2. hypothesis prompt ownership is not PR-E.
3. PR-B substrate core files are not modified by PR-E.
