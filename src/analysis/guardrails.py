"""Post-LLM guardrail validation for AI insight quality.

Validates LLM-generated insights against the structured input data
before they reach the API consumer. Pure deterministic validation —
no additional LLM calls.

Checks performed:
1. Severity vs actual metrics (low mismatch rate + critical severity = flagged)
2. Affected count exceeding available data volume
3. Focus-type consistency (e.g. partner claim under operational focus)
4. Anomaly count consistency against pre-computed TopAnomaly values
"""

import re
from typing import Any

from src.analysis.schemas import AnalysisInput, AnalysisResult

_SEVERITY_ORDER = {"low": 1, "medium": 2, "high": 3, "critical": 4}


class GuardrailFinding:
    """A single guardrail validation finding."""

    def __init__(
        self,
        risk: str,
        insight_index: int,
        field: str,
        message: str,
        detail: str = "",
    ) -> None:
        self.risk = risk
        self.insight_index = insight_index
        self.field = field
        self.message = message
        self.detail = detail

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk": self.risk,
            "insight_index": self.insight_index,
            "field": self.field,
            "message": self.message,
            "detail": self.detail,
        }


class GuardrailResult:
    """Structured output from guardrail validation."""

    def __init__(self) -> None:
        self.findings: list[GuardrailFinding] = []

    def add(self, finding: GuardrailFinding) -> None:
        self.findings.append(finding)

    @property
    def is_valid(self) -> bool:
        return all(f.risk != "high" for f in self.findings)

    @property
    def risk_level(self) -> str:
        risks = {f.risk for f in self.findings}
        if "high" in risks:
            return "high"
        if "medium" in risks:
            return "medium"
        if "low" in risks:
            return "low"
        return "none"

    @property
    def unsupported_claims(self) -> list[GuardrailFinding]:
        return [f for f in self.findings if f.risk == "high"]

    @property
    def warnings(self) -> list[GuardrailFinding]:
        return [f for f in self.findings if f.risk in ("medium", "low")]

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "risk_level": self.risk_level,
            "unsupported_count": len(self.unsupported_claims),
            "warning_count": len(self.warnings),
            "findings": [f.to_dict() for f in self.findings],
        }


def _check_severity_vs_metrics(
    result: GuardrailResult,
    insights: list[AnalysisResult],
    input_data: AnalysisInput,
) -> None:
    """Check if severity levels match the actual metrics.

    - critical severity with mismatch_rate < 5% → high risk
    - high severity with mismatch_rate < 1% → high risk
    """
    metrics = input_data.summary_metrics
    mismatch_rate = metrics.get("mismatch_rate", 0)
    total_tx = metrics.get("total_transactions", 0)

    for i, insight in enumerate(insights):
        sev = insight.severity.lower()
        sev_level = _SEVERITY_ORDER.get(sev, 0)

        if sev_level >= 4 and mismatch_rate < 5:
            result.add(GuardrailFinding(
                risk="high",
                insight_index=i,
                field="severity",
                message=f"Critical severity with {mismatch_rate}% mismatch rate",
                detail=f"Severity '{sev}' exceeds what {mismatch_rate}% mismatch rate warrants",
            ))
        elif sev_level >= 3 and mismatch_rate < 1:
            result.add(GuardrailFinding(
                risk="high",
                insight_index=i,
                field="severity",
                message=f"High severity with {mismatch_rate}% mismatch rate",
                detail=f"Severity '{sev}' is disproportionate to {mismatch_rate}% mismatch rate",
            ))
        elif sev_level >= 3 and mismatch_rate < 5:
            result.add(GuardrailFinding(
                risk="low",
                insight_index=i,
                field="severity",
                message=f"Slightly elevated severity ({sev}) for {mismatch_rate}% mismatch rate",
                detail="",
            ))

        if total_tx > 0 and insight.affected_count > total_tx:
            result.add(GuardrailFinding(
                risk="high",
                insight_index=i,
                field="affected_count",
                message=f"Affected count {insight.affected_count} exceeds total transactions {total_tx}",
                detail=f"Cannot have {insight.affected_count} affected out of {total_tx} total",
            ))


def _check_focus_consistency(
    result: GuardrailResult,
    insights: list[AnalysisResult],
    input_data: AnalysisInput,
) -> None:
    """Check if insight types align with the requested focus.

    - operational focus should not claim partner-specific findings
    - partner focus should not claim ingestion pipeline issues
    - inconsistency focus should not claim operational delays
    """
    focus = input_data.focus
    for i, insight in enumerate(insights):
        insight_type = insight.type.lower() if insight.type else ""
        title = insight.title.lower() if insight.title else ""
        combined = f"{insight_type} {title}"

        if focus == "operational" and any(w in combined for w in ("partner_stability", "partner_pattern")):
            result.add(GuardrailFinding(
                risk="medium",
                insight_index=i,
                field="type",
                message=f"Partner-focused claim under operational focus: '{insight.type}'",
                detail="Operational analysis should focus on ingestion/pipeline issues",
            ))

        if focus == "partner" and any(w in combined for w in ("ingestion", "pipeline", "batch_fail")):
            result.add(GuardrailFinding(
                risk="medium",
                insight_index=i,
                field="type",
                message=f"Ingestion-focused claim under partner focus: '{insight.type}'",
                detail="Partner analysis should focus on partner-side patterns",
            ))

        if focus == "inconsistency" and any(w in combined for w in ("operational_delay", "missing_internal", "batch")):
            result.add(GuardrailFinding(
                risk="low",
                insight_index=i,
                field="type",
                message=f"Operational claim under inconsistency focus: '{insight.type}'",
                detail="",
            ))


def _check_anomaly_consistency(
    result: GuardrailResult,
    insights: list[AnalysisResult],
    input_data: AnalysisInput,
) -> None:
    """Cross-reference LLM claims against known TopAnomaly values.

    If the LLM mentions an anomaly type that exists in top_anomalies,
    the claimed counts should roughly match.
    """
    anomaly_map: dict[str, int] = {
        a.type: a.count for a in input_data.top_anomalies
    }

    for i, insight in enumerate(insights):
        insight_type = insight.type.lower() if insight.type else ""
        title = insight.title.lower() if insight.title else ""

        for anomaly_type, actual_count in anomaly_map.items():
            at = anomaly_type.lower()
            if at not in insight_type and at not in title:
                continue

            claimed = insight.affected_count
            if claimed > actual_count * 2 and actual_count > 0:
                result.add(GuardrailFinding(
                    risk="high",
                    insight_index=i,
                    field="affected_count",
                    message=f"Claimed {claimed} occurrences of '{anomaly_type}' vs {actual_count} actual",
                    detail=f"Overstated by {claimed - actual_count} ({((claimed / actual_count) - 1) * 100:.0f}% over)",
                ))
            elif claimed > actual_count * 1.5 and actual_count > 0:
                result.add(GuardrailFinding(
                    risk="low",
                    insight_index=i,
                    field="affected_count",
                    message=f"Slightly overstated {claimed} vs {actual_count} actual for '{anomaly_type}'",
                    detail="",
                ))


def _check_title_description_consistency(
    result: GuardrailResult,
    insights: list[AnalysisResult],
) -> None:
    """Check if title and description are present and non-empty."""
    for i, insight in enumerate(insights):
        if not insight.title or not insight.title.strip():
            result.add(GuardrailFinding(
                risk="high",
                insight_index=i,
                field="title",
                message="Empty insight title",
                detail="",
            ))
        if not insight.description or not insight.description.strip():
            result.add(GuardrailFinding(
                risk="medium",
                insight_index=i,
                field="description",
                message="Empty insight description",
                detail="",
            ))


def validate_insights(
    input_data: AnalysisInput,
    insights: list[AnalysisResult],
) -> GuardrailResult:
    """Run all guardrail checks against LLM-generated insights.

    Pure deterministic validation — no external calls.
    Cross-references every claim against the structured input data.

    Args:
        input_data: The AnalysisInput that was sent to the LLM.
        insights: The AnalysisResult list returned by the LLM.

    Returns:
        GuardrailResult with findings, risk_level, and validity flag.
    """
    result = GuardrailResult()

    if not insights:
        return result

    _check_title_description_consistency(result, insights)
    _check_severity_vs_metrics(result, insights, input_data)
    _check_focus_consistency(result, insights, input_data)
    _check_anomaly_consistency(result, insights, input_data)

    return result
