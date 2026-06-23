# Codebase Concerns

**Analysis Date:** 2026-06-23

## Tech Debt

### 1. File-level `eslint-disable @typescript-eslint/no-explicit-any` in 7 files

- **Issue:** Entire files disable the `no-explicit-any` rule, nullifying TypeScript benefits across critical modules.
- **Files:**
  - `frontend-next/src/types/review-center.ts`
  - `frontend-next/src/lib/api/review-center-normalizer.ts`
  - `frontend-next/src/components/review-center/use-guided-review.ts`
  - `frontend-next/src/components/review-center/guided-review-modal.tsx`
  - `frontend-next/src/components/mapping-studio/mapping-studio-wizard.tsx`
  - `frontend-next/src/app/mapping-studio/page.tsx`
  - `frontend-next/src/app/reconciliation/page.tsx` (line-level disable)
- **Impact:** All type safety is lost in these files. Runtime errors that could be caught at compile time will slip through. This is the single biggest type-safety deficit in the frontend.
- **Fix approach:** Remove file-level disables. Introduce proper typed interfaces for API responses. Start with `types/review-center.ts` (the type definitions file) and `review-center-normalizer.ts` (the data mapper), then propagate types to consumer files.

### 2. Massive orchestration in `reconciliation/page.tsx` (581 lines)

- **Issue:** The reconciliation page is the largest frontend file (581 lines) and contains data loading, filtering, pagination, state management, error handling, and rendering all in one component.
- **Files:** `frontend-next/src/app/reconciliation/page.tsx`
- **Impact:** Hard to test, hard to reason about. Duplicate logic between `loadPage` and `handleSilentRefresh` — both build the same result-mapping pipeline. The `handle404OrThrow` helper is defined inside the component body, recreating on every render.
- **Fix approach:** Extract data-fetching into a custom hook (similar to `useReviewPackets` pattern). Extract `handle404OrThrow` and `handleLocalRowUpdate` as module-level utilities. Split `loadPage` into focused fetch functions.

### 3. Duplicated packet/selection logic between `loadPage` and `handleSilentRefresh`

- **Issue:** The `loadPage` function (lines 199–286) and `handleSilentRefresh` (lines 92–135) share nearly identical result mapping, review record merging, and stats calculation logic. Both call `api.getStats`, `api.getResults`, `api.getReviewRecords` with the same error handling pattern.
- **Files:** `frontend-next/src/app/reconciliation/page.tsx`
- **Impact:** Any change to result processing must be duplicated in two places, creating a maintenance trap. The functionality has already drifted — `loadPage` fetches insights, `handleSilentRefresh` does not.
- **Fix approach:** Extract a shared `useReconciliationData` hook that handles all fetching, mapping, and error handling. Both load and refresh paths call the same underlying logic.

### 4. `except Exception` blanket catches throughout the Python API layer (39+ occurrences)

- **Issue:** Nearly every FastAPI endpoint uses `except Exception as exc:` with a generic error message, silently swallowing the original error type and stack trace context.
- **Files:**
  - `src/api/reconciliation.py` — 7 occurrences (lines 108, 450, 465, 506, 565, 654, 744)
  - `src/api/mappings.py` — 6 occurrences (lines 157, 232, 345, 566, 675, 727)
  - `src/api/data_explorer.py` — 5 occurrences (lines 124, 140, 206, 226, 284)
  - `src/api/insights.py` — 3 occurrences (lines 273, 379, 439)
  - `src/api/review_packets.py` — 3 occurrences (lines 657, 709)
  - `src/pipeline/ingestion_pipeline.py` — 2 occurrences (lines 284, 469)
  - `src/scheduler/jobs.py` — 2 occurrences (lines 297, 383)
  - `src/fetchers/sftp_fetcher.py` — 1 occurrence (line 88)
  - `src/fetchers/filedrop_fetcher.py` — 1 occurrence (line 87)
  - `src/fetchers/api_fetcher.py` — 1 occurrence (line 108)
  - `src/analysis/provider.py` — 3 occurrences (lines 107, 120)
  - `src/analysis/services.py` — 1 occurrence (line 227)
  - `src/analysis/insights.py` — 1 occurrence (line 886)
  - `src/analysis/reporter.py` — 1 occurrence (line 115)
  - `src/scheduler/scheduler.py` — 1 occurrence (line 161)
  - `src/config/ai_generator.py` — 2 occurrences (lines 301, 320)
  - `src/services/review_packet_actions.py` — 1 occurrence (line 293)
- **Impact:** Specific error types (e.g., `ValueError`, `KeyError`, database connection issues) are all collapsed into `500 Internal Server Error` with generic messages. Debugging production issues becomes guesswork. The `except Exception` pattern in `provider.py` also silently catches provider failures that should propagate.
- **Fix approach:** Replace with specific exception types where predictable. Use FastAPI exception handlers for known error types. Log the full exception with `exc_info=True` before raising `HTTPException`.

### 5. `pass` statements in catch blocks and abstract methods

- **Issue:** Several `except` blocks use bare `pass`, silently ignoring failures. The abstract base class `BaseFetcher.fetch` uses `pass` instead of raising `NotImplementedError`.
- **Files:**
  - `src/analysis/services.py` lines 108, 120, 129 — `pass` after `json.JSONDecodeError` in parsing (fallback behavior, but chains silently)
  - `src/pipeline/ingestion_pipeline.py` line 489 — `pass # Best effort` after secondary exception during error handling
  - `src/analysis/insights.py` line 176 — `pass` during iteration over results
  - `src/fetchers/base.py` line 46 — `pass` in abstract method instead of `raise NotImplementedError`
  - `src/scheduler/scheduler.py` line 121 — docstring mislabeled as `pass`
  - `src/models/mapping_config.py` line 138 — `pass` in counter increment logic
- **Impact:** Silently swallowed errors can cause silent data corruption or partial processing. Missing `NotImplementedError` on abstract methods means subclasses that forget to implement `fetch` will crash at runtime with a confusing `AttributeError`.
- **Fix approach:** Replace `pass` in abstract methods with `raise NotImplementedError`. In catch blocks, log a warning at minimum with context about what was skipped.

### 6. Mock data files shipped with production code (5 mock files)

- **Issue:** The frontend ships mock data generators alongside production API client code. These mocks are not isolated to test directories.
- **Files:**
  - `frontend-next/src/lib/state/mock-reconciliation-data.ts`
  - `frontend-next/src/lib/state/mock-review-center-data.ts`
  - `frontend-next/src/lib/state/mock-schedules-data.ts`
  - `frontend-next/src/lib/state/mock-mapping-data.ts`
  - `frontend-next/src/lib/state/mock-audit-data.ts`
- **Impact:** Mock data is not gated behind feature flags or environment checks. If accidentally imported in production, it serves fake data. Increases bundle size with unused code.
- **Fix approach:** Move to `frontend-next/src/mock/` directory. Import only in development via `if (process.env.NODE_ENV !== 'production')` guards or dynamic imports.

### 7. Legacy `frontend/` directory retained as dead code

- **Issue:** The original Vite-based `frontend/` dashboard is kept as "legacy/reference only" per `NEXTJS_MIGRATION_PLAN.md` and `TODO.md`, but still exists and may confuse developers about which frontend is active.
- **Files:** Entire `frontend/` directory (not migrated to `frontend-next/`)
- **Impact:** Dead code that must be maintained. Developers could make changes to the wrong frontend. Documentation discrepancies between the two codebases.
- **Fix approach:** Archive to a `archive/frontend-vite/` directory or remove entirely once all feature parity is verified. Update docs to remove all references.

### 8. `# type: ignore` comments in Excel reader (8 occurrences)

- **Issue:** The Excel reader suppresses type errors with `# type: ignore[union-attr]`, `# type: ignore[index]`, `# type: ignore[assignment]`, and `# type: ignore[arg-type]` instead of properly handling optional types.
- **Files:** `src/readers/excel_reader.py` lines 149, 160, 166, 170, 173, 177, 180, 235
- **Impact:** If `_workbook` or `_worksheet` is `None` at runtime (e.g., called outside context manager), the code crashes with `AttributeError` instead of a descriptive error. The `_require_workbook()` guard exists but relies on a late runtime check rather than the type system.
- **Fix approach:** Use `assert self._workbook is not None` or narrow types with early returns. Replace `# type: ignore` with proper runtime checks that raise `RuntimeError`.

### 9. Duplicated result mapping and stats recalculation in three places

- **Issue:** The reconciliation page has the same result-mapping + stats-recalculation logic repeated in `loadPage`, `handleSilentRefresh`, and `handleLocalRowUpdate` / `handleLocalRowBatchUpdate` — with slight variations in each.
- **Files:** `frontend-next/src/app/reconciliation/page.tsx` lines 92–135, 199–286, and 137–197
- **Impact:** Any change to the reconciliation result shape or review state merging must be replicated in three places. Inconsistencies are already present (e.g., `loadPage` fetches insights, `handleSilentRefresh` does not, `handleLocalRowUpdate` recalculates stats inline).
- **Fix approach:** Extract into a shared `useReconciliationData` hook with a single `mergeResultsWithReviewRecords(results, reviewRecords)` utility function.

---

## Security Considerations

### 1. SFTP `AutoAddPolicy` enabled

- **Risk:** The SFTP fetcher uses `paramiko.AutoAddPolicy()` which automatically accepts unknown host keys, making it vulnerable to man-in-the-middle attacks.
- **Files:** `src/fetchers/sftp_fetcher.py` line 116
- **Current mitigation:** None.
- **Recommendations:** Replace `AutoAddPolicy` with `WarningPolicy` or `RejectPolicy` with a known host key stored in configuration. At minimum, log a warning when accepting an unknown host key for audit trail purposes.

### 2. Actor header falls back to `"Administrator"` / `"admin"` silently

- **Risk:** When the `X-Actor` header is missing, the frontend defaults to `"Administrator"` (in `lib/actor.ts`) and the backend defaults to `"admin"` (in `api/actor.py` outside test context). This means any unauthenticated request auto-escalates to admin-level permissions.
- **Files:**
  - `frontend-next/src/lib/actor.ts` line 2: `const DEFAULT_ACTOR = "Administrator";`
  - `src/api/actor.py` line 26: `return "admin"`
- **Current mitigation:** The backend checks `X-Actor` header on mutating endpoints via `require_actor()`.
- **Recommendations:** Remove silent fallback to admin-level actors. Return `400 Bad Request` when actor is not provided (the test-passthrough behavior is reasonable). On the frontend, consider adding an explicit actor selector if multiple operator personas are needed.

### 3. `ENCRYPTION_KEY` read from environment variable without validation

- **Risk:** The credential decryption system reads `ENCRYPTION_KEY` from `os.getenv("ENCRYPTION_KEY")` without validating that the key is a valid Fernet key format. A misconfigured key will crash at runtime.
- **Files:** `src/fetchers/base.py` lines 91–99
- **Current mitigation:** Basic existence check only. If `ENCRYPTION_KEY` is present but malformed, `Fernet(encryption_key.encode())` will raise a `ValueError` at decryption time.
- **Recommendations:** Validate the key format on application startup. Log a critical warning at boot time if `ENCRYPTION_KEY` is set but invalid. Document the expected key format in `.env.example`.

### 4. SFTP credentials may be passed as plaintext in config

- **Risk:** The credential resolution system in `src/fetchers/base.py` line 74 allows plain text values: `returns as-is (not recommended for production)`. If a fetch config stores credentials in plaintext, they are logged in error messages and stored in MongoDB.
- **Files:** `src/fetchers/base.py` lines 49–74 (credential resolution), `src/fetchers/sftp_fetcher.py` lines 88–89 (error includes `exc`)
- **Current mitigation:** The codebase supports `env:` and `encrypted:` prefixes, but does not enforce them.
- **Recommendations:** Warn or reject plaintext credentials in non-development environments. Audit existing fetch configs in the database for plaintext values. Redact credentials from error messages.

---

## Performance Bottlenecks

### 1. Reconciliation engine loads all partner records into memory before processing

- **Problem:** `_iter_partner_record_batches` and `_collect_scoped_partner_keys` both load partner records into memory before iterating. For partners with millions of records, this will cause OOM.
- **Files:** `src/reconciliation/engine.py` lines 172–196
- **Cause:** The engine has two code paths — one async cursor (streaming) and one `find_many` (non-streaming). The `find_many` path loads all results into a list. The `_collect_scoped_partner_keys` method iterates all partner records to build a set of partner keys.
- **Improvement path:** Remove the non-streaming path entirely. Use MongoDB aggregation with `$lookup` for the scope-based filtering instead of loading all keys into a Python set. Add integration tests with large data volumes.

### 2. In-memory TTL cache without eviction limit

- **Problem:** `TTLCache` uses an unbounded `dict` for caching. If many partner/date/focus combinations are queried, the cache grows indefinitely until entries expire (default TTL: 5 minutes).
- **Files:** `src/analysis/cache.py` lines 20–23
- **Cause:** No maximum size enforcement. Entries are only removed on read (lazy eviction) or explicit `invalidate`/`clear` calls.
- **Improvement path:** Add a `max_size` parameter with LRU eviction. Use `collections.OrderedDict` or `cachetools.TTLCache` for bounded-size caching.

### 3. Client-side filtering of all results in reconciliation page

- **Problem:** The reconciliation page fetches only 100 results (`{ limit: 100 }`), but filtering, pagination, and stats calculation are all performed client-side in memory.
- **Files:** `frontend-next/src/app/reconciliation/page.tsx` lines 300–340
- **Cause:** The backend API only returns raw data. All business logic for filtering, sorting, and aggregation lives on the frontend.
- **Improvement path:** Move filtering and pagination to the backend API with proper `$match` MongoDB queries. The frontend should only render what it fetches, not filter 100 records down to 40.

### 4. Multiple sequential insight API calls for each category

- **Problem:** The reconciliation page fires 3 separate API calls for `anomalies`, `patterns`, and `recommendations` insights, each with the same 404-error-handling wrapper.
- **Files:** `frontend-next/src/app/reconciliation/page.tsx` lines 208–226
- **Cause:** Each insight type is a separate backend endpoint call.
- **Improvement path:** Add a single `?focus=all` endpoint parameter that returns all insight types in one response. Parallel calls (via `Promise.all`) mitigate this somewhat, but a single round-trip reduces overhead and error handling complexity.

---

## Fragile Areas

### 1. `src/analysis/insights.py` (1088 lines) — Largest file in the codebase

- **Files:** `src/analysis/insights.py`
- **Why fragile:** Contains orchestration for the entire AI analysis pipeline: MongoDB queries, metrics computation, grouping, cache management, LLM provider routing, prompt building, response parsing, guardrail validation, and fallback logic. At 1088 lines it violates the single-responsibility principle.
- **Safe modification:** Changes to prompt templates, cache logic, or fallback behavior all touch this file. Test coverage exists (`test_analysis_insights.py`) but is sparse relative to complexity.
- **Test coverage:** 41 test files exist for `tests/`, including `test_analysis_insights.py`, but coverage of the 1088-line file is incomplete.

### 2. `src/api/reconciliation.py` (748 lines) — API + business logic mix

- **Files:** `src/api/reconciliation.py`
- **Why fragile:** Mixes FastAPI route handlers with data processing logic (stats calculation, result mapping, background task tracking). The `loadPage`/`handleSilentRefresh` duplication on the frontend mirrors backend inconsistency.
- **Safe modification:** The `ReconciliationEngine` (460 lines) is a separate class, making it easier to test. But endpoint handlers contain inline business logic that should live in services.
- **Test coverage:** `test_api_reconciliation.py` and `test_api_reconciliation_review_records.py` exist but may miss edge cases.

### 3. `src/api/review_packets.py` (744 lines) — Approval workflow orchestration

- **Files:** `src/api/review_packets.py`
- **Why fragile:** Contains the entire review packet lifecycle: listing, classification, AI mapping, runtime validation, approval, rejection, and post-approval tracking. 3 `except Exception` blanket catches obscure specific failures.
- **Safe modification:** The `src/services/review_packet_actions.py` (532 lines) extracts some action logic, but the API layer still owns too much orchestration. Changes to approval flow require changes across both files.
- **Test coverage:** `test_api_review_packets.py` (610 lines) is one of the larger test files, which is good. But coverage of edge cases (partial failures, concurrent approvals) is unclear.

### 4. `src/services/copilot_context.py` (558 lines) — Rule-based context builder

- **Files:** `src/services/copilot_context.py`
- **Why fragile:** Contains heavy use of `dict[str, Any]` for all return types (lines 107, 287, 342, 470, 471, 479, 480). No typed return objects. Extensive use of `Any` parameters throughout (lines 18, 23, 45, 49, 64, 402, 435, 531, 542). This makes refactoring risky as changes to internal document shapes won't be caught by the type checker.
- **Safe modification:** Add typed dataclasses or TypedDicts for all return shapes. The `CopilotContext` dataclass at line 79 is a good start but only covers the top-level structure.
- **Test coverage:** `test_copilot_context.py` exists but given the heavy `Any` usage, it likely only tests happy paths.

### 5. Frontend 581-line reconciliation page

- **Files:** `frontend-next/src/app/reconciliation/page.tsx`
- **Why fragile:** Single component owns data loading, error handling, filtering, pagination, stats, row selection, 9 modals/dialogs, and rendering. It uses `handle404OrThrow` defined inline (recreated every render). The `results` state is typed as `ReconciliationRow[]` but extensively accessed via `(r: any)` throughout.
- **Safe modification:** Break into focus-specific hooks (data loading, filtering, pagination, selection). Use proper type assertions instead of `as any`.
- **Test coverage:** No frontend test files detected (`*.test.*` or `*.spec.*` files not found in `frontend-next/`).

### 6. Transaction normalizer (520 lines) with heavy `Any` usage

- **Files:** `src/normalizer/normalizer.py`
- **Why fragile:** The normalizer uses `Any` for nearly every parameter and return type (lines 36, 38, 39, 73, 88, 142, 150, 152, 210, 212, 286, 313, 347, 388, 443, 490). This means any refactoring of the internal data model cannot be validated by the type checker.
- **Safe modification:** Define a `NormalizedRow` TypedDict or dataclass. Use `Union` types for the specific value types the normalizer handles (string, number, None).
- **Test coverage:** `test_normalizer.py` (832 lines) is one of the largest test files but may still miss edge cases due to the unrestricted `Any` types.

---

## Known Bugs

### 1. SFTP fetcher always downloads to `./downloads/` (hardcoded path)

- **Symptoms:** Downloads are always stored in `./downloads/` relative to the working directory. No configuration override exists. If multiple partners fetch simultaneously, filename collisions can occur.
- **Files:** `src/fetchers/sftp_fetcher.py` line 47: `local_dir = Path("./downloads")`
- **Trigger:** Any SFTP fetch operation.
- **Workaround:** Ensure the working directory has a `./downloads/` directory and partner files have unique names.

### 2. Reconciliation page fetches only first 100 results server-side

- **Symptoms:** The pagination UI may show fewer pages than the actual dataset warrants. If the first 100 results don't include all status types, status-filtering dropdowns will show empty counts.
- **Files:** `frontend-next/src/app/reconciliation/page.tsx` lines 96, 206: `{ limit: 100 }`
- **Trigger:** When the total reconciliation result set exceeds 100 rows.
- **Workaround:** Increase the hardcoded limit to match typical dataset sizes, or add server-side pagination.

---

## Test Coverage Gaps

### 1. No frontend tests detected

- **What's not tested:** The entire `frontend-next/` codebase (64+ TypeScript/TSX files) has zero test files. No Jest, Vitest, or Playwright configuration files found.
- **Files:** All 64+ files in `frontend-next/src/`
- **Risk:** Any frontend refactoring (like splitting the reconciliation page or extracting hooks) has no safety net. Regressions in critical flows (approve/reject, reconciliation review, mapping validation) will go undetected.
- **Priority:** High

### 2. Inconsistent backend API test coverage

- **What's not tested:** Some API modules lack dedicated test files:
  - `src/api/automation.py` — no dedicated test (only `test_api_automation.py` and `test_api_automation_run.py` exist partially)
  - `src/api/operations.py` — no dedicated test file
  - `src/api/response_utils.py` — no test file
  - `src/services/audit.py` — no dedicated test
  - `src/services/runtime_validation.py` — no dedicated test
  - `src/analysis/provider.py` — tested indirectly but not directly
  - `src/analysis/cache.py` — `test_config_cache.py` exists but for config cache, not insight cache
- **Files:** Multiple files in `src/api/`, `src/services/`, `src/analysis/`
- **Risk:** Service-layer changes (audit logging, runtime validation, provider fallback) lack direct unit tests.
- **Priority:** Medium

---

## Configuration & Environment Issues

### 1. `PARTNER` and `DATE` hardcoded in reconciliation page

- **Problem:** The reconciliation page hardcodes `const PARTNER = "MOMO"` and `const DATE = new Date().toISOString().slice(0, 10)` instead of reading from URL/search params or user input.
- **Files:** `frontend-next/src/app/reconciliation/page.tsx` lines 26–27
- **Impact:** The page always loads data for MOMO and today's date on first render. Switching partners in the dropdown works but the initial load is hardcoded. Bookmarking or sharing reconciliation URLs with different partner/date parameters is broken.
- **Fix approach:** Read `partner` and `date` from `searchParams` (Next.js search params) with defaults.

### 2. Backend `mongodb_url` falls back to localhost

- **Problem:** `src/config/settings.py` defaults `mongodb_url` to `"mongodb://localhost:27017"`. If `APP_MONGODB_URL` env var is not set, production will silently connect to localhost instead of the production database.
- **Files:** `src/config/settings.py` line 11
- **Impact:** Easy misconfiguration. The scheduler at `src/scheduler/scheduler.py` line 62 also has a fallback `"mongodb://localhost:27017"`.
- **Fix approach:** Remove the fallback default for non-development environments. Validate the connection URL at startup and fail fast if pointing to localhost in production.

### 3. Missing `BACKEND_API_URL` in production deployment config

- **Problem:** The Next.js rewrites in `next.config.ts` use `process.env.BACKEND_API_URL ?? "http://localhost:8000"`. In production, this may point to localhost if the env var is not set.
- **Files:** `frontend-next/next.config.ts` line 3
- **Current mitigation:** `.env.example` includes `BACKEND_API_URL=http://localhost:8000` (line 49).
- **Recommendations:** Add build-time validation or a startup check that verifies the backend URL is reachable. Document the required env var for production deployments.

---

## Dependency Risks

### 1. No pinned dependency versions in `requirements.txt`

- **Risk:** Using `>=` specifiers means `pip install` can pull breaking changes. For example, `fastapi>=0.115.0` could upgrade to 1.0.0 with breaking API changes.
- **Files:** `requirements.txt`
- **Impact:** Builds are non-reproducible. A `docker build` today may succeed but break tomorrow if a dependency releases a breaking change.
- **Migration plan:** Pin exact versions or use `~=` (compatible release) specifiers. Lock with `uv.lock` (already has `uv.lock` in the repo). Document the lockfile workflow.

---

*Concerns audit: 2026-06-23*
