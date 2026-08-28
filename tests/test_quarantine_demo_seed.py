"""Contracts for the repeatable local quarantine demo fixture."""

from datetime import UTC, datetime


def test_demo_fixture_contains_all_operator_workflow_scenarios():
    from scripts.demo.scenarios.seed_quarantine_demo import (
        DEMO_PARTNER,
        build_demo_quarantine_records,
    )

    records = build_demo_quarantine_records(
        now=datetime(2026, 8, 27, 3, 0, tzinfo=UTC)
    )

    assert DEMO_PARTNER == "DEMO"
    assert len(records) == 7
    assert {
        record.resolution_metadata["demoScenarioId"] for record in records
    } == {
        "DEMO-INVALID-001",
        "DEMO-DUPLICATE-001",
        "DEMO-REPROCESS-001",
        "DEMO-ACCEPT-001",
        "DEMO-REJECT-001",
        "DEMO-ESCALATED-001",
        "DEMO-RECOVERY-001",
    }


def test_demo_fixture_marks_priority_and_overdue_cases_without_sensitive_evidence():
    from scripts.demo.scenarios.seed_quarantine_demo import build_demo_quarantine_records

    records = build_demo_quarantine_records(
        now=datetime(2026, 8, 27, 3, 0, tzinfo=UTC)
    )
    by_id = {
        record.resolution_metadata["demoScenarioId"]: record for record in records
    }

    assert by_id["DEMO-DUPLICATE-001"].priority.value == "HIGH"
    assert by_id["DEMO-DUPLICATE-001"].review_due_at < datetime(
        2026, 8, 27, 3, 0, tzinfo=UTC
    )
    assert by_id["DEMO-ESCALATED-001"].escalation_level == 2
    assert by_id["DEMO-REPROCESS-001"].source_unit_key == "demo-unit-reprocess-001"
    assert by_id["DEMO-ACCEPT-001"].existing_fingerprint is not None
    assert "password" not in str(by_id["DEMO-INVALID-001"].raw_row).lower()
    assert "fingerprint" not in str(by_id["DEMO-INVALID-001"].raw_row).lower()
    assert "status" not in by_id["DEMO-INVALID-001"].raw_row
    assert by_id["DEMO-INVALID-001"].errors[0]["field"] == "status"
    assert "id" not in by_id["DEMO-ESCALATED-001"].raw_row
    assert by_id["DEMO-ESCALATED-001"].errors[0]["field"] == "id"


def test_scheduler_demo_source_rows_pass_mapping_gate_and_drive_duplicate_review():
    from scripts.demo.scenarios.seed_quarantine_demo import _demo_source_rows

    now = datetime(2026, 8, 27, 3, 0, tzinfo=UTC)
    rows = _demo_source_rows(now)

    assert len(rows) == 20
    assert all({"id", "trace", "currency", "status", "transDate"} <= row.keys() for row in rows)
    assert rows[0]["id"] == "DEMO-VALID-001-TX"
    assert rows[1]["id"] == "DEMO-DUPLICATE-001-TX"
    assert sum(row["id"].startswith("DEMO-DUPLICATE") for row in rows) == 1
    missing_amount = next(row for row in rows if row["id"] == "DEMO-MISSING-AMOUNT-001-TX")
    assert "amount" not in missing_amount
    assert sum("amount" not in row for row in rows) == 1
    assert sum(row["id"].startswith("DEMO-VALID-") for row in rows) == 18
    assert all(row["transDate"] == now.isoformat() for row in rows)


def test_demo_batch_fatal_source_is_separate_and_missing_status():
    from scripts.demo.scenarios.seed_quarantine_demo import _demo_batch_fatal_source_rows

    rows = _demo_batch_fatal_source_rows(
        now=datetime(2026, 8, 27, 3, 0, tzinfo=UTC)
    )

    assert len(rows) == 20
    assert all("status" not in row for row in rows)
    assert all(row["id"].startswith("DEMO1-BATCH-FATAL") for row in rows)


def test_demo_internal_db_mirrors_the_twenty_scheduler_keys():
    from scripts.demo.scenarios.seed_quarantine_demo import (
        _demo_internal_transactions,
        _demo_source_rows,
    )

    now = datetime(2026, 8, 27, 3, 0, tzinfo=UTC)
    internal = _demo_internal_transactions(now)

    assert len(internal) == 20
    assert [item.partner_txn_id for item in internal] == [row["id"] for row in _demo_source_rows(now)]
    assert all(item.partner == "DEMO" for item in internal)
