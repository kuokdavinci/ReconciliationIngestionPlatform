# Data-quality test fixtures

Fixture nhỏ, deterministic cho generic ingestion data-quality và quarantine
test.

Giữ repository fixture tách khỏi raw file của Fraud Detection Dataset bên ngoài.
Profile mutation được tạo thành CSV `tmp_path` nhỏ thay vì commit raw-data copy.
Chỉ thêm case tối thiểu, đã sanitize, như:

- missing required field;
- conflicting duplicate;
- schema drift;
- invalid amount or timestamp;
- statistical outlier that should remain descriptive and non-gating.

Focused profile coverage nằm trong `tests/test_quality_profile.py`.
