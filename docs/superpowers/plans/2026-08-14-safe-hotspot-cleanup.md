# Safe Hotspot Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dọn các phần legacy và hotspot còn lại có boundary rõ ràng, đồng thời xác nhận backend CI và ingestion CI chạy đúng mà không thêm abstraction không cần thiết.

**Architecture:** API review packet sẽ gọi builder/service thuộc `application/review`; `PartnerData` chỉ còn trong domain. `APIFetcher` vẫn là public entry point, chỉ tách các helper thuần trong cùng file để giảm độ phình của pagination loop. Test suite giữ các contract khác nhau và chỉ loại bỏ setup/test thực sự trùng.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, pytest/pytest-asyncio, Ruff, mypy, uv, GitHub Actions.

## Global Constraints

- Không thay đổi public API của `APIFetcher.fetch` hoặc response/metadata/error contract.
- Không tạo strategy class, state machine, compatibility alias mới hoặc facade mới chỉ để di chuyển code.
- Không gom `src/infrastructure/persistence` với `src/infrastructure/postgres` trong plan này.
- Không sửa các file người dùng đang thay đổi: `TODO.md`, `docs/phase-2/sprint-1-eval-benchmark-run.md` và hai plan chưa commit hiện có.
- Mọi thay đổi production phải có test đỏ trước, sau đó chạy test scope và quality checks.
- Sau thay đổi import/cấu trúc phải kiểm tra và refresh `.codegraph/codegraph.db` nếu cần.

---

### Task 1: Chuyển Studio handoff packet về application review

**Files:**
- Modify: `src/application/review/proposal_creation.py`
- Modify: `src/api/review_packets.py`
- Modify: `tests/test_review_application_boundaries.py`
- Modify: `tests/test_api_review_packets.py`

**Interfaces:**
- Produces `create_studio_handoff_review_packet(*, mapping: MappingConfig, mapping_id: str, packet_repo: ReviewPacketRepository) -> ReviewPacket` in `src.application.review.proposal_creation`.
- The API route keeps loading the mapping and serializing the returned packet; it no longer constructs `ReviewPacket` directly.

- [ ] **Step 1: Add the failing ownership test**

Add a boundary assertion that `src/api/review_packets.py` contains no `ReviewPacket(` constructor, and add an application-level test that calls `create_studio_handoff_review_packet` with a small in-memory repository fake and verifies the persisted packet contains `STUDIO_HANDOFF`, mapping metadata, and the approval recommendation.

- [ ] **Step 2: Run the focused tests and verify the expected failure**

Run:

```bash
uv run pytest tests/test_review_application_boundaries.py tests/test_api_review_packets.py -q
```

Expected: fail because the new application builder is not defined and the API still owns the constructor.

- [ ] **Step 3: Implement the minimal application builder and delegate from the route**

Move the current packet field values into `create_studio_handoff_review_packet`, pass the existing `ReviewPacketRepository` from the route, await its `create`, and return the created packet. Remove only the now-unused constructor import from the API module.

- [ ] **Step 4: Run the focused tests and verify the behavior**

Run:

```bash
uv run pytest tests/test_review_application_boundaries.py tests/test_api_review_packets.py -q
```

Expected: all tests pass and the API boundary assertion confirms packet construction belongs to application review.

- [ ] **Step 5: Run the targeted lint check**

```bash
uv run ruff check src/application/review/proposal_creation.py src/api/review_packets.py tests/test_review_application_boundaries.py tests/test_api_review_packets.py
```

### Task 2: Remove the duplicate core `PartnerData` model

**Files:**
- Modify: `src/core/types.py`
- Modify: `tests/test_core_types.py`
- Modify: `tests/test_partner_transaction_architecture.py`

**Interfaces:**
- `src.domain.partner_transaction.models.PartnerData` remains the only production `PartnerData` model.
- `src.core.types` continues exporting `FieldMapping`, `CanonicalTransaction`, `ValidationError`, `ProcessingStats`, and `BatchInsertResult` unchanged.

- [ ] **Step 1: Add the failing architecture assertion**

Add a test that reads `src/core/types.py` and asserts it no longer defines `class PartnerData`; update the existing domain ownership test to cover the same migration boundary without importing the core duplicate.

- [ ] **Step 2: Run the focused tests and verify the expected failure**

```bash
uv run pytest tests/test_core_types.py tests/test_partner_transaction_architecture.py -q
```

Expected: fail because `src/core/types.py` still defines `PartnerData` and `tests/test_core_types.py` still imports/tests it.

- [ ] **Step 3: Remove only the duplicate model and its duplicate tests**

Delete the `PartnerData` class from `src/core/types.py`, remove its import and `TestPartnerData` block from `tests/test_core_types.py`, and keep the existing domain model tests in `tests/test_models.py` as the canonical behavior coverage.

- [ ] **Step 4: Run the model and architecture tests**

```bash
uv run pytest tests/test_core_types.py tests/test_models.py tests/test_partner_transaction_architecture.py -q
```

Expected: all tests pass and no production file imports `PartnerData` from `src.core.types`.

- [ ] **Step 5: Run the targeted static checks**

```bash
uv run ruff check src/core/types.py tests/test_core_types.py tests/test_partner_transaction_architecture.py
uv run mypy src/ --show-error-codes
```

### Task 3: Decompose API pagination with pure helpers

**Files:**
- Modify: `src/fetchers/api_fetcher.py`
- Modify: `tests/test_api_pagination.py`

**Interfaces:**
- Add `APIFetcher._build_page_request(config, reconciliation_date, base_query_params, local_dir, page, cursor, config_version) -> tuple[dict[str, str], Path, SourceUnitMetadata]`.
- Add `APIFetcher._parse_page_payload(content: bytes, items_path: str | None, next_cursor_path: str | None) -> tuple[list[Any], str | None]`.
- Add `APIFetcher._write_page(response: httpx.Response, local_path: Path) -> str` that writes the response bytes and returns the content type; `PermissionError` remains raised to the existing caller for identical error mapping.
- Keep `_fetch_paginated` responsible for loop state, retry/error mapping, result assembly, repeated-cursor detection, and max-page handling.

- [ ] **Step 1: Add focused tests for the new pure helper contracts**

Add tests for `_build_page_request` preserving the configured page/limit/cursor values, including an empty cursor, and for `_parse_page_payload` returning items/normalized cursor while rejecting a non-list items value and an invalid cursor type.

- [ ] **Step 2: Run the focused tests and verify the expected failure**

```bash
uv run pytest tests/test_api_pagination.py -q
```

Expected: fail because the helper methods do not exist yet.

- [ ] **Step 3: Implement the helpers without changing the fetch contract**

Move only request construction, JSON pagination parsing, and page file writing into the named helpers. Replace the corresponding inline blocks in `_fetch_paginated`; preserve status codes, error codes, source-unit fields, cursor semantics, sample rows, file sizes, and metadata keys byte-for-byte where applicable.

- [ ] **Step 4: Run the complete API fetcher regression suite**

```bash
uv run pytest tests/test_api_pagination.py tests/test_phase8.py -q
```

Expected: all pagination and legacy non-paginated API fetch tests pass.

- [ ] **Step 5: Remove only proven duplicate test setup**

Remove the duplicate consecutive assignment of the same mocked response in `test_source_unit_identity_changes_with_config_version`; do not remove the three non-paginated `TestAPIFetcher` cases in `test_phase8.py` because they cover non-pagination success, HTTP failure, and timeout retry.

- [ ] **Step 6: Run ingestion-scope quality checks**

```bash
uv run ruff check src/fetchers tests/test_api_pagination.py tests/test_phase8.py
uv run mypy src/ --show-error-codes
```

### Task 4: Audit test suite and verify CI workflows

**Files:**
- Inspect: `.github/workflows/backend-quality.yml`
- Inspect: `.github/workflows/ingestion-pipeline.yml`
- Inspect: `tests/test_phase8.py`
- Inspect: `tests/test_api_pagination.py`
- Modify only if a verified command/path is stale: the relevant workflow or test file.

**Interfaces:**
- Backend workflow remains migration → Ruff → mypy → backend tests with `AI_API_KEY=sk-test-fake-key`.
- Ingestion workflow remains migration → ingestion Ruff scope → the five configured ingestion/evaluation test modules.

- [ ] **Step 1: Collect the test suite and inspect duplicate candidates**

```bash
uv run pytest --collect-only -q tests/test_api_pagination.py tests/test_phase8.py tests/test_core_types.py tests/test_models.py
```

Compare behaviors, not test names. Keep complementary non-paginated and paginated API tests; confirm the removed core `PartnerData` tests are covered by `tests/test_models.py`.

- [ ] **Step 2: Run the exact backend workflow commands locally**

```bash
uv run alembic upgrade head
uv run ruff check src dags scripts cli
uv run mypy src/ --show-error-codes
AI_API_KEY=sk-test-fake-key uv run pytest tests/ --ignore=tests/test_analysis_e2e.py --ignore=tests/test_ingestion_integration.py --ignore=tests/test_ingestion_pipeline.py --ignore=tests/test_seed_momo_e2e.py --ignore=tests/test_sprint1_eval_benchmark.py -q --tb=short
```

- [ ] **Step 3: Run the exact ingestion workflow commands locally**

```bash
uv run ruff check src/fetchers src/pipeline src/application/automation src/domain/fetch_config/models.py src/infrastructure/persistence/mongo_indexes.py scripts/demo/scenarios
AI_API_KEY=sk-test-fake-key uv run pytest tests/test_indexes.py tests/test_ingestion_integration.py tests/test_ingestion_pipeline.py tests/test_seed_momo_e2e.py tests/test_sprint1_eval_benchmark.py -q --tb=short
```

- [ ] **Step 4: Refresh and validate the repository codegraph**

Run `rtk codegraph sync` if changed files are not already indexed, then run `rtk codegraph status` and require `Index is up to date`.

- [ ] **Step 5: Run final changed-code validation**

```bash
rtk git diff --check
rtk git status --short
```

Confirm that only intended source/test/spec/plan files changed and all pre-existing user edits remain untouched.
