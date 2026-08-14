from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.config_health import (
    ConfigurationApprovalRequiredError,
    _is_config_stale,
    check_and_refresh_config,
)
from src.core.enums import FileType
from src.config.signature import StructureSignature


def test_legacy_approved_signature_with_matching_headers_is_not_stale():
    config = SimpleNamespace(
        structure_signature={"headers": ["id", "trace", "amount"]},
        config_health={"stale": False},
    )
    signature = StructureSignature(
        headers=["id", "trace", "amount"],
        column_count=3,
        hash="current-structure-hash",
    )

    assert _is_config_stale(config, signature) is False


@pytest.mark.asyncio
async def test_backfill_stops_when_a_daily_file_has_a_different_structure(tmp_path):
    source_file = tmp_path / "settlement_VNPAY_20260812.csv"
    source_file.write_text("id,amount,fee\n1,100,1\n", encoding="utf-8")
    approved_config = SimpleNamespace(
        id="approved-v1",
        structure_signature={"headers": ["id", "amount"], "columnCount": 2},
        config_health={"stale": False},
    )
    config_loader = MagicMock()
    config_loader.load_by_version = AsyncMock(return_value=approved_config)
    config_repo = MagicMock()
    config_repo.collection.database = MagicMock()
    proposal = SimpleNamespace(id="proposal-v2")
    action = SimpleNamespace(id="action-v2")

    with patch(
        "src.config.config_health._create_mapping_proposal",
        new=AsyncMock(return_value=(proposal, action)),
    ) as create_proposal:
        with pytest.raises(ConfigurationApprovalRequiredError) as raised:
            await check_and_refresh_config(
                file_path=source_file,
                partner="VNPAY",
                workflow_type="UPC",
                file_type=FileType.SETTLEMENT,
                config_loader=config_loader,
                config_repo=config_repo,
                config_version="VNPAY_V1",
                source_file_name=source_file.name,
                source_file_path=str(source_file),
                reconciliation_date=datetime(2026, 8, 12, tzinfo=UTC),
                backfill_run_id="backfill-001",
            )

    assert raised.value.proposal_id == "proposal-v2"
    assert raised.value.action_id == "action-v2"
    assert create_proposal.await_args.kwargs["backfill_run_id"] == "backfill-001"


@pytest.mark.asyncio
async def test_backfill_reuses_approved_config_when_daily_structure_matches(tmp_path):
    source_file = tmp_path / "settlement_VNPAY_20260811.csv"
    source_file.write_text("id,amount\n1,100\n", encoding="utf-8")
    approved_config = SimpleNamespace(
        id="approved-v1",
        structure_signature={"headers": ["id", "amount"], "columnCount": 2},
        config_health={"stale": False},
    )
    config_loader = MagicMock()
    config_loader.load_by_version = AsyncMock(return_value=approved_config)
    config_repo = MagicMock()
    config_repo.collection.database = MagicMock()

    with patch(
        "src.config.config_health._create_mapping_proposal",
        new=AsyncMock(),
    ) as create_proposal:
        result = await check_and_refresh_config(
            file_path=source_file,
            partner="VNPAY",
            workflow_type="UPC",
            file_type=FileType.SETTLEMENT,
            config_loader=config_loader,
            config_repo=config_repo,
            config_version="VNPAY_V1",
            source_file_name=source_file.name,
            source_file_path=str(source_file),
            reconciliation_date=datetime(2026, 8, 11, tzinfo=UTC),
            backfill_run_id="backfill-001",
        )

    assert result is approved_config
    create_proposal.assert_not_awaited()
