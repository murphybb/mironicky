# PR-G Hypothesis Real Provider Evidence (2026-04-04)

## 1. Scope
This evidence package covers PR-G only:
1. hypothesis generate main chain (real provider via PR-B substrate)
2. hypothesis persistence + list/detail read-back
3. hypothesis prompt contract ownership and structured output contract
4. hypothesis failure semantics (explicit failure, no fallback hypothesis)
5. hypothesis no-bypass and live-provider tests

Out of scope in this package:
1. extraction main chain implementation ownership (PR-C)
2. route generation/summary implementation ownership (PR-E)
3. candidate confirm + graph + version implementation ownership (PR-D)
4. failure loop/recompute implementation ownership (PR-F)

## 2. Real Provider Success Sample

### 2.1 Chain
`confirmed graph/version context -> hypothesis generate -> hypothesis persistence -> list/detail`

### 2.2 Success IDs and Trace
1. workspace_id: `ws_prg_evidence_20260404`
2. request_id: `req_prg_evidence_hypothesis_success_1`
3. job_id: `job_a0afc29e3804`
4. hypothesis_id: `hypothesis_20fa5aec2cbc`
5. provider_backend: `openai`
6. provider_model: `MiniMax-M2.5`
7. llm_response_id: `chatcmpl-9d38574bf5b5a0b21f4e2f83b8b84ff1`
8. token_usage:
   - prompt_tokens: `1222`
   - completion_tokens: `1384`
   - total_tokens: `2606`
9. trigger_ids:
   - `trigger_weak_support_route_94ca5f4a85b7`
   - `trigger_conflict_node_node_17d98e9b9846`
10. graph/version context slice:
   - graph_latest_version_id: `ver_6d71bc0fb103`

### 2.3 List/Detail Persistence Proof
1. `GET /api/v1/research/hypotheses/{hypothesis_id}` returns:
   - same `hypothesis_id`
   - `provider_backend/provider_model/request_id/llm_response_id/usage`
   - `fallback_used=false`
   - `degraded=false`
2. `GET /api/v1/research/hypotheses?workspace_id=ws_prg_evidence_20260404` contains `hypothesis_20fa5aec2cbc`

### 2.4 Events / Execution Summary Slice
From `GET /api/v1/research/executions/summary?workspace_id=ws_prg_evidence_20260404&request_id=req_prg_evidence_hypothesis_success_1&job_id=job_a0afc29e3804`:

`hypothesis_generation_completed` (`status=completed`) refs:
```json
{
  "hypothesis_id": "hypothesis_20fa5aec2cbc",
  "trigger_ids": [
    "trigger_weak_support_route_94ca5f4a85b7",
    "trigger_conflict_node_node_17d98e9b9846"
  ],
  "trigger_types": ["weak_support", "conflict"],
  "provider_backend": "openai",
  "provider_model": "MiniMax-M2.5",
  "request_id": "req_prg_evidence_hypothesis_success_1",
  "llm_response_id": "chatcmpl-9d38574bf5b5a0b21f4e2f83b8b84ff1",
  "graph_latest_version_id": "ver_6d71bc0fb103"
}
```

`hypothesis_generation_completed` (`status=completed`) metrics:
```json
{
  "novelty_typing": "incremental",
  "validation_action_id": "validation_ed489f61c477",
  "related_object_count": 4,
  "prompt_tokens": 1222,
  "completion_tokens": 1384,
  "total_tokens": 2606,
  "degraded": false,
  "graph_node_count": 22,
  "graph_edge_count": 20,
  "recent_failure_count": 0,
  "existing_hypothesis_count": 0
}
```

## 3. Explicit Failure Sample (No Fallback Hypothesis)

### 3.1 Failure IDs and Outcome
1. request_id: `req_prg_evidence_hypothesis_fail_auth`
2. job_id: `job_a0d1feb148c3`
3. endpoint: `POST /api/v1/research/hypotheses/generate`
4. injected failure mode: `auth_401`
5. status_code: `502`
6. error_code: `research.llm_auth_failed`
7. job status: `failed`
8. fallback hypothesis created: `no`

### 3.2 Error Surface Slice
Job error payload:
```json
{
  "error_code": "research.llm_auth_failed",
  "message": "llm provider authentication/config failed",
  "details": {
    "provider_message": "injected auth_401 failure"
  }
}
```

Execution summary failed event:
```json
{
  "event_name": "hypothesis_generation_completed",
  "status": "failed",
  "error": {
    "error_code": "research.llm_auth_failed",
    "message": "llm provider authentication/config failed",
    "details": {
      "provider_message": "injected auth_401 failure"
    }
  }
}
```

## 4. Test Commands and Results
All commands run from:
`C:\Users\murphy\Desktop\EverMemOS-latest`

1. Unit contract tests
```powershell
$env:PYTHONPATH='src'; uv run pytest tests/unit/research_layer/test_slice9_hypothesis_services.py -q
```
Result: `6 passed`

2. API contract flow tests
```powershell
$env:PYTHONPATH='src'; uv run pytest tests/integration/research_api/test_slice9_hypothesis_engine_flow.py -q
```
Result: `2 passed`

3. Live provider hypothesis/extraction evidence tests
```powershell
$env:PYTHONPATH='src'; uv run pytest tests/integration/research_llm/test_live_provider_flows.py -q
```
Result: `2 passed`

4. Dedicated live hypothesis chain test
```powershell
$env:PYTHONPATH='src'; uv run pytest tests/integration/research_llm/test_live_hypothesis.py -q
```
Result: `1 passed`

5. Failure semantics tests (including hypothesis timeout/invalid_json/auth/rate_limit + duplicate)
```powershell
$env:PYTHONPATH='src'; uv run pytest tests/integration/research_llm/test_failure_semantics.py -q
```
Result: `15 passed`

6. No-bypass integration/e2e chain test
```powershell
$env:PYTHONPATH='src'; uv run pytest tests/integration/research_llm/test_live_hypothesis.py -q
```
Result: `1 passed`

Observed chain covered by the cited test:
`confirmed graph/version context -> hypothesis generate -> hypothesis persistence -> list/detail`

## 5. PR-G Boundary Statements
1. Hypothesis prompt ownership is now under PR-G:
   - `src/research_layer/prompts/hypothesis_generation.txt`
2. Extraction and route prompts were not modified by this PR-G scope:
   - no edits to extraction prompt files
   - no edits to `src/research_layer/prompts/route_summary.txt`
3. Hypothesis generation does not use fallback-generated fake hypothesis.
4. Hypothesis generation goes through PR-B substrate path (`LLMGateway.invoke_json`) and provider failures are explicit `research.llm_*` failures.
