# Timestamp parser review fix

## Changes

- Reject ISO offsets with hours outside `00`–`23` or minutes outside `00`–`59`
  before calling `datetime.fromisoformat`.
- Require all four approved legacy timestamp forms to match their fixed-width
  grammar before parsing with `datetime.strptime`.
- Add pure-parser regression coverage for invalid offset components and
  non-fixed-width legacy inputs.

## TDD evidence

- RED: `tests/test_timestamp_normalization.py` reported 7 expected failures for
  invalid offset minutes and single-digit legacy fields.
- GREEN: `36 passed` for the timestamp parser test module.

## Verification

- `pytest -q tests/test_timestamp_normalization.py tests/test_normalizer.py`:
  `103 passed`.
- `ruff check src dags scripts cli`: passed.
- `mypy src/ --show-error-codes`: `Success: no issues found in 214 source files`.
- `git diff --check`: passed.
