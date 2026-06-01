"""Insight Generator — orchestration layer for AI Analysis.

Entry point for summary and discrepancies endpoints.
Orchestration flow:
1. Query MongoDB for reconciliation results
2. Compute metrics via MetricsService
3. Group results via GroupingEngine
4. Build AnalysisInput via services helpers
5. Call LLM with prompts
6. Parse response and return results

Fallback: if LLM fails, returns rule-based only results.
"""

import logging
import time
from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorCollection

from src.analysis.config import AnalysisConfig
from src.analysis.grouping import GroupingEngine
from src.analysis.metrics import MetricsService
from src.analysis.prompts import build_analysis_prompt, build_system_prompt
from src.analysis.provider import LLMProvider
from src.analysis.schemas import AnalysisInput, AnalysisResult, GroupResult, SummaryResult
from src.analysis.services import (
    build_analysis_input,
    format_findings,
    parse_llm_insights,
    rule_based_pre_process,
)
from src.core.enums import ReconciliationStatus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MongoDB query helper
# ---------------------------------------------------------------------------

async def _query_reconciliation_results(
    collection: AsyncIOMotorCollection,
    partner: str,
    date: str,
) -> list[Any]:
    """Query reconciliation results from MongoDB for a partner on a date.

    Args:
        collection: Motor collection for reconciliation_result.
        partner: Partner identifier to filter by.
        date: Date string (YYYY-MM-DD) to filter by.

    Returns:
        List of reconciliation result objects (as SimpleNamespace-like dicts).
    """
    from types import SimpleNamespace

    cursor = collection.find({"partner": partner, "date": date})
    docs = await cursor.to_list(length=None)

    results = []
    for doc in docs:
        # Convert MongoDB doc to object-like structure expected by
        # MetricsService and GroupingEngine
        result = SimpleNamespace()
        result.partner = doc.get("partner", partner)
        result.date = doc.get("date", date)
        
        # Support both camelCase (db native) and snake_case (class attribute)
        result.partner_amount = doc.get("partnerAmount") if "partnerAmount" in doc else doc.get("partner_amount")
        result.internal_amount = doc.get("internalAmount") if "internalAmount" in doc else doc.get("internal_amount")

        # Convert status string to ReconciliationStatus enum
        status_str = doc.get("reconciliationStatus") if "reconciliationStatus" in doc else doc.get("reconciliation_status", "MATCHED")
        try:
            result.reconciliation_status = ReconciliationStatus(status_str)
        except ValueError:
            result.reconciliation_status = ReconciliationStatus.MATCHED

        results.append(result)

    return results


# ---------------------------------------------------------------------------
# get_summary — orchestration for summary endpoint
# ---------------------------------------------------------------------------

async def get_summary(
    partner: str,
    date: str,
    collection: AsyncIOMotorCollection,
    llm_provider: LLMProvider,
    config: Optional[AnalysisConfig] = None,
) -> dict[str, Any]:
    """Generate summary insights for a partner on a given date.

    Orchestration flow:
    1. Query MongoDB → reconciliation results
    2. MetricsService.compute_summary() → SummaryResult
    3. GroupingEngine.group() → list[GroupResult]
    4. Build AnalysisInput → LLM for key_findings
    5. Return {summary_metrics, grouped_stats, key_findings}

    Args:
        partner: Partner identifier.
        date: Date string (YYYY-MM-DD).
        collection: Motor collection for reconciliation_result.
        llm_provider: LLM provider instance.
        config: Optional AnalysisConfig (uses defaults if not provided).

    Returns:
        Dict with summary_metrics, grouped_stats, key_findings, and metadata.
    """
    start_time = time.monotonic()

    # Step 1: Query MongoDB
    results = await _query_reconciliation_results(collection, partner, date)
    logger.info(
        f"Queried {len(results)} reconciliation results for {partner} on {date}",
        extra={"event": "ai_insight_query", "partner": partner, "date": date, "count": len(results)},
    )

    # Step 2: Compute metrics
    summary = MetricsService.compute_summary(results, partner, date)

    # Step 3: Group results
    groups = GroupingEngine.group(results)

    # Step 4: Build AnalysisInput for summary (operational focus)
    analysis_input = build_analysis_input(
        partner=partner,
        date=date,
        focus="operational",
        metrics_result=summary,
        grouped_results=groups,
    )

    # Step 5: LLM enrichment for key_findings
    key_findings: list[str] = []
    llm_status = "fallback"
    try:
        system_prompt = build_system_prompt()
        user_prompt = build_analysis_prompt(analysis_input)

        llm_response = await llm_provider.generate(user_prompt, system_prompt)
        parsed_results = parse_llm_insights(llm_response)

        if parsed_results:
            key_findings = format_findings(parsed_results)
            llm_status = "success"
        else:
            logger.warning("LLM returned no parseable findings, using rule-based fallback")
    except Exception as exc:
        logger.warning(f"LLM call failed, using rule-based fallback: {exc}")

    # Step 6: Build response
    grouped_stats = [
        {
            "key": g.key,
            "count": g.count,
            "percentage": g.percentage,
            "total_amount": g.total_amount,
            "details": g.details,
        }
        for g in groups
    ]

    elapsed_ms = round((time.monotonic() - start_time) * 1000, 2)
    logger.info(
        f"Summary generated in {elapsed_ms}ms for {partner} on {date}",
        extra={
            "event": "ai_insight_summary_complete",
            "partner": partner,
            "date": date,
            "latency_ms": elapsed_ms,
            "llm_status": llm_status,
        },
    )

    return {
        "partner": partner,
        "date": date,
        "summary_metrics": {
            "total_transactions": summary.total_transactions,
            "matched": summary.matched,
            "mismatch_rate": summary.mismatch_rate,
            "total_amount_mismatch": summary.total_amount_mismatch,
            "by_status": summary.by_status,
        },
        "grouped_stats": grouped_stats,
        "key_findings": key_findings,
        "generated_at": date,  # Will be replaced by actual timestamp in API layer
        "llm_status": llm_status,
    }


# ---------------------------------------------------------------------------
# get_discrepancies — orchestration for discrepancies endpoint
# ---------------------------------------------------------------------------

async def get_discrepancies(
    partner: str,
    date: str,
    focus: str,
    collection: AsyncIOMotorCollection,
    llm_provider: LLMProvider,
    config: Optional[AnalysisConfig] = None,
) -> list[AnalysisResult]:
    """Generate discrepancy insights for a partner on a given date.

    Orchestration flow:
    1. Query MongoDB → reconciliation results
    2. MetricsService.compute_summary() → SummaryResult
    3. GroupingEngine.group() → list[GroupResult]
    4. Rule-based pre-process → anomalies
    5. Build AnalysisInput → generate_insights()
    6. Return list[AnalysisResult]

    Args:
        partner: Partner identifier.
        date: Date string (YYYY-MM-DD).
        focus: Analysis focus (operational | partner | inconsistency).
        collection: Motor collection for reconciliation_result.
        llm_provider: LLM provider instance.
        config: Optional AnalysisConfig.

    Returns:
        List of AnalysisResult objects (LLM-enriched or rule-based fallback).
    """
    start_time = time.monotonic()

    # Step 1: Query MongoDB
    results = await _query_reconciliation_results(collection, partner, date)
    logger.info(
        f"Queried {len(results)} results for discrepancies ({focus}) for {partner} on {date}",
        extra={"event": "ai_insight_discrepancy_query", "partner": partner, "date": date, "focus": focus},
    )

    # Step 2: Compute metrics
    summary = MetricsService.compute_summary(results, partner, date)

    # Step 3: Group results
    groups = GroupingEngine.group(results)

    # Step 4: Rule-based pre-process
    summary_metrics_dict = {
        "total_transactions": summary.total_transactions,
        "matched": summary.matched,
        "mismatch_rate": summary.mismatch_rate,
        "total_amount_mismatch": summary.total_amount_mismatch,
        "by_status": summary.by_status,
        "partner": partner,
    }
    anomalies = rule_based_pre_process(results, focus, summary_metrics_dict)

    # Step 5: Build AnalysisInput
    analysis_input = build_analysis_input(
        partner=partner,
        date=date,
        focus=focus,
        metrics_result=summary,
        grouped_results=groups,
        anomalies=anomalies,
    )

    # Step 6: Generate insights
    insights = await generate_insights(analysis_input, llm_provider)

    elapsed_ms = round((time.monotonic() - start_time) * 1000, 2)
    logger.info(
        f"Discrepancies generated in {elapsed_ms}ms for {partner} on {date} (focus={focus})",
        extra={
            "event": "ai_insight_discrepancy_complete",
            "partner": partner,
            "date": date,
            "focus": focus,
            "latency_ms": elapsed_ms,
            "insight_count": len(insights),
        },
    )

    return insights


# ---------------------------------------------------------------------------
# generate_insights — rule-based pre-process + LLM enrich
# ---------------------------------------------------------------------------

async def generate_insights(
    analysis_input: AnalysisInput,
    llm_provider: LLMProvider,
) -> list[AnalysisResult]:
    """Generate insights from AnalysisInput using rule-based + LLM enrichment.

    Flow:
    1. Rule-based pre-process (already done in analysis_input.top_anomalies)
    2. Build prompts and call LLM
    3. Parse LLM response → AnalysisResult list
    4. Fallback: if LLM fails, return rule-based results

    Args:
        analysis_input: Structured input with metrics, groups, anomalies.
        llm_provider: LLM provider instance.

    Returns:
        List of AnalysisResult objects (LLM-enriched or rule-based fallback).
    """
    start_time = time.monotonic()

    try:
        system_prompt = build_system_prompt()
        user_prompt = build_analysis_prompt(analysis_input)

        logger.info(
            f"Calling LLM for {analysis_input.partner} on {analysis_input.date} (focus={analysis_input.focus})",
            extra={
                "event": "ai_insight_request",
                "partner": analysis_input.partner,
                "date": analysis_input.date,
                "focus": analysis_input.focus,
            },
        )

        llm_response = await llm_provider.generate(user_prompt, system_prompt)
        parsed_results = parse_llm_insights(llm_response)

        elapsed_ms = round((time.monotonic() - start_time) * 1000, 2)
        logger.info(
            f"LLM returned {len(parsed_results)} insights in {elapsed_ms}ms",
            extra={
                "event": "ai_insight_response",
                "partner": analysis_input.partner,
                "date": analysis_input.date,
                "latency_ms": elapsed_ms,
                "insight_count": len(parsed_results),
            },
        )

        if parsed_results:
            return parsed_results

        # LLM returned empty findings — fallback to rule-based
        logger.warning("LLM returned no findings, falling back to rule-based")

    except Exception as exc:
        elapsed_ms = round((time.monotonic() - start_time) * 1000, 2)
        logger.warning(
            f"LLM call failed after {elapsed_ms}ms, falling back to rule-based: {exc}",
            extra={
                "event": "ai_insight_llm_error",
                "partner": analysis_input.partner,
                "date": analysis_input.date,
                "latency_ms": elapsed_ms,
                "error": str(exc),
            },
        )

    # Rule-based fallback
    return _rule_based_fallback(analysis_input)


# ---------------------------------------------------------------------------
# Rule-based fallback — generates insights without LLM
# ---------------------------------------------------------------------------

def _rule_based_fallback(analysis_input: AnalysisInput) -> list[AnalysisResult]:
    """Generate rule-based insights when LLM is unavailable.

    Creates basic AnalysisResult objects from the aggregated data
    without natural language enrichment.

    Args:
        analysis_input: Structured input with metrics, groups, anomalies.

    Returns:
        List of AnalysisResult objects (rule-based only).
    """
    results = []
    metrics = analysis_input.summary_metrics
    focus = analysis_input.focus

    # Mismatch rate insight
    mismatch_rate = metrics.get("mismatch_rate", 0)
    if mismatch_rate > 0:
        severity = "critical" if mismatch_rate > 20 else "high" if mismatch_rate > 10 else "medium" if mismatch_rate > 5 else "low"
        results.append(
            AnalysisResult(
                type="mismatch_rate",
                severity=severity,
                title=f"Mismatch rate: {mismatch_rate}%",
                description=f"Overall mismatch rate is {mismatch_rate}% for {analysis_input.partner} on {analysis_input.date}.",
                affected_count=metrics.get("total_transactions", 0) - metrics.get("matched", 0),
                recommendation="Review mismatched transactions for patterns.",
            )
        )

    # Anomaly-based insights from top_anomalies
    for anomaly in analysis_input.top_anomalies:
        severity = "high" if anomaly.count > 10 else "medium" if anomaly.count > 5 else "low"
        results.append(
            AnalysisResult(
                type=anomaly.type,
                severity=severity,
                title=f"Detected {anomaly.type}: {anomaly.count} occurrences",
                description=f"Found {anomaly.count} {anomaly.type} anomalies"
                + (f" for partners: {', '.join(anomaly.partners_affected)}" if anomaly.partners_affected else "")
                + (f" in amount range {anomaly.amount_range}" if anomaly.amount_range else ""),
                affected_count=anomaly.count,
                recommendation=f"Investigate {anomaly.type} pattern.",
            )
        )

    # Status-specific insights
    by_status = metrics.get("by_status", {})
    missing_internal = by_status.get("MISSING_INTERNAL", 0)
    if missing_internal > 0:
        results.append(
            AnalysisResult(
                type="missing_internal",
                severity="medium" if missing_internal > 5 else "low",
                title=f"{missing_internal} missing internal records",
                description=f"{missing_internal} transactions are MISSING_INTERNAL — internal system has not received data.",
                affected_count=missing_internal,
                recommendation="Check ingestion pipeline for data delivery delays.",
            )
        )

    missing_partner = by_status.get("MISSING_PARTNER", 0)
    if missing_partner > 0:
        results.append(
            AnalysisResult(
                type="missing_partner",
                severity="medium" if missing_partner > 5 else "low",
                title=f"{missing_partner} missing partner records",
                description=f"{missing_partner} transactions are MISSING_PARTNER — partner has not provided data.",
                affected_count=missing_partner,
                recommendation="Contact partner to verify data delivery.",
            )
        )

    return results
