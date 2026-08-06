from src.domain.ingestion.source_units import IngestionOutcome, SourceUnitMetadata


def test_source_unit_metadata_normalizes_camel_and_snake_case_payloads():
    unit = SourceUnitMetadata.from_payload(
        {
            "source_unit_key": "page:1",
            "cursor_before": "cursor-0",
            "highWaterMark": {"page": 1},
        }
    )

    assert unit.source_unit_key == "page:1"
    assert unit.cursor_before == "cursor-0"
    assert unit["sourceUnitKey"] == "page:1"
    assert unit.get("high_water_mark") == {"page": 1}


def test_ingestion_outcome_normalizes_duplicate_and_retry_metadata():
    outcome = IngestionOutcome.from_result(
        {
            "success": False,
            "outcome": "FILE_DUPLICATE",
            "error_code": "duplicate_file",
            "next_retry_at": None,
            "error_metadata": {"fileHash": "hash-1"},
        }
    )

    assert outcome.success is True
    assert outcome.error_code == "duplicate_file"
    assert outcome.error_metadata == {"fileHash": "hash-1"}


def test_ingestion_outcome_preserves_waiting_review_state():
    outcome = IngestionOutcome.from_result(
        {
            "success": False,
            "outcome": "WAITING_REVIEW",
            "errorCode": "configuration_approval_required",
            "error": "A mapping draft is waiting for review.",
        }
    )

    assert outcome.waiting_for_review is True
    assert outcome.error_code == "configuration_approval_required"
