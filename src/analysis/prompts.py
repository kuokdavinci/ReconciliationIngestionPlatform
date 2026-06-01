"""Prompt templates for LLM insight generation.

Provides two prompt templates for MVP:
- build_system_prompt(): defines AI analysis assistant role, constraints, JSON output
- build_analysis_prompt(analysis_input): receives AnalysisInput, generates findings by focus type

Design principles:
- Deterministic output (JSON format)
- Idempotent (same input → same prompt)
- No raw data exposure (only aggregated/grouped data)
- Focus-aware (operational / partner / inconsistency)
"""

import json
from typing import Any

from src.analysis.schemas import AnalysisInput


# ---------------------------------------------------------------------------
# System prompt — defines the AI analysis assistant role and constraints
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an AI analysis assistant for payment reconciliation operations.

## Role
Analyze aggregated reconciliation metrics and provide actionable insights for operators.

## Constraints
1. ONLY discuss the data provided in the input — do not speculate beyond it.
2. Do NOT perform fraud detection — that is out of scope.
3. Output MUST be valid JSON — no markdown, no prose outside JSON.
4. Each insight must include: type, severity, title, description, affected_count, recommendation.
5. Severity must be determined based on the following guidelines:
   - critical: Mismatch rate > 10% OR affected transactions > 50.
   - high: Mismatch rate 5% - 10% OR affected transactions 20 - 50.
   - medium: Mismatch rate 1% - 5% OR affected transactions 5 - 20.
   - low: Mismatch rate < 1% OR affected transactions < 5.
6. Base all findings on the aggregated metrics, grouped stats, and anomalies provided.
7. Do NOT reference specific transaction IDs or individual amounts — only use ranges and totals.

## Output Format
Return a JSON object with a single key "findings" containing an array of insight objects:

```json
{
  "findings": [
    {
      "type": "<insight_type>",
      "severity": "low|medium|high|critical",
      "title": "<short_title>",
      "description": "<detailed_explanation>",
      "affected_count": <number>,
      "recommendation": "<suggested_action>"
    }
  ]
}
```

## Insight Types by Focus

### operational
Focus on: MISSING_INTERNAL, MISSING_PARTNER, ingestion delays, batch failures.
Look for patterns suggesting pipeline issues, scheduler failures, or data ingestion delays.

### partner
Focus on: mismatch rate trends, partner stability, volume patterns, partner-specific error rates.
Look for patterns suggesting partner-side issues or integration degradation.

### inconsistency
Focus on: AMOUNT_MISMATCH, STATUS_MISMATCH, recurring error patterns, amount clustering.
Look for systematic discrepancies rather than one-off errors.
"""


def build_system_prompt() -> str:
    """Build the system prompt for the LLM analysis assistant.

    Returns:
        System prompt string defining role, constraints, and output format.
    """
    return SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Analysis prompt — builds user prompt from AnalysisInput
# ---------------------------------------------------------------------------

_FOCUS_INSTRUCTIONS = {
    "operational": (
        "Analyze operational issues: focus on MISSING_INTERNAL and MISSING_PARTNER records. "
        "Identify potential ingestion delays, batch failures, or pipeline issues. "
        "Highlight any patterns suggesting systematic operational problems."
    ),
    "partner": (
        "Analyze partner behavior: focus on mismatch rate trends, partner stability, "
        "volume patterns, and partner-specific error rates. "
        "Identify any patterns suggesting partner-side issues or integration degradation."
    ),
    "inconsistency": (
        "Analyze data inconsistencies: focus on AMOUNT_MISMATCH and STATUS_MISMATCH records. "
        "Identify recurring error patterns, amount clustering, or systematic discrepancies. "
        "Distinguish between one-off errors and systematic issues."
    ),
}

_DEFAULT_FOCUS_INSTRUCTION = (
    "Analyze the provided reconciliation data and generate actionable insights. "
    "Focus on the most significant findings across all categories."
)


def _format_metrics_section(metrics: dict[str, Any]) -> str:
    """Format summary metrics into a readable text section.

    Args:
        metrics: Dictionary of summary metrics from MetricsService.

    Returns:
        Formatted string representation of the metrics.
    """
    lines = ["## Summary Metrics", ""]
    lines.append(f"- Total Transactions: {metrics.get('total_transactions', 'N/A')}")
    lines.append(f"- Matched: {metrics.get('matched', 'N/A')}")
    lines.append(f"- Mismatch Rate: {metrics.get('mismatch_rate', 'N/A')}%")
    lines.append(f"- Total Mismatch Amount: {metrics.get('total_amount_mismatch', 'N/A')}")

    by_status = metrics.get("by_status", {})
    if by_status:
        lines.append("")
        lines.append("### By Status")
        for status, count in by_status.items():
            lines.append(f"  - {status}: {count}")

    return "\n".join(lines)


def _format_grouped_stats_section(stats: list[dict[str, Any]]) -> str:
    """Format grouped statistics into a readable text section.

    Args:
        stats: List of grouped stat dictionaries from GroupingEngine.

    Returns:
        Formatted string representation of the grouped stats.
    """
    if not stats:
        return "## Grouped Stats\n\nNo grouped statistics available."

    lines = ["## Grouped Stats", ""]
    for group in stats:
        details = group.get("details", {})
        detail_str = ""
        if details:
            detail_parts = [f"{k}: {v}" for k, v in details.items()]
            detail_str = f" ({', '.join(detail_parts)})"

        lines.append(
            f"- **{group['key']}**: {group['count']} records "
            f"({group['percentage']}%), "
            f"total amount: {group.get('total_amount', 0)}{detail_str}"
        )

    return "\n".join(lines)


def _format_anomalies_section(anomalies: list[dict[str, Any]]) -> str:
    """Format top anomalies into a readable text section.

    Args:
        anomalies: List of anomaly dictionaries (pre-processed).

    Returns:
        Formatted string representation of the anomalies.
    """
    if not anomalies:
        return "## Top Anomalies\n\nNo anomalies detected."

    lines = ["## Top Anomalies", ""]
    for anomaly in anomalies:
        lines.append(
            f"- **{anomaly['type']}**: {anomaly['count']} occurrences, "
            f"partners: {', '.join(anomaly.get('partners_affected', []))}, "
            f"amount range: {anomaly.get('amount_range', 'N/A')}"
        )

    return "\n".join(lines)


def build_analysis_prompt(analysis_input: AnalysisInput) -> str:
    """Build the analysis prompt from a structured AnalysisInput.

    Receives aggregated data (no raw transactions) and generates a prompt
    asking the LLM to produce findings according to the specified focus type.

    Args:
        analysis_input: Structured input containing summary_metrics,
                        grouped_stats, top_anomalies, partner, date, focus.

    Returns:
        User prompt string for the LLM.
    """
    focus = analysis_input.focus or "operational"
    focus_instruction = _FOCUS_INSTRUCTIONS.get(focus, _DEFAULT_FOCUS_INSTRUCTION)

    sections = [
        f"# Reconciliation Analysis Request",
        "",
        f"**Partner:** {analysis_input.partner}",
        f"**Date:** {analysis_input.date}",
        f"**Focus:** {focus}",
        "",
        focus_instruction,
        "",
        _format_metrics_section(analysis_input.summary_metrics),
        "",
        _format_grouped_stats_section(analysis_input.grouped_stats),
        "",
        _format_anomalies_section(
            [a.model_dump() for a in analysis_input.top_anomalies]
        ),
        "",
        "Please analyze the data above and return your findings as a JSON object "
        'with a "findings" array, following the output format specified in the system prompt.',
    ]

    return "\n".join(sections)
