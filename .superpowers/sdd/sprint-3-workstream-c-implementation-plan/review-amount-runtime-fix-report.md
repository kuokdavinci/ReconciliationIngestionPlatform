# Review Amount / Runtime Fix Report

## Scope

- Centralized canonical `amount` coercion after DECIMAL, CONSTANT, and MAPPING transformations.
- Added a Decimal-only, finite-value guard to normal and fast canonical builders.
- Mapped structured `INVALID_AMOUNT` runtime evidence directly to `INVALID_DECIMAL`.
- Added RowProcessor parity, defensive builder, and runtime-preview regressions.

## TDD evidence

RED command:

```text
UV_CACHE_DIR=/tmp/workstream-c-uv-cache uv run pytest -q tests/test_normalizer.py tests/test_quality_contract.py tests/test_api_review_packets.py -k 'invalid_normalized_amount or transformed_non_finite_amount or runtime_invalid_amount_code or runtime_preview_reports_non_finite'
```

Result before implementation: `16 failed, 157 deselected`. Failures reproduced normal-mode Pydantic exceptions, fast-mode raw-value evidence, direct canonical construction failures/coercion, `CANONICAL_BUILD_FAILED`, and runtime-preview exceptions.

GREEN result after implementation: `16 passed, 157 deselected`.

## Final verification

- Owned test files: `173 passed in 0.81s`.
- Normalizer: `72 passed in 0.12s`.
- Quality contract: `68 passed in 0.20s`.
- API review packets: `33 passed in 0.49s`.
- Ruff: `All checks passed!` for `src tests`.
- Mypy: `Success: no issues found in 214 source files`.
- `git diff --check`: clean.
- An optional whole-suite run reached 72% without failures, then was interrupted after making no progress/output for several minutes; the requested focused suites above completed cleanly.
