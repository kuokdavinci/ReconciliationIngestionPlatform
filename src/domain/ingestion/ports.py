"""Ports required by the ingestion pipeline.

Concrete MongoDB/PostgreSQL repositories are assembled by the infrastructure
composition root. The pipeline only needs these small contracts.
"""

from typing import Any, Protocol
from uuid import UUID

from src.core.enums import ProcessingStatus
from src.core.types import BatchInsertResult
from src.domain.ingestion.quarantine import IngestionQuarantineRecord


class IngestionFileRepository(Protocol):
    """Claim and update the file-level ingestion record."""

    async def find_by_file_hash(self, file_hash: str) -> Any | None:
        """Return the canonical file claim for a content hash."""

    async def create_or_get_by_file_hash(self, document: Any) -> tuple[Any, bool]:
        """Atomically create or resolve a duplicate file claim."""

    async def create(self, document: Any) -> Any:
        """Create a file record for legacy adapters."""

    async def reclaim_failed_by_file_hash(self, file_hash: str) -> Any | None:
        """Atomically reopen a failed file claim for safe retry."""
        ...

    async def update_processing_stats(
        self,
        file_id: UUID,
        total: int,
        success: int,
        failed: int,
        duplicate: int = 0,
    ) -> bool:
        """Persist processing counters, including database-level duplicates."""

    async def update_status(self, file_id: UUID, status: ProcessingStatus) -> bool:
        """Persist the processing status."""

    async def update_stage_summary(
        self,
        file_id: UUID,
        summary: dict[str, Any],
    ) -> bool:
        """Persist stage-level counters and timing summary."""


class PartnerTransactionWriter(Protocol):
    """Persist canonical partner transactions."""

    async def insert_many(
        self,
        documents: list[Any],
        ordered: bool = True,
        detailed: bool = False,
    ) -> int | BatchInsertResult:
        """Insert a batch and optionally return duplicate/failure counts."""

    async def rebind_source_file_by_ingestion_keys(
        self,
        partner: str,
        ingestion_keys: list[str],
        source_file_id: UUID | str,
    ) -> int:
        """Update lineage for duplicate transaction keys when supported."""


class MappingConfigRepositoryPort(Protocol):
    """Persistence boundary used by config-health checks."""

    collection: Any

    async def find_by_partner_and_type(
        self,
        partner: str,
        workflow_type: str,
        file_type: Any,
    ) -> Any | None:
        """Find the approved mapping for a partner/workflow/file type."""

    async def find_by_version(self, partner: str, version: str) -> Any | None:
        """Find a mapping by explicit version."""


class IngestionQuarantineWriter(Protocol):
    """Persistence boundary for rejected source rows."""

    async def create_many(self, records: list[IngestionQuarantineRecord]) -> int:
        """Persist a batch of quarantine records."""
