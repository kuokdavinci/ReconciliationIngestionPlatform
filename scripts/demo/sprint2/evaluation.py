"""In-memory Sprint 2 recovery evaluation for the ViettelPay fixture."""

import time
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from src.domain.ingestion.checkpoints import IngestionCheckpoint
from src.application.automation.stream_identity import units_after_checkpoint
from src.application.ingestion.source_unit_orchestrator import process_source_units
from src.infrastructure.ingestion.checkpoint_repository import IngestionCheckpointRepository
from scripts.demo.sprint2.fixture import ViettelPayMockFixture
from src.services.retry_policy import RetryPolicy


class _MemoryCheckpointCollection:
    """Small Mongo collection fake; production checkpoint logic stays reused."""

    def __init__(self):
        self.documents: list[dict[str, Any]] = []

    async def insert_one(self, document: dict[str, Any]) -> None:
        self.documents.append(deepcopy(document))

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        for document in self.documents:
            if self._matches(document, query):
                return deepcopy(document)
        return None

    async def find_one_and_update(
        self, query: dict[str, Any], update: dict[str, Any], **_: Any
    ) -> dict[str, Any] | None:
        for index, document in enumerate(self.documents):
            if self._matches(document, query):
                self._apply_update(document, update)
                self.documents[index] = document
                return deepcopy(document)
        return None

    async def update_one(
        self, query: dict[str, Any], update: dict[str, Any]
    ) -> Any:
        for document in self.documents:
            if self._matches(document, query):
                self._apply_update(document, update)
                return SimpleNamespace(modified_count=1)
        return SimpleNamespace(modified_count=0)

    @classmethod
    def _matches(cls, document: dict[str, Any], query: dict[str, Any]) -> bool:
        for key, expected in query.items():
            if key == "$or":
                if not any(cls._matches(document, branch) for branch in expected):
                    return False
                continue
            actual = document.get(key)
            if not cls._matches_value(actual, expected):
                return False
        return True

    @staticmethod
    def _matches_value(actual: Any, expected: Any) -> bool:
        if not isinstance(expected, dict) or not any(
            key.startswith("$") for key in expected
        ):
            return actual == expected
        for operator, value in expected.items():
            if operator == "$ne" and actual == value:
                return False
            if operator == "$in" and actual not in value:
                return False
            if operator == "$lte" and (actual is None or actual > value):
                return False
        return True

    @staticmethod
    def _apply_update(document: dict[str, Any], update: dict[str, Any]) -> None:
        for key, values in update.get("$set", {}).items():
            document[key] = deepcopy(values)
        for key, value in update.get("$inc", {}).items():
            document[key] = document.get(key, 0) + value


class _MemoryDatabase:
    def __init__(self):
        self.collection = _MemoryCheckpointCollection()

    def __getitem__(self, _: str) -> _MemoryCheckpointCollection:
        return self.collection


class _MemoryCheckpointRepository(IngestionCheckpointRepository):
    """Exercise the real state machine against an in-memory collection."""

    def __init__(self):
        super().__init__(_MemoryDatabase())

    async def current_checkpoint(self) -> IngestionCheckpoint | None:
        return await self.find_one({})


def _identity() -> dict[str, str]:
    return {
        "partner": "VIETTELPAY",
        "fetchConfigId": "demo-viettelpay-sprint2",
        "sourceType": "API",
        "streamKey": "VIETTELPAY:API:mock://viettelpay/settlement",
    }


def _checkpoint_snapshot(checkpoint: IngestionCheckpoint | None) -> dict[str, Any]:
    if checkpoint is None:
        return {"status": "ABSENT", "lastCompletedUnitKey": None}
    return {
        "status": checkpoint.status.value,
        "lastCompletedUnitKey": checkpoint.last_completed_unit_key,
        "cursorAfter": checkpoint.cursor_after,
    }


def _scenario(
    scenario_id: str,
    name: str,
    expected: str,
    actual: str,
    passed: bool,
    started: float,
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    unit_key: str | None = None,
    outcome: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "id": scenario_id,
        "name": name,
        "expected": expected,
        "actual": actual,
        "passed": passed,
        "durationMs": round((time.perf_counter() - started) * 1000, 3),
        "checkpointBefore": before,
        "checkpointAfter": after,
        "unitKey": unit_key,
        "outcome": outcome,
        "error": error,
    }


async def run_sprint2_evaluation() -> dict[str, Any]:
    """Run deterministic failure/restart/replay/invariant scenarios."""

    fixture = ViettelPayMockFixture()
    units = fixture.source_units()
    repo = _MemoryCheckpointRepository()
    identity = _identity()
    ingested_keys: list[str] = []
    scenarios = []
    retry_policy = RetryPolicy(initial_backoff_seconds=0)

    async def initial_ingest(unit):
        if unit["sourceUnitKey"] == "page:2":
            return {
                "success": False,
                "error": "controlled page 2 failure",
                "errorCode": "fetch_timeout",
                "retryable": True,
            }
        ingested_keys.append(unit["sourceUnitKey"])
        return {"success": True}

    before = _checkpoint_snapshot(await repo.current_checkpoint())
    started = time.perf_counter()
    first_result = await process_source_units(
        repo,
        stream_identity=identity,
        units=units[:2],
        ingest_unit=initial_ingest,
        retry_policy=retry_policy,
    )
    checkpoint = await repo.current_checkpoint()
    after = _checkpoint_snapshot(checkpoint)
    scenarios.append(
        _scenario(
            "S2-02",
            "Failure giữa page 2",
            "page 1 completed và stream dừng tại page 2",
            f"processed={first_result['processed']}, stoppedAt={first_result.get('stoppedAt')}",
            first_result["processed"] == 1 and first_result.get("stoppedAt") == "page:2",
            started,
            before,
            after,
            unit_key="page:2",
            error=first_result.get("error"),
        )
    )

    if checkpoint is None:
        raise AssertionError("checkpoint must exist after the controlled page 2 failure")
    if checkpoint.last_completed_unit_key is None:
        raise AssertionError("page 1 must be completed before resume")
    pending_units = units_after_checkpoint(units, checkpoint)
    identity["lastCompletedUnitKey"] = checkpoint.last_completed_unit_key
    before = _checkpoint_snapshot(checkpoint)
    started = time.perf_counter()

    async def resumed_ingest(unit):
        ingested_keys.append(unit["sourceUnitKey"])
        return {"success": True}

    resume_result = await process_source_units(
        repo,
        stream_identity=identity,
        units=pending_units,
        ingest_unit=resumed_ingest,
        retry_policy=retry_policy,
    )
    after = _checkpoint_snapshot(await repo.current_checkpoint())
    scenarios.append(
        _scenario(
            "S2-03",
            "Restart và resume",
            "chạy tiếp từ page 2, sau đó page 3",
            f"processed={resume_result['processed']}, units={[u['sourceUnitKey'] for u in pending_units]}",
            resume_result["success"] and [u["sourceUnitKey"] for u in pending_units] == ["page:2", "page:3"],
            started,
            before,
            after,
            unit_key="page:2",
        )
    )

    before = _checkpoint_snapshot(await repo.current_checkpoint())
    checkpoint = await repo.current_checkpoint()
    if checkpoint is None:
        raise AssertionError("checkpoint must exist before replay evaluation")
    if checkpoint.last_completed_unit_key is None:
        raise AssertionError("page 3 must be completed before replay evaluation")
    identity["lastCompletedUnitKey"] = checkpoint.last_completed_unit_key
    started = time.perf_counter()
    replay_result = await process_source_units(
        repo,
        stream_identity=identity,
        units=[units[-1]],
        ingest_unit=resumed_ingest,
        retry_policy=retry_policy,
    )
    after = _checkpoint_snapshot(await repo.current_checkpoint())
    scenarios.append(
        _scenario(
            "S2-05",
            "Cursor/page replay",
            "unit đã completed không ingest lần hai",
            f"replayed={replay_result.get('replayed', 0)}",
            replay_result.get("replayed") == 1 and replay_result["success"],
            started,
            before,
            after,
            unit_key="page:3",
            outcome="FETCH_UNIT_REPLAY",
        )
    )

    duplicate_count = len(ingested_keys) - len(set(ingested_keys))
    scenarios.append(
        _scenario(
            "S2-13",
            "Data invariant",
            "không có duplicate ingestion key sau recovery",
            f"ingestedKeys={ingested_keys}, duplicateCount={duplicate_count}",
            duplicate_count == 0 and len(ingested_keys) == 3,
            time.perf_counter(),
            _checkpoint_snapshot(await repo.current_checkpoint()),
            _checkpoint_snapshot(await repo.current_checkpoint()),
        )
    )
    passed = sum(1 for scenario in scenarios if scenario["passed"])
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "summary": {"total": len(scenarios), "passed": passed, "failed": len(scenarios) - passed},
        "scenarios": scenarios,
        "finalCheckpoint": _checkpoint_snapshot(await repo.current_checkpoint()),
        "finalInvariant": {"duplicateIngestionKeys": duplicate_count},
        "evidenceType": "deterministic in-memory mock; no production database mutation",
    }
