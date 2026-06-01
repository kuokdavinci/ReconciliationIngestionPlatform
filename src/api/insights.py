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

        return result

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error generating summary insights: {exc}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate summary insights: {str(exc)}",
        )


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
        return [r.model_dump() for r in results]

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

        return report

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error generating daily report: {exc}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate daily report: {str(exc)}",
        )
