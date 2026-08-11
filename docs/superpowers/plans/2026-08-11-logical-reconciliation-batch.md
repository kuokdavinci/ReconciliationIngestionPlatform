# Logical Reconciliation Batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (\`- [ ]\`) syntax for tracking.

**Goal:** Group every raw page in one fetch stream into one logical \`reconciliation_file\`, ingest all pages under that identity, and run reconciliation once after the complete batch is verified.

**Architecture:** Raw API pages remain independently stored in Mongo/GridFS under one \`rawStageKey\` for audit and replay. The first successful page creates the batch-level \`reconciliation_file\`; later page transactions are rebound to that file identity and their temporary page claims are removed. The review packet supplies the selected scope before one final reconciliation call.

**Tech Stack:** Python 3.11, FastAPI services, MongoDB/Motor metadata, PostgreSQL/SQLAlchemy transaction store, pytest, uv.

## Global Constraints

- Keep raw payloads page-scoped in Mongo/GridFS; do not concatenate large payloads in memory.
- Use one stable \`sourceFileId\` for all partner rows and reconciliation results in a raw stream.
- Do not call reconciliation until every staged page is ingested successfully.
- A failed page must not leave a partially reconciled batch visible as completed.
- Preserve existing manual retry and Airflow runtime status semantics.

---

### Task 1: Add regression tests for batch identity and single reconciliation

**Files:**
- Modify: tests/test_api_review_packets.py
- Modify: tests/test_review_architecture.py if shared fixtures are required

**Interfaces:**
- Consumes: _reprocess_staged_pages(), fake raw-page repository, fake ingestion pipeline, fake reconciliation service.
- Produces: Tests proving three pages produce one output file ID and one reconciliation invocation.

- [x] **Step 1: Write the failing test**

Add a focused async test for a three-page raw stream:

~~~python
async def test_reprocess_staged_pages_groups_all_pages_into_one_file_and_reconciles_once():
    result = await _reprocess_staged_pages(...)
    assert result["fileId"] == "logical-file-1"
    assert result["stats"]["pageCount"] == 3
    assert result["stats"]["totalRows"] == 6
    reconciliation.execute.assert_awaited_once()
    assert reconciliation.execute.await_args.kwargs["command"].source_file_id == "logical-file-1"
~~~

Configure page ingestion to return page file IDs page-file-1, page-file-2, and page-file-3; assert page 2 and 3 transactions are rebound to logical-file-1, and temporary page file claims are deleted.

- [x] **Step 2: Run the focused test and verify it fails**

Run: uv run pytest tests/test_api_review_packets.py -k "groups_all_pages_into_one_file" -q

Expected: FAIL because the current implementation returns the last page file ID and calls reconciliation once per page.

- [x] **Step 3: Add the failure-path test**

Add an async test where page 2 returns FAILED; assert reconciliation is never called, the logical batch is marked failed, and no page-3 ingestion is attempted.

- [x] **Step 4: Run both focused tests**

Run: uv run pytest tests/test_api_review_packets.py -k "groups_all_pages_into_one_file or stops_before_reconciliation_when_page_fails" -q

Expected: Both tests fail for the current per-page orchestration.

---

### Task 2: Implement batch-level staged-page reprocessing

**Files:**
- Modify: src/services/review_packet_actions.py:574-742
- Modify: src/infrastructure/partner_transaction/repository.py only if a source-file rebind seam is needed

**Interfaces:**
- Consumes: rawStageKey, ordered raw pages, approved packet scope, existing ingestion pipeline.
- Produces: One logical file ID, cumulative page/row stats, one reconciliation command.

- [x] **Step 1: Establish one batch identity**

Use the first successful page's file claim as the logical file ID. Track logical_source_file_id and processed_page_ids. After each later page succeeds, rebind its inserted transactions by ingestion keys to the logical file ID and delete its temporary reconciliation_file claim. Update the logical file metadata with rawStageKey, pageCount, pageIds, expectedRowCount, and actualRowCount.

- [x] **Step 2: Move reconciliation after the page loop**

Remove the reconciliation call from inside the page loop. After all pages succeed, set the packet scope on the logical file and execute one ReconciliationCommand with logical_source_file_id. Set outputFileId, runtime sourceFileId, result fileId, and final stats to the same logical ID.

- [x] **Step 3: Add failure cleanup**

If any page fails, delete transactions belonging to the logical source file, mark the logical batch FAILED, keep remaining raw pages staged for replay, do not invoke reconciliation, and persist pageCount, processedPageCount, and failure details in runtime/post-approval stats.

- [x] **Step 4: Run the focused tests and make them pass**

Run: uv run pytest tests/test_api_review_packets.py -k "groups_all_pages_into_one_file or stops_before_reconciliation_when_page_fails" -q

Expected: PASS.

---

### Task 3: Verify API scope reads the logical batch

**Files:**
- Modify: tests/test_api_reconciliation.py or tests/test_postgres_repository_filters.py
- Modify: src/api/reconciliation.py only if the existing latest-file filter still narrows a completed batch incorrectly

**Interfaces:**
- Consumes: one reconciliation_file with pageCount=3, one runtime run, and six PostgreSQL result rows sharing sourceFileId.
- Produces: /reconciliation/results and /reconciliation/stats return all six rows.

- [x] **Step 1: Write a failing API filter regression test**

Assert that the selected logical file ID is used once and that the returned total is six, not two.

- [x] **Step 2: Run the test to verify the failure**

Run: uv run pytest tests/test_api_reconciliation.py -k "logical_batch" -q

- [x] **Step 3: Fix only the scope resolution if needed**

Prefer the completed post-approval/runtime sourceFileId over an arbitrary newest page file. Do not broaden unrelated historical runs.

- [x] **Step 4: Run the API regression test**

Run: uv run pytest tests/test_api_reconciliation.py -k "logical_batch" -q

Expected: PASS.

---

### Task 4: Document and verify the end-to-end invariants

**Files:**
- Modify: docs/phase-2/sprint-2.6-recovery-hardening.md
- Modify: docs/INDEX.md only if the document index requires a new entry

- [x] **Step 1: Document the batch contract**

Record the raw-page versus logical-file distinction, scope selection in Review Packet, failure behavior, and the six required post-run invariants.

- [x] **Step 2: Run the targeted backend tests**

Run: uv run pytest tests/test_api_review_packets.py tests/test_api_reconciliation.py tests/test_review_architecture.py -q

- [x] **Step 3: Run repository checks**

Run:

~~~text
uv run pytest tests/test_raw_page_staging.py tests/test_reconciliation.py -q
git diff --check
rtk codegraph sync
rtk codegraph status
~~~

- [x] **Step 4: Verify the live data shape after a controlled UI run**

Confirm: raw_ingestion_page has 3 pages with one rawStageKey; reconciliation_file has 1 logical file; partner_transaction has 6 rows with one sourceFileId; reconciliation_result has 6 rows with one sourceFileId and runtime run; reconciliation invocation count is 1.
