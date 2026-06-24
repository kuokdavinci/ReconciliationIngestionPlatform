"""Prompt templates for LLM insight generation.

Provides two prompt templates:
- build_system_prompt(): defines AI analysis assistant role, constraints, JSON output
- build_analysis_prompt(analysis_input): receives AnalysisInput, generates findings by focus type

Design principles:
- Deterministic output (JSON format)
- Idempotent (same input → same prompt)
- No raw data exposure (only aggregated/grouped data)
- Focus-aware (operational / partner / inconsistency)
- Concrete, quantified recommendations — not generic platitudes
"""

from typing import Any

from src.analysis.schemas import AnalysisInput


# ---------------------------------------------------------------------------
# System prompt — defines the AI analysis assistant role and constraints
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an AI analysis assistant for payment reconciliation operations.

## Role
Analyze aggregated reconciliation metrics and provide **concrete, quantified, actionable insights** for operations teams. Your goal is to help operators understand WHAT happened, WHY it matters, and WHAT to do next.

## Quality Rubric — What makes a good insight

An insight is **high quality** when it:
1. Quantifies impact — "18 records (1.4%) worth 24.5M VND"
2. Distinguishes pattern type — "systematic" (affects >60% of batch) vs "sporadic" (random single records)
3. Identifies concentration — are problems spread evenly or concentrated in specific partners/amount ranges?
4. Provides forward-looking signal — "if this trend continues, it will affect X transactions tomorrow"
5. Recommends a specific next step — not "investigate", but "compare partner settlement file against ingestion manifest for batch #1234"

An insight is **poor** when it:
- States the obvious: "There are 18 missing internal records" (data already says this)
- Gives vague recommendations: "Investigate and resolve"
- Parrots the input without adding analysis
- Mentions exact transaction IDs or individual PII

## Constraints
1. ONLY discuss the data provided in the input — do not speculate beyond it.
2. Do NOT perform fraud detection — that is out of scope.
3. Output MUST be valid JSON — no markdown, no prose outside JSON.
4. Each insight must include: type, severity, title, description, affected_count, recommendation.
5. Do NOT reference specific transaction IDs or individual amounts — only use ranges and totals.
6. Generate AT MOST 1 finding per analysis. Zero findings is acceptable when data is clean.
7. If there are multiple findings, ORDER them by business impact (most critical first).
8. **CRITICAL: Use the exact `mismatch_rate` value from Summary Metrics.** Do NOT recompute mismatch rate from the grouped stats or by_status counts. The `mismatch_rate` in Summary Metrics is the authoritative ground truth. If you need to reference mismatch rate in a finding, use that exact number.
9. Treat each response as an operator card, not a raw anomaly list. Merge closely related signals into one synthesized finding when they point to the same operational action.
10. Prefer breadth over fragmentation: one strong finding that covers the dominant pattern is better than several narrow findings.

## Severity Guidelines

Severity is NOT just a function of mismatch rate %. Consider ALL three factors:

| Severity | Mismatch Rate | Affected Count | Monetary Impact |
|----------|--------------|----------------|-----------------|
| critical | > 10% | > 50 tx | > 500M VND |
| high | 5-10% | 20-50 tx | 100M-500M VND |
| medium | 1-5% | 5-20 tx | 10M-100M VND |
| low | < 1% | < 5 tx | < 10M VND |

Use the MOST SEVERE applicable column to determine final severity.
Example: mismatch rate 2% (medium) but monetary impact 800M VND (critical) → severity = critical.

## Pattern Detection Guide

For each finding, classify the underlying pattern:

1. **Systematic error** — affects a consistent subset (e.g., all transactions from a specific hour/partner/amount range)
2. **Random/sporadic** — no clear pattern in affected records
3. **Concentrated** — most impact comes from a few large-value items
4. **Broad/even** — small impact spread across many items

Include this pattern type in the description.

## Output Format

Return a JSON object with a single key "findings" containing an array of insight objects:

```json
{
  "findings": [
    {
      "type": "<insight_type>",
      "severity": "low|medium|high|critical",
      "title": "<very_short_scan_friendly_title_max_6_words>",
      "description": "<detailed_explanation_with_quantified_impact_and_pattern>",
      "affected_count": <number>,
      "recommendation": "<specific_actionable_next_step>"
    }
  ]
}
```

## Operator Card Rules
1. Return no more than one finding for this request.
2. That finding should summarize the highest-value operator takeaway for the requested focus.
3. If several symptoms share the same next action, merge them into one finding instead of listing them separately.
4. Use the description to mention supporting secondary signals briefly, rather than creating extra findings.
5. Recommendations must be phrased as the next operational move, not as a generic investigation note.

## Title and Scanning Rules
1. Make the `title` extremely concise, short (maximum 4-6 words), and scan-friendly.
2. It MUST immediately state the error type and impact (e.g., 'Ingestion: 77 records missing' or 'Amount Mismatch: 32 records' or 'MOMO Mismatch: 5%').
3. Avoid long descriptions or wordy titles.

## Example Insights

### Good (high quality & concise title)
```json
{
  "type": "missing_internal",
  "severity": "high",
  "title": "Ingestion: 18 records missing",
  "description": "18 transactions (1.4% of total, 24.5M VND) exist on MOMO side but are missing internally. Pattern: concentrated — all 18 records share a 10-minute window (14:20-14:30), suggesting a batch ingestion failure rather than random data loss. If this gap repeats daily, it would affect ~500 records/month.",
  "affected_count": 18,
  "recommendation": "Compare MOMO settlement file #B-042 against internal ingestion manifest for 2024-07-07 14:00-15:00. Re-trigger ingestion for that window if missing files are found."
}
```

### Poor (too wordy title)
```json
{
  "type": "missing_internal",
  "severity": "high",
  "title": "There are 18 internal records that are missing which indicates potential ingestion gap in batch #B-042",
  "description": "There are 18 missing internal records.",
  "affected_count": 18,
  "recommendation": "Investigate missing records."
}
```
  "type": "missing_internal",
  "severity": "medium",
  "title": "Missing internal records found",
  "description": "There are 18 missing internal records.",
  "affected_count": 18,
  "recommendation": "Investigate missing records."
}
```

## Insight Types by Focus

### operational
Focus on: MISSING_INTERNAL, MISSING_PARTNER, ingestion delays, batch failures.
Look for: temporal clustering (same time window), single-partner vs multi-partner patterns, ingestion pipeline gaps.

### partner
Focus on: mismatch rate trends, partner stability, volume patterns, partner-specific error rates.
Look for: degradation signals (rate increasing over time), partner-side data quality issues, integration health.

### inconsistency
Focus on: AMOUNT_MISMATCH, STATUS_MISMATCH, recurring error patterns, amount clustering.
Look for: systematic discrepancies (same amount delta across records), rounding/truncation patterns, vs one-off errors.
"""


def build_system_prompt() -> str:
    return SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Focus-specific instructions with concrete analytical questions
# ---------------------------------------------------------------------------

_FOCUS_INSTRUCTIONS = {
    "operational": (
        "Analyze operational issues with these specific questions in mind:\n"
        "1. TEMPORAL CLUSTERING: Do the MISSING_INTERNAL/MISSING_PARTNER records share a common time window? "
        "If so, it suggests a batch/scheduler failure, not random data loss.\n"
        "2. MONETARY IMPACT: What is the total VND amount of affected transactions? "
        "Is the impact concentrated in a few large-value items or spread across many small ones?\n"
        "3. INGESTION HEALTH: Based on the ratio of missing internal vs partner records, "
        "is the problem on our side (ingestion) or partner side (delivery)?\n"
        "4. ACTION SIGNAL: If this pattern repeats daily, what would the monthly impact be?"
    ),
    "partner": (
        "Analyze partner behavior with these specific questions in mind:\n"
        "1. STABILITY SIGNAL: Is the mismatch rate stable, improving, or degrading compared to expected norms? "
        "Note whether this is a new issue or a chronic condition.\n"
        "2. VOLUME ANALYSIS: What proportion of the partner's volume is affected? "
        "A 5% mismatch on 10,000 transactions (500 records) is very different from 5% on 100 (5 records).\n"
        "3. ERROR CONCENTRATION: Are the mismatches concentrated in specific transaction types, "
        "amount ranges, or time periods?\n"
        "4. INTEGRATION HEALTH: Based on the pattern, is this likely a configuration issue "
        "(wrong mapping/fee schedule) or a data delivery issue (missing/incomplete files)?"
    ),
    "inconsistency": (
        "Analyze data inconsistencies with these specific questions in mind:\n"
        "1. SYSTEMATIC vs RANDOM: Do amount mismatches show a consistent difference pattern "
        "(e.g., always off by exact percentage suggesting fee/commission issue)?\n"
        "2. ROUNDING/PRECISION: Are differences clustered around round numbers "
        "(suggesting truncation) or varying amounts (suggesting rate/fee mismatch)?\n"
        "3. STATUS CONCENTRATION: Are STATUS_MISMATCH records clustered under specific "
        "status pairs that suggest a mapping gap?\n"
        "4. MONETARY DISTRIBUTION: What is the avg/median/max difference? "
        "Is total mismatch impact driven by a few extreme outliers?"
    ),
}

_DEFAULT_FOCUS_INSTRUCTION = (
    "Analyze the provided reconciliation data and generate actionable insights. "
    "Focus on the most significant findings across all categories. "
    "For each finding, identify whether the pattern is systematic or sporadic, "
    "quantify the monetary impact, and suggest a specific next action."
)


def _format_metrics_section(metrics: dict[str, Any]) -> str:
    """Format summary metrics into a readable text section."""
    lines = ["## Summary Metrics", ""]
    lines.append(f"- Total Transactions: {metrics.get('total_transactions', 'N/A')}")
    lines.append(f"- Matched: {metrics.get('matched', 'N/A')}")
    lines.append(f"- Mismatch Rate: {metrics.get('mismatch_rate', 'N/A')}%")
    lines.append(f"- Total Mismatch Amount: {_fmt_amount(metrics.get('total_amount_mismatch', 0))}")

    by_status = metrics.get("by_status", {})
    if by_status:
        lines.append("")
        lines.append("### By Status")
        for status, count in by_status.items():
            pct = ""
            total = metrics.get("total_transactions", 0)
            if total:
                pct = f" ({count / total * 100:.1f}%)"
            lines.append(f"  - {status}: {count}{pct}")

    return "\n".join(lines)


def _format_grouped_stats_section(stats: list[dict[str, Any]]) -> str:
    """Format grouped statistics into a readable text section."""
    if not stats:
        return "## Grouped Stats\n\nNo grouped statistics available."

    lines = ["## Grouped Stats", ""]
    for group in stats:
        details = group.get("details", {})
        detail_str = ""
        if details:
            detail_parts = [f"{k}: {v}" for k, v in details.items()]
            detail_str = f" ({', '.join(detail_parts)})"

        amt = group.get("total_amount", 0)
        lines.append(
            f"- **{group['key']}**: {group['count']} records "
            f"({group['percentage']:.1f}%), "
            f"amount: {_fmt_amount(amt)}{detail_str}"
        )

    return "\n".join(lines)


def _format_anomalies_section(anomalies: list[dict[str, Any]]) -> str:
    """Format top anomalies into a readable text section."""
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


def _format_selected_error_signals_section(signals: list[dict[str, Any]]) -> str:
    """Format bounded, selected error signals for the LLM."""
    if not signals:
        return "## Selected Error Signals\n\nNo selected error signals available."

    lines = ["## Selected Error Signals", ""]
    for signal in signals:
        lines.append(
            f"- **{signal['status']}**: {signal['sample_count']} sampled records, "
            f"range: {signal.get('amount_range', 'N/A')}, "
            f"pattern hint: {signal.get('pattern_hint', 'N/A')}"
        )
    return "\n".join(lines)


def _fmt_amount(amount: float | int) -> str:
    """Format a monetary amount for display."""
    if amount >= 1_000_000_000:
        return f"{amount / 1_000_000_000:.2f}B VND"
    if amount >= 1_000_000:
        return f"{amount / 1_000_000:.1f}M VND"
    if amount >= 1_000:
        return f"{amount / 1_000:.0f}K VND"
    return f"{amount:,.0f} VND"


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
        "# Reconciliation Analysis Request",
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
        _format_selected_error_signals_section(
            [s.model_dump() for s in analysis_input.selected_error_signals]
        ),
        "",
        "---",
        "",
        "Now analyze the data above and return your findings as a JSON object "
        'with a "findings" array. Follow the system prompt\'s quality rubric — '
        "quantify impact, identify patterns, and give specific recommendations. "
        "Return at most one synthesized operator card for this focus. "
        "If multiple symptoms point to the same action, merge them into that single finding and mention the supporting signals in the description. "
        "If the data is clean (no significant mismatches), return an empty findings array.",
    ]

    return "\n".join(sections)
