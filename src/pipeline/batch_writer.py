"""Batch persistence coordination for ingestion."""

import asyncio
from typing import Any

from src.domain.ingestion.quality import QualityRuleCode
from src.domain.partner_transaction.duplicates import BatchWriteResult


class BatchWriteCoordinator:
    """Bound concurrent batch writes without owning ingestion statistics."""

    def __init__(self, repository: Any, *, workers: int, ordered: bool) -> None:
        if workers < 1:
            raise ValueError("workers must be at least 1")
        self._repository = repository
        self._workers = workers
        self._ordered = ordered
        self._pending: list[asyncio.Task[BatchWriteResult]] = []

    async def _write(
        self,
        batch: list[Any],
        row_contexts: list[dict[str, Any]] | None = None,
    ) -> BatchWriteResult:
        if row_contexts is not None and len(row_contexts) != len(batch):
            raise ValueError(
                "Batch row context accounting mismatch: "
                f"contexts={len(row_contexts)}, submitted={len(batch)}"
            )
        result = await self._repository.insert_many(
            batch,
            ordered=self._ordered,
        )
        if result.attempted != len(batch):
            raise ValueError(
                "Batch write accounting mismatch: "
                f"attempted={result.attempted}, submitted={len(batch)}"
            )
        if row_contexts and result.duplicate_details:
            for detail in result.duplicate_details:
                if (
                    detail.duplicate_type is QualityRuleCode.CONFLICTING_DUPLICATE
                    and detail.incoming_index < len(row_contexts)
                ):
                    detail.row_context = row_contexts[detail.incoming_index]
        return result

    async def submit(
        self,
        batch: list[Any],
        *,
        row_contexts: list[dict[str, Any]] | None = None,
    ) -> list[BatchWriteResult]:
        """Submit a batch and drain when the worker limit is reached."""

        if not batch:
            return []
        if self._workers == 1:
            return [await self._write(batch, row_contexts)]

        self._pending.append(asyncio.create_task(self._write(batch, row_contexts)))
        if len(self._pending) < self._workers:
            return []
        return await self.drain()

    async def drain(self) -> list[BatchWriteResult]:
        """Wait for all currently queued writes and release their tasks."""

        if not self._pending:
            return []
        pending, self._pending = self._pending, []
        return list(await asyncio.gather(*pending))
