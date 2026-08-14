"""Tests for review packet approval desk endpoints."""

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import src.api.review_packets as review_packets

from src.api.review_packets import (
    ReviewDecisionPayload,
    approve_activate_packet,
    approve_keep_current_packet,
    get_post_approve_run,
    list_review_packets,
    save_draft_mapping_for_packet,
    validate_runtime_packet,
    classify_scope_llm_for_packet,
    _extract_scope_keys,
    _raw_stage_record_count,
    get_review_packet_raw_records,
    SaveDraftMappingPayload,
)
from src.domain.review.models import ReviewPacket
from src.application.review.runtime_validation import run_runtime_validation
from src.models.mapping_config import MappingConfig


def _make_request(db: MagicMock, headers: dict | None = None):
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(db=db)),
        headers=headers or {},
    )


@pytest.mark.asyncio
async def test_approve_keep_current_replays_a_staged_stream_with_active_mapping():
    packet = ReviewPacket(
        _id="pkt-stream",
        sourceType="SCHEDULER_JOB",
        partner="VIETTELPAY",
        fileName="viettelpay.json",
        fileTypeDetected="SETTLEMENT",
        rawStageKey="stage-viettelpay",
        activeRuntimeConfigId="mapping-approved",
        validationGates=[{"gateKey": "runtime_validation", "status": "pass"}],
    )
    repo = MagicMock()
    repo.find_one = AsyncMock(return_value=packet)
    replay = AsyncMock(return_value={"id": "post-approval-stream"})

    with (
        patch("src.api.review_packets._repo", return_value=repo),
        patch("src.api.review_packets.update_packet_scope", new=AsyncMock()),
        patch("src.api.review_packets.reprocess_packet_with_current_mapping", new=replay),
        patch("src.api.review_packets.mark_packet", new=AsyncMock(return_value={"ok": True})),
    ):
        response = await approve_keep_current_packet(
            _make_request(MagicMock(), headers={"x-actor": "tester"}),
            "pkt-stream",
            ReviewDecisionPayload(reviewedBy="tester", scopeType="FULL_SNAPSHOT"),
        )

    assert replay.await_args.args[1:] == (packet, "tester")
    assert response["postApproveRun"]["id"] == "post-approval-stream"


def test_scope_key_extraction_counts_rows_when_mapping_is_deferred():
    received_count, keys = _extract_scope_keys(
        [("1", "MOMO_TXN_9000"), ("2", "MOMO_TXN_9001")],
        SimpleNamespace(field_mappings=[]),
        {"headers": ["STT", "msTransId"]},
    )

    assert received_count == 2
    assert keys == {"MOMO_TXN_9000", "MOMO_TXN_9001"}


def test_json_mapping_generation_uses_header_field_names_not_column_positions():
    mappings = review_packets._apply_source_reference_strategy(
        [
            {"path": "id", "column": 1, "type": "STRING", "required": True},
            {"path": "amount", "column": 3, "type": "DECIMAL", "required": True},
            {"path": "currency", "type": "CONSTANT", "constant": "VND"},
        ],
        headers=["id", "trace", "amount", "currency"],
        source_file_name="api_data_page_0001.json",
    )

    assert mappings == [
        {"path": "id", "sourceField": "id", "type": "STRING", "required": True},
        {"path": "amount", "sourceField": "amount", "type": "DECIMAL", "required": True},
        {"path": "currency", "type": "CONSTANT", "constant": "VND"},
    ]


def test_tabular_mapping_generation_keeps_column_positions():
    mappings = review_packets._apply_source_reference_strategy(
        [{"path": "id", "column": 1, "type": "STRING", "required": True}],
        headers=["id"],
        source_file_name="settlement.csv",
    )

    assert mappings[0]["column"] == 1
    assert "sourceField" not in mappings[0]


@pytest.mark.asyncio
async def test_raw_stage_record_count_sums_all_persisted_api_pages():
    class Cursor:
        async def to_list(self, length=None):
            return [{"itemCount": 2}, {"itemCount": 2}, {"itemCount": 2}]

    collection = MagicMock()
    collection.find.return_value = Cursor()
    db = MagicMock()
    db.__getitem__ = MagicMock(return_value=collection)
    packet = ReviewPacket(
        _id="pkt-api-pages",
        sourceType="SCHEDULER_JOB",
        partner="VIETTELPAY",
        fileName="viettelpay.json",
        fileTypeDetected="SETTLEMENT",
        rawStageKey="stage-viettelpay",
    )

    assert await _raw_stage_record_count(db, packet) == 6


@pytest.mark.asyncio
async def test_raw_records_endpoint_returns_stream_scoped_paginated_rows():
    packet = ReviewPacket(
        _id="pkt-raw",
        sourceType="SCHEDULER_JOB",
        partner="VIETTELPAY",
        fileName="viettelpay.json",
        fileTypeDetected="SETTLEMENT",
        rawStageKey="stage-viettelpay",
    )
    review_repo = MagicMock()
    review_repo.find_one = AsyncMock(return_value=packet)
    request = _make_request(MagicMock())
    stream_page = {
        "packetId": "pkt-raw",
        "rawStageKey": "stage-viettelpay",
        "totalRecords": 6,
        "pageCount": 3,
        "offset": 2,
        "limit": 2,
        "hasMore": True,
        "rows": [{"sourceUnitKey": "unit-2", "values": {"id": "VTP-003"}}],
    }

    with (
        patch("src.api.review_packets._repo", return_value=review_repo),
        patch(
            "src.api.review_packets.read_review_stream_page",
            new=AsyncMock(return_value=stream_page),
        ) as read_stream,
    ):
        response = await get_review_packet_raw_records(
            request, "pkt-raw", offset=2, limit=2
        )

    assert response == stream_page
    read_stream.assert_awaited_once_with(
        db=request.app.state.db,
        packet=packet,
        offset=2,
        limit=2,
    )


@pytest.mark.asyncio
async def test_raw_records_endpoint_rejects_packet_without_evidence():
    packet = ReviewPacket(
        _id="pkt-no-evidence",
        sourceType="UPLOAD",
        partner="MOMO",
        fileName="momo.csv",
        fileTypeDetected="SETTLEMENT",
    )
    review_repo = MagicMock()
    review_repo.find_one = AsyncMock(return_value=packet)
    request = _make_request(MagicMock())

    with patch("src.api.review_packets._repo", return_value=review_repo):
        with pytest.raises(Exception, match="rawStageKey"):
            await get_review_packet_raw_records(request, "pkt-no-evidence", offset=0, limit=50)


def _make_db(
    review_collection=None,
    action_collection=None,
    mapping_collection=None,
    post_approval_run_collection=None,
    audit_collection=None,
):
    db = MagicMock()
    resolved_audit_collection = audit_collection or MagicMock()
    if not hasattr(resolved_audit_collection, "insert_one") or isinstance(
        resolved_audit_collection.insert_one, MagicMock
    ):
        resolved_audit_collection.insert_one = AsyncMock(
            return_value=SimpleNamespace(inserted_id="audit-001")
        )

    def _get_collection(name):
        if name == "review_packet":
            return review_collection or MagicMock()
        if name == "copilot_action":
            return action_collection or MagicMock()
        if name == "reconciliation_mapping_config":
            return mapping_collection or MagicMock()
        if name == "post_approval_run":
            return post_approval_run_collection or MagicMock()
        if name == "audit_event":
            return resolved_audit_collection
        return MagicMock()

    db.__getitem__ = MagicMock(side_effect=_get_collection)
    return db


@pytest.mark.asyncio
async def test_scope_classification_falls_back_when_llm_times_out():
    packet = ReviewPacket(
        _id="pkt-timeout",
        sourceType="UPLOAD",
        partner="MOMO",
        fileName="momo.xlsx",
        fileTypeDetected="SETTLEMENT",
        structureSignature={"sampleRows": []},
    )
    review_repo = MagicMock()
    review_repo.find_one = AsyncMock(return_value=packet)
    internal_repo = MagicMock()
    internal_repo.count_by_partner_and_date_range = AsyncMock(return_value=0)
    provider = MagicMock()

    async def slow_generate(*args, **kwargs):
        await asyncio.sleep(1)
        return "{}"

    provider.generate = AsyncMock(side_effect=slow_generate)
    request = _make_request(_make_db())

    with patch("src.api.review_packets._repo", return_value=review_repo), patch(
        "src.infrastructure.postgres.internal_transaction_repository.InternalTransactionRepository",
        return_value=internal_repo,
    ), patch("src.analysis.config.AnalysisConfig", return_value=SimpleNamespace(timeout=0.01)), patch(
        "src.analysis.provider.create_provider", return_value=provider,
    ):
        result = await classify_scope_llm_for_packet(request, "pkt-timeout")

    assert result["ok"] is True
    assert result["resolution"] == "rule_based_timeout"
    assert result["suggestedScope"] == "FULL_SNAPSHOT"


@pytest.mark.asyncio
async def test_scope_classification_detects_replacement_from_key_coverage(tmp_path):
    source_path = tmp_path / "settlement_MOMO_20260806_phase2.xlsx"
    source_path.touch()
    packet = ReviewPacket(
        _id="pkt-overlap",
        sourceType="UPLOAD",
        partner="MOMO",
        fileName=source_path.name,
        fileTypeDetected="SETTLEMENT",
        draftMappingId="mapping-001",
        sourceFilePath=str(source_path),
        reconciliationDate="2026-08-06T00:00:00+00:00",
        structureSignature={"sampleRows": []},
    )
    review_repo = MagicMock()
    review_repo.find_one = AsyncMock(return_value=packet)
    internal_repo = MagicMock()
    internal_repo.count_by_partner_and_date_range = AsyncMock(return_value=30)
    internal_repo.find_by_partner_and_date_range = AsyncMock(
        return_value=[
            SimpleNamespace(
                id="internal-1",
                partner_txn_id="MOMO_TXN_9000",
                amount="100000",
                currency="VND",
                status=SimpleNamespace(value="SUCCESS"),
                transaction_time=datetime(2026, 8, 5, 17, 0),
            )
        ]
    )
    partner_repo = MagicMock()
    partner_repo.find_reconciliation_keys_by_date_range = AsyncMock(
        return_value={f"MOMO_TXN_90{i:02d}" for i in range(20)}
    )
    mapping_repo = MagicMock()
    mapping_repo.find_one = AsyncMock(
        return_value=SimpleNamespace(
            field_mappings=[
                SimpleNamespace(path="id", column="A"),
                SimpleNamespace(path="trace", column="B"),
            ]
        )
    )

    class _Reader:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def iter_rows(self):
            return iter(
                [
                    (f"id-{index}", f"MOMO_TXN_90{index:02d}")
                    for index in range(20)
                ]
                + [
                    (f"id-new-{index}", f"MOMO_TXN_92{index:02d}")
                    for index in range(10)
                ]
            )

    provider = MagicMock()
    provider.generate = AsyncMock(
        return_value=(
            '{"probabilities":{"FULL_SNAPSHOT":1,"INCREMENTAL_APPEND":0,"REPLACEMENT":0},'
            '"suggested_scope":"FULL_SNAPSHOT","reasoning":"same row count"}'
        )
    )
    request = _make_request(_make_db())

    with patch("src.api.review_packets._repo", return_value=review_repo), patch(
        "src.infrastructure.postgres.internal_transaction_repository.InternalTransactionRepository",
        return_value=internal_repo,
    ), patch(
        "src.infrastructure.mapping.config_repository.MappingConfigRepository",
        return_value=mapping_repo,
    ), patch(
        "src.api.review_packets.DataContainerRepository",
        return_value=partner_repo,
    ), patch(
        "src.readers.create_reader", return_value=_Reader(),
    ), patch(
        "src.analysis.config.AnalysisConfig",
        return_value=SimpleNamespace(timeout=1),
    ), patch(
        "src.analysis.provider.create_provider", return_value=provider,
    ):
        result = await classify_scope_llm_for_packet(request, "pkt-overlap")

    assert result["suggestedScope"] == "REPLACEMENT"
    assert result["resolution"] == "rule_based_key_evidence"
    assert result["internalDbRecordCount"] == 30
    assert result["internalPreview"][0]["partnerTxnId"] == "MOMO_TXN_9000"
    assert result["scopeEvidence"]["incomingUniqueBusinessKeyCount"] == 30
    assert result["scopeEvidence"]["duplicateBusinessKeyCount"] == 20
    assert result["scopeEvidence"]["newBusinessKeyCount"] == 10
    assert result["scopeEvidence"]["duplicateRatio"] == pytest.approx(2 / 3)
    assert result["scopeEvidence"]["historicalCoverage"] == 1.0
    assert result["scopeEvidence"]["ruleBasedScope"] == "REPLACEMENT"
    assert result["scopeEvidence"]["available"] is True


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
async def test_list_review_packets_collapses_duplicate_pending_scheduler_packets():
    review_collection = MagicMock()
    review_collection.find = MagicMock(return_value=_AsyncCursor([
        {
            "_id": "pkt-new",
            "sourceType": "SCHEDULER_JOB",
            "partner": "VIETTELPAY",
            "fileName": "page-3.json",
            "fileTypeDetected": "SETTLEMENT",
            "recommendedAction": {},
            "parseStrategy": {},
            "validationGates": [],
            "samplePreview": [],
            "riskSummary": {},
            "status": "PENDING",
            "createdAt": "2026-08-10T03:00:00+00:00",
        },
        {
            "_id": "pkt-old",
            "sourceType": "SCHEDULER_JOB",
            "partner": "VIETTELPAY",
            "fileName": "page-1.json",
            "fileTypeDetected": "SETTLEMENT",
            "recommendedAction": {},
            "parseStrategy": {},
            "validationGates": [],
            "samplePreview": [],
            "riskSummary": {},
            "status": "PENDING",
            "createdAt": "2026-08-10T02:00:00+00:00",
        },
    ]))
    request = _make_request(_make_db(review_collection=review_collection))

    data = await list_review_packets(request, partner="VIETTELPAY")

    assert [packet["_id"] for packet in data["packets"]] == ["pkt-new"]


@pytest.mark.asyncio
async def test_list_review_packets_hides_pending_packet_for_approved_same_structure():
    review_collection = MagicMock()
    review_collection.find = MagicMock(return_value=_AsyncCursor([
        {
            "_id": "pkt-pending-duplicate",
            "sourceType": "SCHEDULER_JOB",
            "partner": "VNPAY",
            "fileName": "settlement_VNPAY_20260813.xlsx",
            "fileTypeDetected": "SETTLEMENT",
            "structureSignature": {
                "headers": ["id", "trace", "amount"],
                "columnCount": 3,
                "hash": "same-structure",
            },
            "recommendedAction": {},
            "parseStrategy": {},
            "validationGates": [],
            "samplePreview": [],
            "riskSummary": {},
            "status": "PENDING",
            "createdAt": "2026-08-13T03:00:00+00:00",
        },
        {
            "_id": "pkt-approved-start-date",
            "sourceType": "SCHEDULER_JOB",
            "partner": "VNPAY",
            "fileName": "settlement_VNPAY_20260810.xlsx",
            "fileTypeDetected": "SETTLEMENT",
            "structureSignature": {
                "headers": ["id", "trace", "amount"],
                "columnCount": 3,
            },
            "recommendedAction": {},
            "parseStrategy": {},
            "validationGates": [],
            "samplePreview": [],
            "riskSummary": {},
            "status": "APPROVED",
            "createdAt": "2026-08-10T03:00:00+00:00",
        },
    ]))
    request = _make_request(_make_db(review_collection=review_collection))

    data = await list_review_packets(request, partner="VNPAY")

    assert [packet["_id"] for packet in data["packets"]] == ["pkt-approved-start-date"]


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

    data = await approve_keep_current_packet(
        request,
        "pkt-001",
        ReviewDecisionPayload(reviewedBy="admin"),
    )

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
        "src.api.review_packets.approve_packet_mapping_and_reprocess",
        new=AsyncMock(return_value={
            "_id": "run-001",
            "packetId": "pkt-activate-001",
            "status": "QUEUED",
            "stage": "approval",
            "message": "Approved. Post-approval processing is queued.",
            "sourceFileId": "file-001",
        }),
    ), patch(
        "src.models.mapping_config.MappingConfigRepository.find_by_partner_and_type",
        new=AsyncMock(return_value=None),
    ):
        data = await approve_activate_packet(
            request,
            "pkt-activate-001",
            ReviewDecisionPayload(reviewedBy="admin"),
        )

    assert data["ok"] is True
    assert data["packet"]["decisionMode"] == "APPROVE_ACTIVATE_NEXT_RUNTIME"
    assert data["postApproveRun"]["stage"] == "approval"
    assert data["postApproveRun"]["status"] == "QUEUED"


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
        await approve_activate_packet(
            request,
            "pkt-002",
            ReviewDecisionPayload(reviewedBy="admin"),
        )
    assert "Runtime validation must pass" in str(exc.value)


@pytest.mark.asyncio
async def test_approve_keep_current_requires_actor():
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
    request = _make_request(_make_db(review_collection=review_collection, action_collection=action_collection))

    with pytest.raises(Exception) as exc:
        await approve_keep_current_packet(request, "pkt-001", ReviewDecisionPayload())

    assert "Actor is required" in str(exc.value)


@pytest.mark.asyncio
async def test_get_post_approve_run():
    post_approval_run_collection = MagicMock()
    post_approval_run_collection.find_one = AsyncMock(return_value={
        "_id": "run-001",
        "packetId": "pkt-activate-001",
        "partner": "MOMO",
        "date": "2024-06-05",
        "status": "RECONCILING",
        "stage": "reconciliation",
        "message": "Reconciling ingested partner rows against internal transactions.",
        "sourceFileId": "file-001",
        "outputFileId": "file-002",
        "reconciliationCount": 12,
        "stats": {"totalRows": 12, "successRows": 12, "failedRows": 0},
        "errors": [],
        "createdAt": "2024-01-01T00:00:00+00:00",
        "updatedAt": "2024-01-01T00:01:00+00:00",
    })
    request = _make_request(_make_db(post_approval_run_collection=post_approval_run_collection))

    data = await get_post_approve_run(request, "pkt-activate-001")

    assert data["run"]["packetId"] == "pkt-activate-001"
    assert data["run"]["status"] == "RECONCILING"
    assert data["run"]["stage"] == "reconciliation"


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

    with patch("src.api.review_packets.run_runtime_validation", new=AsyncMock(return_value={
        "gateKey": "runtime_validation",
        "label": "Runtime validation",
        "status": "pass",
        "reason": "Validated successfully on 20/20 sampled rows.",
        "details": {
            "sampledRows": 20,
            "successRows": 20,
            "failedRows": 0,
            "validatedAt": "2024-01-01T00:00:00+00:00",
            "validatedMappingVersion": "MOMO_v01",
            "successRate": 1.0,
            "riskLevel": "LOW",
        },
    })):
        data = await validate_runtime_packet(request, "pkt-003")

    assert data["ok"] is True
    assert data["gate"]["status"] == "pass"


@pytest.mark.asyncio
async def test_save_draft_mapping_for_packet_attaches_real_draft_id():
    review_collection = MagicMock()
    mapping_collection = MagicMock()
    review_collection.find_one = AsyncMock(return_value={
        "_id": "pkt-004",
        "sourceType": "SCHEDULER_JOB",
        "partner": "MOMO",
        "fileName": "momo.xlsx",
        "fileTypeDetected": "SETTLEMENT",
        "structureSignature": {"headers": ["txn_id", "amount", "date"]},
        "validationGates": [],
        "parseStrategy": {},
        "status": "PENDING",
        "createdAt": "2024-01-01T00:00:00+00:00",
    })
    review_collection.update_one = AsyncMock()
    mapping_collection.find_one = AsyncMock(return_value=None)
    mapping_collection.count_documents = AsyncMock(return_value=3)
    mapping_collection.insert_one = AsyncMock()
    request = _make_request(_make_db(
        review_collection=review_collection,
        mapping_collection=mapping_collection,
    ))

    payload = SaveDraftMappingPayload.model_validate({
        "sheetName": "Sheet1",
        "startRow": 2,
        "fieldMappings": [
            {"path": "id", "column": 1, "type": "STRING", "required": True},
            {"path": "amount", "column": 2, "type": "DECIMAL", "required": True},
            {"path": "transDate", "column": 3, "type": "DATE", "required": True},
            {"path": "status", "constant": "SUCCESS", "type": "CONSTANT", "required": True},
        ],
    })

    with patch(
        "src.api.review_packets._next_pending_version",
        new=AsyncMock(return_value="MOMO-V004"),
    ):
        data = await save_draft_mapping_for_packet(request, "pkt-004", payload)

    assert data["ok"] is True
    assert data["draftMappingId"]
    assert data["fieldMappingCount"] == 5
    assert data["warnings"]


@pytest.mark.asyncio
async def test_save_draft_mapping_preserves_existing_signature_when_packet_has_none():
    review_collection = MagicMock()
    review_collection.find_one = AsyncMock(return_value={
        "_id": "pkt-signature-fallback",
        "sourceType": "SCHEDULER_JOB",
        "partner": "MOMO",
        "fileName": "momo.xlsx",
        "fileTypeDetected": "SETTLEMENT",
        "draftMappingId": "mapping-001",
        "structureSignature": None,
        "validationGates": [],
        "parseStrategy": {},
        "status": "PENDING",
        "createdAt": "2024-01-01T00:00:00+00:00",
    })
    review_collection.update_one = AsyncMock()
    mapping_repo = MagicMock()
    mapping_repo.find_one = AsyncMock(return_value=SimpleNamespace(
        id="mapping-001",
        workflow_type="UPC",
        config_version="MOMO_v001",
        structure_signature={"headers": ["txn_id", "amount"]},
    ))
    mapping_repo.collection.update_one = AsyncMock()
    request = _make_request(_make_db(review_collection=review_collection))

    payload = SaveDraftMappingPayload.model_validate({
        "sheetName": "Sheet1",
        "startRow": 2,
        "fieldMappings": [
            {"path": "id", "column": 1, "type": "STRING", "required": True},
            {"path": "amount", "column": 2, "type": "DECIMAL", "required": True},
            {"path": "status", "constant": "SUCCESS", "type": "CONSTANT", "required": True},
        ],
    })

    with patch("src.api.review_packets.MappingConfigRepository", return_value=mapping_repo):
        await save_draft_mapping_for_packet(request, "pkt-signature-fallback", payload)

    update_payload = mapping_repo.collection.update_one.await_args.args[1]["$set"]
    assert update_payload["structureSignature"] == {"headers": ["txn_id", "amount"]}


@pytest.mark.asyncio
async def test_save_draft_mapping_for_packet_rejects_missing_status():
    review_collection = MagicMock()
    mapping_collection = MagicMock()
    review_collection.find_one = AsyncMock(return_value={
        "_id": "pkt-006",
        "sourceType": "SCHEDULER_JOB",
        "partner": "MOMO",
        "fileName": "momo.xlsx",
        "fileTypeDetected": "SETTLEMENT",
        "structureSignature": {"headers": ["txn_id", "amount", "date"]},
        "validationGates": [],
        "parseStrategy": {},
        "status": "PENDING",
        "createdAt": "2024-01-01T00:00:00+00:00",
    })
    mapping_collection.find_one = AsyncMock(return_value=None)
    mapping_collection.count_documents = AsyncMock(return_value=3)
    request = _make_request(_make_db(
        review_collection=review_collection,
        mapping_collection=mapping_collection,
    ))

    payload = SaveDraftMappingPayload.model_validate({
        "sheetName": "Sheet1",
        "startRow": 2,
        "fieldMappings": [
            {"path": "id", "column": 1, "type": "STRING", "required": True},
            {"path": "amount", "column": 2, "type": "DECIMAL", "required": True},
        ],
    })

    with pytest.raises(Exception) as exc:
        await save_draft_mapping_for_packet(request, "pkt-006", payload)

    assert "status" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_validate_runtime_packet_uses_sample_preview_when_source_file_missing():
    review_collection = MagicMock()
    mapping_collection = MagicMock()
    review_collection.find_one = AsyncMock(return_value={
        "_id": "pkt-005",
        "sourceType": "STUDIO_HANDOFF",
        "partner": "MOMO",
        "fileName": "manual.xlsx",
        "fileTypeDetected": "SETTLEMENT",
        "draftMappingId": "cfg-005",
        "samplePreview": [
            {"rowIndex": 2, "values": ["TXN001", "1000", "2024-06-05"]},
            {"rowIndex": 3, "values": ["TXN002", "2500", "2024-06-05"]},
        ],
        "validationGates": [],
        "status": "PENDING",
        "createdAt": "2024-01-01T00:00:00+00:00",
    })
    review_collection.update_one = AsyncMock()
    mapping_collection.find_one = AsyncMock(return_value={
        "_id": "cfg-005",
        "partner": "MOMO",
        "workflowType": "UPC",
        "fileType": "SETTLEMENT",
        "sheetName": "Sheet1",
        "startRow": 2,
        "fieldMappings": [
            {"path": "id", "column": 1, "type": "STRING", "required": True},
            {"path": "amount", "column": 2, "type": "DECIMAL", "required": True},
            {"path": "transDate", "column": 3, "type": "DATE", "required": True},
            {"path": "currency", "constant": "VND", "type": "CONSTANT", "required": True},
            {"path": "status", "constant": "SUCCESS", "type": "CONSTANT", "required": True},
        ],
        "status": "PENDING_APPROVAL",
        "configHealth": {},
        "createdAt": "2024-01-01T00:00:00+00:00",
    })
    request = _make_request(_make_db(review_collection=review_collection, mapping_collection=mapping_collection))

    data = await validate_runtime_packet(request, "pkt-005")

    assert data["ok"] is True
    assert data["gate"]["status"] == "pass"
    assert data["gate"]["details"]["validatedAt"]
    assert data["gate"]["details"]["validatedMappingVersion"] == "cfg-005"
    assert data["gate"]["details"]["successRate"] == 1
    assert data["gate"]["details"]["riskLevel"] == "LOW"
    trace_samples = data["gate"]["details"]["traceSamples"]
    assert len(trace_samples) == 2
    assert trace_samples[0]["row"] == 2
    assert any(
        item["path"] == "id"
        and item["sourceValue"] == "TXN001"
        and item["outputValue"] == "TXN001"
        and item["status"] == "ok"
        and item["errorCode"] is None
        and item["errorMessage"] is None
        for item in trace_samples[0]["fieldTraces"]
    )
    assert any(
        item["path"] == "currency"
        and item["sourceValue"] == "VND"
        and item["outputValue"] == "VND"
        and item["status"] == "ok"
        for item in trace_samples[0]["fieldTraces"]
    )


@pytest.mark.asyncio
async def test_run_runtime_validation_returns_medium_risk_for_partial_pass():
    review_collection = MagicMock()
    review_collection.update_one = AsyncMock()
    packet = SimpleNamespace(
        id="pkt-007",
        source_file_path=None,
        sample_preview=[
            {"rowIndex": 2, "values": ["TXN001", "1000", "2024-06-05"]},
            {"rowIndex": 3, "values": ["TXN002", "2500", "2024-06-05"]},
            {"rowIndex": 4, "values": ["TXN003", "3750", "2024-06-05"]},
            {"rowIndex": 5, "values": ["TXN004", "4100", "2024-06-05"]},
            {"rowIndex": 6, "values": ["TXN005", "bad-amount", "2024-06-05"]},
        ],
        validation_gates=[],
    )
    config = MappingConfig.model_validate({
        "_id": "cfg-007",
        "partner": "MOMO",
        "workflowType": "UPC",
        "fileType": "SETTLEMENT",
        "sheetName": "Sheet1",
        "startRow": 2,
        "configVersion": "MOMO_v07",
        "fieldMappings": [
            {"path": "id", "column": 1, "type": "STRING", "required": True},
            {"path": "amount", "column": 2, "type": "DECIMAL", "required": True},
            {"path": "transDate", "column": 3, "type": "DATE", "required": True},
            {"path": "currency", "type": "CONSTANT", "constant": "VND", "required": True},
            {"path": "status", "type": "CONSTANT", "constant": "SUCCESS", "required": True},
        ],
        "status": "PENDING_APPROVAL",
        "configHealth": {},
    })
    db = _make_db(review_collection=review_collection)
    gate = await run_runtime_validation(db, packet, config)

    assert gate["status"] == "pass"
    assert gate["details"]["riskLevel"] == "MEDIUM"
    assert gate["details"]["validatedMappingVersion"] == "MOMO_v07"
    amount_trace = next(item for item in gate["details"]["traceSamples"][4]["fieldTraces"] if item["path"] == "amount")
    assert amount_trace["status"] == "error"
    assert amount_trace["errorCode"] == "INVALID_DECIMAL"
    assert amount_trace["errorMessage"]


@pytest.mark.asyncio
async def test_run_runtime_validation_returns_high_risk_for_failed_validation():
    review_collection = MagicMock()
    review_collection.update_one = AsyncMock()
    packet = SimpleNamespace(
        id="pkt-008",
        source_file_path=None,
        sample_preview=[
            {"rowIndex": 2, "values": ["TXN001", "1000", "bad-date"]},
        ],
        validation_gates=[],
    )
    config = MappingConfig.model_validate({
        "_id": "cfg-008",
        "partner": "MOMO",
        "workflowType": "UPC",
        "fileType": "SETTLEMENT",
        "sheetName": "Sheet1",
        "startRow": 2,
        "configVersion": "MOMO_v08",
        "fieldMappings": [
            {"path": "id", "column": 1, "type": "STRING", "required": True},
            {"path": "amount", "column": 2, "type": "DECIMAL", "required": True},
            {"path": "transDate", "column": 3, "type": "DATE", "required": True},
            {"path": "currency", "type": "CONSTANT", "constant": "VND", "required": True},
            {"path": "status", "type": "CONSTANT", "required": True},
        ],
        "status": "PENDING_APPROVAL",
        "configHealth": {},
    })
    db = _make_db(review_collection=review_collection)
    gate = await run_runtime_validation(db, packet, config)

    assert gate["status"] == "fail"
    assert gate["details"]["riskLevel"] == "HIGH"
    codes = {item["errorCode"] for item in gate["details"]["traceSamples"][0]["fieldTraces"] if item["errorCode"]}
    assert "INVALID_DATE" in codes
    assert "MAPPING_RULE_MISSING" in codes


@pytest.mark.asyncio
async def test_runtime_validation_reads_all_staged_stream_pages(tmp_path):
    first = tmp_path / "page-1.json"
    first.write_text('{"items":[{"id":"TXN001","amount":"1000","transDate":"2024-06-05"}]}')
    second = tmp_path / "page-2.json"
    second.write_text('{"items":[{"id":"TXN002","amount":"bad","transDate":"2024-06-05"}]}')
    pages = [
        SimpleNamespace(page=1, source_unit_key="unit-1", local_path=str(first)),
        SimpleNamespace(page=2, source_unit_key="unit-2", local_path=str(second)),
    ]
    raw_repo = SimpleNamespace(
        find_for_replay=AsyncMock(return_value=pages),
        materialize=AsyncMock(side_effect=lambda page, _destination: page.local_path),
    )
    packet = SimpleNamespace(
        id="pkt-stream-validation",
        source_file_path=None,
        raw_stage_key="stage-stream-validation",
        structure_signature={"firstDataRowIndex": 1},
        sample_preview=[
            {"rowIndex": 1, "values": ["TXN001", "1000", "2024-06-05"]},
        ],
        validation_gates=[],
    )
    config = MappingConfig.model_validate({
        "_id": "cfg-stream-validation",
        "partner": "MOMO",
        "workflowType": "UPC",
        "fileType": "SETTLEMENT",
        "sheetName": "Sheet1",
        "startRow": 1,
        "configVersion": "MOMO_stream_v1",
        "fieldMappings": [
            {"path": "id", "column": 1, "type": "STRING", "required": True},
            {"path": "amount", "column": 2, "type": "DECIMAL", "required": True},
            {"path": "transDate", "column": 3, "type": "DATE", "required": True},
            {"path": "currency", "type": "CONSTANT", "constant": "VND", "required": True},
            {"path": "status", "type": "CONSTANT", "constant": "SUCCESS", "required": True},
        ],
        "status": "PENDING_APPROVAL",
        "configHealth": {},
    })

    review_collection = MagicMock()
    review_collection.update_one = AsyncMock()
    with patch(
        "src.application.review.raw_stream.RawIngestionPageRepository",
        return_value=raw_repo,
    ):
        gate = await run_runtime_validation(
            _make_db(review_collection=review_collection), packet, config
        )

    assert gate["details"]["sampledRows"] == 2
    assert gate["details"]["successRows"] == 1
    assert gate["details"]["failedRows"] == 1


@pytest.mark.asyncio
async def test_runtime_validation_reads_file_level_packet_source(tmp_path):
    source = tmp_path / "settlement.csv"
    source.write_text("TXN001,1000,2024-06-05\nTXN002,2500,2024-06-05\n")
    packet = SimpleNamespace(
        id="pkt-file-validation",
        source_file_path=str(source),
        raw_stage_key=None,
        structure_signature={"firstDataRowIndex": 1},
        sample_preview=[],
        validation_gates=[],
    )
    config = MappingConfig.model_validate({
        "_id": "cfg-file-validation",
        "partner": "MOMO",
        "workflowType": "UPC",
        "fileType": "SETTLEMENT",
        "sheetName": "Sheet1",
        "startRow": 1,
        "configVersion": "MOMO_file_v1",
        "fieldMappings": [
            {"path": "id", "column": 1, "type": "STRING", "required": True},
            {"path": "amount", "column": 2, "type": "DECIMAL", "required": True},
            {"path": "transDate", "column": 3, "type": "DATE", "required": True},
            {"path": "currency", "type": "CONSTANT", "constant": "VND", "required": True},
            {"path": "status", "type": "CONSTANT", "constant": "SUCCESS", "required": True},
        ],
        "status": "PENDING_APPROVAL",
    })

    gate = await run_runtime_validation(
        _make_db(review_collection=MagicMock(update_one=AsyncMock())), packet, config
    )

    assert gate["status"] == "pass"
    assert gate["details"]["sampledRows"] == 2
    assert gate["details"]["successRows"] == 2


@pytest.mark.asyncio
async def test_runtime_validation_preserves_object_rows_for_source_field_mapping(tmp_path):
    first = tmp_path / "page-1.json"
    first.write_text('{"items":[{"id":"VTP-001","amount":"1000","status":"SUCCESS"}]}')
    raw_repo = SimpleNamespace(
        find_for_replay=AsyncMock(return_value=[SimpleNamespace(page=1, source_unit_key="unit-1", local_path=str(first))]),
        materialize=AsyncMock(side_effect=lambda page, _destination: page.local_path),
    )
    packet = SimpleNamespace(
        id="pkt-object-mapping",
        source_file_path=None,
        raw_stage_key="stage-object-mapping",
        structure_signature={"firstDataRowIndex": 1},
        sample_preview=[],
        validation_gates=[],
    )
    config = MappingConfig.model_validate({
        "_id": "cfg-object-mapping",
        "partner": "VIETTELPAY",
        "workflowType": "UPC",
        "fileType": "SETTLEMENT",
        "sheetName": "JSON",
        "startRow": 1,
        "fieldMappings": [
            {"path": "id", "sourceField": "id", "type": "STRING", "required": True},
            {"path": "amount", "sourceField": "amount", "type": "DECIMAL", "required": True},
            {"path": "status", "sourceField": "status", "type": "MAPPING", "mapping": {"SUCCESS": "SUCCESS"}, "required": True},
            {"path": "currency", "type": "CONSTANT", "constant": "VND", "required": True},
        ],
        "status": "PENDING_APPROVAL",
    })

    with patch("src.application.review.raw_stream.RawIngestionPageRepository", return_value=raw_repo):
        gate = await run_runtime_validation(
            _make_db(review_collection=MagicMock(update_one=AsyncMock())), packet, config
        )

    assert gate["status"] == "pass"
    assert gate["details"]["successRows"] == 1
