"""TDD contracts for authoritative quarantine reprocess input resolution."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.domain.ingestion.quarantine import IngestionQuarantineRecord, QuarantinePhase


def _record(**overrides) -> IngestionQuarantineRecord:
    payload = {
        "sourceFileId": "file-1",
        "sourceUnitKey": "unit-1",
        "partner": "MOMO",
        "reconciliationDate": datetime(2026, 8, 1, tzinfo=UTC),
        "rowNumber": 7,
        "rawRow": ("TX-007", "100"),
        "phase": QuarantinePhase.VALIDATION,
    }
    payload.update(overrides)
    return IngestionQuarantineRecord(**payload)


def test_reprocess_request_uses_aliases_and_explicit_modes():
    from src.application.ingestion.quarantine_reprocessing import (
        QuarantineReprocessMode,
        QuarantineReprocessRequest,
    )

    request = QuarantineReprocessRequest(
        recordId="record-1",
        operatorId="operator-1",
        actionId="action-1",
        expectedStatus="PENDING",
        mode="CORRECTED_ROW",
        correctedRow={"id": "TX-007", "amount": "100"},
        mappingVersion="mapping-v2",
    )

    assert request.mode is QuarantineReprocessMode.CORRECTED_ROW
    assert request.record_id == "record-1"
    assert request.model_dump(by_alias=True)["mappingVersion"] == "mapping-v2"


@pytest.mark.asyncio
async def test_resolver_prefers_authoritative_source_file_row():
    from src.application.ingestion.quarantine_reprocessing import (
        QuarantineReprocessMode,
        QuarantineReprocessRequest,
        resolve_reprocess_input,
    )

    source_file_repo = SimpleNamespace(
        read_row=AsyncMock(return_value={"id": "TX-007", "amount": "125"})
    )
    raw_page_repo = SimpleNamespace(read_row=AsyncMock())
    request = QuarantineReprocessRequest(
        recordId="record-1",
        operatorId="operator-1",
        actionId="action-1",
        expectedStatus="PENDING",
        mode=QuarantineReprocessMode.REPLAY_SOURCE_ROW,
    )

    resolved = await resolve_reprocess_input(
        _record(), request, source_file_repo, raw_page_repo
    )

    assert resolved.row == {"id": "TX-007", "amount": "125"}
    assert resolved.origin == "AUTHORITATIVE_SOURCE_FILE"
    source_file_repo.read_row.assert_awaited_once_with("file-1", 7)
    raw_page_repo.read_row.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolver_uses_staged_raw_page_when_file_row_is_unavailable():
    from src.application.ingestion.quarantine_reprocessing import (
        QuarantineReprocessMode,
        QuarantineReprocessRequest,
        resolve_reprocess_input,
    )

    source_file_repo = SimpleNamespace(read_row=AsyncMock(return_value=None))
    raw_page_repo = SimpleNamespace(
        read_row=AsyncMock(return_value=("TX-007", "125"))
    )
    request = QuarantineReprocessRequest(
        recordId="record-1",
        operatorId="operator-1",
        actionId="action-1",
        expectedStatus="PENDING",
        mode=QuarantineReprocessMode.REPLAY_SOURCE_ROW,
    )

    resolved = await resolve_reprocess_input(
        _record(), request, source_file_repo, raw_page_repo
    )

    assert resolved.row == ("TX-007", "125")
    assert resolved.origin == "STAGED_RAW_PAGE"
    raw_page_repo.read_row.assert_awaited_once_with("unit-1", 7)


@pytest.mark.asyncio
async def test_corrected_row_explicitly_overrides_authoritative_sources():
    from src.application.ingestion.quarantine_reprocessing import (
        QuarantineReprocessMode,
        QuarantineReprocessRequest,
        resolve_reprocess_input,
    )

    source_file_repo = SimpleNamespace(read_row=AsyncMock())
    raw_page_repo = SimpleNamespace(read_row=AsyncMock())
    request = QuarantineReprocessRequest(
        recordId="record-1",
        operatorId="operator-1",
        actionId="action-1",
        expectedStatus="PENDING",
        mode=QuarantineReprocessMode.CORRECTED_ROW,
        correctedRow={"id": "TX-007", "amount": "130"},
    )

    resolved = await resolve_reprocess_input(
        _record(), request, source_file_repo, raw_page_repo
    )

    assert resolved.row == {"id": "TX-007", "amount": "130"}
    assert resolved.origin == "CORRECTED_ROW"
    source_file_repo.read_row.assert_not_awaited()
    raw_page_repo.read_row.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolver_rejects_sanitized_row_without_authoritative_source():
    from src.application.ingestion.quarantine_reprocessing import (
        QuarantineReprocessMode,
        QuarantineReprocessRequest,
        resolve_reprocess_input,
    )

    source_file_repo = SimpleNamespace(read_row=AsyncMock(return_value=None))
    raw_page_repo = SimpleNamespace(read_row=AsyncMock(return_value=None))
    request = QuarantineReprocessRequest(
        recordId="record-1",
        operatorId="operator-1",
        actionId="action-1",
        expectedStatus="PENDING",
        mode=QuarantineReprocessMode.REPLAY_SOURCE_ROW,
    )

    with pytest.raises(ValueError, match="authoritative"):
        await resolve_reprocess_input(
            _record(rawRow={"id": "TX-007", "secret": "[REDACTED]"}),
            request,
            source_file_repo,
            raw_page_repo,
        )


@pytest.mark.asyncio
async def test_resolver_reports_missing_source_for_replay():
    from src.application.ingestion.quarantine_reprocessing import (
        QuarantineReprocessMode,
        QuarantineReprocessRequest,
        resolve_reprocess_input,
    )

    request = QuarantineReprocessRequest(
        recordId="record-1",
        operatorId="operator-1",
        actionId="action-1",
        expectedStatus="PENDING",
        mode=QuarantineReprocessMode.REPLAY_SOURCE_ROW,
    )

    with pytest.raises(ValueError, match="source"):
        await resolve_reprocess_input(
            _record(sourceFileId=None, sourceUnitKey=None, rawRow=None),
            request,
            SimpleNamespace(read_row=AsyncMock(return_value=None)),
            SimpleNamespace(read_row=AsyncMock(return_value=None)),
        )


@pytest.mark.asyncio
async def test_resolver_never_uses_unsanitized_quarantine_row_as_replay_source():
    from src.application.ingestion.quarantine_reprocessing import (
        QuarantineReprocessMode,
        QuarantineReprocessRequest,
        resolve_reprocess_input,
    )

    request = QuarantineReprocessRequest(
        recordId="record-1",
        operatorId="operator-1",
        actionId="action-1",
        expectedStatus="PENDING",
        mode=QuarantineReprocessMode.REPLAY_SOURCE_ROW,
    )

    with pytest.raises(ValueError, match="authoritative"):
        await resolve_reprocess_input(
            _record(rawRow={"id": "TX-007", "amount": "100"}),
            request,
            SimpleNamespace(read_row=AsyncMock(return_value=None)),
            SimpleNamespace(read_row=AsyncMock(return_value=None)),
        )
