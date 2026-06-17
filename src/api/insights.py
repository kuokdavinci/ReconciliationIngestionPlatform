"""FastAPI Router for AI Analysis insights endpoints.

Provides three endpoints:
- GET /api/v1/insights/summary — summary + groups + key_findings
- GET /api/v1/insights/discrepancies — LLM-powered discrepancy analysis
- GET /api/v1/reports/daily — daily batch report

All endpoints validate request parameters and handle errors gracefully.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from motor.motor_asyncio import AsyncIOMotorCollection

from src.api.response_utils import camelize
from src.analysis.config import AnalysisConfig
from src.analysis.provider import create_provider
from src.analysis.schemas import AnalysisResult

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")


# ---------------------------------------------------------------------------
# Request validation helpers
# ---------------------------------------------------------------------------

def _validate_date(date_str: Optional[str]) -> str:
    """Validate date format (YYYY-MM-DD).

    Args:
        date_str: Date string to validate.

    Returns:
        Validated date string.

    Raises:
        HTTPException: If date is missing or format is invalid.
    """
    if date_str is None:
        raise HTTPException(
            status_code=400,
            detail="Date parameter is required (YYYY-MM-DD format).",
        )
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid date format: '{date_str}'. Expected YYYY-MM-DD.",
        )
    return date_str


def _validate_partner(partner: Optional[str]) -> str:
    """Validate partner identifier.

    Args:
        partner: Partner identifier to validate.

    Returns:
        Validated partner string.

    Raises:
        HTTPException: If partner is empty or missing.
    """
    if not partner or not partner.strip():
        raise HTTPException(
            status_code=400,
            detail="Partner identifier is required.",
        )
    return partner.strip()


def _get_collection(request: Request) -> AsyncIOMotorCollection:
    """Get the reconciliation_result collection from app state.

    Args:
        request: FastAPI request object.

    Returns:
        Motor collection for reconciliation_result.

    Raises:
        HTTPException: If database connection is not available.
    """
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(
            status_code=503,
            detail="Database connection not available.",
        )
    return db["reconciliation_result"]


def _get_llm_provider() -> object:
    """Create and return an LLM provider instance.

    Returns:
        LLMProvider instance configured from environment.
    """
    config = AnalysisConfig()
    return create_provider(config)


# ---------------------------------------------------------------------------
# GET /api/v1/insights/sample — UI demo data (no DB required)
# ---------------------------------------------------------------------------

@router.get("/insights/sample")
async def insights_sample():
    """Return sample AI observation data for UI testing.

    Returns hardcoded but realistic data so the front-end can be
    verified without MongoDB or a real LLM provider.
    """
    sample_observation = {
        "partner": "MOMO",
        "date": "2024-07-07",
        "focus": "operational",
        "provider": "openai",
        "model": "gpt-4o-mini",
        "latency_ms": 2347.89,
        "prompt_tokens": 856,
        "completion_tokens": 312,
        "total_tokens": 1168,
        "estimated_cost_usd": 0.000294,
        "cache_hit": False,
        "cache_key": "momo:2024-07-07:operational:gpt-4o-mini",
        "schema_valid": True,
        "resolution": "llm",
        "guardrail_result": {
            "is_valid": False,
            "risk_level": "high",
            "unsupported_count": 1,
            "warning_count": 2,
            "findings": [
                {
                    "risk": "high",
                    "insight_index": 0,
                    "field": "affected_count",
                    "message": "LLM says 50 records affected — only 12 actual anomalies in data",
                    "detail": "Insight overstates affected_count by 38 records (316%). Likely cause: LLM extrapolated from mismatch rate instead of reading the actual anomaly count.",
                },
                {
                    "risk": "medium",
                    "insight_index": 1,
                    "field": "severity",
                    "message": "LLM assigned 'critical' severity to 0.5% mismatch rate",
                    "detail": "0.5% mismatch rate should be at most 'low' severity. False alarm risk: operators may waste time investigating a non-critical issue.",
                },
                {
                    "risk": "low",
                    "insight_index": 0,
                    "field": "type",
                    "message": "LLM used 'partner_pattern' under 'operational' analysis focus",
                    "detail": "Insight type mismatches the requested focus. The observation may still be useful but is flagged for scope alignment.",
                },
            ],
        },
    }
    return {
        "partner": "MOMO",
        "date": "2024-07-07",
        "summaryMetrics": {
            "totalTransactions": 1250,
            "matched": 1187,
            "mismatchRate": 5.04,
            "totalAmountMismatch": 24500000.0,
            "byStatus": {
                "MATCHED": 1187,
                "AMOUNT_MISMATCH": 32,
                "MISSING_INTERNAL": 18,
                "MISSING_PARTNER": 13,
            },
        },
        "groupedStats": [
            {"key": "MATCHED", "count": 1187, "percentage": 94.96, "totalAmount": 2450000000.0, "details": {}},
            {"key": "AMOUNT_MISMATCH", "count": 32, "percentage": 2.56, "totalAmount": 24500000.0, "details": {"avgDifference": 765625.0}},
            {"key": "MISSING_INTERNAL", "count": 18, "percentage": 1.44, "totalAmount": 0.0, "details": {}},
            {"key": "MISSING_PARTNER", "count": 13, "percentage": 1.04, "totalAmount": 0.0, "details": {}},
        ],
        "keyFindings": [
            "[CRITICAL] Ingestion gap at 14:20-14:30 — 18 records missing internally (24.5M VND)",
            "[HIGH] 32 amount mismatches, 3 outliers drive 60% of 24.5M VND impact",
            "[MEDIUM] MOMO mismatch rate 5.04% — second consecutive day above threshold",
        ],
        "guardrailResult": camelize(sample_observation["guardrail_result"]),
        "generatedAt": "2024-07-07T12:00:00+00:00",
        "llmStatus": "success",
        "aiObservation": camelize(sample_observation),
    }


# ---------------------------------------------------------------------------
# GET /api/v1/insights/sample-stats — UI demo data (no DB required)
# ---------------------------------------------------------------------------

@router.get("/insights/sample-stats")
async def insights_sample_stats():
    """Return sample reconciliation stats for UI testing."""
    return {
        "total": 1250,
        "matched": 1187,
        "mismatchRate": 5.04,
        "byStatus": {
            "MATCHED": 1187,
            "AMOUNT_MISMATCH": 32,
            "STATUS_MISMATCH": 0,
            "MULTIPLE_MISMATCH": 0,
            "MISSING_INTERNAL": 18,
            "MISSING_PARTNER": 13,
            "UNMAPPED_SKIPPED": 0,
        },
    }


# ---------------------------------------------------------------------------
# GET /api/v1/insights/summary
# ---------------------------------------------------------------------------

@router.get("/insights/summary")
async def insights_summary(
    request: Request,
    partner: Optional[str] = Query(default=None, description="Partner identifier"),
    date: Optional[str] = Query(default=None, description="Date (YYYY-MM-DD)"),
):
    """Get summary insights for a partner on a given date.

    Returns aggregated metrics, grouped stats, and AI-generated key findings.

    **Parameters:**
    - `partner`: Partner identifier (required)
    - `date`: Date string in YYYY-MM-DD format (required)

    **Response:**
    - `partner`: Partner identifier
    - `date`: Date string
    - `summary_metrics`: Aggregated statistics
    - `grouped_stats`: Grouped reconciliation results
    - `key_findings`: AI-generated findings
    - `generated_at`: Timestamp of generation
    """
    try:
        partner = _validate_partner(partner)
        date = _validate_date(date)
    except HTTPException:
        raise

    try:
        from src.analysis.insights import get_summary

        collection = _get_collection(request)
        llm_provider = _get_llm_provider()

        result = await get_summary(
            partner=partner,
            date=date,
            collection=collection,
            llm_provider=llm_provider,
        )

        # Replace generated_at with proper timestamp
        result["generated_at"] = datetime.now(timezone.utc).isoformat()

        return camelize(result)

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error generating summary insights: {exc}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate summary insights: {str(exc)}",
        )


# ---------------------------------------------------------------------------
# GET /api/v1/insights/sample-discrepancies — UI demo data (no DB required)
# ---------------------------------------------------------------------------

@router.get("/insights/sample-discrepancies")
async def insights_sample_discrepancies():
    """Return sample discrepancy data for UI testing."""
    return [
        {
            "type": "missing_internal",
            "severity": "critical",
            "title": "18 records missing internally — gap in batch #B-042 at 14:20-14:30",
            "description": "18 transactions (1.4% of total, 24.5M VND) confirmed by MOMO but absent internally. Pattern: concentrated — all 18 share a 10-minute ingestion window (14:20-14:30), consistent with a batch scheduler failure rather than random data loss. If this gap repeats daily, ~540 records/month would be affected.",
            "affected_count": 18,
            "recommendation": "Compare MOMO settlement file #B-042 against internal ingestion manifest for 2024-07-07 14:00-15:00. Re-trigger ingestion for that window if missing files are found, then verify all 18 records appear.",
        },
        {
            "type": "amount_mismatch",
            "severity": "high",
            "title": "32 amount mismatches — avg delta 765K VND, 3 transactions drive 60% of impact",
            "description": "Amount mismatch across 32 transactions (2.6% of volume) totaling 24.5M VND. Pattern: concentrated — 3 large-value transactions (>5M VND each) account for 60% of total mismatch amount, suggesting a rate/fee application issue rather than random rounding errors. Average delta per outlier: 4.9M VND vs 82K VND for remaining 29.",
            "affected_count": 32,
            "recommendation": "Audit fee/commission configuration for MOMO transactions >5M VND. Compare partner-reported amounts against internal fee schedule for the 3 outlier transactions. Verify if a recent rate change was applied inconsistently.",
        },
        {
            "type": "partner_pattern",
            "severity": "medium",
            "title": "MOMO mismatch rate at 5.04% — second consecutive day above 5% threshold",
            "description": "Overall mismatch rate of 5.04% exceeds the 5% operational threshold. At this rate, ~63 transactions are affected daily, equivalent to ~1,890 records/month. This is the second consecutive day above threshold, suggesting a chronic issue rather than a one-day spike.",
            "affected_count": 63,
            "recommendation": "Escalate to MOMO partner operations team with the 3-day trend data. Schedule a root cause analysis call focused on the amount_mismatch cluster. Prepare daily monitoring dashboard for the next 5 business days.",
        },
    ]


# ---------------------------------------------------------------------------
# GET /api/v1/insights/discrepancies
# ---------------------------------------------------------------------------

@router.get("/insights/discrepancies")
async def insights_discrepancies(
    request: Request,
    partner: Optional[str] = Query(default=None, description="Partner identifier"),
    date: Optional[str] = Query(default=None, description="Date (YYYY-MM-DD)"),
    focus: Optional[str] = Query(
        default="operational",
        description="Analysis focus: operational | partner | inconsistency",
    ),
):
    """Get LLM-powered discrepancy analysis for a partner on a given date.

    Returns detailed analysis of discrepancies based on the specified focus type.

    **Parameters:**
    - `partner`: Partner identifier (required)
    - `date`: Date string in YYYY-MM-DD format (required)
    - `focus`: Analysis focus type (default: operational)
      - `operational`: MISSING_INTERNAL, MISSING_PARTNER, ingestion delays
      - `partner`: Mismatch rate trends, partner stability, volume patterns
      - `inconsistency`: AMOUNT_MISMATCH, STATUS_MISMATCH, recurring patterns

    **Response:**
    - List of AnalysisResult objects with type, severity, title, description,
      affected_count, and recommendation.
    """
    try:
        partner = _validate_partner(partner)
        date = _validate_date(date)
    except HTTPException:
        raise

    # Validate focus type
    valid_focuses = ("operational", "partner", "inconsistency")
    if focus not in valid_focuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid focus: '{focus}'. Must be one of: {', '.join(valid_focuses)}.",
        )

    try:
        from src.analysis.insights import get_discrepancies

        collection = _get_collection(request)
        llm_provider = _get_llm_provider()

        results = await get_discrepancies(
            partner=partner,
            date=date,
            focus=focus,
            collection=collection,
            llm_provider=llm_provider,
        )

        # Convert AnalysisResult objects to dicts for JSON response
        return [camelize(r.model_dump()) for r in results]

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error generating discrepancy insights: {exc}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate discrepancy insights: {str(exc)}",
        )


# ---------------------------------------------------------------------------
# GET /api/v1/reports/daily
# ---------------------------------------------------------------------------

@router.get("/reports/daily")
async def reports_daily(
    request: Request,
    date: Optional[str] = Query(default=None, description="Date (YYYY-MM-DD)"),
):
    """Get daily batch report for all active partners.

    Returns a consolidated report with summary metrics for each partner,
    global statistics, and any threshold alerts.

    **Parameters:**
    - `date`: Date string in YYYY-MM-DD format (required)

    **Response:**
    - `date`: Report date
    - `generated_at`: Timestamp of generation
    - `partners`: List of partner reports with summary_metrics, grouped_stats, key_findings
    - `global_stats`: Aggregated statistics across all partners
    - `alerts`: List of threshold breach alerts
    """
    try:
        date = _validate_date(date)
    except HTTPException:
        raise

    try:
        from src.analysis.reporter import DailyReporter
        from src.analysis.alerter import ThresholdAlerter

        collection = _get_collection(request)
        llm_provider = _get_llm_provider()
        config = AnalysisConfig()

        reporter = DailyReporter(collection, llm_provider, config)
        report = await reporter.generate_report(date)

        # Generate alerts for the report
        alerter = ThresholdAlerter(config)
        alerts = alerter.alerts_for_report(report)
        report["alerts"] = [a.model_dump() for a in alerts]

        # Add proper timestamp
        report["generated_at"] = datetime.now(timezone.utc).isoformat()

        return camelize(report)

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error generating daily report: {exc}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate daily report: {str(exc)}",
        )
