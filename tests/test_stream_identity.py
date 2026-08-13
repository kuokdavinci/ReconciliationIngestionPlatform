from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from src.domain.fetch_config.models import APIConfig, FetchConfig, FetchMethod
from src.domain.ingestion.checkpoints import IngestionMode


def _api_config() -> FetchConfig:
    return FetchConfig(
        partner="VIETTELPAY",
        fetchMethod=FetchMethod.API,
        api=APIConfig(baseUrl="https://partner.example/settlement"),
        updatedAt=datetime(2026, 8, 13, tzinfo=UTC),
    )


def test_stream_identity_is_stable_for_scheduled_runs() -> None:
    from src.application.automation.stream_identity import (
        fetch_source_endpoint,
        source_stream_key,
        stream_identity,
    )

    config = _api_config()

    assert fetch_source_endpoint(config) == "https://partner.example/settlement"
    assert source_stream_key(config) == (
        "VIETTELPAY:API:https://partner.example/settlement"
    )
    assert stream_identity(config)["streamKey"] == source_stream_key(config)


def test_backfill_identity_is_date_scoped() -> None:
    from src.application.automation.stream_identity import (
        source_stream_key,
        stream_identity,
    )

    config = _api_config()
    reconciliation_date = datetime(2026, 8, 13, tzinfo=UTC)

    scheduled = stream_identity(config)
    backfill = stream_identity(
        config,
        mode=IngestionMode.BACKFILL,
        reconciliation_date=reconciliation_date,
    )

    assert backfill["streamKey"] == (
        f"{source_stream_key(config)}:backfill:2026-08-13"
    )
    assert backfill["streamKey"] != scheduled["streamKey"]


def test_backfill_identity_requires_a_reconciliation_date() -> None:
    from src.application.automation.stream_identity import stream_identity

    with pytest.raises(
        ValueError,
        match="Backfill stream identity requires reconciliation_date.",
    ):
        stream_identity(_api_config(), mode=IngestionMode.BACKFILL)


def test_raw_stage_key_is_scoped_by_date_and_config_version() -> None:
    from src.application.automation.stream_identity import raw_stage_key

    config = _api_config()

    result = raw_stage_key(config, datetime(2026, 8, 13, tzinfo=UTC))

    assert result == (
        "VIETTELPAY:VIETTELPAY:API:https://partner.example/settlement:"
        "2026-08-13:2026-08-13 00:00:00+00:00"
    )


def test_units_after_checkpoint_supports_legacy_content_hash() -> None:
    from src.application.automation.stream_identity import units_after_checkpoint

    checkpoint = SimpleNamespace(
        last_completed_unit_key="legacy-mtime-sensitive-key",
        high_water_mark={"contentHash": "same-content"},
    )
    units = [
        {
            "sourceUnitKey": "new-mtime-sensitive-key",
            "contentHash": "same-content",
        },
        {"sourceUnitKey": "next-file", "contentHash": "new-content"},
    ]

    remaining = units_after_checkpoint(units, checkpoint)

    assert [unit.source_unit_key for unit in remaining] == ["next-file"]
