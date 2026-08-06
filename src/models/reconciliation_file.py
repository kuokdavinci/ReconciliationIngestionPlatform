"""Compatibility exports for the ingestion file bounded context.

New production code should import the model from ``src.domain.ingestion`` and
the repository from ``src.infrastructure.ingestion``. This module remains as
a stable bridge for legacy scripts and tests during the migration.
"""

from src.domain.ingestion.models import ReconciliationFile
from src.infrastructure.ingestion.file_repository import ReconciliationFileRepository

__all__ = ["ReconciliationFile", "ReconciliationFileRepository"]
