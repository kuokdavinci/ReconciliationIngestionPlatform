# Benchmark v2 credential redaction review fix

## Scope

- Removed `mongodb_url` from the v2 benchmark report and Markdown evidence.
- Retained only the safe environment metadata `mongodb: configured` and
  `db_name`.
- Preserved MongoDB connection behavior, benchmark mapping/configuration,
  counters, and bounded errors.
- Did not modify frozen v1 artifacts or credentials.

## Regression coverage

The benchmark artifact test injects
`mongodb://review_user:review_password@localhost:27017/db`, generates JSON and
Markdown through `run_benchmark`, and verifies that neither credentials nor the
raw URI occur while the safe metadata remains.

## Verification

- RED: `pytest -q tests/test_benchmark_fraud_detection.py` produced the
  expected credential-leak assertion failure.
- GREEN: `pytest -q tests/test_benchmark_fraud_detection.py` — 14 passed.
- `ruff check scripts/benchmark_fraud_detection.py
  tests/test_benchmark_fraud_detection.py` — no issues.
- `mypy scripts/benchmark_fraud_detection.py
  tests/test_benchmark_fraud_detection.py` — no issues.
- `git diff --check` — clean.
