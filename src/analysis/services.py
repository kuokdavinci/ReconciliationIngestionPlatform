"""Helper functions for the AI Analysis Layer orchestration.

Pure functions only — no IO, no query, no orchestration.
Provides:
- build_analysis_input(): build standardized input contract for LLM
- parse_llm_insights(): parse JSON response from LLM into AnalysisResult list
- format_findings(): format AnalysisResult list into short string findings

These helpers are used by insights.py (orchestration layer) but contain
no business logic themselves — only data transformation.
"""

import json
import logging
from typing import Any

from src.analysis.schemas import AnalysisInput, AnalysisResult, GroupResult, SummaryResult, TopAnomaly

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# build_analysis_input — constructs the LLM input contract
# ---------------------------------------------------------------------------

def build_analysis_input(
    partner: str,
    date: str,
    focus: str,
    metrics_result: SummaryResult,
    grouped_results: list[GroupResult],
    anomalies: list[TopAnomaly] | None = None,
) -> AnalysisInput:
    """Build a standardized AnalysisInput from metrics and grouped output.

    This is the ONLY place where AnalysisInput is constructed. It ensures
    the contract is always valid and follows the privacy rules (no raw data).

    Args:
        partner: Partner identifier.
        date: Date string (YYYY-MM-DD).
        focus: Analysis focus type (operational | partner | inconsistency).
        metrics_result: SummaryResult from MetricsService.compute_summary().
        grouped_results: List of GroupResult from GroupingEngine.group().
        anomalies: Optional list of pre-processed TopAnomaly objects.

    Returns:
        AnalysisInput ready to be sent to the LLM.
    """
    summary_metrics = {
        "total_transactions": metrics_result.total_transactions,
        "matched": metrics_result.matched,
        "mismatch_rate": metrics_result.mismatch_rate,
        "total_amount_mismatch": metrics_result.total_amount_mismatch,
        "by_status": metrics_result.by_status,
    }

    grouped_stats = [
        {
            "key": g.key,
            "count": g.count,
            "percentage": g.percentage,
            "total_amount": g.total_amount,
            "details": g.details,
        }
        for g in grouped_results
    ]

    return AnalysisInput(
        partner=partner,
        date=date,
        focus=focus,
        summary_metrics=summary_metrics,
        grouped_stats=grouped_stats,
        top_anomalies=anomalies or [],
    )


# ---------------------------------------------------------------------------
# parse_llm_insights — parses LLM JSON response into AnalysisResult list
# ---------------------------------------------------------------------------

def _extract_json_from_response(llm_response: str) -> dict[str, Any] | None:
    """Extract JSON object from LLM response string.

    Handles cases where the LLM wraps JSON in markdown code blocks
    or includes extra text around the JSON.

    Args:
        llm_response: Raw string response from the LLM.

    Returns:
        Parsed JSON dict, or None if extraction fails.
    """
    # Try direct parse first
    try:
        return json.loads(llm_response)
    except json.JSONDecodeError:
        pass

    # Try to extract from markdown code blocks
    import re

    # Look for ```json ... ``` or ``` ... ``` blocks
    pattern = r"```(?:json)?\s*\n(.*?)\n```"
    match = re.search(pattern, llm_response, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find a JSON object by looking for { ... } pattern
    start = llm_response.find("{")
    end = llm_response.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(llm_response[start : end + 1])
        except json.JSONDecodeError:
            pass

    return None


def parse_llm_insights(llm_response: str) -> list[AnalysisResult]:
    """Parse LLM JSON response into a list of AnalysisResult objects.

    Legacy parser — uses manual dict extraction.
    Prefer parse_structured_insight() for new code.

    Expected JSON format:
    ```json
    {
      "findings": [
        {
          "type": "operational_delay",
          "severity": "medium",
          "title": "Delay detected",
          "description": "...",
          "affected_count": 5,
          "recommendation": "..."
        }
      ]
    }
    ```

    Args:
        llm_response: Raw string response from the LLM.

    Returns:
        List of AnalysisResult objects. Empty list if parsing fails.
    """
    data = _extract_json_from_response(llm_response)
    if data is None:
        logger.warning("Failed to parse LLM response as JSON")
        return []

    findings = data.get("findings", [])
    if not isinstance(findings, list):
        logger.warning("LLM response 'findings' is not a list")
        return []

    results = []
    for finding in findings:
        try:
            result = AnalysisResult(
                type=str(finding.get("type", "unknown")),
                severity=str(finding.get("severity", "low")),
                title=str(finding.get("title", "")),
                description=str(finding.get("description", "")),
                affected_count=int(finding.get("affected_count", 0)),
                recommendation=str(finding.get("recommendation", "")),
            )
            results.append(result)
        except (TypeError, ValueError) as exc:
            logger.warning(f"Skipping invalid finding: {exc}")
            continue

    return results


def parse_structured_insight(
    llm_response: str,
) -> tuple[list[AnalysisResult], bool]:
    """Parse LLM response using the AIInsight schema with pydantic validation.

    Uses AIInsightResponse pydantic model for strict schema validation.
    Returns both parsed results and a schema_valid flag.

    Args:
        llm_response: Raw string response from the LLM.

    Returns:
        Tuple of (list of AnalysisResult, schema_valid boolean).
        If schema validation fails, returns (empty list, False).
    """
    from src.analysis.schemas import AIInsightResponse

    data = _extract_json_from_response(llm_response)
    if data is None:
        logger.warning("Failed to parse LLM response as JSON")
        return [], False

    try:
        validated = AIInsightResponse(**data)
        results = [
            AnalysisResult(
                type=insight.type,
                severity=insight.severity,
                title=insight.title,
                description=insight.description,
                affected_count=insight.affected_count,
                recommendation=insight.recommendation,
            )
            for insight in validated.findings
        ]
        return results, True
    except Exception as exc:
        logger.warning(f"Schema validation failed for LLM response: {exc}")
        return [], False


# ---------------------------------------------------------------------------
# format_findings — formats AnalysisResult list into short strings
# ---------------------------------------------------------------------------

def format_findings(analysis_results: list[AnalysisResult]) -> list[str]:
    """Format AnalysisResult list into short string findings.

    Used by the summary endpoint to present key findings concisely.
    Each string is a one-line summary suitable for display.

    Args:
        analysis_results: List of AnalysisResult objects.

    Returns:
        List of short string representations.
    """
    if not analysis_results:
        return []

    findings = []
    for r in analysis_results:
        severity_marker = {
            "critical": "[CRITICAL]",
            "high": "[HIGH]",
            "medium": "[MEDIUM]",
            "low": "[LOW]",
        }.get(r.severity.lower(), "")

        finding = f"{severity_marker} {r.title}"
        if r.affected_count > 0:
            finding += f" ({r.affected_count} affected)"
        findings.append(finding)

    return findings


# ---------------------------------------------------------------------------
# Rule-based pre-processing helpers for focus-specific anomaly detection
# ---------------------------------------------------------------------------

def _get_status_value(result: Any) -> str:
    """Extract status value string from a reconciliation result.

    Args:
        result: Object with reconciliation_status attribute.

    Returns:
        Status string value.
    """
    status = result.reconciliation_status
    return status.value if hasattr(status, "value") else str(status)


def extract_operational_anomalies(results: list[Any]) -> list[TopAnomaly]:
    """Extract operational anomalies from reconciliation results.

    Focuses on MISSING_INTERNAL and MISSING_PARTNER records.

    Args:
        results: List of reconciliation result objects.

    Returns:
        List of TopAnomaly objects for operational issues.
    """
    missing_internal = []
    missing_partner = []

    for r in results:
        status = _get_status_value(r)
        if status == "MISSING_INTERNAL":
            missing_internal.append(r)
        elif status == "MISSING_PARTNER":
            missing_partner.append(r)

    anomalies = []
    if missing_internal:
        partner = getattr(missing_internal[0], "partner", "unknown")
        anomalies.append(
            TopAnomaly(
                type="missing_internal",
                count=len(missing_internal),
                partners_affected=[partner] if isinstance(partner, str) else [],
                amount_range="N/A",
            )
        )
    if missing_partner:
        partner = getattr(missing_partner[0], "partner", "unknown")
        anomalies.append(
            TopAnomaly(
                type="missing_partner",
                count=len(missing_partner),
                partners_affected=[partner] if isinstance(partner, str) else [],
                amount_range="N/A",
            )
        )

    return anomalies


def extract_partner_anomalies(
    results: list[Any],
    summary_metrics: dict[str, Any],
) -> list[TopAnomaly]:
    """Extract partner-focused anomalies from reconciliation results.

    Focuses on mismatch rate and partner-specific patterns.

    Args:
        results: List of reconciliation result objects.
        summary_metrics: Pre-computed metrics dictionary.

    Returns:
        List of TopAnomaly objects for partner issues.
    """
    anomalies = []
    mismatch_rate = summary_metrics.get("mismatch_rate", 0)
    by_status = summary_metrics.get("by_status", {})

    if mismatch_rate > 5.0:
        anomalies.append(
            TopAnomaly(
                type="high_mismatch_rate",
                count=int(summary_metrics.get("total_transactions", 0) * mismatch_rate / 100),
                partners_affected=[summary_metrics.get("partner", "unknown")] if isinstance(summary_metrics.get("partner"), str) else [],
                amount_range="N/A",
            )
        )

    return anomalies


def extract_inconsistency_anomalies(results: list[Any]) -> list[TopAnomaly]:
    """Extract inconsistency-focused anomalies from reconciliation results.

    Focuses on AMOUNT_MISMATCH and STATUS_MISMATCH records.

    Args:
        results: List of reconciliation result objects.

    Returns:
        List of TopAnomaly objects for inconsistency issues.
    """
    from decimal import Decimal

    amount_mismatches = []
    status_mismatches = []

    for r in results:
        status = _get_status_value(r)
        if status in ("AMOUNT_MISMATCH", "MULTIPLE_MISMATCH"):
            amount_mismatches.append(r)
        elif status == "STATUS_MISMATCH":
            status_mismatches.append(r)

    anomalies = []
    if amount_mismatches:
        # Compute amount range label for the cluster
        diffs = []
        for r in amount_mismatches:
            partner_amt = getattr(r, "partner_amount", None)
            internal_amt = getattr(r, "internal_amount", None)
            if partner_amt is not None and internal_amt is not None:
                diff = abs(
                    (partner_amt if isinstance(partner_amt, Decimal) else Decimal(str(partner_amt)))
                    - (internal_amt if isinstance(internal_amt, Decimal) else Decimal(str(internal_amt)))
                )
                diffs.append(diff)

        if diffs:
            avg_diff = float(sum(diffs) / len(diffs))
            if avg_diff < 100_000:
                range_label = "0-100k"
            elif avg_diff < 1_000_000:
                range_label = "100k-1M"
            else:
                range_label = "1M+"
        else:
            range_label = "N/A"

        anomalies.append(
            TopAnomaly(
                type="amount_mismatch_cluster",
                count=len(amount_mismatches),
                partners_affected=[],
                amount_range=range_label,
            )
        )

    if status_mismatches:
        anomalies.append(
            TopAnomaly(
                type="status_mismatch_cluster",
                count=len(status_mismatches),
                partners_affected=[],
                amount_range="N/A",
            )
        )

    return anomalies


def rule_based_pre_process(
    results: list[Any],
    focus: str,
    summary_metrics: dict[str, Any] | None = None,
) -> list[TopAnomaly]:
    """Rule-based pre-processing of reconciliation results by focus type.

    Generates TopAnomaly objects before LLM enrichment.

    Args:
        results: List of reconciliation result objects.
        focus: Analysis focus type (operational | partner | inconsistency).
        summary_metrics: Optional pre-computed metrics (used for partner focus).

    Returns:
        List of TopAnomaly objects for the given focus type.
    """
    if focus == "operational":
        return extract_operational_anomalies(results)
    elif focus == "partner":
        return extract_partner_anomalies(results, summary_metrics or {})
    elif focus == "inconsistency":
        return extract_inconsistency_anomalies(results)
    else:
        return []
