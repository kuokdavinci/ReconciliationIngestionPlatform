"""Architecture checks for source-unit domain contracts."""

from src.domain.ingestion.source_units import IngestionOutcome, SourceUnitMetadata
from src.application.ingestion.source_unit_orchestrator import (
    process_source_units as application_process_source_units,
)
def test_source_unit_contracts_are_domain_owned() -> None:
    assert IngestionOutcome.__module__ == "src.domain.ingestion.source_units"
    assert SourceUnitMetadata.__module__ == "src.domain.ingestion.source_units"


def test_source_unit_orchestrator_is_application_owned() -> None:
    assert application_process_source_units.__module__ == (
        "src.application.ingestion.source_unit_orchestrator"
    )
