Status: DONE

Task: Decompose API pagination with pure helpers

Summary:
- Extracted page request construction from `APIFetcher._fetch_paginated` into `_build_page_request`.
- Extracted JSON decoding and pagination payload validation into `_parse_page_payload`.
- Extracted page write + content-type return into `_write_page`.
- Kept retry/error mapping, loop state, repeated-cursor handling, max-page handling, and fetch result assembly in `_fetch_paginated`.

Files changed:
- `src/fetchers/api_fetcher.py`
- `tests/test_api_pagination.py`

Test-first evidence:
- Added focused unit tests for `_build_page_request` and `_parse_page_payload`.
- Verified RED with `uv run pytest tests/test_api_pagination.py -q`:
  - failed because `APIFetcher` did not yet define `_build_page_request`
  - failed because `APIFetcher` did not yet define `_parse_page_payload`
- Implemented the smallest extraction needed to satisfy the new tests while preserving existing pagination behavior.

Behavior preserved:
- Page, page size, cursor, source identity, source-unit key, local filename, config version, and empty-cursor semantics remain unchanged.
- `_parse_page_payload` preserves JSON decoding, list validation, cursor type validation, and cursor normalization.
- `_write_page` still allows `PermissionError` to be handled by `_fetch_paginated` and mapped to `fetch_storage_permission_denied`.
- Public `fetch` API and pagination result/error contracts unchanged.

Verification:
- `uv run pytest tests/test_api_pagination.py -q` → 13 passed
- `uv run pytest tests/test_api_pagination.py tests/test_phase8.py -q` → 55 passed
- `uv run ruff check src/fetchers tests/test_api_pagination.py tests/test_phase8.py` → passed
- `uv run mypy src/ --show-error-codes` → passed

Notes:
- The requested duplicate consecutive mocked-response assignment in `test_source_unit_identity_changes_with_config_version` was not present in the current file, so no change was needed there.
- The three non-paginated `TestAPIFetcher` cases in `tests/test_phase8.py` were left unchanged.

Concerns:
- None.
