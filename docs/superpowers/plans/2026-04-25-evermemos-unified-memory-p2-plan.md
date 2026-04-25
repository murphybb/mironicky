# EverMemOS Unified Memory P2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Close the real P2 gaps in Mironicky's EverMemOS integration without turning the graph layer into an unsafe dual-write system.

**Architecture:** Claim ledger stays the truth source. EverMemOS is a long-term memory and recall engine. Source import writes a source-level memory record; confirmed claims write claim-level memory records; graph edits only re-sync their existing claim refs instead of creating independent memory truth.

**Tech Stack:** Python, FastAPI controllers, ResearchApiStateStore SQLite, local EverMemOS MemoryManager, pytest.

---

## Boundaries

- Do not touch hypothesis multi-agent files in this branch.
- Do not write fake memory results. If EverMemOS is unavailable, surface failed/skipped status through events and persisted links.
- Do not add a new frontend feature in this task.
- Do not make graph nodes/edges the truth source. Graph edits must reuse existing claim refs.
- Do not store full raw PDF bytes in EverMemOS. Raw source remains in Research SQLite/source artifacts/hash.

## Success Criteria

1. Source import persists the source/hash/artifacts as before and additionally attempts a source-level EverMemOS write with explicit event status.
2. Local MemoryManager claim writes store a stable non-empty `memory_id` in `claim_memory_links`.
3. Graph node/edge create/patch/archive re-syncs the existing `claim_id` memory link when that graph object has a claim, without creating independent graph memories.
4. Existing recall behavior still works.
5. Targeted backend tests pass.
6. Independent reviewer confirms no unrelated hypothesis-agent changes were touched.

## Task 1: Addressable Local Claim Memory Link

**Files:**
- Modify: `backend/src/research_layer/services/evermemos_bridge_service.py`
- Test: `backend/tests/unit/research_layer/test_evermemos_unified_memory_p2.py`

- [x] Add a test proving local `sync_claim()` returns a non-empty stable `memory_id` and status `written_addressable_ref` when local MemoryManager reports success.
- [x] Implement a deterministic local memory ref from the claim id, for example `local_memory_manager:claim:<claim_id>`.
- [x] Keep `sync_mode=local_memory_manager`; do not pretend the local ref is an HTTP EverMemOS id.

## Task 2: Source Import Writes Source-Level Memory

**Files:**
- Modify: `backend/src/research_layer/services/evermemos_bridge_service.py`
- Modify: `backend/src/research_layer/services/source_memory_recall_service.py`
- Modify: `backend/src/research_layer/services/source_import_service.py`
- Test: `backend/tests/unit/research_layer/test_evermemos_unified_memory_p2.py`

- [x] Add a service method that writes one source-level memory summary after source persistence.
- [x] The memory content must include title, source type, source id, parser/hash metadata when present, and a short normalized content preview.
- [x] Emit and persist explicit events: `source_memory_bridge_started` and `source_memory_bridge_completed`.
- [x] Keep source recall after source write, so import still discovers historical related memories.

## Task 3: Graph Edits Re-Sync Claim Memory

**Files:**
- Modify: `backend/src/research_layer/api/controllers/research_graph_controller.py`
- Test: `backend/tests/unit/research_layer/test_evermemos_unified_memory_p2.py`

- [x] Add tests for graph node create, node patch, and edge archive triggering `ResearchMemoryBridge.sync_claim()` when the object has `claim_id`.
- [x] Add a small helper in the controller that loads the claim and calls the bridge.
- [x] Emit explicit graph-memory events only through the existing bridge; do not create graph-only memories.
- [x] If a graph object lacks a claim, emit no memory sync and do not fail the graph operation.

## Task 4: Verification and Review

**Files:**
- Modify: this plan only to record completion status if needed.

- [x] Run targeted tests: `uv run pytest backend/tests/unit/research_layer/test_evermemos_unified_memory_p2.py backend/tests/unit/research_layer/test_source_memory_recall_service.py backend/tests/unit/research_layer/test_p1_memory_recall_main_paths.py -q`.
- [x] Run integration guard: `uv run pytest backend/tests/integration/research_api/test_c_plus_claim_memory_flow.py -q`.
- [x] Dispatch independent reviewer to check spec compliance and code quality.
- [x] Fix reviewer findings and rerun tests.

## Acceptance Record

- Implemented source-level EverMemOS/local MemoryManager write after source import, while keeping source recall intact.
- Implemented addressable local claim memory refs and retrieval resolution for `local_memory_manager:claim:<claim_id>`.
- Implemented graph node/edge create, patch, and archive claim-memory re-sync through existing claim refs.
- Verified: `PYTHONPATH=backend/src uv run pytest backend/tests/unit/research_layer/test_evermemos_unified_memory_p2.py backend/tests/unit/research_layer/test_source_memory_recall_service.py backend/tests/unit/research_layer/test_p1_memory_recall_main_paths.py backend/tests/integration/research_api/test_c_plus_claim_memory_flow.py -q` => 27 passed.
- Independent reviewer approved after second review.
