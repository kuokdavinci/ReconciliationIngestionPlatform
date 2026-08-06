"""Architecture checks for source-unit domain contracts."""

from src.domain.ingestion.source_units import IngestionOutcome, SourceUnitMetadata
from src.application.ingestion.source_unit_orchestrator import (
    process_source_units as application_process_source_units,
)
from src.models.source_unit import (
    IngestionOutcome as LegacyIngestionOutcome,
    SourceUnitMetadata as LegacySourceUnitMetadata,
)


def test_legacy_source_unit_module_is_a_compatibility_facade() -> None:
    """Legacy imports must resolve to the ingestion domain implementation."""

    assert LegacyIngestionOutcome is IngestionOutcome
    assert LegacySourceUnitMetadata is SourceUnitMetadata


def test_scheduler_source_unit_module_is_an_application_compatibility_facade() -> None:
    from src.scheduler.source_unit_orchestrator import process_source_units

    assert process_source_units is application_process_source_units
