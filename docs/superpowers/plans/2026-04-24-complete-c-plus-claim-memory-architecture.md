# Complete C+ Claim Memory Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the C+ architecture so Mironicky uses claim ledger as truth source, EverMemOS as long-term recall, and graph/routes/reports as traceable projections instead of loose generated objects.

**Architecture:** Claim ledger is the only source of truth for research assertions. Graph nodes, graph edges, routes, conflicts, and reports must either point to claim ids or explicitly report why no projection is allowed. EverMemOS remains a recall engine: it can suggest related history and conflict candidates, but it cannot overwrite claim truth.

**Tech Stack:** Python 3.12, FastAPI/Litestar-style controllers, SQLite-backed `ResearchApiStateStore`, EverMemOS local `MemoryManager`, React/Vite static frontend, pytest, Playwright for final browser checks.

---

## Current Gaps

1. Graph writes are not fully gated by claim/source provenance. Manual node/edge creation can still enter graph without `claim_id`.
2. Source import does not yet run a stable cross-document recall pass and persist the result as first-class research state.
3. New-vs-old claim conflict detection is not a dedicated claim-vs-claim workflow.
4. Routes are not automatically marked as challenged, weakened, or needing review when claim conflicts are found.
5. GraphRAG is not a first-class query path. Current behavior is graph query plus memory recall, not a grounded graph retrieval answer.
6. Cross-document research report is not implemented as a source-grounded, claim-grounded report.
7. Frontend has basic related memory display, but not a clear workflow showing historical recall, conflict review, route risk, and source-grounded answers.

## Success Criteria

1. Any graph node or edge created through public graph write APIs must have a valid `claim_id` from the same workspace, or the API returns explicit `400 research.invalid_request`.
2. Confirming candidates still works and automatically creates claim-backed graph projections.
3. Importing or extracting a new source writes `source_memory_recall_results` with related historical claim refs from EverMemOS, including explicit skipped/failed status when unavailable.
4. Claim conflict detection creates reviewable `claim_conflicts` rows with `new_claim_id`, `existing_claim_id`, `conflict_type`, `status`, `evidence`, and `source_ref`.
5. Route detail and route list expose `challenge_status`: `clean`, `challenged`, `weakened`, or `needs_review`.
6. A GraphRAG query endpoint returns answer text plus cited `claim_ids`, graph paths, source artifact refs, and memory refs.
7. A cross-document report endpoint returns sections for claims, routes, conflicts, unresolved gaps, and reused historical context, all with source refs.
8. Frontend shows all four surfaces: import history recall, conflict review, route challenge status, and GraphRAG answers.
9. Targeted unit tests, integration tests, frontend build, and one real-browser smoke test pass.

## File Map

**Backend store and schema**
- Modify: `backend/src/research_layer/api/controllers/_state_store.py`
- Modify: `backend/src/research_layer/api/schemas/graph.py`
- Create: `backend/src/research_layer/api/schemas/claim_conflict.py`
- Create: `backend/src/research_layer/api/schemas/graphrag.py`

**Backend services**
- Create: `backend/src/research_layer/services/claim_projection_guard_service.py`
- Create: `backend/src/research_layer/services/source_memory_recall_service.py`
- Create: `backend/src/research_layer/services/claim_conflict_service.py`
- Create: `backend/src/research_layer/services/route_challenge_service.py`
- Create: `backend/src/research_layer/services/graphrag_service.py`
- Create: `backend/src/research_layer/services/cross_document_report_service.py`
- Modify: `backend/src/research_layer/services/candidate_confirmation_service.py`
- Modify: `backend/src/research_layer/services/graph_build_service.py`
- Modify: `backend/src/research_layer/services/route_generation_service.py`
- Modify: `backend/src/research_layer/services/source_import_service.py`
- Modify: `backend/src/research_layer/services/evermemos_bridge_service.py`

**Backend controllers**
- Modify: `backend/src/research_layer/api/controllers/research_graph_controller.py`
- Modify: `backend/src/research_layer/api/controllers/research_route_controller.py`
- Modify: `backend/src/research_layer/api/controllers/research_source_controller.py`
- Create: `backend/src/research_layer/api/controllers/research_conflict_controller.py`
- Create: `backend/src/research_layer/api/controllers/research_graphrag_controller.py`
- Create: `backend/src/research_layer/api/controllers/research_cross_document_report_controller.py`

**Frontend**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/pages1.tsx`
- Modify: `frontend/src/pages2.tsx`
- Modify: `frontend/src/App.tsx`
- Create: `frontend/src/pages3.tsx` if a dedicated conflict/report page is cleaner than expanding existing pages.

**Tests**
- Create: `backend/tests/unit/research_layer/test_claim_projection_guard_service.py`
- Create: `backend/tests/unit/research_layer/test_source_memory_recall_service.py`
- Create: `backend/tests/unit/research_layer/test_claim_conflict_service.py`
- Create: `backend/tests/unit/research_layer/test_route_challenge_service.py`
- Create: `backend/tests/unit/research_layer/test_graphrag_service.py`
- Create: `backend/tests/unit/research_layer/test_cross_document_report_service.py`
- Modify: `backend/tests/integration/research_api/test_slice5_graph_foundation_flow.py`
- Create: `backend/tests/integration/research_api/test_c_plus_claim_memory_flow.py`
- Modify or create browser check: `frontend/tests` only if this repo already has frontend test wiring; otherwise use `npx playwright-cli` smoke script in the final verification step.

---

## Task 0: Branch Safety and Baseline

**Files:**
- No production edits.

- [ ] **Step 1: Confirm branch and status**

Run:

```powershell
git branch --show-current
git status --short
```

Expected:

```text
codex/p2-evermemos-frontend-recall
?? .hypothesis/
```

If there are additional modified tracked files, stop and inspect them before coding.

- [ ] **Step 2: Create a new implementation branch from current branch**

Run:

```powershell
git switch -c codex/complete-c-plus-claim-memory
```

Expected:

```text
Switched to a new branch 'codex/complete-c-plus-claim-memory'
```

- [ ] **Step 3: Run current focused backend tests**

Run:

```powershell
cd backend
$env:PYTHONPATH='src'
uv run pytest tests/unit/research_layer/test_slice12_memory_recall_paths.py tests/unit/research_layer/test_p1_memory_recall_main_paths.py -q
```

Expected: all selected tests pass.

---

## Task 1: Hard Claim Projection Gate

**Goal:** Public graph write APIs cannot create research graph objects without valid claim provenance.

**Files:**
- Create: `backend/src/research_layer/services/claim_projection_guard_service.py`
- Modify: `backend/src/research_layer/api/schemas/graph.py`
- Modify: `backend/src/research_layer/api/controllers/research_graph_controller.py`
- Test: `backend/tests/unit/research_layer/test_claim_projection_guard_service.py`
- Test: `backend/tests/integration/research_api/test_slice5_graph_foundation_flow.py`

- [ ] **Step 1: Write failing guard unit tests**

Create `backend/tests/unit/research_layer/test_claim_projection_guard_service.py`:

```python
from __future__ import annotations

import pytest

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.services.claim_projection_guard_service import (
    ClaimProjectionGuardError,
    ClaimProjectionGuardService,
)


def _build_store(tmp_path) -> ResearchApiStateStore:
    return ResearchApiStateStore(db_path=str(tmp_path / "claim_projection_guard.sqlite3"))


def _seed_claim(store: ResearchApiStateStore, workspace_id: str) -> dict[str, object]:
    source = store.create_source(
        workspace_id=workspace_id,
        source_type="paper",
        title="source",
        content="Claim text",
        metadata={},
        import_request_id="req_guard",
    )
    candidate = store.create_candidate(
        workspace_id=workspace_id,
        source_id=str(source["source_id"]),
        candidate_type="claim",
        text="Claim text",
        source_span={"start": 0, "end": 10},
        trace_refs={"source_id": source["source_id"]},
        status="pending",
    )
    return store.create_claim_from_candidate(
        candidate=candidate,
        normalized_text="claim text",
    )


def test_guard_accepts_claim_from_same_workspace(tmp_path) -> None:
    store = _build_store(tmp_path)
    claim = _seed_claim(store, "ws_guard")
    guard = ClaimProjectionGuardService(store)

    result = guard.require_claim(workspace_id="ws_guard", claim_id=str(claim["claim_id"]))

    assert result["claim_id"] == claim["claim_id"]


def test_guard_rejects_missing_claim_id(tmp_path) -> None:
    store = _build_store(tmp_path)
    guard = ClaimProjectionGuardService(store)

    with pytest.raises(ClaimProjectionGuardError) as exc:
        guard.require_claim(workspace_id="ws_guard", claim_id=None)

    assert exc.value.status_code == 400
    assert exc.value.reason == "missing_claim_id"


def test_guard_rejects_cross_workspace_claim(tmp_path) -> None:
    store = _build_store(tmp_path)
    claim = _seed_claim(store, "ws_owner")
    guard = ClaimProjectionGuardService(store)

    with pytest.raises(ClaimProjectionGuardError) as exc:
        guard.require_claim(workspace_id="ws_other", claim_id=str(claim["claim_id"]))

    assert exc.value.reason == "claim_workspace_mismatch"
```

- [ ] **Step 2: Run test and verify it fails because service does not exist**

Run:

```powershell
cd backend
$env:PYTHONPATH='src'
uv run pytest tests/unit/research_layer/test_claim_projection_guard_service.py -q
```

Expected: failure with `ModuleNotFoundError` for `claim_projection_guard_service`.

- [ ] **Step 3: Implement guard service**

Create `backend/src/research_layer/services/claim_projection_guard_service.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from research_layer.api.controllers._state_store import ResearchApiStateStore


@dataclass(frozen=True)
class ClaimProjectionGuardError(Exception):
    status_code: int
    reason: str
    message: str
    details: dict[str, object]


class ClaimProjectionGuardService:
    def __init__(self, store: ResearchApiStateStore) -> None:
        self._store = store

    def require_claim(
        self,
        *,
        workspace_id: str,
        claim_id: str | None,
    ) -> dict[str, object]:
        normalized_claim_id = str(claim_id or "").strip()
        if not normalized_claim_id:
            raise ClaimProjectionGuardError(
                status_code=400,
                reason="missing_claim_id",
                message="graph projection requires claim_id",
                details={"workspace_id": workspace_id},
            )
        claim = self._store.get_claim(normalized_claim_id)
        if claim is None:
            raise ClaimProjectionGuardError(
                status_code=400,
                reason="claim_not_found",
                message="claim_id does not exist",
                details={"workspace_id": workspace_id, "claim_id": normalized_claim_id},
            )
        if str(claim["workspace_id"]) != workspace_id:
            raise ClaimProjectionGuardError(
                status_code=400,
                reason="claim_workspace_mismatch",
                message="claim_id belongs to a different workspace",
                details={
                    "workspace_id": workspace_id,
                    "claim_id": normalized_claim_id,
                    "claim_workspace_id": claim["workspace_id"],
                },
            )
        return claim
```

- [ ] **Step 4: Run guard tests**

Run:

```powershell
cd backend
$env:PYTHONPATH='src'
uv run pytest tests/unit/research_layer/test_claim_projection_guard_service.py -q
```

Expected: `3 passed`.

- [ ] **Step 5: Extend graph create schemas with `claim_id`**

Modify `backend/src/research_layer/api/schemas/graph.py`:

```python
class GraphNodeCreateRequest(WorkspaceScopedBody):
    node_type: str = Field(min_length=1)
    object_ref_type: str = Field(min_length=1)
    object_ref_id: str = Field(min_length=1)
    short_label: str = Field(min_length=1, max_length=128)
    full_description: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    short_tags: list[str] = Field(default_factory=list)
    visibility: str = Field(default="workspace", pattern=r"^(private|workspace|package_public)$")
    source_refs: list[dict[str, object]] = Field(default_factory=list)
```

Modify `GraphEdgeCreateRequest`:

```python
class GraphEdgeCreateRequest(WorkspaceScopedBody):
    source_node_id: str = Field(min_length=1)
    target_node_id: str = Field(min_length=1)
    edge_type: str = Field(min_length=1)
    object_ref_type: str = Field(min_length=1)
    object_ref_id: str = Field(min_length=1)
    strength: float = Field(ge=0.0, le=1.0)
    claim_id: str = Field(min_length=1)
```

- [ ] **Step 6: Wire guard into graph controller create endpoints**

Modify `backend/src/research_layer/api/controllers/research_graph_controller.py`:

```python
from research_layer.services.claim_projection_guard_service import (
    ClaimProjectionGuardError,
    ClaimProjectionGuardService,
)
```

In `__init__`:

```python
self._claim_guard = ClaimProjectionGuardService(STORE)
```

Add helper:

```python
def _require_projection_claim(self, *, workspace_id: str, claim_id: str) -> dict[str, object]:
    try:
        return self._claim_guard.require_claim(workspace_id=workspace_id, claim_id=claim_id)
    except ClaimProjectionGuardError as exc:
        raise_http_error(
            status_code=exc.status_code,
            code=ResearchErrorCode.INVALID_REQUEST.value,
            message=exc.message,
            details={"reason": exc.reason, **exc.details},
        )
```

Before `STORE.create_graph_node(...)`, call:

```python
claim = self._require_projection_claim(workspace_id=workspace, claim_id=payload.claim_id)
```

Pass:

```python
claim_id=str(claim["claim_id"]),
source_ref={
    "claim_id": claim["claim_id"],
    "source_id": claim["source_id"],
    "source_span": claim.get("source_span", {}),
    "trace_refs": claim.get("trace_refs", {}),
},
```

Before `STORE.create_graph_edge(...)`, call the same guard and pass `claim_id` plus `source_ref`.

- [ ] **Step 7: Add integration tests for graph API gate**

Append to `backend/tests/integration/research_api/test_slice5_graph_foundation_flow.py`:

```python
def test_slice5_graph_manual_create_requires_claim_id() -> None:
    client = _build_test_client()

    response = client.post(
        "/api/v1/research/graph/nodes",
        json={
            "workspace_id": "ws_manual_claim_gate",
            "node_type": "claim",
            "object_ref_type": "manual_note",
            "object_ref_id": "manual_1",
            "short_label": "Manual node",
            "full_description": "Manual graph writes must bind a claim.",
        },
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "research.invalid_request"
    assert response.json()["details"]["reason"] == "missing_claim_id"
```

Add a happy-path test by importing and confirming one candidate, then manually creating a second node with the returned `claim_id`.

- [ ] **Step 8: Run tests**

Run:

```powershell
cd backend
$env:PYTHONPATH='src'
uv run pytest tests/unit/research_layer/test_claim_projection_guard_service.py tests/integration/research_api/test_slice5_graph_foundation_flow.py::test_slice5_graph_manual_create_requires_claim_id -q
```

Expected: selected tests pass.

- [ ] **Step 9: Commit**

Run:

```powershell
git add backend/src/research_layer/services/claim_projection_guard_service.py backend/src/research_layer/api/schemas/graph.py backend/src/research_layer/api/controllers/research_graph_controller.py backend/tests/unit/research_layer/test_claim_projection_guard_service.py backend/tests/integration/research_api/test_slice5_graph_foundation_flow.py
git commit -m "Enforce claim-backed graph projections"
```

---

## Task 2: Source Import Historical Recall

**Goal:** New source import/extraction produces persisted historical recall from EverMemOS, scoped to source text and extracted claim candidates.

**Files:**
- Modify: `backend/src/research_layer/api/controllers/_state_store.py`
- Create: `backend/src/research_layer/services/source_memory_recall_service.py`
- Modify: `backend/src/research_layer/services/source_import_service.py`
- Modify: `backend/src/research_layer/api/controllers/research_source_controller.py`
- Test: `backend/tests/unit/research_layer/test_source_memory_recall_service.py`
- Test: `backend/tests/integration/research_api/test_c_plus_claim_memory_flow.py`

- [ ] **Step 1: Add failing store/service tests**

Create `backend/tests/unit/research_layer/test_source_memory_recall_service.py`:

```python
from __future__ import annotations

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.services.source_memory_recall_service import SourceMemoryRecallService


def test_source_memory_recall_persists_completed_result(monkeypatch, tmp_path) -> None:
    store = ResearchApiStateStore(db_path=str(tmp_path / "source_recall.sqlite3"))
    source = store.create_source(
        workspace_id="ws_source_recall",
        source_type="paper",
        title="new paper",
        content="New claim discusses brand attitude.",
        metadata={},
        import_request_id="req_source_recall",
    )
    service = SourceMemoryRecallService(store)

    def _fake_recall(**kwargs):
        return {
            "status": "completed",
            "reason": "logical_not_supported_by_evermemos",
            "requested_method": "logical",
            "applied_method": "hybrid",
            "total": 1,
            "items": [
                {
                    "memory_type": "episodic_memory",
                    "memory_id": "mem_1",
                    "score": 0.91,
                    "title": "prior claim",
                    "snippet": "Prior claim about brand attitude.",
                    "linked_claim_refs": [{"claim_id": "claim_old"}],
                    "source_ref": {},
                }
            ],
            "trace_refs": {"group_id": "research_claims::ws_source_recall"},
        }

    monkeypatch.setattr(service._memory_recall_service, "recall", _fake_recall)

    result = service.recall_for_source(
        workspace_id="ws_source_recall",
        source_id=str(source["source_id"]),
        query_text="brand attitude claim",
        request_id="req_source_recall",
    )

    assert result["status"] == "completed"
    loaded = store.list_source_memory_recall_results(
        workspace_id="ws_source_recall",
        source_id=str(source["source_id"]),
    )
    assert loaded[0]["total"] == 1
    assert loaded[0]["items"][0]["memory_id"] == "mem_1"
```

- [ ] **Step 2: Run test and verify missing service/store methods**

Run:

```powershell
cd backend
$env:PYTHONPATH='src'
uv run pytest tests/unit/research_layer/test_source_memory_recall_service.py -q
```

Expected: failure due to missing service or store methods.

- [ ] **Step 3: Add `source_memory_recall_results` table and methods**

Modify `backend/src/research_layer/api/controllers/_state_store.py` schema list:

```sql
CREATE TABLE IF NOT EXISTS source_memory_recall_results (
    recall_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    status TEXT NOT NULL,
    reason TEXT,
    requested_method TEXT,
    applied_method TEXT,
    total INTEGER NOT NULL DEFAULT 0,
    items_json TEXT NOT NULL DEFAULT '[]',
    trace_refs_json TEXT NOT NULL DEFAULT '{}',
    request_id TEXT,
    created_at TEXT NOT NULL
)
```

Add methods:

```python
def create_source_memory_recall_result(
    self,
    *,
    workspace_id: str,
    source_id: str,
    status: str,
    reason: str | None,
    requested_method: str | None,
    applied_method: str | None,
    total: int,
    items: list[dict[str, object]],
    trace_refs: dict[str, object],
    request_id: str,
    conn: sqlite3.Connection | None = None,
) -> dict[str, object]:
    recall_id = self.gen_id("source_recall")
    now = self._to_iso(self.now())
    self._execute(
        """
        INSERT INTO source_memory_recall_results (
            recall_id, workspace_id, source_id, status, reason, requested_method,
            applied_method, total, items_json, trace_refs_json, request_id, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            recall_id,
            workspace_id,
            source_id,
            status,
            reason,
            requested_method,
            applied_method,
            int(total),
            self._dumps(items),
            self._dumps(trace_refs),
            request_id,
            now,
        ),
        conn=conn,
    )
    return self.get_source_memory_recall_result(recall_id, conn=conn)
```

Also add `get_source_memory_recall_result`, `list_source_memory_recall_results`, and `_row_to_source_memory_recall_result` mirroring existing source artifact row conversion.

- [ ] **Step 4: Implement service**

Create `backend/src/research_layer/services/source_memory_recall_service.py`:

```python
from __future__ import annotations

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.services.evermemos_bridge_service import EverMemOSRecallService


class SourceMemoryRecallService:
    def __init__(self, store: ResearchApiStateStore) -> None:
        self._store = store
        self._memory_recall_service = EverMemOSRecallService(store)

    def recall_for_source(
        self,
        *,
        workspace_id: str,
        source_id: str,
        query_text: str,
        request_id: str,
    ) -> dict[str, object]:
        response = self._memory_recall_service.recall(
            workspace_id=workspace_id,
            requested_method="logical",
            query_text=query_text,
            scope_claim_ids=[],
            reason="source_import_historical_recall",
            trace_refs={"source_id": source_id},
        )
        return self._store.create_source_memory_recall_result(
            workspace_id=workspace_id,
            source_id=source_id,
            status=str(response.get("status") or "failed"),
            reason=str(response.get("reason") or ""),
            requested_method=str(response.get("requested_method") or "logical"),
            applied_method=str(response.get("applied_method") or ""),
            total=int(response.get("total") or 0),
            items=list(response.get("items") or []),
            trace_refs=dict(response.get("trace_refs") or {}),
            request_id=request_id,
        )
```

- [ ] **Step 5: Call service after source import/extract path has source content**

Modify `backend/src/research_layer/services/source_import_service.py` or the extraction completion path that already has `source_id`, `workspace_id`, and text. Call:

```python
SourceMemoryRecallService(self._store).recall_for_source(
    workspace_id=workspace_id,
    source_id=source_id,
    query_text=source_content[:4000],
    request_id=request_id,
)
```

If this path is inside a transaction, call recall after transaction commit. EverMemOS must not block source persistence.

- [ ] **Step 6: Expose recall on source list/detail API**

Modify `backend/src/research_layer/api/controllers/research_source_controller.py` response payload to include:

```python
"memory_recall": self._store.list_source_memory_recall_results(
    workspace_id=workspace_id,
    source_id=source_id,
)[:1]
```

- [ ] **Step 7: Run tests**

Run:

```powershell
cd backend
$env:PYTHONPATH='src'
uv run pytest tests/unit/research_layer/test_source_memory_recall_service.py tests/integration/research_api/test_c_plus_claim_memory_flow.py -q
```

Expected: source recall test passes. Integration test should verify response includes `memory_recall` with explicit status.

- [ ] **Step 8: Commit**

Run:

```powershell
git add backend/src/research_layer/api/controllers/_state_store.py backend/src/research_layer/services/source_memory_recall_service.py backend/src/research_layer/services/source_import_service.py backend/src/research_layer/api/controllers/research_source_controller.py backend/tests/unit/research_layer/test_source_memory_recall_service.py backend/tests/integration/research_api/test_c_plus_claim_memory_flow.py
git commit -m "Persist source historical memory recall"
```

---

## Task 3: Claim-vs-Claim Conflict Detection

**Goal:** New claims are compared against historical claims and possible contradictions become reviewable state.

**Files:**
- Modify: `backend/src/research_layer/api/controllers/_state_store.py`
- Create: `backend/src/research_layer/api/schemas/claim_conflict.py`
- Create: `backend/src/research_layer/services/claim_conflict_service.py`
- Create: `backend/src/research_layer/api/controllers/research_conflict_controller.py`
- Modify: app controller registration file if controllers are explicitly registered.
- Test: `backend/tests/unit/research_layer/test_claim_conflict_service.py`
- Test: `backend/tests/integration/research_api/test_c_plus_claim_memory_flow.py`

- [ ] **Step 1: Write conflict service tests**

Create `backend/tests/unit/research_layer/test_claim_conflict_service.py`:

```python
from __future__ import annotations

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.services.claim_conflict_service import ClaimConflictService


def _claim(store, workspace_id, text):
    source = store.create_source(
        workspace_id=workspace_id,
        source_type="paper",
        title=text[:20],
        content=text,
        metadata={},
        import_request_id="req_conflict",
    )
    candidate = store.create_candidate(
        workspace_id=workspace_id,
        source_id=str(source["source_id"]),
        candidate_type="claim",
        text=text,
        source_span={"start": 0, "end": len(text)},
        trace_refs={"source_id": source["source_id"]},
        status="pending",
    )
    return store.create_claim_from_candidate(candidate=candidate, normalized_text=text.lower())


def test_claim_conflict_service_records_direct_contradiction(tmp_path) -> None:
    store = ResearchApiStateStore(db_path=str(tmp_path / "claim_conflicts.sqlite3"))
    old_claim = _claim(store, "ws_conflict", "Brand trust increases purchase intention.")
    new_claim = _claim(store, "ws_conflict", "Brand trust does not increase purchase intention.")
    service = ClaimConflictService(store)

    result = service.detect_for_claim(
        workspace_id="ws_conflict",
        new_claim_id=str(new_claim["claim_id"]),
        candidate_claim_ids=[str(old_claim["claim_id"])],
        request_id="req_conflict",
    )

    assert result["created_count"] == 1
    conflicts = store.list_claim_conflicts(workspace_id="ws_conflict")
    assert conflicts[0]["new_claim_id"] == new_claim["claim_id"]
    assert conflicts[0]["existing_claim_id"] == old_claim["claim_id"]
    assert conflicts[0]["status"] == "needs_review"
```

- [ ] **Step 2: Add `claim_conflicts` table and store methods**

Add table:

```sql
CREATE TABLE IF NOT EXISTS claim_conflicts (
    conflict_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    new_claim_id TEXT NOT NULL,
    existing_claim_id TEXT NOT NULL,
    conflict_type TEXT NOT NULL,
    status TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    source_ref_json TEXT NOT NULL DEFAULT '{}',
    created_request_id TEXT,
    resolved_request_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
```

Add methods:

```python
create_claim_conflict(...)
list_claim_conflicts(...)
update_claim_conflict_status(...)
```

Statuses: `needs_review`, `accepted`, `rejected`, `resolved`.

- [ ] **Step 3: Implement deterministic first-pass conflict detector**

Create `backend/src/research_layer/services/claim_conflict_service.py` with:

```python
NEGATION_MARKERS = (" not ", " no ", "does not", "cannot", "fails to", "没有", "不", "不能", "未")

class ClaimConflictService:
    def __init__(self, store: ResearchApiStateStore) -> None:
        self._store = store

    def detect_for_claim(
        self,
        *,
        workspace_id: str,
        new_claim_id: str,
        candidate_claim_ids: list[str],
        request_id: str,
    ) -> dict[str, object]:
        new_claim = self._store.get_claim(new_claim_id)
        if new_claim is None or str(new_claim["workspace_id"]) != workspace_id:
            return {"created_count": 0, "conflict_ids": []}
        created_ids: list[str] = []
        for existing_id in candidate_claim_ids:
            existing = self._store.get_claim(existing_id)
            if existing is None or existing["claim_id"] == new_claim["claim_id"]:
                continue
            if str(existing["workspace_id"]) != workspace_id:
                continue
            if self._looks_contradictory(str(new_claim["normalized_text"]), str(existing["normalized_text"])):
                conflict = self._store.create_claim_conflict(
                    workspace_id=workspace_id,
                    new_claim_id=str(new_claim["claim_id"]),
                    existing_claim_id=str(existing["claim_id"]),
                    conflict_type="possible_contradiction",
                    status="needs_review",
                    evidence={
                        "new_text": new_claim["text"],
                        "existing_text": existing["text"],
                        "detector": "negation_overlap_v1",
                    },
                    source_ref={
                        "new_claim_id": new_claim["claim_id"],
                        "existing_claim_id": existing["claim_id"],
                    },
                    created_request_id=request_id,
                )
                created_ids.append(str(conflict["conflict_id"]))
        return {"created_count": len(created_ids), "conflict_ids": created_ids}
```

Use this deterministic version first. Add LLM classification only after this path is stable.

- [ ] **Step 4: Wire conflict detection after claim creation**

In `candidate_confirmation_service.py`, after memory bridge, use existing workspace claims as candidates:

```python
existing_claim_ids = [
    str(item["claim_id"])
    for item in self._store.list_claims(workspace_id)
    if str(item["claim_id"]) != str(claim["claim_id"])
]
ClaimConflictService(self._store).detect_for_claim(
    workspace_id=workspace_id,
    new_claim_id=str(claim["claim_id"]),
    candidate_claim_ids=existing_claim_ids[:50],
    request_id=request_id,
)
```

- [ ] **Step 5: Add conflict controller**

Create `backend/src/research_layer/api/controllers/research_conflict_controller.py` endpoints:

```text
GET /api/v1/research/conflicts/{workspace_id}
PATCH /api/v1/research/conflicts/{conflict_id}
```

Patch accepts `workspace_id`, `status`, and `decision_note`.

- [ ] **Step 6: Run tests**

Run:

```powershell
cd backend
$env:PYTHONPATH='src'
uv run pytest tests/unit/research_layer/test_claim_conflict_service.py tests/integration/research_api/test_c_plus_claim_memory_flow.py -q
```

Expected: conflict service and conflict API pass.

- [ ] **Step 7: Commit**

Run:

```powershell
git add backend/src/research_layer/api/controllers/_state_store.py backend/src/research_layer/api/schemas/claim_conflict.py backend/src/research_layer/services/claim_conflict_service.py backend/src/research_layer/api/controllers/research_conflict_controller.py backend/src/research_layer/services/candidate_confirmation_service.py backend/tests/unit/research_layer/test_claim_conflict_service.py backend/tests/integration/research_api/test_c_plus_claim_memory_flow.py
git commit -m "Add claim conflict detection"
```

---

## Task 4: Route Challenge Status

**Goal:** Routes show whether their supporting claims are challenged by unresolved claim conflicts.

**Files:**
- Create: `backend/src/research_layer/services/route_challenge_service.py`
- Modify: `backend/src/research_layer/services/route_generation_service.py`
- Modify: `backend/src/research_layer/api/controllers/research_route_controller.py`
- Modify: route schemas if route responses are typed there.
- Test: `backend/tests/unit/research_layer/test_route_challenge_service.py`

- [ ] **Step 1: Write route challenge tests**

Create `backend/tests/unit/research_layer/test_route_challenge_service.py`:

```python
from __future__ import annotations

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.services.route_challenge_service import RouteChallengeService


def test_route_challenge_status_marks_route_needing_review(tmp_path) -> None:
    store = ResearchApiStateStore(db_path=str(tmp_path / "route_challenge.sqlite3"))
    route = {
        "route_id": "route_1",
        "node_ids": ["node_a"],
        "claim_ids": ["claim_a"],
    }
    store.create_claim_conflict(
        workspace_id="ws_route_challenge",
        new_claim_id="claim_a",
        existing_claim_id="claim_b",
        conflict_type="possible_contradiction",
        status="needs_review",
        evidence={"reason": "test"},
        source_ref={"new_claim_id": "claim_a", "existing_claim_id": "claim_b"},
        created_request_id="req_route_challenge",
    )
    service = RouteChallengeService(store)

    result = service.evaluate_route(workspace_id="ws_route_challenge", route=route)

    assert result["challenge_status"] == "needs_review"
    assert result["conflict_count"] == 1
```

- [ ] **Step 2: Implement route challenge service**

Create `backend/src/research_layer/services/route_challenge_service.py`:

```python
from __future__ import annotations

from research_layer.api.controllers._state_store import ResearchApiStateStore


class RouteChallengeService:
    def __init__(self, store: ResearchApiStateStore) -> None:
        self._store = store

    def evaluate_route(self, *, workspace_id: str, route: dict[str, object]) -> dict[str, object]:
        claim_ids = {str(value) for value in route.get("claim_ids", []) if str(value).strip()}
        if not claim_ids:
            return {"challenge_status": "clean", "conflict_count": 0, "conflict_ids": []}
        conflicts = self._store.list_claim_conflicts(workspace_id=workspace_id)
        active = [
            item
            for item in conflicts
            if str(item["status"]) in {"needs_review", "accepted"}
            and (
                str(item["new_claim_id"]) in claim_ids
                or str(item["existing_claim_id"]) in claim_ids
            )
        ]
        if not active:
            status = "clean"
        elif any(str(item["status"]) == "accepted" for item in active):
            status = "weakened"
        else:
            status = "needs_review"
        return {
            "challenge_status": status,
            "conflict_count": len(active),
            "conflict_ids": [str(item["conflict_id"]) for item in active],
        }
```

- [ ] **Step 3: Add `claim_ids` and challenge status to route payloads**

Where routes are created or serialized, include:

```python
"claim_ids": route_claim_ids,
"challenge_status": challenge["challenge_status"],
"challenge_refs": {
    "conflict_count": challenge["conflict_count"],
    "conflict_ids": challenge["conflict_ids"],
},
```

Use node `claim_id` values already stored on graph nodes.

- [ ] **Step 4: Run tests**

Run:

```powershell
cd backend
$env:PYTHONPATH='src'
uv run pytest tests/unit/research_layer/test_route_challenge_service.py tests/unit/research_layer/test_slice7_route_engine.py -q
```

Expected: selected tests pass.

- [ ] **Step 5: Commit**

Run:

```powershell
git add backend/src/research_layer/services/route_challenge_service.py backend/src/research_layer/services/route_generation_service.py backend/src/research_layer/api/controllers/research_route_controller.py backend/tests/unit/research_layer/test_route_challenge_service.py
git commit -m "Mark routes with claim challenge status"
```

---

## Task 5: GraphRAG Query Endpoint

**Goal:** Provide a grounded research answer that uses graph paths, claim ids, source artifacts, and EverMemOS recall.

**Files:**
- Create: `backend/src/research_layer/api/schemas/graphrag.py`
- Create: `backend/src/research_layer/services/graphrag_service.py`
- Create: `backend/src/research_layer/api/controllers/research_graphrag_controller.py`
- Test: `backend/tests/unit/research_layer/test_graphrag_service.py`
- Test: `backend/tests/integration/research_api/test_c_plus_claim_memory_flow.py`

- [ ] **Step 1: Write service test**

Create `backend/tests/unit/research_layer/test_graphrag_service.py`:

```python
from __future__ import annotations

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.services.graphrag_service import GraphRAGService


def test_graphrag_answer_returns_claim_and_source_refs(monkeypatch, tmp_path) -> None:
    store = ResearchApiStateStore(db_path=str(tmp_path / "graphrag.sqlite3"))
    service = GraphRAGService(store)

    monkeypatch.setattr(
        service._retrieval_service,
        "retrieve",
        lambda **kwargs: {
            "items": [
                {
                    "object_type": "claim",
                    "object_id": "claim_1",
                    "score": 0.9,
                    "text": "Evidence supports the claim.",
                    "source_ref": {"source_id": "src_1"},
                }
            ],
            "trace_refs": {"retrieval": "fake"},
        },
    )
    monkeypatch.setattr(
        service._memory_recall_service,
        "recall",
        lambda **kwargs: {
            "status": "completed",
            "items": [],
            "total": 0,
            "trace_refs": {},
        },
    )

    result = service.answer(
        workspace_id="ws_graphrag",
        question="What supports the claim?",
        request_id="req_graphrag",
    )

    assert result["answer"]
    assert result["citations"][0]["claim_id"] == "claim_1"
    assert result["trace_refs"]["workspace_id"] == "ws_graphrag"
```

- [ ] **Step 2: Implement GraphRAG service**

Create `backend/src/research_layer/services/graphrag_service.py`:

```python
from __future__ import annotations

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.services.evermemos_bridge_service import EverMemOSRecallService
from research_layer.services.retrieval_views_service import RetrievalViewsService


class GraphRAGService:
    def __init__(self, store: ResearchApiStateStore) -> None:
        self._store = store
        self._retrieval_service = RetrievalViewsService(store)
        self._memory_recall_service = EverMemOSRecallService(store)

    def answer(self, *, workspace_id: str, question: str, request_id: str) -> dict[str, object]:
        retrieval = self._retrieval_service.retrieve(
            workspace_id=workspace_id,
            query=question,
            limit=8,
        )
        items = list(retrieval.get("items") or [])
        claim_ids = [
            str(item.get("object_id"))
            for item in items
            if str(item.get("object_type") or "") == "claim" and str(item.get("object_id") or "")
        ]
        memory = self._memory_recall_service.recall(
            workspace_id=workspace_id,
            requested_method="logical",
            query_text=question,
            scope_claim_ids=claim_ids,
            reason="graphrag_query",
            trace_refs={"request_id": request_id},
        )
        citations = [
            {
                "claim_id": str(item.get("object_id") or ""),
                "text": str(item.get("text") or ""),
                "source_ref": dict(item.get("source_ref") or {}),
                "score": float(item.get("score") or 0.0),
            }
            for item in items
            if str(item.get("object_id") or "")
        ]
        answer = self._compose_answer(question=question, citations=citations)
        return {
            "workspace_id": workspace_id,
            "question": question,
            "answer": answer,
            "citations": citations,
            "memory_recall": memory,
            "trace_refs": {
                "workspace_id": workspace_id,
                "request_id": request_id,
                "claim_ids": claim_ids,
                "retrieval": retrieval.get("trace_refs", {}),
            },
        }

    def _compose_answer(self, *, question: str, citations: list[dict[str, object]]) -> str:
        if not citations:
            return "没有找到足够的 claim 依据来回答这个问题。"
        joined = "；".join(str(item["text"]) for item in citations[:3])
        return f"基于已入库 claim，问题“{question}”的当前依据是：{joined}"
```

- [ ] **Step 3: Add schemas and controller**

Create request/response models in `backend/src/research_layer/api/schemas/graphrag.py`:

```python
from __future__ import annotations

from pydantic import BaseModel, Field


class GraphRAGRequest(BaseModel):
    workspace_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    limit: int = Field(default=8, ge=1, le=20)


class GraphRAGResponse(BaseModel):
    workspace_id: str
    question: str
    answer: str
    citations: list[dict[str, object]]
    memory_recall: dict[str, object]
    trace_refs: dict[str, object]
```

Create controller endpoint:

```text
POST /api/v1/research/graphrag/query
```

- [ ] **Step 4: Run tests**

Run:

```powershell
cd backend
$env:PYTHONPATH='src'
uv run pytest tests/unit/research_layer/test_graphrag_service.py -q
```

Expected: GraphRAG unit test passes.

- [ ] **Step 5: Commit**

Run:

```powershell
git add backend/src/research_layer/api/schemas/graphrag.py backend/src/research_layer/services/graphrag_service.py backend/src/research_layer/api/controllers/research_graphrag_controller.py backend/tests/unit/research_layer/test_graphrag_service.py
git commit -m "Add claim-grounded GraphRAG query"
```

---

## Task 6: Cross-Document Research Report

**Goal:** Produce a report across all workspace sources using claim ledger, route status, conflicts, and memory recall.

**Files:**
- Create: `backend/src/research_layer/services/cross_document_report_service.py`
- Create: `backend/src/research_layer/api/controllers/research_cross_document_report_controller.py`
- Test: `backend/tests/unit/research_layer/test_cross_document_report_service.py`
- Test: `backend/tests/integration/research_api/test_c_plus_claim_memory_flow.py`

- [ ] **Step 1: Write report service test**

Create `backend/tests/unit/research_layer/test_cross_document_report_service.py`:

```python
from __future__ import annotations

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.services.cross_document_report_service import CrossDocumentReportService


def test_cross_document_report_summarizes_claims_and_conflicts(tmp_path) -> None:
    store = ResearchApiStateStore(db_path=str(tmp_path / "cross_doc_report.sqlite3"))
    store.create_claim_conflict(
        workspace_id="ws_report",
        new_claim_id="claim_new",
        existing_claim_id="claim_old",
        conflict_type="possible_contradiction",
        status="needs_review",
        evidence={"new_text": "A", "existing_text": "not A"},
        source_ref={"new_claim_id": "claim_new", "existing_claim_id": "claim_old"},
        created_request_id="req_report",
    )
    service = CrossDocumentReportService(store)

    report = service.build(workspace_id="ws_report", request_id="req_report")

    assert report["workspace_id"] == "ws_report"
    assert report["summary"]["conflict_count"] == 1
    assert report["sections"]["conflicts"][0]["status"] == "needs_review"
```

- [ ] **Step 2: Implement report service**

Create `backend/src/research_layer/services/cross_document_report_service.py`:

```python
from __future__ import annotations

from research_layer.api.controllers._state_store import ResearchApiStateStore


class CrossDocumentReportService:
    def __init__(self, store: ResearchApiStateStore) -> None:
        self._store = store

    def build(self, *, workspace_id: str, request_id: str) -> dict[str, object]:
        claims = self._store.list_claims(workspace_id)
        conflicts = self._store.list_claim_conflicts(workspace_id=workspace_id)
        source_recalls = self._store.list_source_memory_recall_results(workspace_id=workspace_id)
        return {
            "workspace_id": workspace_id,
            "summary": {
                "claim_count": len(claims),
                "conflict_count": len(conflicts),
                "source_recall_count": len(source_recalls),
            },
            "sections": {
                "claims": claims[:50],
                "conflicts": conflicts[:50],
                "historical_recall": source_recalls[:20],
                "unresolved_gaps": [
                    conflict
                    for conflict in conflicts
                    if str(conflict.get("status")) == "needs_review"
                ],
            },
            "trace_refs": {"request_id": request_id},
        }
```

- [ ] **Step 3: Add controller**

Create endpoint:

```text
GET /api/v1/research/reports/{workspace_id}/cross-document
```

Return `CrossDocumentReportService(STORE).build(...)`.

- [ ] **Step 4: Run tests**

Run:

```powershell
cd backend
$env:PYTHONPATH='src'
uv run pytest tests/unit/research_layer/test_cross_document_report_service.py -q
```

Expected: report unit test passes.

- [ ] **Step 5: Commit**

Run:

```powershell
git add backend/src/research_layer/services/cross_document_report_service.py backend/src/research_layer/api/controllers/research_cross_document_report_controller.py backend/tests/unit/research_layer/test_cross_document_report_service.py
git commit -m "Add cross-document research report"
```

---

## Task 7: Frontend C+ Workflow Surfaces

**Goal:** Users can see historical recall, conflict review, route challenge status, and GraphRAG answers.

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/pages1.tsx`
- Modify: `frontend/src/pages2.tsx`
- Modify: `frontend/src/App.tsx`
- Create: `frontend/src/pages3.tsx` if needed.

- [ ] **Step 1: Add API clients**

Modify `frontend/src/api.ts`:

```ts
export interface ClaimConflictRecord {
  conflict_id: string;
  workspace_id: string;
  new_claim_id: string;
  existing_claim_id: string;
  conflict_type: string;
  status: string;
  evidence: Record<string, unknown>;
  source_ref: Record<string, unknown>;
}

export interface GraphRAGResponse {
  workspace_id: string;
  question: string;
  answer: string;
  citations: Array<Record<string, unknown>>;
  memory_recall: MemoryRecallResponse | null;
  trace_refs: Record<string, unknown>;
}

export async function listClaimConflicts(workspaceId: string): Promise<ClaimConflictRecord[]> {
  const payload = await apiGet(`/api/v1/research/conflicts/${encodeURIComponent(workspaceId)}`);
  return Array.isArray(payload?.items) ? payload.items : [];
}

export async function queryGraphRAG(workspaceId: string, question: string): Promise<GraphRAGResponse> {
  const payload = await apiPost('/api/v1/research/graphrag/query', {
    workspace_id: workspaceId,
    question,
  });
  return {
    workspace_id: String(payload?.workspace_id || workspaceId),
    question: String(payload?.question || question),
    answer: String(payload?.answer || ''),
    citations: Array.isArray(payload?.citations) ? payload.citations : [],
    memory_recall: normalizeMemoryRecall(payload?.memory_recall),
    trace_refs: payload?.trace_refs || {},
  };
}
```

- [ ] **Step 2: Show route challenge status in route list and detail**

Modify `frontend/src/pages1.tsx` route card rendering:

```tsx
const challenge = route.challenge_status || 'clean';
const challengeLabel: Record<string, string> = {
  clean: '未被挑战',
  challenged: '存在挑战',
  weakened: '已削弱',
  needs_review: '需复核',
};
```

Render:

```tsx
<span className={`pill challenge-${challenge}`}>
  {challengeLabel[challenge] || challenge}
</span>
```

- [ ] **Step 3: Add conflict review panel**

Either create `frontend/src/pages3.tsx` or add a side panel to `pages1.tsx`:

```tsx
<section className="panel">
  <h2>冲突复核</h2>
  {conflicts.map((item) => (
    <article key={item.conflict_id} className="conflict-card">
      <div>{item.conflict_type}</div>
      <div>{String(item.evidence?.new_text || '')}</div>
      <div>{String(item.evidence?.existing_text || '')}</div>
      <div>{item.status}</div>
    </article>
  ))}
</section>
```

- [ ] **Step 4: Add GraphRAG query box**

Add to research route or knowledge page:

```tsx
const [graphRagQuestion, setGraphRagQuestion] = useState('');
const [graphRagResult, setGraphRagResult] = useState<GraphRAGResponse | null>(null);
```

On submit:

```tsx
const result = await queryGraphRAG(workspaceId, graphRagQuestion);
setGraphRagResult(result);
```

Render answer, citations, and source refs. If citations are empty, show “没有找到足够的 claim 依据”.

- [ ] **Step 5: Run frontend build**

Run:

```powershell
cd frontend
npm run lint
npm run build
```

Expected: both commands pass.

- [ ] **Step 6: Commit**

Run:

```powershell
git add frontend/src/api.ts frontend/src/pages1.tsx frontend/src/pages2.tsx frontend/src/App.tsx frontend/src/pages3.tsx
git commit -m "Surface claim conflicts and GraphRAG in frontend"
```

---

## Task 8: End-to-End Real PDF Verification

**Goal:** Prove the finished C+ flow works with a real PDF, not demo data.

**Files:**
- No production files unless verification exposes bugs.
- Optional artifact: `docs/superpowers/reports/2026-04-24-c-plus-real-pdf-verification.md`

- [ ] **Step 1: Start backend and frontend with fixed logs and PID files**

Run:

```powershell
cd C:\Users\murphy\Desktop\mironicky-main\backend
if (Get-NetTCPConnection -LocalPort 1995 -State Listen -ErrorAction SilentlyContinue) { throw "1995 is already in use" }
$backend = Start-Process -FilePath "uv" -ArgumentList @("run","python","src/run.py") -WorkingDirectory (Get-Location) -RedirectStandardOutput "c-plus-backend.log" -RedirectStandardError "c-plus-backend.err.log" -PassThru
$backend.Id | Set-Content "c-plus-backend.pid"
```

Start static frontend with the project’s existing command. Do not assume `npm dev`; first inspect the existing frontend startup docs or package scripts.

- [ ] **Step 2: Verify access**

Run:

```powershell
curl.exe -s -w "`n%{http_code}" http://127.0.0.1:1995/health
curl.exe -s -w "`n%{http_code}" http://127.0.0.1:4174/index.html
```

Expected: both return `200`.

- [ ] **Step 3: Use Playwright CLI for browser smoke**

Run:

```powershell
npx playwright-cli open http://127.0.0.1:4174/index.html
```

Then use browser automation to:

1. Open import page.
2. Upload `C:\Users\murphy\Desktop\文化认知、差序格局和品牌态度的关系研究——以社会主流向善一致性为中介_于锦荣.pdf`.
3. Wait until extraction finishes.
4. Confirm candidates.
5. Open graph workbench.
6. Click one node and verify related memory section is visible.
7. Open route list and verify challenge status is visible.
8. Open conflict review and verify empty or populated state is explicit.
9. Ask one GraphRAG question: `差序格局如何影响品牌态度？`
10. Verify answer includes citations.

- [ ] **Step 4: API verification**

Run:

```powershell
curl.exe -s http://127.0.0.1:1995/api/v1/research/conflicts/ws-default-1
curl.exe -s -X POST http://127.0.0.1:1995/api/v1/research/graphrag/query -H "Content-Type: application/json" --data-binary "@graphrag-question.json"
curl.exe -s http://127.0.0.1:1995/api/v1/research/reports/ws-default-1/cross-document
```

Expected:

```text
conflicts endpoint returns 200
graphrag endpoint returns answer and citations
cross-document report returns summary and sections
```

- [ ] **Step 5: Stop processes by PID**

Run:

```powershell
cd C:\Users\murphy\Desktop\mironicky-main\backend
Get-Content c-plus-backend.pid | ForEach-Object { Stop-Process -Id ([int]$_) -Force }
Remove-Item c-plus-backend.pid,c-plus-backend.log,c-plus-backend.err.log -Force -ErrorAction SilentlyContinue
```

Also stop frontend by recorded PID. Do not kill by fuzzy process name.

- [ ] **Step 6: Commit verification fixes or report**

If no code changes:

```powershell
git status --short
```

Expected only ignored or intentionally untracked files.

If a verification report is created:

```powershell
git add docs/superpowers/reports/2026-04-24-c-plus-real-pdf-verification.md
git commit -m "Document C+ real PDF verification"
```

---

## Final Verification Matrix

Run:

```powershell
cd backend
$env:PYTHONPATH='src'
uv run pytest tests/unit/research_layer/test_claim_projection_guard_service.py tests/unit/research_layer/test_source_memory_recall_service.py tests/unit/research_layer/test_claim_conflict_service.py tests/unit/research_layer/test_route_challenge_service.py tests/unit/research_layer/test_graphrag_service.py tests/unit/research_layer/test_cross_document_report_service.py tests/integration/research_api/test_c_plus_claim_memory_flow.py -q
```

Run:

```powershell
cd frontend
npm run lint
npm run build
```

Run browser smoke with `npx playwright-cli`, not MCP if MCP permission fails.

Expected:

1. All targeted backend tests pass.
2. Frontend lint/build pass.
3. Browser smoke confirms real PDF produces claim-backed graph, routes, visible recall, conflict state, GraphRAG answer, and report.
4. `git status --short` contains only intentionally untracked files.

## Risk Controls

1. Do not make EverMemOS the truth source. It only returns recall suggestions.
2. Do not silently fall back. If recall, GraphRAG, or conflict detection cannot run, return explicit `skipped` or `failed` with reason.
3. Do not add fake frontend sample data. Every displayed item must come from backend API.
4. Do not broaden manual graph creation. Manual graph writes must bind a claim.
5. Keep deterministic tests first. LLM-based improvements can be added after the core claim ledger behavior passes.

## Self-Review

Spec coverage:

1. Hard claim gate: Task 1.
2. Import-time historical recall: Task 2.
3. Claim-vs-claim conflicts: Task 3.
4. Route challenge state: Task 4.
5. GraphRAG: Task 5.
6. Cross-document report: Task 6.
7. Frontend workflow: Task 7.
8. Real PDF verification: Task 8.

Placeholder scan:

No unresolved placeholders are intentionally left in this plan.

Type consistency:

The plan uses `claim_id`, `source_ref`, `memory_recall`, `claim_conflicts`, `challenge_status`, `GraphRAGResponse`, and `source_memory_recall_results` consistently across backend, API, and frontend tasks.

