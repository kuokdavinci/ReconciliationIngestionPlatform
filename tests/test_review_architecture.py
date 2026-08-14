"""Architecture checks for the review workflow bounded context."""

from datetime import datetime, timezone
import json
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.config_health import _collect_review_sample_rows, _create_mapping_proposal
from src.config.signature import StructureSignature
from src.core.enums import FileType
from src.application.review.actions import (
    _rebind_replacement_transactions,
    approve_packet_mapping_and_reprocess,
)
from src.domain.mapping.models import MappingConfigStatus

from src.domain.review.models import (
    CopilotAction,
    CopilotActionStatus,
    CopilotActionType,
    PostApprovalRun,
    PostApprovalRunStage,
    PostApprovalRunStatus,
    ReconciliationReviewNote,
    ReconciliationReviewRecord,
    ReviewDecisionMode,
    ReviewPacket,
    ReviewPacketSourceType,
    ReviewPacketStatus,
)
from src.infrastructure.review.repository import (
    CopilotActionRepository,
    PostApprovalRunRepository,
    ReconciliationReviewRecordRepository,
    ReviewPacketRepository,
)


class _Cursor:
    def __init__(self, documents):
        self._documents = documents

    def sort(self, *_args, **_kwargs):
        return self

    async def to_list(self, length=None):
        return self._documents


class _SourceFileCollection:
    def __init__(self, documents):
        self._documents = documents

    def find(self, *_args, **_kwargs):
        return _Cursor(self._documents)


class _Database:
    def __init__(self, source_files):
        self._collections = {"reconciliation_file": _SourceFileCollection(source_files)}

    def __getitem__(self, name):
        return self._collections[name]


@pytest.mark.asyncio
async def test_approved_mapping_still_resumes_waiting_backfill() -> None:
    mapping_repo = MagicMock()
    mapping_repo.find_one = AsyncMock(
        return_value=SimpleNamespace(
            id="mapping-v1",
            partner="VNPAY",
            workflow_type="UPC",
            file_type=FileType.SETTLEMENT,
            status=MappingConfigStatus.APPROVED,
            config_version="VNPAY_v01",
            config_health={},
        )
    )
    mapping_repo.find_by_partner_and_type = AsyncMock(return_value=None)
    mapping_repo.collection.update_one = AsyncMock()
    backfill_service = MagicMock()
    backfill_service.resume_after_approval = AsyncMock(
        return_value=SimpleNamespace(id="backfill-001")
    )
    packet = SimpleNamespace(
        draft_mapping_id="mapping-v1",
        backfill_run_id="backfill-001",
    )

    with patch(
        "src.application.review.actions.MappingConfigRepository",
        return_value=mapping_repo,
    ), patch(
        "src.application.review.actions.BackfillRunService",
        return_value=backfill_service,
    ), patch(
        "src.application.review.actions.serialize_backfill_run",
        return_value={"_id": "backfill-001", "status": "QUEUED"},
    ):
        result = await approve_packet_mapping_and_reprocess(
            db=MagicMock(),
            packet=packet,
            reviewed_by="reviewer@example.com",
            schedule_background=lambda _awaitable: None,
            workflow_gateway=MagicMock(),
        )

    assert result == {
        "backfillRun": {"_id": "backfill-001", "status": "QUEUED"}
    }
    backfill_service.resume_after_approval.assert_awaited_once_with(
        backfill_run_id="backfill-001",
        mapping_version="VNPAY_v01",
    )


@pytest.mark.asyncio
async def test_mapping_status_sync_does_not_close_backfill_packet() -> None:
    collection = MagicMock()
    collection.update_many = AsyncMock(return_value=SimpleNamespace(modified_count=1))
    repository = object.__new__(ReviewPacketRepository)
    repository.collection = collection

    changed = await repository.sync_mapping_status(
        "mapping-v1",
        ReviewPacketStatus.APPROVED,
        datetime(2026, 8, 13, tzinfo=timezone.utc),
    )

    assert changed == 1
    query = collection.update_many.await_args.args[0]
    assert query["backfillRunId"] == {"$exists": False}


@pytest.mark.asyncio
async def test_replacement_rebinds_duplicate_ingestion_keys_to_new_source_file():
    repository = MagicMock()
    repository.rebind_source_file_by_ingestion_keys = AsyncMock(return_value=30)
    packet = SimpleNamespace(scope_type="REPLACEMENT")
    config = SimpleNamespace(partner="MOMO")
    ingestion_result = SimpleNamespace(
        ingestion_keys=["MOMO_TXN_9000", "MOMO_TXN_9000", "MOMO_TXN_9100"],
    )

    with patch(
        "src.application.review.actions.DataContainerRepository",
        return_value=repository,
    ):
        rebound = await _rebind_replacement_transactions(
            db=MagicMock(),
            packet=packet,
            config=config,
            ingestion_result=ingestion_result,
            source_file_id="replacement-file",
        )

    assert rebound == 30
    repository.rebind_source_file_by_ingestion_keys.assert_awaited_once_with(
        "MOMO",
        ["MOMO_TXN_9000", "MOMO_TXN_9100"],
        "replacement-file",
    )
from src.models.copilot_action import (
    CopilotAction as LegacyCopilotAction,
    CopilotActionRepository as LegacyCopilotActionRepository,
    CopilotActionStatus as LegacyCopilotActionStatus,
    CopilotActionType as LegacyCopilotActionType,
)
from src.models.post_approval_run import (
    PostApprovalRun as LegacyPostApprovalRun,
    PostApprovalRunRepository as LegacyPostApprovalRunRepository,
    PostApprovalRunStage as LegacyPostApprovalRunStage,
    PostApprovalRunStatus as LegacyPostApprovalRunStatus,
)
from src.models.reconciliation_review_record import (
    ReconciliationReviewNote as LegacyReconciliationReviewNote,
    ReconciliationReviewRecord as LegacyReconciliationReviewRecord,
    ReconciliationReviewRecordRepository as LegacyReconciliationReviewRecordRepository,
)
from src.models.review_packet import (
    ReviewDecisionMode as LegacyReviewDecisionMode,
    ReviewPacket as LegacyReviewPacket,
    ReviewPacketRepository as LegacyReviewPacketRepository,
    ReviewPacketSourceType as LegacyReviewPacketSourceType,
    ReviewPacketStatus as LegacyReviewPacketStatus,
)


def test_legacy_review_modules_are_compatibility_facades() -> None:
    """Legacy imports must resolve to domain and infrastructure implementations."""

    assert LegacyPostApprovalRun is PostApprovalRun
    assert LegacyPostApprovalRunRepository is PostApprovalRunRepository
    assert LegacyPostApprovalRunStage is PostApprovalRunStage
    assert LegacyPostApprovalRunStatus is PostApprovalRunStatus
    assert LegacyReconciliationReviewNote is ReconciliationReviewNote
    assert LegacyReconciliationReviewRecord is ReconciliationReviewRecord
    assert LegacyReconciliationReviewRecordRepository is ReconciliationReviewRecordRepository
    assert LegacyReviewPacket is ReviewPacket
    assert LegacyReviewPacketRepository is ReviewPacketRepository
    assert LegacyReviewPacketSourceType is ReviewPacketSourceType
    assert LegacyReviewPacketStatus is ReviewPacketStatus
    assert LegacyReviewDecisionMode is ReviewDecisionMode
    assert LegacyCopilotAction is CopilotAction
    assert LegacyCopilotActionRepository is CopilotActionRepository
    assert LegacyCopilotActionStatus is CopilotActionStatus
    assert LegacyCopilotActionType is CopilotActionType


@pytest.mark.asyncio
async def test_reused_pending_review_packet_tracks_latest_source_file() -> None:
    pending_config = SimpleNamespace(
        id="mapping-001",
        config_health={"confidence": 0.8},
    )
    existing_action = SimpleNamespace(id="action-001")
    existing_packet = SimpleNamespace(id="packet-001")
    signature = SimpleNamespace(
        sample_rows=[["new-row"]],
        to_dict=MagicMock(return_value={"sampleRows": [["new-row"]]}),
    )
    config_repo = MagicMock(collection=SimpleNamespace(database=MagicMock()))
    config_repo.find_latest_pending_by_partner_and_type = AsyncMock(return_value=pending_config)
    action_repo = MagicMock()
    action_repo.find_one = AsyncMock(return_value=existing_action)
    packet_repo = MagicMock()
    packet_repo.find_latest_by_proposal = AsyncMock(return_value=existing_packet)
    packet_repo.update_one = AsyncMock(return_value=True)

    with patch(
        "src.config.config_health.CopilotActionRepository",
        return_value=action_repo,
    ), patch(
        "src.config.config_health.ReviewPacketRepository",
        return_value=packet_repo,
    ), patch(
        "src.config.config_health.classify_scope",
        new=AsyncMock(
            return_value={
                "scopeType": "INCREMENTAL_APPEND",
                "scopeConfidence": 0.9,
                "scopeReason": [],
                "scopeSignals": {},
            }
        ),
    ):
        result = await _create_mapping_proposal(
            sig=cast(StructureSignature, signature),
            partner="MOMO",
            workflow_type="UPC",
            file_type=FileType.SETTLEMENT,
            config_repo=config_repo,
            action_repo=action_repo,
            config_version="v1",
            reason="new source file",
            source_file_name="settlement_MOMO_phase2.xlsx",
            source_file_id="new-file-001",
            source_file_path="/tmp/settlement_MOMO_phase2.xlsx",
            reconciliation_date=datetime(2026, 8, 6, tzinfo=timezone.utc),
            backfill_run_id="backfill-001",
        )

    assert result == (pending_config, existing_action)
    packet_repo.update_one.assert_awaited_once()
    query, update = packet_repo.update_one.await_args.args
    assert query == {"_id": "packet-001", "status": "PENDING"}
    assert update["sourceFileId"] == "new-file-001"
    assert update["sourceFilePath"] == "/tmp/settlement_MOMO_phase2.xlsx"
    assert update["backfillRunId"] == "backfill-001"


@pytest.mark.asyncio
async def test_review_sample_aggregates_all_persisted_api_pages(tmp_path) -> None:
    page_paths = []
    source_files = []
    for page in range(1, 4):
        path = tmp_path / f"page-{page}.json"
        path.write_text(
            json.dumps(
                [
                    {"id": f"VTP-{page * 2 - 1:03d}", "amount": page * 100},
                    {"id": f"VTP-{page * 2:03d}", "amount": page * 100 + 1},
                ]
            ),
            encoding="utf-8",
        )
        page_paths.append(str(path))
        source_files.append({"fetchUnitMetadata": {"localPath": str(path)}})

    rows = await _collect_review_sample_rows(
        database=_Database(source_files),
        partner="VIETTELPAY",
        reconciliation_date=datetime(2026, 8, 10, tzinfo=timezone.utc),
        current_file_path=page_paths[-1],
        current_rows=[["VTP-005", "300"], ["VTP-006", "301"]],
    )

    assert len(rows) == 6
    assert [row[0] for row in rows] == [
        "VTP-001",
        "VTP-002",
        "VTP-003",
        "VTP-004",
        "VTP-005",
        "VTP-006",
    ]


@pytest.mark.asyncio
async def test_review_sample_uses_persisted_metadata_after_file_cleanup() -> None:
    rows = await _collect_review_sample_rows(
        database=_Database(
            [
                {"fetchUnitMetadata": {"sampleRows": [{"id": "VTP-001"}, {"id": "VTP-002"}]}},
                {"fetchUnitMetadata": {"sampleRows": [{"id": "VTP-003"}, {"id": "VTP-004"}]}},
                {"fetchUnitMetadata": {"sampleRows": [{"id": "VTP-005"}, {"id": "VTP-006"}]}},
            ]
        ),
        partner="VIETTELPAY",
        reconciliation_date=datetime(2026, 8, 10, tzinfo=timezone.utc),
        current_file_path=None,
        current_rows=[["VTP-006"]],
    )

    assert [row[0] for row in rows] == [
        "VTP-001",
        "VTP-002",
        "VTP-003",
        "VTP-004",
        "VTP-005",
        "VTP-006",
    ]


@pytest.mark.asyncio
async def test_new_review_packet_keeps_all_page_samples(tmp_path) -> None:
    page_paths = []
    source_files = []
    for page in range(1, 4):
        path = tmp_path / f"packet-page-{page}.json"
        path.write_text(
            json.dumps([
                {"id": f"VTP-{page * 2 - 1:03d}"},
                {"id": f"VTP-{page * 2:03d}"},
            ]),
            encoding="utf-8",
        )
        page_paths.append(str(path))
        source_files.append({"fetchUnitMetadata": {"localPath": str(path)}})

    database = _Database(source_files)
    config_repo = MagicMock(collection=SimpleNamespace(database=database))
    config_repo.find_latest_pending_by_partner_and_type = AsyncMock(return_value=None)
    config_repo.create = AsyncMock()
    config_repo.find_by_partner_and_type = AsyncMock(return_value=None)
    action_repo = MagicMock()
    action_repo.create = AsyncMock()
    packet_repo = MagicMock()
    packet_repo.create = AsyncMock()
    signature = StructureSignature(
        headers=["id"],
        column_count=1,
        sample_rows=[["VTP-005"], ["VTP-006"]],
        hash="hash",
        first_data_row_index=1,
    )

    with patch(
        "src.config.config_health.CopilotActionRepository",
        return_value=action_repo,
    ), patch(
        "src.config.config_health.ReviewPacketRepository",
        return_value=packet_repo,
    ), patch(
        "src.config.config_health.classify_scope",
        new=AsyncMock(
            return_value={
                "scopeType": "FULL_SNAPSHOT",
                "scopeConfidence": 0.9,
                "scopeReason": [],
                "scopeSignals": {},
            }
        ),
    ):
        await _create_mapping_proposal(
            sig=signature,
            partner="VIETTELPAY",
            workflow_type="UPC",
            file_type=FileType.SETTLEMENT,
            config_repo=config_repo,
            action_repo=action_repo,
            config_version="v1",
            reason="No approved config found",
            source_file_name="api_data_page_0003.json",
            source_file_id="page-3",
            source_file_path=page_paths[-1],
            reconciliation_date=datetime(2026, 8, 10, tzinfo=timezone.utc),
            backfill_run_id="backfill-001",
        )

    packet = packet_repo.create.await_args.args[0]
    assert packet.backfill_run_id == "backfill-001"
    assert len(packet.sample_preview) == 6
    assert [row["values"][0] for row in packet.sample_preview] == [
        "VTP-001",
        "VTP-002",
        "VTP-003",
        "VTP-004",
        "VTP-005",
        "VTP-006",
    ]


@pytest.mark.asyncio
async def test_retry_reuses_pending_packet_for_same_raw_stage_key() -> None:
    reused_proposal = SimpleNamespace(id="mapping-001")
    reused_action = SimpleNamespace(id="action-001")
    staged_packet = SimpleNamespace(
        id="packet-001",
        draft_mapping_id="mapping-001",
        target_action_id="action-001",
    )
    signature = SimpleNamespace(
        sample_rows=[["new-row"]],
        to_dict=MagicMock(return_value={"sampleRows": [["new-row"]]}),
    )
    config_repo = MagicMock(collection=SimpleNamespace(database=MagicMock()))
    config_repo.find_latest_pending_by_partner_and_type = AsyncMock(return_value=None)
    config_repo.find_one = AsyncMock(return_value=reused_proposal)
    action_repo = MagicMock()
    action_repo.find_one = AsyncMock(return_value=reused_action)
    packet_repo = MagicMock()
    packet_repo.find_latest_pending_by_stage = AsyncMock(return_value=staged_packet)
    packet_repo.update_one = AsyncMock(return_value=True)

    with patch(
        "src.config.config_health.CopilotActionRepository",
        return_value=action_repo,
    ), patch(
        "src.config.config_health.ReviewPacketRepository",
        return_value=packet_repo,
    ), patch(
        "src.config.config_health.classify_scope",
        new=AsyncMock(
            return_value={
                "scopeType": "FULL_SNAPSHOT",
                "scopeConfidence": 0.9,
                "scopeReason": [],
                "scopeSignals": {},
            }
        ),
    ):
        result = await _create_mapping_proposal(
            sig=cast(StructureSignature, signature),
            partner="VIETTELPAY",
            workflow_type="UPC",
            file_type=FileType.SETTLEMENT,
            config_repo=config_repo,
            action_repo=action_repo,
            config_version="v1",
            reason="retry",
            reconciliation_date=datetime(2026, 8, 10, tzinfo=timezone.utc),
            raw_stage_key="VIETTELPAY:API:stage-2026-08-10",
        )

    assert result == (reused_proposal, reused_action)
    config_repo.create.assert_not_called()
    action_repo.create.assert_not_called()
    packet_repo.create.assert_not_called()
    packet_repo.update_one.assert_awaited_once()
