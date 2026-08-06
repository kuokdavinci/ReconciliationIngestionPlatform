"""Architecture checks for the review workflow bounded context."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.config_health import _create_mapping_proposal

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
            sig=signature,
            partner="MOMO",
            workflow_type="UPC",
            file_type=MagicMock(value="SETTLEMENT"),
            config_repo=config_repo,
            action_repo=action_repo,
            config_version="v1",
            reason="new source file",
            source_file_name="settlement_MOMO_phase2.xlsx",
            source_file_id="new-file-001",
            source_file_path="/tmp/settlement_MOMO_phase2.xlsx",
            reconciliation_date=datetime(2026, 8, 6, tzinfo=timezone.utc),
        )

    assert result == (pending_config, existing_action)
    packet_repo.update_one.assert_awaited_once()
    query, update = packet_repo.update_one.await_args.args
    assert query == {"_id": "packet-001", "status": "PENDING"}
    assert update["sourceFileId"] == "new-file-001"
    assert update["sourceFilePath"] == "/tmp/settlement_MOMO_phase2.xlsx"
