"""Application policy translating quality decisions into workflow actions."""

from enum import StrEnum

from src.domain.ingestion.quality import (
    QualityDecision,
    QualityOutcome,
    QualityRuleCode,
    QualitySummary,
)


class OrchestrationAction(StrEnum):
    CONTINUE = "CONTINUE"
    HOLD_FOR_REVIEW = "HOLD_FOR_REVIEW"
    FAIL = "FAIL"


def orchestration_action_for(summary: QualitySummary) -> OrchestrationAction:
    """Map a domain quality summary to an application workflow action."""

    if summary.decision is QualityDecision.FAIL:
        return OrchestrationAction.FAIL
    if summary.rule_counts.get(
        QualityRuleCode.CONFLICTING_DUPLICATE.value, 0
    ) or summary.outcome_counts.get(QualityOutcome.CONFLICTING_DUPLICATE.value, 0):
        return OrchestrationAction.HOLD_FOR_REVIEW
    return OrchestrationAction.CONTINUE


__all__ = ["OrchestrationAction", "orchestration_action_for"]
