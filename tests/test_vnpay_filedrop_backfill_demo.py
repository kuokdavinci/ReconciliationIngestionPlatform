from datetime import date
from pathlib import Path

from src.domain.fetch_config.models import FetchMethod
from scripts.demo.sprint2.seed_vnpay_filedrop_backfill import (
    DEFAULT_PARTNER,
    build_backfill_dates,
    build_backfill_run,
    build_draft_mapping,
    build_fetch_config,
    build_internal_preview,
    build_internal_transactions,
    build_review_packet,
    build_source_filename,
    SEED_BACKFILL_RUN_ID,
)


def test_vnpay_fixture_expands_inclusive_ordered_business_dates():
    assert build_backfill_dates("2026-08-09", "2026-08-12") == [
        date(2026, 8, 9),
        date(2026, 8, 10),
        date(2026, 8, 11),
        date(2026, 8, 12),
    ]


def test_vnpay_fixture_uses_date_scoped_filedrop_config():
    config = build_fetch_config()

    assert config.partner == DEFAULT_PARTNER == "VNPAY"
    assert config.fetch_method == FetchMethod.FILEDROP
    assert config.enabled is True
    assert config.filedrop is not None
    assert config.filedrop.pattern == "settlement_VNPAY_{date:%Y%m%d}.xlsx"


def test_vnpay_fixture_mapping_supplies_required_currency_constant():
    currency = next(item for item in build_draft_mapping(date(2026, 8, 10))["fieldMappings"] if item["path"] == "currency")

    assert currency == {
        "path": "currency",
        "type": "CONSTANT",
        "constant": "VND",
        "required": True,
    }


def test_vnpay_fixture_filename_is_deterministic():
    assert build_source_filename(date(2026, 8, 12)) == "settlement_VNPAY_20260812.xlsx"


def test_vnpay_fixture_seeds_internal_rows_for_review_evidence():
    day = date(2026, 8, 10)
    rows = build_internal_transactions(day)
    packet = build_review_packet(day, Path("mock_data/file.xlsx"))

    assert [row.partner_txn_id for row in rows] == [
        "TRACE_20260810_001",
        "TRACE_20260810_002",
        "TRACE_20260810_003",
    ]
    assert len(build_internal_preview(day)) == packet["internalRecordCount"] == 3
    assert packet["internalPreview"][0]["partnerTxnId"] == "TRACE_20260810_001"
    assert packet["structureSignature"]["headers"] == ["id", "trace", "amount", "status", "transDate"]
    assert packet["structureSignature"]["columnCount"] == 5


def test_vnpay_fixture_seeds_waiting_checkpoint_at_first_business_date():
    run = build_backfill_run(
        date(2026, 8, 10),
        date(2026, 8, 13),
        "vnpay-fetch-config",
        f"{SEED_BACKFILL_RUN_ID}-packet-20260810",
    )

    assert run["_id"] == SEED_BACKFILL_RUN_ID
    assert run["status"] == "WAITING_CONFIG"
    assert run["currentDate"] == "2026-08-10"
    assert run["approvalRequired"] is True
    assert run["approvalContext"]["reviewPacketId"].endswith("20260810")
    assert [day["businessDate"] for day in run["days"]] == [
        "2026-08-10",
        "2026-08-11",
        "2026-08-12",
        "2026-08-13",
    ]


def test_vnpay_fixture_links_review_packet_to_waiting_checkpoint():
    packet = build_review_packet(
        date(2026, 8, 10),
        Path("mock_data/settlement_VNPAY_20260810.xlsx"),
        backfill_run_id=SEED_BACKFILL_RUN_ID,
    )

    assert packet["backfillRunId"] == SEED_BACKFILL_RUN_ID
