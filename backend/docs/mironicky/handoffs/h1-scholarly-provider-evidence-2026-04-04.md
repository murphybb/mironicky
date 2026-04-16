# H1 Scholarly Provider Evidence - 2026-04-04

## Final Status
- Proposed status: `DONE_WITH_CONCERNS`
- H1 scope completed: scholarly provider integration, scholarly source cache persistence, evidence ref persistence, direct API/read-model wiring, contract/cache/failure tests, and one real live scholarly provider success sample.
- Remaining concern: Semantic Scholar is wired but does not have live proof in the current environment because `SCHOLARLY_SEMANTIC_SCHOLAR_API_KEY` is not configured.

## Scope Integrity Declaration
- Gate primary success evidence below comes from a real external Crossref call. No monkeypatch, fixture replay, or fake provider was used for that live proof.
- Controlled stubs remain in non-live contract/cache/failure tests only. They are not used as gate primary success evidence.
- No package build/publish, cold-start, route, extraction, or hypothesis mainline work was added.
- No new canonical controller boundary was invented. H1 stays inside the existing source controller and retrieval read-model boundary.

## Real Live Provider Success Proof
### Command
```powershell
$env:SCHOLARLY_CROSSREF_MAILTO='codex-crossref-live@example.com'
pytest -q C:\Users\murphy\Desktop\EverMemOS-latest\tests\integration\research_scholarly\test_live_scholarly_provider.py::test_live_crossref_lookup_persists_cache_and_evidence
```

### Result
```text
.                                                                        [100%]
1 passed in 7.96s
```

### Live DOI Used
- DOI: `10.1038/nphys1170`
- Crossref title returned: `Measured measurement`

### Live Provider Trace Excerpt
This trace came from the same live run path that persisted cache and evidence refs:

```json
{
  "query": "doi:10.1038/nphys1170",
  "provider_trace": [
    {
      "provider_name": "crossref",
      "cache_hit": false,
      "request_id": null,
      "request_url": "https://api.crossref.org/works/10.1038%2Fnphys1170",
      "http_status": 200
    }
  ]
}
```

Interpretation:
- Provider/backend proved: `crossref`
- Request identifier equivalent proved: `request_url`
- Upstream success proved: `http_status == 200`

## Real Persisted `scholarly_source_cache` Slice
The following row was persisted by the same live Crossref run:

```json
[
  {
    "provider_name": "crossref",
    "normalized_query": "doi:10.1038/nphys1170",
    "provider_record_id": "10.1038/nphys1170",
    "title": "Measured measurement",
    "doi": "10.1038/nphys1170",
    "url": "https://doi.org/10.1038/nphys1170",
    "venue": "Nature Physics",
    "publication_year": 2009,
    "metadata_json": "{\"type\": \"journal-article\", \"score\": 1, \"lookup_mode\": \"doi\", \"citation_count\": null, \"influential_citation_count\": null}",
    "authority_tier": "tier_a_peer_reviewed",
    "authority_score": 0.98,
    "created_at": "2026-04-04T14:09:14.692909+00:00"
  }
]
```

## Real Persisted `evidence_refs` Slice
The following rows were persisted by the same live Crossref run after candidate confirmation:

```json
[
  {
    "ref_type": "literature",
    "layer": "fragment",
    "title": "Measured measurement",
    "doi": "10.1038/nphys1170",
    "url": "https://doi.org/10.1038/nphys1170",
    "venue": "Nature Physics",
    "publication_year": 2009,
    "locator_json": "{\"section\": \"abstract\", \"paragraph_index\": 0, \"char_start\": 0, \"char_end\": 87, \"chunk_id\": \"chunk_0\", \"text\": \"The paper examines how measurement itself constrains interpretation of quantum systems.\"}",
    "authority_tier": "tier_a_peer_reviewed",
    "authority_score": 1.0,
    "metadata_json": "{\"candidate_id\": \"cand_a6fa983073dc\", \"candidate_batch_id\": \"batch_a1fe88e7f678\", \"request_id\": \"req_h1_live_evidence_confirm\"}",
    "created_at": "2026-04-04T14:09:14.873427+00:00"
  },
  {
    "ref_type": "literature",
    "layer": "work",
    "title": "Measured measurement",
    "doi": "10.1038/nphys1170",
    "url": "https://doi.org/10.1038/nphys1170",
    "venue": "Nature Physics",
    "publication_year": 2009,
    "locator_json": "{\"source_id\": \"src_986834f2fb35\", \"scope\": \"work\"}",
    "authority_tier": "tier_a_peer_reviewed",
    "authority_score": 0.98,
    "metadata_json": "{\"source_input_mode\": \"manual_text\", \"external_provider\": \"crossref\"}",
    "created_at": "2026-04-04T14:09:14.873427+00:00"
  }
]
```

## Current H1 Suite Verification
### Command
```powershell
$env:SCHOLARLY_CROSSREF_MAILTO='codex-crossref-live@example.com'
pytest -q -rs C:\Users\murphy\Desktop\EverMemOS-latest\tests\integration\research_scholarly
```

### Result
```text
.s.......                                                                [100%]
=========================== short test summary info ===========================
SKIPPED [1] tests\integration\research_scholarly\test_live_scholarly_provider.py:87: set SCHOLARLY_CROSSREF_MAILTO and SCHOLARLY_SEMANTIC_SCHOLAR_API_KEY for Semantic Scholar live test
8 passed, 1 skipped in 19.54s
```

Interpretation:
- Passed:
  - controller/service boundary contract
  - evidence ref persistence contract
  - scholarly cache persistence contract
  - provider misconfigured error contract
  - provider not-found contract
  - cache hit/miss contract
  - cache expiry refresh contract
  - provider unavailable contract
  - live Crossref success contract
- Skipped:
  - live Semantic Scholar enrichment proof only

## Failure Semantics Proof
### Misconfigured Provider
Real endpoint sample without required Crossref mailto:

```json
{
  "status_code": 500,
  "body": {
    "detail": {
      "error_code": "research.scholarly_provider_misconfigured",
      "message": "crossref mailto is required",
      "details": {
        "provider_name": "crossref"
      }
    }
  }
}
```

### Command Coverage
This behavior is enforced in the passing suite above and specifically covered by:
- `test_provider_error_contract_misconfigured_is_explicit`
- `test_provider_unavailable_is_explicit`
- `test_provider_no_result_contract_is_explicit`

## Semantic Scholar Status
- Wiring status: implemented in `src/research_layer/services/scholarly_connector.py`
- Live proof status: not completed in current environment
- Reason: `SCHOLARLY_SEMANTIC_SCHOLAR_API_KEY` missing
- No Semantic Scholar success evidence is claimed here

## Non-Live Test Evidence Policy
- Controlled stubs are still present in contract/cache/failure tests to exercise deterministic boundary cases.
- Those stubbed cases are not used as live success proof and are not the primary gate evidence for provider success.

## Files Changed For This Review Closure
- `C:\Users\murphy\Desktop\EverMemOS-latest\tests\integration\research_scholarly\test_live_scholarly_provider.py`
- `C:\Users\murphy\Desktop\EverMemOS-latest\docs\mironicky\handoffs\h1-scholarly-provider-evidence-2026-04-04.md`

## Full H1 File Set
- `C:\Users\murphy\Desktop\Ô­ÐÍ²Ý¸å\docs\mironicky\contracts\h1_scholarly_provider_integration_contract.md`
- `C:\Users\murphy\Desktop\EverMemOS-latest\src\research_layer\api\controllers\_state_store.py`
- `C:\Users\murphy\Desktop\EverMemOS-latest\src\research_layer\api\controllers\research_source_controller.py`
- `C:\Users\murphy\Desktop\EverMemOS-latest\src\research_layer\api\schemas\retrieval.py`
- `C:\Users\murphy\Desktop\EverMemOS-latest\src\research_layer\api\schemas\scholarly.py`
- `C:\Users\murphy\Desktop\EverMemOS-latest\src\research_layer\services\candidate_confirmation_service.py`
- `C:\Users\murphy\Desktop\EverMemOS-latest\src\research_layer\services\retrieval_views_service.py`
- `C:\Users\murphy\Desktop\EverMemOS-latest\src\research_layer\services\scholarly_connector.py`
- `C:\Users\murphy\Desktop\EverMemOS-latest\src\research_layer\services\scholarly_source_service.py`
- `C:\Users\murphy\Desktop\EverMemOS-latest\tests\integration\research_scholarly\_helpers.py`
- `C:\Users\murphy\Desktop\EverMemOS-latest\tests\integration\research_scholarly\test_scholarly_provider_contracts.py`
- `C:\Users\murphy\Desktop\EverMemOS-latest\tests\integration\research_scholarly\test_scholarly_cache_and_failures.py`
- `C:\Users\murphy\Desktop\EverMemOS-latest\tests\integration\research_scholarly\test_live_scholarly_provider.py`
- `C:\Users\murphy\Desktop\EverMemOS-latest\docs\mironicky\handoffs\h1-scholarly-provider-evidence-2026-04-04.md`

## Gate Summary
- Real provider integration implemented: yes
- At least one real scholarly provider success sample executed: yes, Crossref DOI lookup
- Explicit provider error semantics implemented: yes
- `scholarly_source_cache` persistence proved with live data: yes
- `evidence_refs` persistence proved with live data: yes
- Semantic Scholar live proof completed: no
