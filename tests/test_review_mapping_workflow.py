"""Application tests for review-packet mapping workflows."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.application.review.errors import ReviewValidationError
from src.application.review.mapping_workflow import ReviewMappingWorkflow
from src.application.review.scope_classification import (
    ScopeClassificationCommand,
    ScopeClassificationService,
)
from src.domain.review.models import (
    ReviewDecisionMode,
    ReviewPacket,
    ReviewPacketSourceType,
    ReviewPacketStatus,
)
from src.core.enums import FileType


def _packet(*, packet_id="packet-1", status=ReviewPacketStatus.PENDING, gates=None):
    return ReviewPacket(
        _id=packet_id,
        sourceType=ReviewPacketSourceType.UPLOAD,
        partner="MOMO",
        fileName="settlement.json",
        fileTypeDetected=FileType.SETTLEMENT.value,
        structureSignature={
            "headers": ["transaction_id", "amount"],
            "sampleRows": [["TX-1", "100"]],
            "headerRowIndex": 0,
            "firstDataRowIndex": 1,
        },
        draftMappingId="draft-1",
        validationGates=gates or [],
        status=status,
    )


def _mapping_repo(existing=None):
    repo = MagicMock()
    repo.find_one = AsyncMock(return_value=existing)
    repo.find_by_partner_and_type = AsyncMock(return_value=None)
    repo.allocate_next_version = AsyncMock(return_value="MOMO_v03")
    repo.create = AsyncMock()
    repo.update_pending_draft = AsyncMock()
    return repo


def _workflow(*, packet, existing=None, context=None, generator=None, **overrides):
    packet_repo = MagicMock()
    packet_repo.find_one = AsyncMock(return_value=packet)
    packet_repo.update_mapping_draft = AsyncMock()
    mapping_repo = _mapping_repo(existing)
    context_resolver = AsyncMock(
        return_value=context
        or {
            "headers": ["transaction_id", "amount"],
            "sample_rows": [["TX-1", "100"]],
            "header_row_index": 0,
            "first_data_row_index": 1,
        }
    )
    generator = generator or AsyncMock(
        return_value=(
            {
                "sheetName": "Sheet1",
                "startRow": 2,
                "fieldMappings": [
                    {"path": "id", "column": 1, "type": "STRING", "required": True},
                    {"path": "amount", "column": 2, "type": "DECIMAL"},
                ],
            },
            None,
        )
    )
    return ReviewMappingWorkflow(
        db=MagicMock(),
        packet_repo=packet_repo,
        mapping_repo=mapping_repo,
        context_resolver=context_resolver,
        config_generator=generator,
        **overrides,
    ), packet_repo, mapping_repo, context_resolver, generator


@pytest.mark.asyncio
async def test_generate_rejects_packet_without_header_evidence():
    workflow, _packet_repo, _mapping_repo_instance, context_resolver, generator = _workflow(
        packet=_packet(),
        context={"headers": [], "sample_rows": [], "header_row_index": None, "first_data_row_index": None},
    )

    with pytest.raises(ReviewValidationError, match="header signature"):
        await workflow.generate("packet-1")

    generator.assert_not_awaited()
    context_resolver.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_canonicalizes_json_mapping_and_invalidates_runtime_gate():
    packet = _packet(
        gates=[
            {"gateKey": "runtime_validation", "status": "pass"},
            {"gateKey": "structure_signature", "status": "pass"},
        ]
    )
    workflow, packet_repo, mapping_repo, _context_resolver, generator = _workflow(packet=packet)

    result = await workflow.generate("packet-1", force=True)

    assert result["ok"] is True
    assert result["mapping"]["fieldMappings"][0]["path"] == "id"
    mapping_repo.create.assert_awaited_once()
    packet_repo.update_mapping_draft.assert_awaited_once()
    packet_update = packet_repo.update_mapping_draft.await_args.kwargs
    assert all(gate["gateKey"] != "runtime_validation" for gate in packet_update["validation_gates"])
    generator.assert_awaited_once()


@pytest.mark.asyncio
async def test_approve_activate_requires_a_passing_runtime_gate_and_delegates_action():
    packet = _packet(gates=[{"gateKey": "runtime_validation", "status": "fail"}])
    approve_action = AsyncMock()
    mark_packet = AsyncMock(return_value={"ok": True, "packet": {"_id": "packet-1"}})
    workflow, _packet_repo, _mapping_repo_instance, _context, _generator = _workflow(
        packet=packet,
        approve_activate_action=approve_action,
        mark_packet=mark_packet,
        update_packet_scope=AsyncMock(),
    )

    with pytest.raises(ReviewValidationError, match="Runtime validation"):
        await workflow.approve_activate("packet-1", actor="reviewer@example.com")
    approve_action.assert_not_awaited()

    packet.validation_gates = [{"gateKey": "runtime_validation", "status": "pass"}]
    approve_action.return_value = {"postApproveRun": {"_id": "run-1"}}
    result = await workflow.approve_activate(
        "packet-1",
        actor="reviewer@example.com",
        scope_type="FULL_SNAPSHOT",
    )

    assert result["ok"] is True
    approve_action.assert_awaited_once()
    mark_packet.assert_awaited_once()
    assert mark_packet.await_args.args[3] is ReviewDecisionMode.APPROVE_ACTIVATE_NEXT_RUNTIME


@pytest.mark.asyncio
async def test_approve_activate_retries_approved_backfill_packet_idempotently():
    packet = _packet(
        status=ReviewPacketStatus.APPROVED,
        gates=[{"gateKey": "runtime_validation", "status": "pass"}],
    )
    packet.backfill_run_id = "backfill-001"
    packet.decision_mode = ReviewDecisionMode.APPROVE_ACTIVATE_NEXT_RUNTIME
    approve_action = AsyncMock(return_value={"backfillRun": {"_id": "backfill-001"}})
    mark_packet = AsyncMock()
    workflow, _packet_repo, _mapping_repo_instance, _context, _generator = _workflow(
        packet=packet,
        approve_activate_action=approve_action,
        mark_packet=mark_packet,
        update_packet_scope=AsyncMock(),
    )

    result = await workflow.approve_activate("packet-1", actor="reviewer@example.com")

    assert result["ok"] is True
    assert result["backfillRun"] == {"_id": "backfill-001"}
    approve_action.assert_awaited_once()
    mark_packet.assert_not_awaited()


@pytest.mark.asyncio
async def test_save_rejects_invalid_mapping_contract():
    workflow, _packet_repo, _mapping_repo_instance, _context, _generator = _workflow(packet=_packet())

    with pytest.raises(ReviewValidationError, match="incomplete or invalid"):
        await workflow.save(
            "packet-1",
            field_mappings=[{"path": "amount", "column": 2, "type": "DECIMAL"}],
            sheet_name="Sheet1",
            start_row=2,
        )


@pytest.mark.asyncio
async def test_scope_classification_persists_evidence_and_uses_key_overlap():
    packet_repo = MagicMock()
    packet_repo.find_one = AsyncMock(return_value=_packet(packet_id="packet-scope"))
    packet_repo.update_scope_evidence = AsyncMock()

    service = ScopeClassificationService(
        db=MagicMock(),
        packet_repo=packet_repo,
        internal_count_loader=AsyncMock(return_value=100),
        internal_evidence_builder=AsyncMock(return_value={"recordCount": 100, "sample": [{"id": "I-1"}]}),
        received_evidence_loader=AsyncMock(return_value=(3, {"TX-1", "TX-2", "TX-3"})),
        existing_keys_loader=AsyncMock(return_value={"TX-1", "TX-2"}),
        prior_file_count_loader=AsyncMock(return_value=1),
        llm_provider_factory=lambda _config: None,
    )

    result = await service.classify(ScopeClassificationCommand(packet_id="packet-scope"))

    assert result["ok"] is True
    assert result["suggestedScope"] == "REPLACEMENT"
    assert result["scopeEvidence"]["incomingUniqueBusinessKeyCount"] == 3
    assert result["scopeEvidence"]["duplicateBusinessKeyCount"] == 2
    assert result["scopeEvidence"]["duplicateRatio"] == pytest.approx(2 / 3)
    packet_repo.update_scope_evidence.assert_awaited_once()
