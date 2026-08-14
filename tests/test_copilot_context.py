"""Tests for CopilotContextService compact decision-mode fields."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.application.copilot.context import CopilotContextService


def _make_mock_repo(find_many_result=None):
    """Create a mock repository with configurable find_many."""
    repo = MagicMock()
    repo.find_many = AsyncMock(return_value=find_many_result or [])
    return repo


def _mapping(
    *,
    status: str = "APPROVED",
    config_id: str = "cfg-001",
    created: str = "2026-06-01T00:00:00+00:00",
    version: str = "v1",
):
    obj = SimpleNamespace()
    obj.id = config_id
    obj.partner = "MOMO"
    obj.workflow_type = "UPC"
    obj.file_type = "SETTLEMENT"
    obj.sheet_name = "Sheet1"
    obj.start_row = 2
    obj.field_mappings = []
    obj.config_version = version
    obj.status = status
    obj.config_health = {"confidence": 1.0, "reasoning": "Ready."}
    obj.created_at = created
    obj.approved_at = created
    return obj


def _file(
    *,
    status: str = "COMPLETED",
    failed_rows: int = 0,
    file_id: str | None = None,
):
    obj = SimpleNamespace()
    obj.id = file_id or str(uuid4())
    obj.partner = "MOMO"
    obj.file_name = "settlement_MOMO_20260605.xlsx"
    obj.file_hash = "hash-001"
    obj.file_type = "SETTLEMENT"
    obj.reconciliation_date = "2026-06-05T00:00:00+00:00"
    obj.processing_status = status
    obj.total_rows = 100
    obj.success_rows = 100 - failed_rows
    obj.failed_rows = failed_rows
    obj.config_version = "v1"
    obj.uploaded_at = "2026-06-05T01:00:00+00:00"
    obj.created_at = "2026-06-05T01:00:00+00:00"
    return obj


def _packet(packet_id: str = "pkt-001"):
    obj = SimpleNamespace()
    obj.id = packet_id
    obj.source_type = "SCHEDULER_JOB"
    obj.partner = "MOMO"
    obj.file_name = "settlement_MOMO_20260605.xlsx"
    obj.file_type_detected = "SETTLEMENT"
    obj.proposal_config_id = "cfg-002"
    obj.recommended_action = {"actionType": "APPROVE_AND_ACTIVATE_NEXT_RUNTIME", "reason": "Structure changed."}
    obj.parse_strategy = {}
    obj.validation_gates = []
    obj.sample_preview = []
    obj.risk_summary = {"severity": "medium", "summary": "Structure changed."}
    obj.status = "PENDING"
    obj.created_at = "2026-06-05T01:05:00+00:00"
    return obj


@pytest.fixture
def healthy_setup():
    """Setup: approved runtime, completed file, no pending review."""
    mapping_repo = _make_mock_repo([_mapping()])
    file_repo = _make_mock_repo([_file()])
    packet_repo = _make_mock_repo([])
    service = CopilotContextService(MagicMock())
    service.mapping_repo = mapping_repo
    service.file_repo = file_repo
    service.packet_repo = packet_repo
    return service


@pytest.fixture
def monitor_setup():
    """Setup: approved runtime, file with failed status."""
    mapping_repo = _make_mock_repo([_mapping()])
    file_repo = _make_mock_repo([_file(status="FAILED", failed_rows=10)])
    packet_repo = _make_mock_repo([])
    service = CopilotContextService(MagicMock())
    service.mapping_repo = mapping_repo
    service.file_repo = file_repo
    service.packet_repo = packet_repo
    return service


@pytest.fixture
def needs_review_packet_setup():
    """Setup: approved runtime, failed file, pending review packet."""
    mapping_repo = _make_mock_repo([_mapping(), _mapping(status="PENDING_APPROVAL", config_id="cfg-002")])
    file_repo = _make_mock_repo([_file(status="FAILED", failed_rows=100)])
    packet_repo = _make_mock_repo([_packet()])
    service = CopilotContextService(MagicMock())
    service.mapping_repo = mapping_repo
    service.file_repo = file_repo
    service.packet_repo = packet_repo
    return service


@pytest.fixture
def needs_review_draft_setup():
    """Setup: no runtime, pending draft mapping, no packet."""
    mapping_repo = _make_mock_repo([_mapping(status="PENDING_APPROVAL", config_id="cfg-002")])
    file_repo = _make_mock_repo([_file(status="FAILED")])
    packet_repo = _make_mock_repo([])
    service = CopilotContextService(MagicMock())
    service.mapping_repo = mapping_repo
    service.file_repo = file_repo
    service.packet_repo = packet_repo
    return service


@pytest.fixture
def blocked_setup():
    """Setup: no runtime, no drafts, no packets."""
    mapping_repo = _make_mock_repo([])
    file_repo = _make_mock_repo([_file(status="FAILED")])
    packet_repo = _make_mock_repo([])
    service = CopilotContextService(MagicMock())
    service.mapping_repo = mapping_repo
    service.file_repo = file_repo
    service.packet_repo = packet_repo
    return service


# --- _summary tests ---

@pytest.mark.asyncio
async def test_summary_healthy(healthy_setup):
    ctx = await healthy_setup.context(partner="MOMO", date="2026-06-05")
    assert ctx["summary"] == "Runtime is ready and no action is required."


@pytest.mark.asyncio
async def test_summary_monitor(monitor_setup):
    ctx = await monitor_setup.context(partner="MOMO", date="2026-06-05")
    assert ctx["summary"] == "Latest file needs monitoring, but approved runtime remains available."


@pytest.mark.asyncio
async def test_summary_needs_review(needs_review_packet_setup):
    ctx = await needs_review_packet_setup.context(partner="MOMO", date="2026-06-05")
    assert ctx["summary"] == "A review item is waiting before runtime changes can be approved."


@pytest.mark.asyncio
async def test_summary_blocked(blocked_setup):
    ctx = await blocked_setup.context(partner="MOMO", date="2026-06-05")
    assert ctx["summary"] == "No approved runtime is available."


# --- _reasons tests ---

@pytest.mark.asyncio
async def test_reasons_count(healthy_setup):
    ctx = await healthy_setup.context(partner="MOMO", date="2026-06-05")
    reasons = ctx["reasons"]
    assert isinstance(reasons, list)
    assert 1 <= len(reasons) <= 3


@pytest.mark.asyncio
async def test_reasons_healthy(healthy_setup):
    ctx = await healthy_setup.context(partner="MOMO", date="2026-06-05")
    reasons = ctx["reasons"]
    assert any("approved runtime config is active" in r.lower() for r in reasons)
    assert any("no mapping review action" in r.lower() for r in reasons)
    assert any("no blocking processing failure" in r.lower() for r in reasons)


@pytest.mark.asyncio
async def test_reasons_blocked(blocked_setup):
    ctx = await blocked_setup.context(partner="MOMO", date="2026-06-05")
    reasons = ctx["reasons"]
    assert any("no approved runtime config" in r.lower() for r in reasons)
    assert any("no usable draft" in r.lower() for r in reasons)


@pytest.mark.asyncio
async def test_reasons_with_file_failure(monitor_setup):
    ctx = await monitor_setup.context(partner="MOMO", date="2026-06-05")
    reasons = ctx["reasons"]
    assert any("failed processing" in r.lower() for r in reasons)


# --- primaryAction tests ---

@pytest.mark.asyncio
async def test_primary_action_healthy(healthy_setup):
    ctx = await healthy_setup.context(partner="MOMO", date="2026-06-05")
    assert ctx["primaryAction"] is None


@pytest.mark.asyncio
async def test_primary_action_blocked(blocked_setup):
    ctx = await blocked_setup.context(partner="MOMO", date="2026-06-05")
    assert ctx["primaryAction"] is not None
    assert ctx["primaryAction"]["key"] == "open_mapping_details"
    assert ctx["primaryAction"]["label"] == "Open Mapping Studio"


@pytest.mark.asyncio
async def test_primary_action_monitor(monitor_setup):
    ctx = await monitor_setup.context(partner="MOMO", date="2026-06-05")
    assert ctx["primaryAction"] is not None
    assert ctx["primaryAction"]["key"] == "open_mapping_details"
    assert "Open file details" in ctx["primaryAction"]["label"]


@pytest.mark.asyncio
async def test_primary_action_needs_review_packet(needs_review_packet_setup):
    ctx = await needs_review_packet_setup.context(partner="MOMO", date="2026-06-05")
    assert ctx["primaryAction"] is not None
    assert ctx["primaryAction"]["key"] == "review_proposal"
    assert ctx["primaryAction"]["label"] == "Open Review Center"


@pytest.mark.asyncio
async def test_primary_action_needs_review_draft(needs_review_draft_setup):
    ctx = await needs_review_draft_setup.context(partner="MOMO", date="2026-06-05")
    assert ctx["primaryAction"] is not None
    assert ctx["primaryAction"]["key"] == "review_proposal"


# --- secondaryActions tests ---

@pytest.mark.asyncio
async def test_secondary_actions_healthy(healthy_setup):
    ctx = await healthy_setup.context(partner="MOMO", date="2026-06-05")
    assert isinstance(ctx["secondaryActions"], list)
    assert len(ctx["secondaryActions"]) == 1
    assert ctx["secondaryActions"][0]["key"] == "refresh_context"


@pytest.mark.asyncio
async def test_secondary_actions_blocked(blocked_setup):
    ctx = await blocked_setup.context(partner="MOMO", date="2026-06-05")
    assert isinstance(ctx["secondaryActions"], list)
    keys = [a["key"] for a in ctx["secondaryActions"]]
    assert "refresh_context" in keys


@pytest.mark.asyncio
async def test_secondary_actions_monitor(monitor_setup):
    ctx = await monitor_setup.context(partner="MOMO", date="2026-06-05")
    assert isinstance(ctx["secondaryActions"], list)
    keys = [a["key"] for a in ctx["secondaryActions"]]
    assert "refresh_context" in keys


# --- backward compatibility tests ---

@pytest.mark.asyncio
async def test_backward_compatibility_old_keys_present(healthy_setup):
    ctx = await healthy_setup.context(partner="MOMO", date="2026-06-05")
    # All old keys must still be present
    assert "actions" in ctx
    assert "explanation" in ctx
    assert "evidence" in ctx
    assert "headline" in ctx
    assert "status" in ctx
    assert "riskLevel" in ctx
    assert "recommendedAction" in ctx
    assert "generatedAt" in ctx
    # All new keys must be present
    assert "primaryAction" in ctx
    assert "secondaryActions" in ctx
    assert "summary" in ctx
    assert "reasons" in ctx


@pytest.mark.asyncio
async def test_backward_compatibility_actions_unchanged(healthy_setup):
    ctx = await healthy_setup.context(partner="MOMO", date="2026-06-05")
    # actions should be non-empty list
    assert isinstance(ctx["actions"], list)
    assert len(ctx["actions"]) >= 1


@pytest.mark.asyncio
async def test_backward_compatibility_recommended_action(healthy_setup):
    ctx = await healthy_setup.context(partner="MOMO", date="2026-06-05")
    # recommendedAction should equal primaryAction
    assert ctx["recommendedAction"] == ctx["primaryAction"]


@pytest.mark.asyncio
async def test_backward_compatibility_actions_combines_primary_and_secondary(healthy_setup):
    ctx = await healthy_setup.context(partner="MOMO", date="2026-06-05")
    # actions should contain all primary + secondary actions
    expected_len = (1 if ctx["primaryAction"] is not None else 0) + len(ctx["secondaryActions"])
    assert len(ctx["actions"]) == expected_len


@pytest.mark.asyncio
async def test_backward_compatibility_explanation_exists(blocked_setup):
    ctx = await blocked_setup.context(partner="MOMO", date="2026-06-05")
    assert isinstance(ctx["explanation"], list)
    assert len(ctx["explanation"]) > 0


@pytest.mark.asyncio
async def test_backward_compatibility_evidence_structure(blocked_setup):
    ctx = await blocked_setup.context(partner="MOMO", date="2026-06-05")
    assert "latestFile" in ctx["evidence"]
    assert "runtime" in ctx["evidence"]
    assert "proposal" in ctx["evidence"]
    assert "safeChecks" in ctx["evidence"]


# --- decisionActions tests ---

@pytest.mark.asyncio
async def test_decision_actions_empty_when_no_packet():
    """decisionActions should be empty when no pending packet exists."""
    mapping_repo = _make_mock_repo([_mapping(status="PENDING_APPROVAL", config_id="cfg-002")])
    file_repo = _make_mock_repo([_file(status="FAILED")])
    packet_repo = _make_mock_repo([])
    service = CopilotContextService(MagicMock())
    service.mapping_repo = mapping_repo
    service.file_repo = file_repo
    service.packet_repo = packet_repo
    ctx = await service.context(partner="MOMO", date="2026-06-05")
    assert isinstance(ctx["decisionActions"], list)
    assert len(ctx["decisionActions"]) == 0


@pytest.mark.asyncio
async def test_decision_actions_populated_when_packet_exists():
    """decisionActions should contain decision keys when a pending packet exists."""
    mapping_repo = _make_mock_repo([_mapping(status="PENDING_APPROVAL", config_id="cfg-002")])
    file_repo = _make_mock_repo([_file(status="FAILED")])
    packet_repo = _make_mock_repo([_packet()])
    service = CopilotContextService(MagicMock())
    service.mapping_repo = mapping_repo
    service.file_repo = file_repo
    service.packet_repo = packet_repo
    ctx = await service.context(partner="MOMO", date="2026-06-05")
    assert isinstance(ctx["decisionActions"], list)
    assert len(ctx["decisionActions"]) > 0
    keys = [a["key"] for a in ctx["decisionActions"]]
    assert "approve_activate_next_runtime" in keys
    assert "approve_keep_current" in keys
    assert "reject_proposal" in keys


@pytest.mark.asyncio
async def test_decision_actions_not_mixed_in_secondary():
    """Decision keys should NOT appear in secondaryActions when decisionActions is populated."""
    mapping_repo = _make_mock_repo([_mapping(status="PENDING_APPROVAL", config_id="cfg-002")])
    file_repo = _make_mock_repo([_file(status="FAILED")])
    packet_repo = _make_mock_repo([_packet()])
    service = CopilotContextService(MagicMock())
    service.mapping_repo = mapping_repo
    service.file_repo = file_repo
    service.packet_repo = packet_repo
    ctx = await service.context(partner="MOMO", date="2026-06-05")
    decision_keys = {"approve_activate_next_runtime", "approve_keep_current", "reject_proposal"}
    secondary_keys = {a["key"] for a in ctx["secondaryActions"]}
    assert not (decision_keys & secondary_keys), "Decision keys leaked into secondaryActions"


# --- step field tests ---

@pytest.mark.asyncio
async def test_step_brief_when_healthy(healthy_setup):
    ctx = await healthy_setup.context(partner="MOMO", date="2026-06-05")
    assert ctx["step"] == "brief"


@pytest.mark.asyncio
async def test_step_brief_when_monitor(monitor_setup):
    ctx = await monitor_setup.context(partner="MOMO", date="2026-06-05")
    assert ctx["step"] == "brief"


@pytest.mark.asyncio
async def test_step_review_when_draft_only():
    mapping_repo = _make_mock_repo([_mapping(status="PENDING_APPROVAL", config_id="cfg-002")])
    file_repo = _make_mock_repo([_file(status="FAILED")])
    packet_repo = _make_mock_repo([])
    service = CopilotContextService(MagicMock())
    service.mapping_repo = mapping_repo
    service.file_repo = file_repo
    service.packet_repo = packet_repo
    ctx = await service.context(partner="MOMO", date="2026-06-05")
    assert ctx["step"] == "review"


@pytest.mark.asyncio
async def test_step_decision_when_packet_exists():
    mapping_repo = _make_mock_repo([_mapping(status="PENDING_APPROVAL", config_id="cfg-002")])
    file_repo = _make_mock_repo([_file(status="FAILED")])
    packet_repo = _make_mock_repo([_packet()])
    service = CopilotContextService(MagicMock())
    service.mapping_repo = mapping_repo
    service.file_repo = file_repo
    service.packet_repo = packet_repo
    ctx = await service.context(partner="MOMO", date="2026-06-05")
    assert ctx["step"] == "decision"


# --- new compact fields in all decision states ---

@pytest.mark.asyncio
async def test_all_new_keys_in_all_states():
    """Verify all 4 decision states have all new compact keys."""
    states = [
        ("healthy", [("mapping", [_mapping()]), ("file", [_file()]), ("packet", [])]),
        ("monitor", [("mapping", [_mapping()]), ("file", [_file(status="FAILED")]), ("packet", [])]),
        ("needs_review", [("mapping", [_mapping(), _mapping(status="PENDING_APPROVAL", config_id="cfg-002")]), ("file", [_file(status="FAILED")]), ("packet", [_packet()])]),
        ("blocked", [("mapping", []), ("file", [_file(status="FAILED")]), ("packet", [])]),
    ]
    for state_name, repos_data in states:
        mapping_repo = _make_mock_repo(repos_data[0][1])
        file_repo = _make_mock_repo(repos_data[1][1])
        packet_repo = _make_mock_repo(repos_data[2][1])
        service = CopilotContextService(MagicMock())
        service.mapping_repo = mapping_repo
        service.file_repo = file_repo
        service.packet_repo = packet_repo
        ctx = await service.context(partner="MOMO", date="2026-06-05")
        assert "primaryAction" in ctx, f"{state_name}: missing primaryAction"
        assert "secondaryActions" in ctx, f"{state_name}: missing secondaryActions"
        assert "summary" in ctx, f"{state_name}: missing summary"
        assert "reasons" in ctx, f"{state_name}: missing reasons"
        assert isinstance(ctx["secondaryActions"], list), f"{state_name}: secondaryActions not a list"
        assert isinstance(ctx["reasons"], list), f"{state_name}: reasons not a list"


# --- legacy field name leak check ---

@pytest.mark.asyncio
async def test_no_legacy_field_leak():
    """No proposalConfigId or targetConfigId in any string value."""
    mapping_repo = _make_mock_repo([_mapping(), _mapping(status="PENDING_APPROVAL", config_id="cfg-002")])
    file_repo = _make_mock_repo([_file(status="FAILED")])
    packet_repo = _make_mock_repo([_packet()])
    service = CopilotContextService(MagicMock())
    service.mapping_repo = mapping_repo
    service.file_repo = file_repo
    service.packet_repo = packet_repo
    ctx = await service.context(partner="MOMO", date="2026-06-05")
    rendered = str(ctx)
    assert "proposalConfigId" not in rendered
    assert "targetConfigId" not in rendered
