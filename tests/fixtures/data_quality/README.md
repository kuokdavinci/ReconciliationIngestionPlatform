# Data-quality test fixtures

Small, deterministic fixtures for generic ingestion data-quality and quarantine
tests.

Keep repository fixtures separate from the external Fraud Detection Dataset raw
file. Profile mutations are generated as small `tmp_path` CSVs, rather than
committed raw-data copies. Add only minimal, sanitized cases such as:

- missing required field;
- conflicting duplicate;
- schema drift;
- invalid amount or timestamp;
- statistical outlier that should remain descriptive and non-gating.

The focused profile coverage lives in `tests/test_quality_profile.py`.
