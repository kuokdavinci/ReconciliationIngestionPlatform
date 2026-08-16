"""File-drop and SFTP source stream execution."""

from typing import Any

from src.application.automation.stream_failure import file_fetch_failure_result
from src.application.automation.stream_fetching import (
    source_units,
    unit_high_water_mark,
)
from src.application.automation.stream_identity import units_after_checkpoint
from src.application.automation.stream_lifecycle import StreamRunContext


async def run_file_stream(
    *,
    context: StreamRunContext,
    method_config: Any,
) -> dict[str, Any]:
    """Fetch and process the discovered non-paginated file units."""

    identity = context.identity
    fetch_result = await context.fetcher.fetch(
        method_config,
        context.reconciliation_date,
        fetch_metadata={"configVersion": identity["configVersion"]},
    )
    if not fetch_result.success:
        no_new_file = (
            fetch_result.metadata.get("scanned_files") == 0
            and "No files matching" in (fetch_result.error or "")
        )
        if no_new_file:
            return {
                "success": True,
                "processed": 0,
                "failed": 0,
                "outcome": "NO_NEW_FILE",
            }
        return file_fetch_failure_result(fetch_result.error)

    fetched_units = source_units(fetch_result.units or [])
    units = units_after_checkpoint(fetched_units, context.checkpoint)
    if fetched_units and not units:
        return {
            "success": True,
            "processed": 0,
            "failed": 0,
            "replayed": len(fetched_units),
            "outcome": "FETCH_UNIT_REPLAY",
            "reconciliationSkipped": True,
        }
    if not fetched_units:
        return {
            "success": True,
            "processed": 0,
            "failed": 0,
            "outcome": "NO_NEW_FILE",
            "reconciliationSkipped": True,
        }

    for unit in units:
        unit.fetch_metadata = {
            **fetch_result.metadata,
            **({"rawStageKey": context.stage_key} if context.stage_key else {}),
        }
        unit.high_water_mark = unit_high_water_mark(unit)

    return await context.dependencies.process_source_units(
        context.checkpoint_repo,
        stream_identity={
            **identity,
            "lastCompletedUnitKey": context.checkpoint.last_completed_unit_key
            if context.checkpoint
            else None,
        },
        units=units,
        ingest_unit=context.ingest_unit,
        mode=context.mode,
        retry_policy=context.retry_policy,
        on_unit_completed=context.cleanup_unit,
    )


__all__ = ["run_file_stream"]
