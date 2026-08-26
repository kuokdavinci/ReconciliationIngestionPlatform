"""TDD contracts for bounded quarantine API endpoints."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from src.domain.ingestion.quarantine import (
    IngestionQuarantineRecord,
    QuarantinePhase,
    QuarantineStatus,
)


def _request():
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(db=MagicMock())),
        headers={},
    )


def _record(**overrides) -> IngestionQuarantineRecord:
    payload = {
        "sourceFileId": "file-1",
        "sourceUnitKey": "unit-1",
        "partner": "MOMO",
        "reconciliationDate": datetime(2026, 8, 1, tzinfo=UTC),
        "rowNumber": 7,
        "rawRow": {"id": "TX-007", "secret": "[REDACTED]"},
        "errors": [
            {
                "errorCode": "CONFLICTING_DUPLICATE",
                "rawRow": {"password": "not-returned"},
            }
        ],
        "phase": QuarantinePhase.BATCH,
        "status": QuarantineStatus.PENDING,
    }
    payload.update(overrides)
    return IngestionQuarantineRecord(**payload)


@pytest.mark.asyncio
async def test_list_quarantine_returns_bounded_metadata_and_structured_filters():
    from src.api.quarantine import list_quarantine

    repository = MagicMock()
    repository.find_many = AsyncMock(return_value=([_record()], "next-cursor"))

    with patch("src.api.quarantine.IngestionQuarantineRepository", return_value=repository):
        result = await list_quarantine(
            _request(),
            partner="MOMO",
            status=QuarantineStatus.PENDING,
            phase=QuarantinePhase.BATCH,
            error_code="CONFLICTING_DUPLICATE",
            source_file_id="file-1",
            source_unit_key="unit-1",
            limit=25,
            cursor=None,
        )

    query = repository.find_many.await_args.args[0]
    assert query.partner == "MOMO"
    assert query.status is QuarantineStatus.PENDING
    assert query.source_unit_key == "unit-1"
    assert result["nextCursor"] == "next-cursor"
    assert "rawRow" not in result["items"][0]
    assert result["items"][0]["errorCodes"] == ["CONFLICTING_DUPLICATE"]


@pytest.mark.asyncio
async def test_detail_returns_bounded_sanitized_evidence_without_raw_secrets():
    from src.api.quarantine import get_quarantine_record

    repository = MagicMock()
    repository.find_by_id = AsyncMock(return_value=_record())

    with patch("src.api.quarantine.IngestionQuarantineRepository", return_value=repository):
        result = await get_quarantine_record(_request(), "record-1")

    assert result["rawRow"]["secret"] == "[REDACTED]"
    assert "not-returned" not in str(result)
    assert len(result["errors"]) == 1
    assert "rawRow" not in result["errors"][0]
    assert len(result["resolutionHistory"]) <= 50


@pytest.mark.asyncio
async def test_missing_detail_returns_404():
    from src.api.quarantine import get_quarantine_record

    repository = MagicMock()
    repository.find_by_id = AsyncMock(return_value=None)

    with patch("src.api.quarantine.IngestionQuarantineRepository", return_value=repository):
        with pytest.raises(HTTPException) as exc_info:
            await get_quarantine_record(_request(), "missing")

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_concurrent_claim_conflict_returns_409():
    from src.api.quarantine import QuarantineReprocessPayload, reprocess_quarantine_record
    from src.application.ingestion.quarantine_service import (
        QuarantineResolutionResult,
    )
    from src.domain.ingestion.quarantine import QuarantineAction

    service = MagicMock()
    service.resolve = AsyncMock(
        return_value=QuarantineResolutionResult(
            record_id="record-1",
            success=False,
            status=None,
            outcome="CLAIM_NOT_ACQUIRED",
            action=QuarantineAction.REPROCESS,
        )
    )
    with patch("src.api.quarantine._resolution_service", return_value=service):
        with pytest.raises(HTTPException) as exc_info:
            await reprocess_quarantine_record(
                _request(),
                "record-1",
                QuarantineReprocessPayload(operatorId="operator-1"),
            )

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_reject_requires_non_empty_reason_with_422():
    from src.api.quarantine import QuarantineRejectPayload, reject_quarantine_record

    with pytest.raises(HTTPException) as exc_info:
        await reject_quarantine_record(
            _request(),
            "record-1",
            QuarantineRejectPayload(operatorId="operator-1", reason=" "),
        )

    assert exc_info.value.status_code == 422


def test_create_app_registers_quarantine_router():
    from src.api import create_app

    app = create_app()
    paths = {
        route.path
        for router in app.routes
        for route in getattr(
            getattr(router, "original_router", router),
            "routes",
            [router],
        )
        if hasattr(route, "path")
    }
    assert "/api/v1/quarantine" in paths
    assert "/api/v1/quarantine/{record_id}/reprocess" in paths
