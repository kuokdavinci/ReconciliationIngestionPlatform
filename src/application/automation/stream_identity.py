"""Stable identities for source streams, staged pages, and checkpoints."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from src.domain.fetch_config.models import FetchConfig, FetchMethod
from src.domain.ingestion.checkpoints import IngestionMode
from src.domain.ingestion.source_units import SourceUnitMetadata


def fetch_source_endpoint(config: FetchConfig) -> str:
    method_config = config.get_method_config()
    if config.fetch_method == FetchMethod.API:
        return method_config.base_url
    if config.fetch_method == FetchMethod.SFTP:
        return f"sftp://{method_config.host}:{method_config.port}{method_config.remote_path}"
    if config.fetch_method == FetchMethod.FILEDROP:
        return f"filedrop://{method_config.directory}/{method_config.pattern}"
    raise ValueError(f"Unsupported fetch method: {config.fetch_method}")


def source_stream_key(config: FetchConfig) -> str:
    """Return a stable logical stream identity, independent of run date."""

    return f"{config.partner}:{config.fetch_method.value}:{fetch_source_endpoint(config)}"


def raw_stage_key(config: FetchConfig, reconciliation_date: datetime) -> str:
    """Return the raw-page staging identity for one date/config version."""

    return ":".join(
        (
            config.partner,
            source_stream_key(config),
            reconciliation_date.date().isoformat(),
            str(config.updated_at),
        )
    )


def stream_identity(
    config: FetchConfig,
    *,
    mode: IngestionMode = IngestionMode.SCHEDULED,
    reconciliation_date: datetime | None = None,
) -> dict[str, Any]:
    stream_key = source_stream_key(config)
    if mode == IngestionMode.BACKFILL:
        if reconciliation_date is None:
            raise ValueError("Backfill stream identity requires reconciliation_date.")
        stream_key = f"{stream_key}:backfill:{reconciliation_date.date().isoformat()}"
    return {
        "partner": config.partner,
        "fetchConfigId": str(config.id),
        "sourceType": config.fetch_method.value,
        "streamKey": stream_key,
        "configVersion": str(config.updated_at),
        "sourceEndpoint": fetch_source_endpoint(config),
    }


def _source_units(
    units: Sequence[SourceUnitMetadata | dict[str, Any]],
) -> list[SourceUnitMetadata]:
    return [SourceUnitMetadata.from_payload(unit) for unit in units]


def units_after_checkpoint(
    units: Sequence[SourceUnitMetadata | dict[str, Any]], checkpoint: Any
) -> list[SourceUnitMetadata]:
    """Skip the completed prefix while keeping legacy replay compatibility."""

    normalized_units = _source_units(units)
    completed_key = getattr(checkpoint, "last_completed_unit_key", None)
    completed_hash = (getattr(checkpoint, "high_water_mark", None) or {}).get(
        "contentHash"
    )
    if not completed_key:
        completed_key = None
    for index, unit in enumerate(normalized_units):
        # The content-hash fallback keeps checkpoints created before the
        # mtime-independent source-unit identity change replay-safe.
        if unit.source_unit_key == completed_key or (
            completed_hash and unit.content_hash == completed_hash
        ):
            return normalized_units[index + 1 :]
    return normalized_units


__all__ = [
    "fetch_source_endpoint",
    "raw_stage_key",
    "source_stream_key",
    "stream_identity",
    "units_after_checkpoint",
]
