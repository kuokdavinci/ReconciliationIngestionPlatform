"""Application-level tests for mapping approval and proposal workflows."""

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.application.mapping.proposals import (
    CreateMappingProposalCommand,
    MappingProposalService,
)
from src.application.mapping.service import (
    ApproveMappingCommand,
    MappingApplicationService,
    RejectMappingCommand,
    SaveMappingCommand,
)
from src.core.enums import FileType
from src.domain.mapping.models import MappingConfig, MappingConfigStatus
from src.domain.review.models import (
    CopilotActionStatus,
    ReviewPacketStatus,
)


def _config(
    *,
    config_id: str,
    status: MappingConfigStatus,
    version: str = "MOMO_v01",
) -> MappingConfig:
    return MappingConfig(
        _id=config_id,
        partner="MOMO",
        workflowType="UPC",
        fileType=FileType.SETTLEMENT,
        sheetName="Sheet1",
        startRow=2,
        fieldMappings=[
            {"path": "id", "column": "A", "type": "STRING", "required": True},
        ],
        configVersion=version,
        status=status,
    )


def _mapping_dependencies(config: MappingConfig):
    mapping_repo = MagicMock()
    mapping_repo.find_one = AsyncMock(return_value=config)
    mapping_repo.find_by_partner_and_type = AsyncMock(return_value=None)
    mapping_repo.mark_approved = AsyncMock()
    mapping_repo.mark_rejected = AsyncMock()
    mapping_repo.mark_superseded = AsyncMock()
    mapping_repo.allocate_next_version = AsyncMock(return_value="MOMO_v03")
    mapping_repo.replace_approved = AsyncMock()
    mapping_repo.insert_approved = AsyncMock()

    action_repo = MagicMock()
    action_repo.sync_mapping_status = AsyncMock()
    packet_repo = MagicMock()
    packet_repo.sync_mapping_status = AsyncMock()
    audit = AsyncMock()
    cache = AsyncMock()
    return mapping_repo, action_repo, packet_repo, audit, cache


@pytest.mark.asyncio
async def test_approve_supersedes_current_mapping_and_tolerates_cache_failure():
    pending = _config(config_id="draft-2", status=MappingConfigStatus.PENDING_APPROVAL)
    current = _config(config_id="live-1", status=MappingConfigStatus.APPROVED, version="MOMO_v01")
    mapping_repo, action_repo, packet_repo, audit, cache = _mapping_dependencies(pending)
    mapping_repo.find_by_partner_and_type.return_value = current
    cache.side_effect = RuntimeError("cache is unavailable")
    approved_at = datetime(2026, 8, 13, tzinfo=timezone.utc)

    service = MappingApplicationService(
        mapping_repo=mapping_repo,
        action_repo=action_repo,
        review_packet_repo=packet_repo,
        audit_recorder=audit,
        cache_invalidator=cache,
        clock=lambda: approved_at,
    )

    result = await service.approve(
        ApproveMappingCommand(
            config_id="draft-2",
            actor="reviewer@example.com",
            confidence=0.91,
            reasoning="Verified against the sample file.",
        )
    )

    assert result.status is MappingConfigStatus.APPROVED
    assert result.config.approved_by == "reviewer@example.com"
    mapping_repo.mark_superseded.assert_awaited_once_with("live-1", "draft-2", approved_at)
    mapping_repo.mark_approved.assert_awaited_once()
    action_repo.sync_mapping_status.assert_awaited_once_with(
        "draft-2", CopilotActionStatus.APPROVED, "reviewer@example.com", approved_at
    )
    packet_repo.sync_mapping_status.assert_awaited_once_with(
        "draft-2", ReviewPacketStatus.APPROVED, approved_at
    )
    audit.assert_awaited_once()
    assert audit.await_args.kwargs["actor"] == "reviewer@example.com"
    assert audit.await_args.kwargs["action"] == "APPROVED"


@pytest.mark.asyncio
async def test_reject_marks_mapping_and_related_review_artifacts():
    pending = _config(config_id="draft-3", status=MappingConfigStatus.PENDING_APPROVAL)
    mapping_repo, action_repo, packet_repo, audit, cache = _mapping_dependencies(pending)
    rejected_at = datetime(2026, 8, 13, tzinfo=timezone.utc)

    service = MappingApplicationService(
        mapping_repo=mapping_repo,
        action_repo=action_repo,
        review_packet_repo=packet_repo,
        audit_recorder=audit,
        cache_invalidator=cache,
        clock=lambda: rejected_at,
    )

    result = await service.reject(
        RejectMappingCommand(config_id="draft-3", actor="reviewer@example.com")
    )

    assert result.status is MappingConfigStatus.REJECTED
    mapping_repo.mark_rejected.assert_awaited_once()
    action_repo.sync_mapping_status.assert_awaited_once_with(
        "draft-3", CopilotActionStatus.REJECTED, "reviewer@example.com", rejected_at
    )
    packet_repo.sync_mapping_status.assert_awaited_once_with(
        "draft-3", ReviewPacketStatus.REJECTED, rejected_at
    )
    audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_save_allocates_partner_version_and_uses_named_repository_method():
    config = _config(config_id="manual-1", status=MappingConfigStatus.PENDING_APPROVAL, version="latest")
    mapping_repo, action_repo, packet_repo, audit, cache = _mapping_dependencies(config)
    mapping_repo.find_one.return_value = None

    service = MappingApplicationService(
        mapping_repo=mapping_repo,
        action_repo=action_repo,
        review_packet_repo=packet_repo,
        audit_recorder=audit,
        cache_invalidator=cache,
        clock=lambda: datetime(2026, 8, 13, tzinfo=timezone.utc),
    )

    result = await service.save(SaveMappingCommand(config=config, actor="admin@example.com"))

    assert result.status is MappingConfigStatus.APPROVED
    assert result.config.config_version == "MOMO_v03"
    mapping_repo.allocate_next_version.assert_awaited_once_with("MOMO")
    mapping_repo.insert_approved.assert_awaited_once()
    cache.assert_awaited_once_with("MOMO", "")


@pytest.mark.asyncio
async def test_proposal_creates_pending_mapping_action_and_review_packet():
    signature = SimpleNamespace(
        headers=["transaction_id", "amount"],
        sample_rows=[["TX-1", "100"]],
        header_row_index=0,
        first_data_row_index=1,
        to_dict=lambda: {"headers": ["transaction_id", "amount"]},
    )
    mapping_repo = MagicMock()
    mapping_repo.allocate_next_version = AsyncMock(return_value="MOMO_v04")
    mapping_repo.create = AsyncMock()
    mapping_repo.find_by_partner_and_type = AsyncMock(return_value=None)
    action_repo = MagicMock()
    action_repo.create = AsyncMock()
    packet_repo = MagicMock()
    packet_repo.create = AsyncMock()

    async def generate(**_kwargs):
        return (
            {
                "sheetName": "Sheet1",
                "startRow": 2,
                "fieldMappings": [
                    {"path": "id", "column": "A", "type": "STRING", "required": True},
                    {"path": "amount", "column": "B", "type": "DECIMAL"},
                ],
                "confidence": 0.88,
                "reasoning": "The headers are unambiguous.",
            },
            None,
        )

    async def classify(**_kwargs):
        return {
            "scopeType": "FULL_SNAPSHOT",
            "scopeConfidence": 0.82,
            "scopeReason": ["First delivery."],
            "scopeSignals": {"sameDayFileCount": 0},
        }

    service = MappingProposalService(
        mapping_repo=mapping_repo,
        action_repo=action_repo,
        review_packet_repo=packet_repo,
        signature_builder=lambda _path: signature,
        config_generator=generate,
        scope_classifier=classify,
    )

    result = await service.create_from_source_file(
        CreateMappingProposalCommand(
            partner="MOMO",
            source_file_path=Path("/tmp/momo.xlsx"),
        )
    )

    assert result.response["configStatus"] == MappingConfigStatus.PENDING_APPROVAL.value
    assert result.response["draftMappingId"] == str(result.proposal.id)
    assert result.response["reviewItemId"] == str(result.packet.id)
    assert result.proposal.status is MappingConfigStatus.PENDING_APPROVAL
    mapping_repo.create.assert_awaited_once()
    action_repo.create.assert_awaited_once()
    packet_repo.create.assert_awaited_once()
