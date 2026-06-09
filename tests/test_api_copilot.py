"""Tests for embedded Copilot dashboard context."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.api.copilot import CopilotActionPayload, execute_copilot_action, get_context


def _make_request(db: MagicMock):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db=db)))


class _AsyncCursor:
    def __init__(self, docs):
        self._docs = docs
        self._idx = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._idx >= len(self._docs):
            raise StopAsyncIteration
        value = self._docs[self._idx]
        self._idx += 1
        return value


def _make_collection(docs=None):
    collection = MagicMock()
    collection.find = MagicMock(side_effect=lambda *_args, **_kwargs: _AsyncCursor(docs or []))
    collection.find_one = AsyncMock(return_value=None)
    collection.update_one = AsyncMock()
    collection.update_many = AsyncMock()
    return collection


def _make_db(files=None, mappings=None, packets=None, actions=None):
    file_collection = _make_collection(files)
    mapping_collection = _make_collection(mappings)
    packet_collection = _make_collection(packets)
    action_collection = _make_collection(actions)
    db = MagicMock()

    def _get_collection(name):
        if name == "reconciliation_file":
            return file_collection
        if name == "reconciliation_mapping_config":
            return mapping_collection
        if name == "review_packet":
            return packet_collection
        if name == "copilot_action":
            return action_collection
        return MagicMock()

    db.__getitem__ = MagicMock(side_effect=_get_collection)
    return db


def _mapping(status="APPROVED", config_id="cfg-001", created="2026-06-01T00:00:00+00:00"):
    return {
        "_id": config_id,
        "partner": "MOMO",
        "workflowType": "UPC",
        "fileType": "SETTLEMENT",
        "sheetName": "Sheet1",
        "startRow": 2,
        "fieldMappings": [],
        "configVersion": "MOMO_v01",
        "status": status,
        "configHealth": {"confidence": 1.0, "reasoning": "Ready."},
        "createdAt": created,
    }


def _file(status="COMPLETED", failed_rows=0):
    return {
        "_id": str(uuid4()),
        "partner": "MOMO",
        "fileName": "settlement_MOMO_20260605.xlsx",
        "fileHash": "hash-001",
        "fileType": "SETTLEMENT",
        "reconciliationDate": "2026-06-05T00:00:00+00:00",
        "processingStatus": status,
        "totalRows": 100,
        "successRows": 100 - failed_rows,
        "failedRows": failed_rows,
        "configVersion": "MOMO_v01",
        "uploadedAt": "2026-06-05T01:00:00+00:00",
        "createdAt": "2026-06-05T01:00:00+00:00",
    }


def _packet(packet_id="pkt-001"):
    return {
        "_id": packet_id,
        "sourceType": "SCHEDULER_JOB",
        "partner": "MOMO",
        "fileName": "settlement_MOMO_20260605.xlsx",
        "fileTypeDetected": "SETTLEMENT",
        "proposalConfigId": "cfg-002",
        "recommendedAction": {"actionType": "APPROVE_AND_ACTIVATE_NEXT_RUNTIME", "reason": "Structure changed."},
        "parseStrategy": {},
        "validationGates": [],
        "samplePreview": [],
        "riskSummary": {"severity": "medium", "summary": "Structure changed."},
        "status": "PENDING",
        "createdAt": "2026-06-05T01:05:00+00:00",
    }


@pytest.mark.asyncio
async def test_copilot_context_healthy_without_raw_ids():
    request = _make_request(_make_db(files=[_file()], mappings=[_mapping()], packets=[]))

    data = await get_context(request, partner="MOMO", date="2026-06-05")

    assert data["status"] == "healthy"
    assert data["riskLevel"] == "low"
    assert data["recommendedAction"] is None
    assert data["headline"] == "No action needed"
    rendered = str(data)
    assert "proposalConfigId" not in rendered
    assert "reviewPacketId" not in rendered
    assert "copilotAction" not in rendered


@pytest.mark.asyncio
async def test_copilot_action_review_target_uses_business_ids():
    request = _make_request(_make_db(
        files=[_file(status="FAILED", failed_rows=100)],
        mappings=[_mapping(), _mapping(status="PENDING_APPROVAL", config_id="cfg-002")],
        packets=[_packet("pkt-002")],
    ))

    data = await execute_copilot_action(
        request,
        "review_proposal",
        CopilotActionPayload(partner="MOMO", date="2026-06-05"),
    )

    assert data["ok"] is True
    assert data["target"]["type"] == "review_drawer"
    assert data["target"]["reviewItemId"] == "pkt-002"
    assert "reviewPacketId" not in data["target"]


@pytest.mark.asyncio
async def test_copilot_context_monitor_when_runtime_can_continue_but_file_failed():
    request = _make_request(_make_db(files=[_file(status="FAILED", failed_rows=10)], mappings=[_mapping()], packets=[]))

    data = await get_context(request, partner="MOMO", date="2026-06-05")

    assert data["status"] == "monitor"
    assert data["riskLevel"] == "medium"
    assert data["recommendedAction"]["key"] == "open_mapping_details"


@pytest.mark.asyncio
async def test_copilot_context_needs_review_for_pending_packet():
    request = _make_request(_make_db(
        files=[_file(status="FAILED", failed_rows=100)],
        mappings=[_mapping(), _mapping(status="PENDING_APPROVAL", config_id="cfg-002")],
        packets=[_packet()],
    ))

    data = await get_context(request, partner="MOMO", date="2026-06-05")

    assert data["status"] == "needs_review"
    assert data["recommendedAction"] == {"key": "review_proposal", "label": "Open Review Queue", "style": "primary", "enabled": True}
    assert data["headline"] == "File structure changed; a review item is ready"
    assert data["evidence"]["proposal"]["source"] == "review_packet"


@pytest.mark.asyncio
async def test_copilot_context_needs_review_for_pending_proposal_without_packet():
    request = _make_request(_make_db(
        files=[_file(status="FAILED")],
        mappings=[_mapping(status="PENDING_APPROVAL", config_id="cfg-002")],
        packets=[],
    ))

    data = await get_context(request, partner="MOMO", date="2026-06-05")

    assert data["status"] == "needs_review"
    assert data["riskLevel"] == "high"
    assert data["headline"] == "MOMO cannot continue safely until a draft is reviewed"
    assert data["evidence"]["proposal"]["source"] == "mapping_proposal"


@pytest.mark.asyncio
async def test_copilot_context_blocked_without_runtime_or_proposal():
    request = _make_request(_make_db(files=[_file(status="FAILED")], mappings=[], packets=[]))

    data = await get_context(request, partner="MOMO", date="2026-06-05")

    assert data["status"] == "blocked"
    assert data["riskLevel"] == "high"
    assert data["headline"] == "MOMO is blocked until a runtime mapping is approved"
    assert data["evidence"]["runtime"]["state"] == "missing"


@pytest.mark.asyncio
async def test_copilot_action_wraps_existing_review_packet_handler():
    request = _make_request(_make_db(
        files=[_file()],
        mappings=[_mapping(), _mapping(status="PENDING_APPROVAL", config_id="cfg-002")],
        packets=[_packet()],
    ))

    with patch(
        "src.api.copilot.approve_keep_current_packet",
        new=AsyncMock(return_value={"ok": True, "packet": {"_id": "pkt-001"}}),
    ) as approve_mock:
        data = await execute_copilot_action(
            request,
            "approve_keep_current",
            CopilotActionPayload(partner="MOMO", date="2026-06-05"),
        )

    assert data["ok"] is True
    approve_mock.assert_awaited_once()
    assert data["context"]["status"] == "needs_review"
