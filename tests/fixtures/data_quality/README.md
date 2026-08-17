# Data-quality test fixtures

Small, deterministic fixtures for data-quality and quarantine tests.

Keep these fixtures separate from the external IBM AML-LI raw dataset. Add only
minimal, sanitized cases such as:

- missing required field;
- conflicting duplicate;
- schema drift;
- invalid amount or timestamp;
- statistical outlier that should remain a warning/review.

