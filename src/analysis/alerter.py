"""Threshold Alerter — check only, no duplicate computation.

ThresholdAlerter reads thresholds from AnalysisConfig and compares
them against metrics from MetricsService output. It does NOT compute
metrics itself — only checks values against configured thresholds.

Usage:
    alerter = ThresholdAlerter(config)
    alerts = alerter.check_thresholds(summary_result)
    all_alerts = alerter.alerts_for_report(report)
"""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field

from src.analysis.config import AnalysisConfig
from src.analysis.schemas import SummaryResult

logger = logging.getLogger(__name__)


class Alert(BaseModel):
    """A threshold breach alert.

    Represents a single metric that has exceeded its configured threshold.
    """

    type: str = Field(description="Alert type (e.g. mismatch_rate_breach)")
    severity: str = Field(description="Alert severity: low | medium | high | critical")
    partner: str = Field(description="Partner identifier")
    date: str = Field(description="Date string (YYYY-MM-DD)")
    metric: str = Field(description="Metric name that breached threshold")
    value: float = Field(description="Actual metric value")
    threshold: float = Field(description="Configured threshold value")
    message: str = Field(description="Human-readable alert message")


class ThresholdAlerter:
    """Check metrics against configured thresholds — no computation.

    Reads thresholds from AnalysisConfig and compares them against
    values from MetricsService output. Does NOT compute metrics.
    """

    def __init__(self, config: Optional[AnalysisConfig] = None):
        """Initialize ThresholdAlerter.

        Args:
            config: AnalysisConfig with threshold settings.
                    Uses defaults if not provided.
        """
        self.config = config or AnalysisConfig()

    def check_thresholds(self, summary_result: SummaryResult) -> list[Alert]:
        """Check a SummaryResult against configured thresholds.

        Checks:
        - Mismatch rate vs AI_ALERT_MISMATCH_RATE_THRESHOLD
        - Missing internal count vs AI_ALERT_MISSING_COUNT_THRESHOLD

        Does NOT compute metrics — only reads from SummaryResult.

        Args:
            summary_result: SummaryResult from MetricsService.compute_summary().

        Returns:
            List of Alert objects for threshold breaches.
        """
        alerts = []

        # Check mismatch rate threshold
        mismatch_rate = summary_result.mismatch_rate
        rate_threshold = self.config.ai_alert_mismatch_rate_threshold

        if mismatch_rate > rate_threshold:
            severity = self._rate_severity(mismatch_rate, rate_threshold)
            alerts.append(
                Alert(
                    type="mismatch_rate_breach",
                    severity=severity,
                    partner=summary_result.partner,
                    date=summary_result.date,
                    metric="mismatch_rate",
                    value=mismatch_rate,
                    threshold=rate_threshold,
                    message=(
                        f"Mismatch rate {mismatch_rate}% exceeds threshold "
                        f"{rate_threshold}% for {summary_result.partner} on {summary_result.date}"
                    ),
                )
            )

        # Check missing internal count threshold
        by_status = summary_result.by_status
        missing_internal = by_status.get("MISSING_INTERNAL", 0)
        missing_threshold = self.config.ai_alert_missing_count_threshold

        if missing_internal > missing_threshold:
            alerts.append(
                Alert(
                    type="missing_internal_breach",
                    severity="high" if missing_internal > missing_threshold * 2 else "medium",
                    partner=summary_result.partner,
                    date=summary_result.date,
                    metric="missing_internal_count",
                    value=float(missing_internal),
                    threshold=float(missing_threshold),
                    message=(
                        f"Missing internal count ({missing_internal}) exceeds threshold "
                        f"({missing_threshold}) for {summary_result.partner} on {summary_result.date}"
                    ),
                )
            )

        # Check missing partner count threshold
        missing_partner = by_status.get("MISSING_PARTNER", 0)

        if missing_partner > missing_threshold:
            alerts.append(
                Alert(
                    type="missing_partner_breach",
                    severity="high" if missing_partner > missing_threshold * 2 else "medium",
                    partner=summary_result.partner,
                    date=summary_result.date,
                    metric="missing_partner_count",
                    value=float(missing_partner),
                    threshold=float(missing_threshold),
                    message=(
                        f"Missing partner count ({missing_partner}) exceeds threshold "
                        f"({missing_threshold}) for {summary_result.partner} on {summary_result.date}"
                    ),
                )
            )

        # Log alerts
        for alert in alerts:
            logger.warning(
                alert.message,
                extra={
                    "event": "threshold_alert",
                    "type": alert.type,
                    "severity": alert.severity,
                    "partner": alert.partner,
                    "date": alert.date,
                    "metric": alert.metric,
                    "value": alert.value,
                    "threshold": alert.threshold,
                },
            )

        return alerts

    def alerts_for_report(self, report: dict[str, Any]) -> list[Alert]:
        """Check thresholds for all partners in a daily report.

        Iterates through each partner's summary_metrics in the report
        and runs check_thresholds() for each.

        Does NOT compute metrics — only reads from report data.

        Args:
            report: Daily report dict from DailyReporter.generate_report().

        Returns:
            Combined list of Alert objects for all partners.
        """
        all_alerts = []

        for partner_data in report.get("partners", []):
            # Build a SummaryResult from the report data
            metrics = partner_data.get("summary_metrics", {})
            summary = SummaryResult(
                partner=partner_data["partner"],
                date=report["date"],
                total_transactions=metrics.get("total_transactions", 0),
                matched=metrics.get("matched", 0),
                mismatch_rate=metrics.get("mismatch_rate", 0.0),
                total_amount_mismatch=metrics.get("total_amount_mismatch", 0.0),
                by_status=metrics.get("by_status", {}),
            )

            partner_alerts = self.check_thresholds(summary)
            all_alerts.extend(partner_alerts)

        return all_alerts

    @staticmethod
    def _rate_severity(mismatch_rate: float, threshold: float) -> str:
        """Determine alert severity based on how much the rate exceeds threshold.

        Args:
            mismatch_rate: Actual mismatch rate percentage.
            threshold: Configured threshold percentage.

        Returns:
            Severity string: low | medium | high | critical.
        """
        ratio = mismatch_rate / threshold if threshold > 0 else 1.0

        if ratio > 4:
            return "critical"
        elif ratio > 2:
            return "high"
        elif ratio > 1.5:
            return "medium"
        else:
            return "low"
