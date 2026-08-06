"""Pipeline package — ingestion orchestration for reconciliation files.

Exports:
    IngestionPipeline: Main pipeline class with async process_file() method.
    IngestionResult: Dataclass holding processing results.
"""

from src.application.ingestion.contracts import IngestionResult, ProcessFileCommand
from src.pipeline.ingestion_pipeline import IngestionPipeline
from src.pipeline.batch_writer import BatchWriteCoordinator
from src.pipeline.config_preparation import ConfigPreparationService
from src.pipeline.file_claim import FileClaimService
from src.pipeline.metrics import IngestionPerformance
from src.pipeline.observability import IngestionStage
from src.pipeline.row_processor import RowProcessor
from src.pipeline.row_pipeline import RowPipelineExecutor, RowPipelineRequest, RowPipelineResult
from src.pipeline.finalizer import IngestionRunFinalizer
from src.pipeline.run_state import IngestionRunState

__all__ = [
    "BatchWriteCoordinator",
    "ConfigPreparationService",
    "FileClaimService",
    "IngestionPerformance",
    "IngestionStage",
    "IngestionPipeline",
    "IngestionResult",
    "ProcessFileCommand",
    "RowProcessor",
    "RowPipelineExecutor",
    "RowPipelineRequest",
    "RowPipelineResult",
    "IngestionRunState",
    "IngestionRunFinalizer",
]
