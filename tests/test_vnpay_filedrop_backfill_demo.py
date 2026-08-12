from datetime import date
from pathlib import Path

from src.domain.fetch_config.models import FetchMethod
from scripts.demo.sprint2.seed_vnpay_filedrop_backfill import (
    DEFAULT_PARTNER,
    build_backfill_dates,
    build_draft_mapping,
    build_fetch_config,
    build_internal_preview,
    build_internal_transactions,
    build_review_packet,
    build_source_filename,
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
