import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.application.ingestion.contracts import IngestionResult, ProcessFileCommand
from src.infrastructure.ingestion.composition import build_ingestion_pipeline
import src.pipeline.ingestion_pipeline as ingestion_pipeline_module
from src.pipeline.ingestion_pipeline import IngestionPipeline


def test_ingestion_pipeline_accepts_injected_repository_ports():
    file_repo = MagicMock()
    partner_repo = MagicMock()
    mapping_repo = MagicMock()

    pipeline = IngestionPipeline(
        db=MagicMock(),
        config_loader=MagicMock(),
        file_repo=file_repo,
        partner_repo=partner_repo,
        mapping_repo=mapping_repo,
    )

    assert pipeline._recon_repo is file_repo
    assert pipeline._data_repo is partner_repo
    assert pipeline._mapping_repo is mapping_repo


def test_ingestion_composition_builds_pipeline_with_injected_adapters():
    pipeline = build_ingestion_pipeline(
        MagicMock(),
        config_loader=MagicMock(),
        file_repo=MagicMock(),
        partner_repo=MagicMock(),
        mapping_repo=MagicMock(),
    )

    assert isinstance(pipeline, IngestionPipeline)


def test_pipeline_does_not_import_concrete_repository_adapters():
    source = inspect.getsource(ingestion_pipeline_module)

    assert "src.infrastructure" not in source
    assert "ReconciliationFileRepository" not in source
    assert "DataContainerRepository" not in source
    assert "MappingConfigRepository(" not in source


def test_pipeline_fails_fast_without_repository_ports():
    pipeline = IngestionPipeline(db=MagicMock(), config_loader=MagicMock())

    try:
        pipeline._require_repository_ports()
    except RuntimeError as exc:
        assert "Use build_ingestion_pipeline()" in str(exc)
    else:
        raise AssertionError("Missing repository ports must fail fast")


@pytest.mark.asyncio
async def test_pipeline_execute_accepts_application_command():
    pipeline = IngestionPipeline(db=MagicMock(), config_loader=MagicMock())
    expected = object()
    pipeline._process_file = AsyncMock(return_value=expected)

    result = await pipeline.execute(
        ProcessFileCommand(
            file_path="file.xlsx",
            partner="MOMO",
            workflow_type="UPC",
            file_type="SETTLEMENT",
            reconciliation_date="2024-01-15",
        )
    )

    assert result is expected
    assert isinstance(IngestionResult, type)
