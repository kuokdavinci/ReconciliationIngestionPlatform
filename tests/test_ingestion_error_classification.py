from src.application.ingestion.contracts import is_missing_ingestion_key_failure


def test_missing_ingestion_key_classifier_requires_all_rows_and_both_identity_fields():
    assert is_missing_ingestion_key_failure(
        total_rows=2,
        success_rows=0,
        failed_rows=2,
        errors=[
            {"field": "id", "reason": "missing"},
            {"field": "trace", "reason": "missing"},
        ],
    ) is True

    assert is_missing_ingestion_key_failure(
        total_rows=2,
        success_rows=1,
        failed_rows=1,
        errors=[{"field": "id"}, {"field": "trace"}],
    ) is False
