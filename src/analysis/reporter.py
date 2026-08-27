"""Daily Batch Report — format only, no duplicate computation.

DailyReporter uses MetricsService and insights.get_summary() as single
source of truth. It does NOT compute metrics itself — only formats
and aggregates data from existing services.

Usage:
    reporter = DailyReporter(collection, llm_provider, config)
    report = await reporter.generate_report("2024-07-07")
    path = await reporter.save_report("2024-07-07")
"""

import json
import logging
from pathlib import Path
from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorCollection

from src.analysis.config import AnalysisConfig
from src.infrastructure.postgres.reconciliation_result_repository import ReconciliationResultRepository
from src.analysis.provider import AIProviderRouter, LLMProvider

logger = logging.getLogger(__name__)


class DailyReporter:
    """Generate daily batch reports — format only, no computation.

    Uses MetricsService and insights.get_summary() as single source of truth.
    Does NOT duplicate any metric computation.
    """

    def __init__(
        self,
        collection: AsyncIOMotorCollection | ReconciliationResultRepository,
        llm_provider: LLMProvider | AIProviderRouter,
        config: Optional[AnalysisConfig] = None,
    ):
        """Initialize DailyReporter.

        Args:
            collection: Motor collection for reconciliation_result.
            llm_provider: LLM provider for insight generation.
            config: Optional AnalysisConfig (uses defaults if not provided).
        """
        self.collection = collection
        self.llm_provider = llm_provider
        self.config = config or AnalysisConfig()

    async def generate_report(self, date: str) -> dict[str, Any]:
        """Generate a daily batch report for all active partners.

        For each active partner, calls insights.get_summary() to get
        aggregated metrics and AI findings. Aggregates into a single
        report with global statistics.

        Does NOT compute metrics — only formats data from MetricsService.

        Args:
            date: Date string (YYYY-MM-DD) for the report.

        Returns:
            Report dict with:
            - date: Report date
            - generated_at: Timestamp (will be replaced by caller)
            - partners: List of partner reports
            - global_stats: Aggregated statistics across all partners
        """
        from src.analysis.insights import get_summary

        # Get active partners for the date
        partners = await self._get_active_partners(date)

        if not partners:
            return {
                "date": date,
                "generated_at": date,
                "partners": [],
                "global_stats": {
                    "total_mismatch_rate": 0.0,
                    "total_volume": 0,
                    "alert_count": 0,
                },
            }

        partner_reports = []
        total_transactions = 0
        total_matched = 0
        total_mismatch_amount = 0.0
        alert_count = 0

        for partner in partners:
            try:
                summary = await get_summary(
                    partner=partner,
                    date=date,
                    collection=self.collection,
                    llm_provider=self.llm_provider,
                )

                partner_report = {
                    "partner": partner,
                    "summary_metrics": summary["summary_metrics"],
                    "grouped_stats": summary["grouped_stats"],
                    "key_findings": summary["key_findings"],
                }
                partner_reports.append(partner_report)

                # Accumulate global stats
                metrics = summary["summary_metrics"]
                total_transactions += metrics.get("total_transactions", 0)
                total_matched += metrics.get("matched", 0)
                total_mismatch_amount += metrics.get("total_amount_mismatch", 0)

            except Exception as exc:
                logger.warning(
                    f"Failed to generate summary for {partner} on {date}: {exc}",
                    extra={"event": "daily_report_partner_error", "partner": partner, "date": date},
                )
                # Skip this partner but continue with others
                continue

        # Compute global stats (simple aggregation, not duplicate computation)
        total_mismatched = total_transactions - total_matched
        global_mismatch_rate = (
            round((total_mismatched / total_transactions) * 100, 2)
            if total_transactions > 0
            else 0.0
        )

        return {
            "date": date,
            "generated_at": date,  # Will be replaced by API layer with proper timestamp
            "partners": partner_reports,
            "global_stats": {
                "total_mismatch_rate": global_mismatch_rate,
                "total_volume": total_transactions,
                "total_mismatch_amount": total_mismatch_amount,
                "alert_count": alert_count,
            },
        }

    async def save_report(self, date: str) -> str:
        """Generate and save daily report to disk.

        Saves JSON report to ./reports/daily/{date}.json.

        Args:
            date: Date string (YYYY-MM-DD) for the report.

        Returns:
            Path to saved report file.
        """
        report = await self.generate_report(date)

        # Ensure reports directory exists
        report_dir = Path("./reports/daily")
        report_dir.mkdir(parents=True, exist_ok=True)

        report_path = report_dir / f"{date}.json"

        with open(report_path, "w") as f:
            json.dump(report, f, indent=2, default=str)

        logger.info(
            f"Daily report saved to {report_path}",
            extra={"event": "daily_report_saved", "date": date, "path": str(report_path)},
        )

        return str(report_path)

    async def _get_active_partners(self, date: str) -> list[str]:
        """Get list of partners with reconciliation data for a date.

        Args:
            date: Date string (YYYY-MM-DD).

        Returns:
            List of unique partner identifiers.
        """
        if isinstance(self.collection, ReconciliationResultRepository):
            return await self.collection.distinct_partners_by_date(date)
        partners = await self.collection.distinct("partner", {"date": date})
        return partners if isinstance(partners, list) else []
