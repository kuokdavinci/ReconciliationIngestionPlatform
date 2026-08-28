"""TDD contracts for bounded quarantine API endpoints."""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from src.domain.ingestion.quarantine import (
    IngestionQuarantineRecord,
    QuarantineAction,
    QuarantineIssueType,
    QuarantinePhase,
    QuarantinePriority,
    QuarantineResolutionEvent,
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
    assert result["summary"] == {
        "pending": 1,
        "reprocessing": 0,
        "resolved": 0,
        "rejected": 0,
        "overdue": 0,
        "highPriority": 1,
    }


@pytest.mark.asyncio
async def test_list_quarantine_exposes_bounded_terminal_decision_actor():
    from src.api.quarantine import list_quarantine

    event = QuarantineResolutionEvent(
        fromStatus=QuarantineStatus.REPROCESSING,
        toStatus=QuarantineStatus.REJECTED,
        action=QuarantineAction.REJECT,
        actor="demo-operator",
        reason="Bounded operator reason",
        attempt=2,
        actionId="reject-action-1",
        outcome="REJECTED",
    )
    record = _record(
        status=QuarantineStatus.REJECTED,
        claimedBy=None,
        resolutionHistory=[event],
    )
    repository = MagicMock()
    repository.find_many = AsyncMock(return_value=([record], None))

    with patch("src.api.quarantine.IngestionQuarantineRepository", return_value=repository):
        result = await list_quarantine(_request(), partner="MOMO")

    assert result["items"][0]["lastActionActor"] == "demo-operator"


@pytest.mark.asyncio
async def test_detail_marks_missing_error_field_in_full_sample_evidence():
    from src.api.quarantine import get_quarantine_record

    record = _record(
        rawRow={
            "id": "TX-007",
            "trace": "TRACE-7",
            "currency": "USD",
            "status": "SUCCESS",
            "transDate": "2026-08-28T00:00:00Z",
        },
        errors=[
            {
                "errorCode": "MALFORMED_ROW",
                "field": "amount",
                "reason": "sourceField 'amount' not found in row keys",
            }
        ],
    )
    repository = MagicMock()
    repository.find_by_id = AsyncMock(return_value=record)

    with patch("src.api.quarantine.IngestionQuarantineRepository", return_value=repository):
        result = await get_quarantine_record(_request(), "record-1")

    amount = next(item for item in result["evidence"]["sampleFields"] if item["sourceField"] == "amount")
    assert amount["value"] is None
    assert amount["state"] == "MISSING"
    assert result["issueSummary"] == "Missing amount"


@pytest.mark.asyncio
async def test_detail_returns_bounded_sanitized_evidence_without_raw_secrets():
    from src.api.quarantine import get_quarantine_record

    repository = MagicMock()
    repository.find_by_id = AsyncMock(return_value=_record())

    with patch("src.api.quarantine.IngestionQuarantineRepository", return_value=repository):
        result = await get_quarantine_record(_request(), "record-1")

    assert result["rawRow"]["secret"] == "[REDACTED]"
    assert "not-returned" not in str(result)
    assert "fingerprint" not in str(result).lower()
    assert len(result["errors"]) == 1
    assert "rawRow" not in result["errors"][0]
    assert len(result["resolutionHistory"]) <= 50


@pytest.mark.asyncio
async def test_detail_returns_required_mapping_and_named_sample_evidence():
    from types import SimpleNamespace

    from src.api.quarantine import get_quarantine_record

    record = _record(
        configVersion="MOMO_v01",
        rawRow={"id": "TX-007", "amount": "10.00", "currency": "USD"},
        errors=[
            {
                "errorCode": "MISSING_REQUIRED_FIELD",
                "field": "status",
                "reason": "Required field is missing.",
                "expected": "non-empty value",
                "actual": None,
            }
        ],
    )
    config = SimpleNamespace(
        config_version="MOMO_v01",
        field_mappings=[
            SimpleNamespace(path="id", sourceField="id", column=None, type="STRING", required=True),
            SimpleNamespace(path="amount", sourceField="amount", column=None, type="DECIMAL", required=True),
            SimpleNamespace(path="currency", sourceField="currency", column=None, type="STRING", required=True),
            SimpleNamespace(path="status", sourceField="status", column=None, type="MAPPING", required=True),
        ],
    )
    repository = MagicMock()
    repository.find_by_id = AsyncMock(return_value=record)
    mapping_repository = MagicMock()
    mapping_repository.find_by_version = AsyncMock(return_value=config)

    with (
        patch("src.api.quarantine.IngestionQuarantineRepository", return_value=repository),
        patch("src.api.quarantine.MappingConfigRepository", return_value=mapping_repository),
    ):
        result = await get_quarantine_record(_request(), "record-1")

    assert result["issueType"] == "REQUIRED_FIELD"
    assert result["evidence"]["mapping"]["configVersion"] == "MOMO_v01"
    required_status = next(
        item for item in result["evidence"]["mapping"]["requiredFields"]
        if item["canonicalPath"] == "status"
    )
    assert required_status["state"] == "MISSING"
    sample_status = next(
        item for item in result["evidence"]["sampleFields"]
        if item["canonicalPath"] == "status"
    )
    assert sample_status["state"] == "MISSING"


@pytest.mark.asyncio
async def test_duplicate_detail_returns_safe_existing_comparison():
    from types import SimpleNamespace

    from src.api.quarantine import get_quarantine_record

    record = _record(
        ingestionKey="TX-007",
        rawRow={
            "id": "TX-007",
            "trace": "TRACE-7",
            "amount": "11.00",
            "currency": "USD",
            "status": "SUCCESS",
        },
    )
    existing = SimpleNamespace(
        partner_data=SimpleNamespace(
            id="TX-007",
            trace="TRACE-7",
            amount="10.00",
            currency="USD",
            status="SUCCESS",
            extra={"secret": "must-not-return"},
        )
    )
    repository = MagicMock()
    repository.find_by_id = AsyncMock(return_value=record)
    transaction_repository = MagicMock()
    transaction_repository.find_by_ingestion_key = AsyncMock(return_value=existing)

    with (
        patch("src.api.quarantine.IngestionQuarantineRepository", return_value=repository),
        patch("src.api.quarantine.DataContainerRepository", return_value=transaction_repository),
    ):
        result = await get_quarantine_record(_request(), "record-1")

    comparison = result["evidence"]["duplicate"]
    assert comparison["status"] == "CONFLICT"
    amount = next(item for item in comparison["fields"] if item["name"] == "amount")
    assert amount == {
        "name": "amount",
        "incoming": "11.00",
        "existing": "10.00",
        "result": "DIFF",
    }
    assert "fingerprint" not in str(comparison).lower()
    assert "must-not-return" not in str(comparison)


@pytest.mark.asyncio
async def test_duplicate_detail_treats_numeric_amount_formats_as_equivalent():
    from types import SimpleNamespace

    from src.api.quarantine import get_quarantine_record

    record = _record(
        ingestionKey="TX-007",
        rawRow={
            "id": "TX-007",
            "trace": "TRACE-7",
            "amount": "125000",
            "currency": "USD",
            "status": "SUCCESS",
        },
    )
    existing = SimpleNamespace(
        partner_data=SimpleNamespace(
            id="TX-007",
            trace="TRACE-7",
            amount=Decimal("125000.00"),
            currency="USD",
            status="SUCCESS",
        )
    )
    repository = MagicMock()
    repository.find_by_id = AsyncMock(return_value=record)
    transaction_repository = MagicMock()
    transaction_repository.find_by_ingestion_key = AsyncMock(return_value=existing)

    with (
        patch("src.api.quarantine.IngestionQuarantineRepository", return_value=repository),
        patch("src.api.quarantine.DataContainerRepository", return_value=transaction_repository),
    ):
        result = await get_quarantine_record(_request(), "record-1")

    comparison = result["evidence"]["duplicate"]
    assert comparison["status"] == "EQUIVALENT"
    assert next(item for item in comparison["fields"] if item["name"] == "amount")["result"] == "MATCH"


@pytest.mark.asyncio
async def test_list_quarantine_passes_issue_type_to_repository_query():
    from src.api.quarantine import list_quarantine

    repository = MagicMock()
    repository.find_many = AsyncMock(return_value=([], None))

    with patch("src.api.quarantine.IngestionQuarantineRepository", return_value=repository):
        await list_quarantine(
            _request(),
            partner="MOMO",
            issue_type=QuarantineIssueType.DUPLICATE,
        )

    query = repository.find_many.await_args.args[0]
    assert query.issue_type is QuarantineIssueType.DUPLICATE


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
    service.resolve_claimed = AsyncMock(
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
            QuarantineReprocessPayload(
                operatorId="operator-1",
                actionId="action-1",
                expectedStatus=QuarantineStatus.REPROCESSING,
            ),
        )

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_reject_requires_non_empty_reason_with_422():
    from src.api.quarantine import QuarantineRejectPayload, reject_quarantine_record

    with pytest.raises(HTTPException) as exc_info:
        await reject_quarantine_record(
        _request(),
        "record-1",
        QuarantineRejectPayload(
            operatorId="operator-1",
            actionId="action-1",
            expectedStatus=QuarantineStatus.REPROCESSING,
            reason=" ",
        ),
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
    assert {
        "/api/v1/quarantine",
        "/api/v1/quarantine/{record_id}",
        "/api/v1/quarantine/{record_id}/claim",
        "/api/v1/quarantine/{record_id}/reprocess",
        "/api/v1/quarantine/{record_id}/accept-existing",
        "/api/v1/quarantine/{record_id}/reject",
        "/api/v1/quarantine/{record_id}/escalate",
        "/api/v1/quarantine/source-units/{source_unit_key}/resume",
    } <= paths


@pytest.mark.asyncio
async def test_claim_route_accepts_header_actor_and_returns_bounded_action_result():
    from src.api.quarantine import QuarantineClaimPayload, claim_quarantine_record
    from src.application.ingestion.quarantine_service import QuarantineResolutionResult
    from src.domain.ingestion.quarantine import QuarantineAction

    service = MagicMock()
    service.claim = AsyncMock(
        return_value=QuarantineResolutionResult(
            record_id="record-1",
            success=True,
            status=QuarantineStatus.REPROCESSING,
            outcome="CLAIMED",
            action=QuarantineAction.REPROCESS,
            action_id="action-1",
            previous_status=QuarantineStatus.PENDING,
            attempt_count=2,
            escalation_level=0,
        )
    )
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(db=MagicMock())),
        headers={"X-Actor": "header-operator"},
    )

    with patch("src.api.quarantine._resolution_service", return_value=service):
        result = await claim_quarantine_record(
            request,
            "record-1",
            QuarantineClaimPayload(actionId="action-1", expectedStatus="PENDING"),
        )

    assert result["actionId"] == "action-1"
    assert result["status"] == "REPROCESSING"
    assert "errors" not in result
    service.claim.assert_awaited_once_with(
        "record-1", "header-operator", "action-1", QuarantineStatus.PENDING
    )


@pytest.mark.asyncio
async def test_terminal_action_waits_for_explicit_reconciliation_continuation():
    from src.api.quarantine import _action_response
    from src.application.ingestion.quarantine_service import QuarantineResolutionResult
    from src.domain.ingestion.quarantine import QuarantineAction

    result = QuarantineResolutionResult(
        record_id="record-1",
        success=True,
        status=QuarantineStatus.RESOLVED,
        outcome="RESOLVED",
        action=QuarantineAction.REPROCESS,
        action_id="action-1",
        previous_status=QuarantineStatus.REPROCESSING,
    )
    repository = MagicMock()
    repository.find_by_id = AsyncMock(
        return_value=SimpleNamespace(post_approval_run_id="run-1")
    )

    with patch("src.api.quarantine.IngestionQuarantineRepository", return_value=repository):
        payload = await _action_response(_request(), result)

    assert payload["outcome"] == "RESOLVED"
    assert "continuation" not in payload
    repository.find_by_id.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_claim_maps_to_409():
    from src.api.quarantine import QuarantineClaimPayload, claim_quarantine_record
    from src.application.ingestion.quarantine_service import QuarantineResolutionResult
    from src.domain.ingestion.quarantine import QuarantineAction

    service = MagicMock()
    service.claim = AsyncMock(
        return_value=QuarantineResolutionResult(
            record_id="record-1",
            success=False,
            status=QuarantineStatus.REPROCESSING,
            outcome="STALE_STATUS",
            action=QuarantineAction.REPROCESS,
        )
    )
    with patch("src.api.quarantine._resolution_service", return_value=service):
        with pytest.raises(HTTPException) as exc_info:
            await claim_quarantine_record(
                _request(),
                "record-1",
                QuarantineClaimPayload(
                    operatorId="operator-1",
                    actionId="action-1",
                    expectedStatus=QuarantineStatus.PENDING,
                ),
            )

    assert exc_info.value.status_code == 409


def test_operator_mutation_payload_requires_action_id_and_expected_status():
    from pydantic import ValidationError
    from src.api.quarantine import QuarantineClaimPayload

    with pytest.raises(ValidationError):
        QuarantineClaimPayload()


@pytest.mark.asyncio
async def test_queue_filters_and_summary_are_independent_of_page_limit():
    from src.api.quarantine import list_quarantine

    repository = MagicMock()
    repository.find_many = AsyncMock(return_value=([], None))
    repository.summarize = AsyncMock(
        return_value={
            "pending": 9,
            "reprocessing": 3,
            "resolved": 4,
            "rejected": 2,
            "overdue": 5,
            "highPriority": 6,
        }
    )
    with patch("src.api.quarantine.IngestionQuarantineRepository", return_value=repository):
        result = await list_quarantine(
            _request(),
            claimed_by="operator-1",
            priority=QuarantinePriority.HIGH,
            overdue=True,
            limit=1,
        )

    query = repository.find_many.await_args.args[0]
    assert query.claimed_by == "operator-1"
    assert query.priority is QuarantinePriority.HIGH
    assert query.overdue is True
    repository.summarize.assert_awaited_once()
    assert result["summary"]["pending"] == 9
