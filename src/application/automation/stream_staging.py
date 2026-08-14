"""Durable raw-page staging boundary for source streams."""

from typing import Any


async def stage_stream_unit(
    raw_page_repo: Any,
    *,
    stage_key: str,
    partner: str,
    fetch_config_id: str,
    source_type: str,
    stream_key: str,
    reconciliation_date,
    unit,
) -> bool:
    """Stage a fetched unit and report whether the adapter supports staging."""
    try:
        await raw_page_repo.stage_from_path(
            stage_key=stage_key,
            partner=partner,
            fetch_config_id=fetch_config_id,
            source_type=source_type,
            stream_key=stream_key,
            reconciliation_date=reconciliation_date,
            unit=unit,
        )
    except TypeError as exc:
        # Lightweight test doubles and legacy adapters may not expose a
        # Motor database. Real storage/network errors must still propagate.
        if (
            "must be MotorDatabase" not in str(exc)
            and "can't be used in 'await' expression" not in str(exc)
        ):
            raise
        return False
    return True
