from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.application.review import proposal_creation
from src.application.review import reprocessing
from src.application.review.proposal_creation import build_review_packet
from src.core.enums import FileType
from src.domain.mapping.models import MappingConfig
from src.domain.review.models import ReviewPacketSourceType

ROOT = Path(__file__).resolve().parents[1]
REVIEW_ROOT = ROOT / "src" / "application" / "review"
COPILOT_ROOT = ROOT / "src" / "application" / "copilot"


def test_review_application_has_no_fastapi_or_api_dependency() -> None:
    assert REVIEW_ROOT.exists()
    source = "\n".join(path.read_text() for path in REVIEW_ROOT.glob("*.py"))

    assert "from fastapi" not in source
    assert "src.api" not in source
    assert "HTTPException" not in source
    assert "Request" not in source


def test_copilot_application_has_no_fastapi_or_api_dependency() -> None:
    assert COPILOT_ROOT.exists()
    source = "\n".join(path.read_text() for path in COPILOT_ROOT.glob("*.py"))

    assert "from fastapi" not in source
    assert "src.api" not in source
    assert "HTTPException" not in source
    assert "Request" not in source


def test_review_errors_are_transport_neutral() -> None:
    from src.application.review.errors import (
        ReviewConflictError,
        ReviewNotFoundError,
        ReviewUnavailableError,
        ReviewValidationError,
    )

    for error_type in (
        ReviewNotFoundError,
        ReviewConflictError,
        ReviewValidationError,
        ReviewUnavailableError,
    ):
        assert not hasattr(error_type, "status_code")


def test_config_health_delegates_review_artifact_creation_to_application() -> None:
    source = (ROOT / "src" / "config" / "config_health.py").read_text()

    assert "src.application.review.proposal_creation" in source
    assert "ReviewPacket(" not in source
    assert "CopilotAction(" not in source
    assert "from src.domain.review.models import" not in source
    assert "from src.infrastructure.review.repository import" not in source


def test_review_packets_router_delegates_studio_handoff_packet_creation_to_application() -> None:
    source = (ROOT / "src" / "api" / "review_packets.py").read_text()

    assert "create_studio_handoff_review_packet" in source
    assert "ReviewPacket(" not in source


def test_reprocessing_is_a_facade_for_replay_and_post_approval_lifecycle() -> None:
    source = (REVIEW_ROOT / "reprocessing.py").read_text()

    assert "staged_page_replay" in source
    assert "post_approval_reconciliation" in source
    assert "RawIngestionPageRepository(db)" not in source
    assert "build_reconciliation_service(db" not in source
    assert "async def reprocess_staged_pages" in source
    assert "async def reprocess_and_reconcile" in source


def test_review_packet_builder_preserves_source_metadata() -> None:
    packet = build_review_packet(
        source_type=ReviewPacketSourceType.SCHEDULER_JOB.value,
        partner="MOMO",
        file_name="momo-page-1.json",
        file_type=FileType.SETTLEMENT,
        fields={"rawStageKey": "momo:2026-08-14", "sourceFilePath": "/tmp/page.json"},
    )

    assert packet.file_name == "momo-page-1.json"
    assert packet.raw_stage_key == "momo:2026-08-14"
    assert packet.source_file_path == "/tmp/page.json"


@pytest.mark.asyncio
async def test_reprocessing_facade_forwards_legacy_builder_patch_points() -> None:
    pipeline = object()
    config_loader = object()
    reconciliation = object()
    facade_result = {"ok": True}

    with patch(
        "src.application.review.reprocessing._reconcile_approved_packet",
        new=AsyncMock(return_value=facade_result),
    ) as reconcile:
        with patch.object(reprocessing, "build_ingestion_pipeline", pipeline), patch.object(
            reprocessing, "build_config_loader", config_loader
        ), patch.object(reprocessing, "build_reconciliation_service", reconciliation):
            result = await reprocessing.reprocess_and_reconcile(
                object(),
                object(),
                object(),
                "run-001",
            )

    assert result == facade_result
    assert reconcile.await_args.kwargs["pipeline_builder"] is pipeline
    assert reconcile.await_args.kwargs["config_loader_builder"] is config_loader
    assert reconcile.await_args.kwargs["reconciliation_service_builder"] is reconciliation


@pytest.mark.asyncio
async def test_create_studio_handoff_review_packet_preserves_route_fields() -> None:
    class InMemoryPacketRepo:
        def __init__(self) -> None:
            self.created_packet = None

        async def create(self, packet):
            self.created_packet = packet
            return packet

    mapping = MappingConfig(
        _id="mapping-123",
        partner="MOMO",
        workflowType="UPC",
        fileType=FileType.SETTLEMENT,
        sheetName="Studio Sheet",
        startRow=4,
        fieldMappings=[
            {"path": "id", "column": "A", "type": "STRING", "required": True},
            {"path": "amount", "column": "B", "type": "DECIMAL", "required": True},
            {"path": "currency", "type": "CONSTANT", "constant": "VND"},
        ],
        structureSignature={"columns": ["id", "amount", "currency"]},
    )
    repo = InMemoryPacketRepo()

    packet = await proposal_creation.create_studio_handoff_review_packet(
        mapping=mapping,
        mapping_id="mapping-123",
        packet_repo=repo,
    )

    assert repo.created_packet is packet
    assert packet.source_type == ReviewPacketSourceType.STUDIO_HANDOFF
    assert packet.partner == "MOMO"
    assert packet.draft_mapping_id == "mapping-123"
    assert packet.file_name == "Studio Sheet"
    assert packet.parse_strategy == {
        "sheetName": "Studio Sheet",
        "startRow": 4,
        "fieldMappingCount": 3,
    }
    assert packet.risk_summary == {
        "severity": "medium",
        "summary": "Draft mapping handed off from Mapping Studio for review.",
    }
    assert packet.recommended_action == {
        "actionType": "APPROVE_REQUIRED_BEFORE_RUNTIME",
        "reason": "Draft mapping ready for review and approval.",
    }
