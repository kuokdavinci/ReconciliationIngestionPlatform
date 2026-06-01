"""Tests for ThresholdAlerter — check only, no duplicate computation."""

import pytest

from src.analysis.alerter import Alert, ThresholdAlerter
from src.analysis.config import AnalysisConfig
from src.analysis.schemas import SummaryResult


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

def _make_summary(
    partner: str = "MOMO",
    date: str = "2024-07-07",
    total: int = 100,
    matched: int = 95,
    mismatch_rate: float = 5.0,
    total_mismatch: float = 500000.0,
    by_status: dict | None = None,
) -> SummaryResult:
    """Create a SummaryResult for testing."""
    return SummaryResult(
        partner=partner,
        date=date,
        total_transactions=total,
        matched=matched,
        mismatch_rate=mismatch_rate,
        total_amount_mismatch=total_mismatch,
        by_status=by_status or {"MATCHED": 95, "AMOUNT_MISMATCH": 5},
    )


class TestThresholdAlerterInit:
    """Test ThresholdAlerter initialization."""

    def test_initializes_with_defaults(self) -> None:
        alerter = ThresholdAlerter()
        assert alerter.config.alert_mismatch_rate_threshold == 5.0
        assert alerter.config.alert_missing_count_threshold == 10

    def test_initializes_with_custom_config(self) -> None:
        config = AnalysisConfig(
            alert_mismatch_rate_threshold=10.0,
            alert_missing_count_threshold=20,
        )
        alerter = ThresholdAlerter(config)
        assert alerter.config.alert_mismatch_rate_threshold == 10.0
        assert alerter.config.alert_missing_count_threshold == 20


class TestCheckThresholds:
    """Test ThresholdAlerter.check_thresholds()."""

    def test_no_alerts_when_within_thresholds(self) -> None:
        summary = _make_summary(mismatch_rate=3.0, by_status={"MATCHED": 97, "AMOUNT_MISMATCH": 3})
        alerter = ThresholdAlerter()

        alerts = alerter.check_thresholds(summary)

        assert alerts == []

    def test_alert_on_mismatch_rate_breach(self) -> None:
        summary = _make_summary(mismatch_rate=8.0, by_status={"MATCHED": 92, "AMOUNT_MISMATCH": 8})
        alerter = ThresholdAlerter()

        alerts = alerter.check_thresholds(summary)

        assert len(alerts) == 1
        assert alerts[0].type == "mismatch_rate_breach"
        assert alerts[0].metric == "mismatch_rate"
        assert alerts[0].value == 8.0
        assert alerts[0].threshold == 5.0
        assert alerts[0].partner == "MOMO"
        assert alerts[0].date == "2024-07-07"

    def test_alert_on_missing_internal_breach(self) -> None:
        summary = _make_summary(
            mismatch_rate=0.0,
            by_status={"MATCHED": 85, "MISSING_INTERNAL": 15},
        )
        alerter = ThresholdAlerter()

        alerts = alerter.check_thresholds(summary)

        assert len(alerts) == 1
        assert alerts[0].type == "missing_internal_breach"
        assert alerts[0].metric == "missing_internal_count"
        assert alerts[0].value == 15.0
        assert alerts[0].threshold == 10.0

    def test_alert_on_missing_partner_breach(self) -> None:
        summary = _make_summary(
            mismatch_rate=0.0,
            by_status={"MATCHED": 85, "MISSING_PARTNER": 15},
        )
        alerter = ThresholdAlerter()

        alerts = alerter.check_thresholds(summary)

        assert len(alerts) == 1
        assert alerts[0].type == "missing_partner_breach"
        assert alerts[0].metric == "missing_partner_count"
        assert alerts[0].value == 15.0

    def test_multiple_alerts_for_multiple_breaches(self) -> None:
        summary = _make_summary(
            mismatch_rate=10.0,
            by_status={"MATCHED": 80, "AMOUNT_MISMATCH": 5, "MISSING_INTERNAL": 15},
        )
        alerter = ThresholdAlerter()

        alerts = alerter.check_thresholds(summary)

        assert len(alerts) == 2
        types = [a.type for a in alerts]
        assert "mismatch_rate_breach" in types
        assert "missing_internal_breach" in types

    def test_no_alerts_when_all_matched(self) -> None:
        summary = _make_summary(
            mismatch_rate=0.0,
            matched=100,
            by_status={"MATCHED": 100},
        )
        alerter = ThresholdAlerter()

        alerts = alerter.check_thresholds(summary)

        assert alerts == []


class TestAlertSeverity:
    """Test alert severity scaling."""

    def test_low_severity_just_above_threshold(self) -> None:
        summary = _make_summary(mismatch_rate=6.0, by_status={"MATCHED": 94, "AMOUNT_MISMATCH": 6})
        alerter = ThresholdAlerter()

        alerts = alerter.check_thresholds(summary)

        assert len(alerts) == 1
        assert alerts[0].severity == "low"

    def test_medium_severity_1_5x_threshold(self) -> None:
        summary = _make_summary(mismatch_rate=8.0, by_status={"MATCHED": 92, "AMOUNT_MISMATCH": 8})
        alerter = ThresholdAlerter()

        alerts = alerter.check_thresholds(summary)

        assert len(alerts) == 1
        assert alerts[0].severity == "medium"

    def test_high_severity_2x_threshold(self) -> None:
        summary = _make_summary(mismatch_rate=12.0, by_status={"MATCHED": 88, "AMOUNT_MISMATCH": 12})
        alerter = ThresholdAlerter()

        alerts = alerter.check_thresholds(summary)

        assert len(alerts) == 1
        assert alerts[0].severity == "high"

    def test_critical_severity_4x_threshold(self) -> None:
        summary = _make_summary(mismatch_rate=25.0, by_status={"MATCHED": 75, "AMOUNT_MISMATCH": 25})
        alerter = ThresholdAlerter()

        alerts = alerter.check_thresholds(summary)

        assert len(alerts) == 1
        assert alerts[0].severity == "critical"


class TestAlertsForReport:
    """Test ThresholdAlerter.alerts_for_report()."""

    def test_checks_all_partners_in_report(self) -> None:
        report = {
            "date": "2024-07-07",
            "partners": [
                {
                    "partner": "MOMO",
                    "summary_metrics": {
                        "total_transactions": 100,
                        "matched": 90,
                        "mismatch_rate": 10.0,
                        "total_amount_mismatch": 1000000,
                        "by_status": {"MATCHED": 90, "AMOUNT_MISMATCH": 10},
                    },
                    "grouped_stats": [],
                    "key_findings": [],
                },
                {
                    "partner": "VIETTEL",
                    "summary_metrics": {
                        "total_transactions": 50,
                        "matched": 40,
                        "mismatch_rate": 20.0,
                        "total_amount_mismatch": 500000,
                        "by_status": {"MATCHED": 40, "AMOUNT_MISMATCH": 10},
                    },
                    "grouped_stats": [],
                    "key_findings": [],
                },
            ],
            "global_stats": {"total_mismatch_rate": 13.33, "total_volume": 150, "alert_count": 0},
        }

        alerter = ThresholdAlerter()

        alerts = alerter.alerts_for_report(report)

        # Both partners have mismatch rate > 5%
        assert len(alerts) == 2
        partners_with_alerts = {a.partner for a in alerts}
        assert "MOMO" in partners_with_alerts
        assert "VIETTEL" in partners_with_alerts

    def test_returns_empty_for_report_without_breaches(self) -> None:
        report = {
            "date": "2024-07-07",
            "partners": [
                {
                    "partner": "MOMO",
                    "summary_metrics": {
                        "total_transactions": 100,
                        "matched": 98,
                        "mismatch_rate": 2.0,
                        "total_amount_mismatch": 0,
                        "by_status": {"MATCHED": 98, "AMOUNT_MISMATCH": 2},
                    },
                    "grouped_stats": [],
                    "key_findings": [],
                },
            ],
            "global_stats": {"total_mismatch_rate": 2.0, "total_volume": 100, "alert_count": 0},
        }

        alerter = ThresholdAlerter()

        alerts = alerter.alerts_for_report(report)

        assert alerts == []

    def test_returns_empty_for_empty_report(self) -> None:
        report = {
            "date": "2024-07-07",
            "partners": [],
            "global_stats": {"total_mismatch_rate": 0.0, "total_volume": 0, "alert_count": 0},
        }

        alerter = ThresholdAlerter()

        alerts = alerter.alerts_for_report(report)

        assert alerts == []


class TestAlertModel:
    """Test Alert pydantic model."""

    def test_alert_creation(self) -> None:
        alert = Alert(
            type="mismatch_rate_breach",
            severity="high",
            partner="MOMO",
            date="2024-07-07",
            metric="mismatch_rate",
            value=10.0,
            threshold=5.0,
            message="Mismatch rate 10% exceeds threshold 5%",
        )

        assert alert.type == "mismatch_rate_breach"
        assert alert.severity == "high"
        assert alert.value == 10.0
        assert alert.threshold == 5.0

    def test_alert_model_dump(self) -> None:
        alert = Alert(
            type="test_alert",
            severity="medium",
            partner="TEST",
            date="2024-07-07",
            metric="test_metric",
            value=1.0,
            threshold=0.5,
            message="Test alert",
        )

        dumped = alert.model_dump()
        assert dumped["type"] == "test_alert"
        assert dumped["severity"] == "medium"
        assert dumped["message"] == "Test alert"
