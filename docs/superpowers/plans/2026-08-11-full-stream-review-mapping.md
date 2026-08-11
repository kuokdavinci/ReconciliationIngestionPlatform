# Full-Stream Review Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose all raw records belonging to a Review Packet's staged stream during mapping review and keep validation/replay on the same stream scope.

**Architecture:** `rawStageKey` is the stream root; `sourceUnitKey` identifies each page. Add a packet-scoped paginated raw-records API backed by the existing Mongo metadata/GridFS payload store, then add a Guided Review table that consumes that API. Runtime validation and post-approval replay use the same stream root.

**Tech Stack:** FastAPI, Motor/MongoDB, GridFS, existing source readers, Next.js/React, TypeScript, pytest, Vitest/Playwright where existing frontend tests apply, uv.

## Global Constraints

- Preserve `sourceUnitKey`/`fetchUnitKey` as per-page idempotency identities; do not replace them with a stream-wide identifier.
- Preserve `rawStageKey` as the stream-wide scope used by staging and replay.
- Never embed large raw payloads in a Mongo BSON Review Packet document.
- Use `uv` for Python dependency/test commands.
- Use `tests/asgi_test_client.py`/async ASGI transport; do not introduce blocking `TestClient` calls inside async tests.
- Use `apply_patch` for edits and refresh `.codegraph/codegraph.db` after structural changes.

### Task 1: Backend stream reader contract

**Files:**
- Modify: `src/infrastructure/ingestion/raw_page_repository.py`
- Create or modify: `src/services/review_raw_stream.py`
- Test: `tests/test_review_raw_stream.py`

**Interfaces:**
- Produces `read_review_stream_page(db, packet, offset, limit) -> dict` or an equivalent service boundary returning ordered rows, `totalRecords`, `pageCount`, and pagination metadata.
- Consumes `ReviewPacket.raw_stage_key`, `RawIngestionPageRepository.find_for_replay`, GridFS materialization, and existing source-reader/signature utilities.

- [ ] Write a failing test proving pages from one `rawStageKey` are ordered and concatenated across a page boundary.
- [ ] Run `uv run pytest tests/test_review_raw_stream.py -q` and confirm the new behavior fails before implementation.
- [ ] Write a failing test proving another partner/date stream is excluded even when it has the same reconciliation date.
- [ ] Implement the smallest stream reader that queries only `STAGED`/`CONSUMED` pages for the packet's `rawStageKey`, materializes GridFS payloads, and applies global offset/limit.
- [ ] Add explicit missing-stage and missing-payload errors; do not fallback to `sourceFileId` or a same-day query.
- [ ] Run the focused tests and confirm they pass.

### Task 2: Packet-scoped API

**Files:**
- Modify: `src/api/review_packets.py`
- Modify: `tests/test_api_review_packets.py`

**Interfaces:**
- Produces `GET /api/v1/review-packets/{packet_id}/raw-records?offset=0&limit=50`.
- Consumes the Task 1 service and serializes rows with `page`, `sourceUnitKey`, and raw values.

- [ ] Add a failing endpoint test for `totalRecords`, `pageCount`, `rows`, `offset`, `limit`, and `hasMore`.
- [ ] Add a failing endpoint test that a packet without `rawStageKey` returns a deterministic client error.
- [ ] Implement packet lookup, pending/retained stream checks, query validation (`1 <= limit <= 200`, `offset >= 0`), and service delegation.
- [ ] Keep packet sample preview and AI mapping context bounded; the new endpoint is the full-data inspection path.
- [ ] Run API tests and confirm they pass.

### Task 3: Full-stream runtime validation consistency

**Files:**
- Modify: `src/services/runtime_validation.py`
- Modify: `src/api/review_packets.py`
- Test: `tests/test_runtime_validation.py` or the existing review-packet test module

**Interfaces:**
- Produces validation counts over the packet's staged stream while retaining at most five trace samples and bounded failed examples.
- Consumes the same raw stream reader as the API viewer, plus the draft mapping.

- [ ] Add a failing test with two staged pages where only the second page contains an invalid mapped row; assert validation sees both pages and reports the invalid row.
- [ ] Run the focused test and confirm it fails because current validation reads only `sourceFilePath`/one page.
- [ ] Refactor validation input behind a stream-row iterator; preserve the current fallback only for legacy packets without `rawStageKey`.
- [ ] Keep response payload bounded: aggregate `sampledRows/successRows/failedRows`, cap traces/examples, and never return all validation traces in one packet.
- [ ] Run runtime-validation and review-packet tests.

### Task 4: Guided Review raw stream table

**Files:**
- Modify: `frontend-next/src/types/review-center.ts`
- Modify: `frontend-next/src/lib/api/review-center.ts`
- Create or modify: `frontend-next/src/components/review-center/guided-review-raw-stream-step.tsx`
- Modify: `frontend-next/src/components/review-center/guided-review-modal.tsx`
- Modify: `frontend-next/src/components/review-center/use-guided-review.ts`
- Test: existing frontend test location for Review Center, or add a focused component test beside the component

**Interfaces:**
- Produces typed `RawStreamPage`/`RawStreamRow` models and `getReviewPacketRawRecords(packetId, offset, limit)`.
- Consumes `ReviewPacket.rawStageKey` and renders paginated raw values with source-unit provenance.

- [ ] Add a failing frontend test for loading the first page, rendering total/page metadata, and requesting the next page with the same packet ID.
- [ ] Implement the API client and table with loading, empty, expired-payload, and pagination states.
- [ ] Place the table in the mapping review flow before approval controls; do not replace the bounded AI sample/validation trace UI.
- [ ] Run frontend lint/typecheck/tests and fix only feature-related failures.

### Task 5: Approval/replay contract verification and docs

**Files:**
- Modify: `tests/test_review_architecture.py`
- Modify: `tests/test_api_review_packets.py`
- Modify: `docs/phase-2/sprint-2.6-recovery-hardening.md`
- Modify: `docs/superpowers/specs/2026-08-11-full-stream-review-mapping-design.md`

- [ ] Add a regression test proving approval replays every page under one `rawStageKey` and marks each page consumed.
- [ ] Add a regression test proving a retry reuses the same stream scope and does not create a second packet for the same pending stage.
- [ ] Update progress docs with endpoint contract, UI behavior, retention limitation, and live acceptance commands.
- [ ] Run `uv run ruff check` on changed Python files, `uv run pytest` on the complete affected test set, frontend checks, `git diff --check`, and `rtk codegraph status`.
- [ ] Verify live packet raw-record pagination against a staged demo stream without modifying unrelated data.

