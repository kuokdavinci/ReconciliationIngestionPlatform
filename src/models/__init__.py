"""Compatibility package for legacy model imports.

Production code should import from the relevant ``src.domain`` or
``src.infrastructure`` bounded context. This package remains as a stable
package-level bridge for downstream phases and legacy integrations.
"""

from src.core.enums import FileType
from src.domain.audit.models import AuditEvent
from src.domain.fetch_config.models import (
    APIConfig,
    APIPaginationConfig,
    FetchConfig,
    FetchMethod,
    FileDropConfig,
    SFTPConfig,
)
from src.domain.ingestion.checkpoints import (
    CheckpointRepository,
    CheckpointStatus,
    IngestionCheckpoint,
    IngestionMode,
)
from src.domain.ingestion.models import ReconciliationFile
from src.domain.ingestion.raw_pages import RawIngestionPage, RawPageStatus
from src.domain.ingestion.source_units import IngestionOutcome, SourceUnitMetadata
from src.domain.internal_transaction.models import InternalTransaction
from src.domain.mapping.models import MappingConfig, MappingConfigStatus
from src.domain.partner_transaction.models import DataContainer, PartnerData
from src.domain.reconciliation.models import ReconciliationResult
from src.domain.reconciliation.run import ReconciliationRun, ReconciliationRunStatus
from src.domain.review.models import (
    CopilotAction,
    CopilotActionStatus,
    CopilotActionType,
    PostApprovalRun,
    PostApprovalRunStage,
    PostApprovalRunStatus,
    ReconciliationReviewNote,
    ReconciliationReviewRecord,
    ReviewDecisionMode,
    ReviewPacket,
    ReviewPacketSourceType,
    ReviewPacketStatus,
)
from src.domain.runtime.models import (
    PartnerRuntimeRun,
    PartnerRuntimeRunStatus,
    PartnerRuntimeTriggerType,
)
from src.infrastructure.audit.repository import AuditEventRepository
from src.infrastructure.fetch_config.repository import FetchConfigRepository
from src.infrastructure.ingestion.checkpoint_repository import IngestionCheckpointRepository
from src.infrastructure.ingestion.file_repository import ReconciliationFileRepository
from src.infrastructure.ingestion.raw_page_repository import RawIngestionPageRepository
from src.infrastructure.mapping.config_repository import MappingConfigRepository
from src.infrastructure.partner_transaction.repository import (
    DataContainerRepository,
    data_container_to_row,
    row_to_data_container,
)
from src.infrastructure.persistence.mongo_indexes import INDEXES, apply_indexes
from src.infrastructure.persistence.mongo_repository import BaseRepository
from src.infrastructure.persistence.postgres_connection import (
    _alembic_config,
    get_pg_engine,
    init_postgres_db,
    set_pg_engine,
)
from src.infrastructure.persistence.postgres_schema import (
    Base,
    InternalTransactionTable,
    PartnerTransactionTable,
    ReconciliationResultTable,
)
from src.infrastructure.postgres.internal_transaction_repository import (
    InternalTransactionRepository,
    internal_transaction_to_row,
    row_to_internal_transaction,
)
from src.infrastructure.postgres.reconciliation_result_repository import (
    ReconciliationResultRepository,
    reconciliation_result_to_row,
    row_to_reconciliation_result,
)
from src.infrastructure.reconciliation.run_repository import ReconciliationRunRepository
from src.infrastructure.review.repository import (
    CopilotActionRepository,
    PostApprovalRunRepository,
    ReconciliationReviewRecordRepository,
    ReviewPacketRepository,
)
from src.infrastructure.runtime.repository import PartnerRuntimeRunRepository

__all__ = [
    "AuditEvent",
    "AuditEventRepository",
    "APIConfig",
    "APIPaginationConfig",
    "Base",
    "BaseRepository",
    "CheckpointRepository",
    "CheckpointStatus",
    "CopilotAction",
    "CopilotActionRepository",
    "CopilotActionStatus",
    "CopilotActionType",
    "DataContainer",
    "DataContainerRepository",
    "FileDropConfig",
    "FileType",
    "FetchConfig",
    "FetchConfigRepository",
    "FetchMethod",
    "INDEXES",
    "IngestionCheckpoint",
    "IngestionCheckpointRepository",
    "IngestionMode",
    "IngestionOutcome",
    "InternalTransaction",
    "InternalTransactionRepository",
    "InternalTransactionTable",
    "MappingConfig",
    "MappingConfigRepository",
    "MappingConfigStatus",
    "PartnerData",
    "PartnerRuntimeRun",
    "PartnerRuntimeRunRepository",
    "PartnerRuntimeRunStatus",
    "PartnerRuntimeTriggerType",
    "PartnerTransactionTable",
    "PostApprovalRun",
    "PostApprovalRunRepository",
    "PostApprovalRunStage",
    "PostApprovalRunStatus",
    "ReconciliationFile",
    "ReconciliationFileRepository",
    "RawIngestionPage",
    "RawPageStatus",
    "RawIngestionPageRepository",
    "ReconciliationResult",
    "ReconciliationResultRepository",
    "ReconciliationResultTable",
    "ReconciliationReviewNote",
    "ReconciliationReviewRecord",
    "ReconciliationReviewRecordRepository",
    "ReconciliationRun",
    "ReconciliationRunRepository",
    "ReconciliationRunStatus",
    "ReviewDecisionMode",
    "ReviewPacket",
    "ReviewPacketRepository",
    "ReviewPacketSourceType",
    "ReviewPacketStatus",
    "SFTPConfig",
    "SourceUnitMetadata",
    "apply_indexes",
    "data_container_to_row",
    "get_pg_engine",
    "init_postgres_db",
    "internal_transaction_to_row",
    "reconciliation_result_to_row",
    "row_to_data_container",
    "row_to_internal_transaction",
    "row_to_reconciliation_result",
    "set_pg_engine",
    "_alembic_config",
]
