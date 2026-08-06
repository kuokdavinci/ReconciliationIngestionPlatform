"""Batch persistence coordination for ingestion."""

import asyncio
from typing import Any

from src.core.types import BatchInsertResult


class BatchWriteCoordinator:
    """Bound concurrent batch writes without owning ingestion statistics."""

    def __init__(self, repository: Any, *, workers: int, ordered: bool) -> None:
        if workers < 1:
            raise ValueError("workers must be at least 1")
        self._repository = repository
        self._workers = workers
        self._ordered = ordered
        self._pending: list[asyncio.Task[int | BatchInsertResult]] = []

    async def _write(self, batch: list[Any]) -> int | BatchInsertResult:
        return await self._repository.insert_many(
            batch,
            ordered=self._ordered,
            detailed=True,
        )

    async def submit(self, batch: list[Any]) -> list[int | BatchInsertResult]:
        """Submit a batch and drain when the worker limit is reached."""

        if not batch:
            return []
        if self._workers == 1:
            return [await self._write(batch)]

        self._pending.append(asyncio.create_task(self._write(batch)))
        if len(self._pending) < self._workers:
            return []
        return await self.drain()

    async def drain(self) -> list[int | BatchInsertResult]:
        """Wait for all currently queued writes and release their tasks."""

        if not self._pending:
            return []
        pending, self._pending = self._pending, []
        return list(await asyncio.gather(*pending))
