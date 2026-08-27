"""File identity and atomic claim workflow for ingestion."""

import asyncio
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from src.core.enums import ProcessingStatus
from src.core.utils import compute_file_hash
from src.domain.ingestion.models import ReconciliationFile
from src.domain.ingestion.ports import IngestionFileRepository
from src.reconciliation.scope import classify_scope


@dataclass(frozen=True)
class FileClaimResult:
    file_record: ReconciliationFile
    created: bool
    duplicate_code: str | None = None


class FileClaimService:
    """Create one canonical file claim and identify replay attempts."""

    def __init__(self, db: Any, repository: IngestionFileRepository | None) -> None:
        self._db = db
        self._repository = repository

    async def compute_file_hash(self, file_path: str) -> str:
        return await asyncio.to_thread(compute_file_hash, file_path)

    def derive_fetch_unit_key(
        self,
        *,
        partner: str,
        workflow_type: str,
        file_type: Any,
        reconciliation_date: Any,
        config_version: Optional[str],
        metadata: Optional[dict[str, Any]],
    ) -> Optional[str]:
        if not metadata:
            return None

        explicit_source_unit_key = metadata.get("sourceUnitKey")
        if isinstance(explicit_source_unit_key, str) and explicit_source_unit_key.strip():
            return explicit_source_unit_key.strip()

        identity = {
            "partner": partner,
            "workflowType": workflow_type,
            "fileType": getattr(file_type, "value", file_type),
            "reconciliationDate": reconciliation_date.isoformat(),
            "configVersion": config_version,
            "sourceEndpoint": metadata.get("sourceEndpoint"),
            "page": metadata.get("page"),
            "cursor": metadata.get("cursor"),
            "windowStart": metadata.get("windowStart"),
            "windowEnd": metadata.get("windowEnd"),
        }
        if not identity["sourceEndpoint"]:
            raise ValueError("fetch_unit metadata requires sourceEndpoint")
        if not any(identity[field] is not None for field in ("page", "cursor", "windowStart", "windowEnd")):
            raise ValueError("fetch_unit metadata requires page, cursor, or a fetch window")

        canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    async def claim(
        self,
        *,
        file_path: str,
        partner: str,
        workflow_type: str,
        file_type: Any,
        reconciliation_date: Any,
        config_version: Optional[str],
        fetch_unit_metadata: Optional[dict[str, Any]],
        file_hash: str | None = None,
        fetch_unit_key: str | None = None,
        repository: IngestionFileRepository | None = None,
    ) -> FileClaimResult:
        repository = repository or self._repository
        if repository is None:
            raise RuntimeError("FileClaimService requires an ingestion file repository")
        if file_hash is None:
            file_hash = await self.compute_file_hash(file_path)
        if fetch_unit_key is None:
            fetch_unit_key = self.derive_fetch_unit_key(
                partner=partner,
                workflow_type=workflow_type,
                file_type=file_type,
                reconciliation_date=reconciliation_date,
                config_version=config_version,
                metadata=fetch_unit_metadata,
            )
        existing = await repository.find_by_file_hash(partner, file_hash)
        if isinstance(existing, ReconciliationFile):
            if existing.processing_status == ProcessingStatus.FAILED:
                reclaim = getattr(repository, "reclaim_failed_by_file_hash", None)
                if reclaim is not None:
                    reclaimed = await reclaim(partner, file_hash)
                    if isinstance(reclaimed, ReconciliationFile):
                        return FileClaimResult(reclaimed, True)
            return FileClaimResult(existing, False, "file_duplicate")

        scope_meta = await classify_scope(
            self._db,
            partner=partner,
            reconciliation_date=reconciliation_date,
        )
        file_name = Path(file_path).name
        candidate = ReconciliationFile(
            partner=partner,
            fileName=file_name,
            fileHash=file_hash,
            fileType=file_type,
            reconciliationDate=reconciliation_date,
            processingStatus=ProcessingStatus.PROCESSING,
            configVersion=config_version,
            fetchUnitKey=fetch_unit_key,
            fetchUnitMetadata=fetch_unit_metadata or {},
            sourceFilePath=file_path,
            scopeType=scope_meta["scopeType"],
            scopeConfidence=scope_meta["scopeConfidence"],
            scopeReason=scope_meta["scopeReason"],
            scopeSignals=scope_meta["scopeSignals"],
        )

        if hasattr(repository, "create_or_get_by_file_hash"):
            result = await repository.create_or_get_by_file_hash(candidate)
            if (
                isinstance(result, tuple)
                and len(result) == 2
                and isinstance(result[0], ReconciliationFile)
            ):
                file_record, created = result
            elif isinstance(result, ReconciliationFile):
                file_record, created = result, True
            else:
                file_record, created = await repository.create(candidate), True
        else:
            file_record, created = await repository.create(candidate), True

        if created:
            return FileClaimResult(file_record, True)

        duplicate_code = (
            "fetch_unit_duplicate"
            if fetch_unit_key
            and file_record.fetch_unit_key == fetch_unit_key
            and file_record.file_hash != file_hash
            else "file_duplicate"
        )
        return FileClaimResult(file_record, False, duplicate_code)
