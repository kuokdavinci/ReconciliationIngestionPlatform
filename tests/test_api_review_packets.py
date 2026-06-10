"""Tests for review packet approval desk endpoints."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.review_packets import (
    ReviewDecisionPayload,
    approve_activate_packet,
    approve_keep_current_packet,
    list_review_packets,
    validate_runtime_packet,
)


def _make_request(db: MagicMock):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db=db)))


def _make_db(review_collection=None, action_collection=None, mapping_collection=None):
    db = MagicMock()

    def _get_collection(name):
        if name == "review_packet":
            return review_collection or MagicMock()
        if name == "copilot_action":
            return action_collection or MagicMock()
        if name == "reconciliation_mapping_config":
            return mapping_collection or MagicMock()
        return MagicMock()

    db.__getitem__ = MagicMock(side_effect=_get_collection)
    return db


class _AsyncCursor:
    def __init__(self, docs):
        self._docs = docs
        self._idx = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._idx >= len(self._docs):
            raise StopAsyncIteration
        val = self._docs[self._idx]
        self._idx += 1
        return val


@pytest.mark.asyncio
async def test_list_review_packets():
    review_collection = MagicMock()
    review_collection.find = MagicMock(return_value=_AsyncCursor([
        {
            "_id": "pkt-001",
            "sourceType": "UPLOAD",
            "partner": "MOMO",
            "fileName": "momo.xlsx",
            "fileTypeDetected": "SETTLEMENT",
            "recommendedAction": {"actionType": "APPROVE_REQUIRED_BEFORE_RUNTIME"},
            "parseStrategy": {},
            "validationGates": [],
            "samplePreview": [],
            "riskSummary": {},
            "status": "PENDING",
            "createdAt": "2024-01-01T00:00:00+00:00",
        }
    ]))
    request = _make_request(_make_db(review_collection=review_collection))

    data = await list_review_packets(request, partner="MOMO")

    assert len(data["packets"]) == 1
    assert data["packets"][0]["partner"] == "MOMO"
    assert data["packets"][0]["reviewItemId"] == "pkt-001"
    assert data["packets"][0]["draftMappingId"] is None


@pytest.mark.asyncio
async def test_list_review_packets_exposes_draft_mapping_alias():
    review_collection = MagicMock()
    review_collection.find = MagicMock(return_value=_AsyncCursor([
        {
            "_id": "pkt-002",
            "sourceType": "UPLOAD",
            "partner": "MOMO",
            "fileName": "momo.xlsx",
            "fileTypeDetected": "SETTLEMENT",
            "proposalConfigId": "cfg-002",
            "recommendedAction": {"actionType": "APPROVE_REQUIRED_BEFORE_RUNTIME"},
            "parseStrategy": {},
            "validationGates": [],
            "samplePreview": [],
            "riskSummary": {},
            "status": "PENDING",
            "createdAt": "2024-01-01T00:00:00+00:00",
        }
    ]))
    request = _make_request(_make_db(review_collection=review_collection))

    data = await list_review_packets(request, partner="MOMO")

    assert data["packets"][0]["reviewItemId"] == "pkt-002"
    assert data["packets"][0]["draftMappingId"] == "cfg-002"


@pytest.mark.asyncio
async def test_approve_keep_current_packet():
    review_collection = MagicMock()
    action_collection = MagicMock()
    review_collection.find_one = AsyncMock(return_value={
        "_id": "pkt-001",
        "sourceType": "UPLOAD",
        "partner": "MOMO",
        "fileName": "momo.xlsx",
        "fileTypeDetected": "SETTLEMENT",
        "targetActionId": "act-001",
        "recommendedAction": {"actionType": "APPROVE_REQUIRED_BEFORE_RUNTIME"},
        "parseStrategy": {},
        "validationGates": [{"gateKey": "runtime_validation", "status": "pass"}],
        "samplePreview": [],
        "riskSummary": {},
        "status": "PENDING",
        "createdAt": "2024-01-01T00:00:00+00:00",
    })
    review_collection.update_one = AsyncMock()
    action_collection.update_one = AsyncMock()
    request = _make_request(_make_db(review_collection=review_collection, action_collection=action_collection))

    data = await approve_keep_current_packet(request, "pkt-001", ReviewDecisionPayload())

    assert data["ok"] is True
    assert data["packet"]["decisionMode"] == "APPROVE_KEEP_CURRENT_FOR_FILE"


@pytest.mark.asyncio
async def test_approve_activate_packet_triggers_post_approve_processing():
    review_collection = MagicMock()
    action_collection = MagicMock()
    mapping_collection = MagicMock()

    review_collection.find_one = AsyncMock(return_value={
        "_id": "pkt-activate-001",
        "sourceType": "SCHEDULER_JOB",
        "partner": "MOMO",
        "fileName": "momo_20240605.csv",
        "fileTypeDetected": "SETTLEMENT",
        "proposalConfigId": "cfg-pending-001",
        "targetActionId": "act-001",
        "sourceFileId": "file-001",
        "sourceFilePath": "/tmp/momo_20240605.csv",
        "recommendedAction": {"actionType": "APPROVE_AND_ACTIVATE_NEXT_RUNTIME"},
        "parseStrategy": {},
        "validationGates": [{"gateKey": "runtime_validation", "status": "pass"}],
        "samplePreview": [],
        "riskSummary": {},
        "status": "PENDING",
        "createdAt": "2024-01-01T00:00:00+00:00",
    })
    review_collection.update_one = AsyncMock()
    action_collection.update_one = AsyncMock()
    mapping_collection.find_one = AsyncMock(return_value={
        "_id": "cfg-pending-001",
        "partner": "MOMO",
        "workflowType": "UPC",
        "fileType": "SETTLEMENT",
        "sheetName": "Sheet1",
        "startRow": 2,
        "fieldMappings": [],
        "status": "PENDING_APPROVAL",
        "configHealth": {},
        "createdAt": "2024-01-01T00:00:00+00:00",
    })
    mapping_collection.update_one = AsyncMock()

    request = _make_request(_make_db(
        review_collection=review_collection,
        action_collection=action_collection,
        mapping_collection=mapping_collection,
    ))

    with patch(
        "src.api.review_packets._reprocess_and_reconcile",
        new=AsyncMock(return_value={
            "ok": True,
            "stage": "reconciliation",
            "processingStatus": "COMPLETED",
            "reconciliationCount": 12,
            "insightCacheInvalidated": 3,
            "stats": {"totalRows": 12, "successRows": 12, "failedRows": 0},
            "errors": [],
        }),
    ), patch(
        "src.models.mapping_config.MappingConfigRepository.find_by_partner_and_type",
        new=AsyncMock(return_value=None),
    ):
        data = await approve_activate_packet(
            request,
            "pkt-activate-001",
            ReviewDecisionPayload(),
        )

    assert data["ok"] is True
    assert data["packet"]["decisionMode"] == "APPROVE_ACTIVATE_NEXT_RUNTIME"
    assert data["postApproveRun"]["stage"] == "reconciliation"
    assert data["postApproveRun"]["reconciliationCount"] == 12


@pytest.mark.asyncio
async def test_approve_activate_requires_runtime_validation():
    review_collection = MagicMock()
    review_collection.find_one = AsyncMock(return_value={
        "_id": "pkt-002",
        "sourceType": "SCHEDULER_JOB",
        "partner": "MOMO",
        "fileName": "momo.xlsx",
        "fileTypeDetected": "SETTLEMENT",
        "proposalConfigId": "cfg-002",
        "validationGates": [],
        "status": "PENDING",
        "createdAt": "2024-01-01T00:00:00+00:00",
    })
    request = _make_request(_make_db(review_collection=review_collection))

    with pytest.raises(Exception) as exc:
        await approve_activate_packet(request, "pkt-002", ReviewDecisionPayload())
    assert "Runtime validation must pass" in str(exc.value)


@pytest.mark.asyncio
async def test_validate_runtime_packet_updates_gate():
    review_collection = MagicMock()
    mapping_collection = MagicMock()
    review_collection.find_one = AsyncMock(return_value={
        "_id": "pkt-003",
        "sourceType": "SCHEDULER_JOB",
        "partner": "MOMO",
        "fileName": "momo.xlsx",
        "fileTypeDetected": "SETTLEMENT",
        "proposalConfigId": "cfg-003",
        "sourceFilePath": "/tmp/momo.xlsx",
        "validationGates": [],
        "status": "PENDING",
        "createdAt": "2024-01-01T00:00:00+00:00",
    })
    review_collection.update_one = AsyncMock()
    mapping_collection.find_one = AsyncMock(return_value={
        "_id": "cfg-003",
        "partner": "MOMO",
        "workflowType": "UPC",
        "fileType": "SETTLEMENT",
        "sheetName": "Sheet1",
        "startRow": 2,
        "fieldMappings": [],
        "status": "PENDING_APPROVAL",
        "configHealth": {},
        "createdAt": "2024-01-01T00:00:00+00:00",
    })
    request = _make_request(_make_db(review_collection=review_collection, mapping_collection=mapping_collection))

    with patch("src.api.review_packets._run_runtime_validation", new=AsyncMock(return_value={
        "gateKey": "runtime_validation",
        "label": "Runtime validation",
        "status": "pass",
        "reason": "Validated successfully on 20/20 sampled rows.",
        "details": {"sampledRows": 20, "successRows": 20, "failedRows": 0},
    })):
        data = await validate_runtime_packet(request, "pkt-003")

    assert data["ok"] is True
    assert data["gate"]["status"] == "pass"
