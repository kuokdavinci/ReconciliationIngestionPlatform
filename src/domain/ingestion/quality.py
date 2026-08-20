"""Domain quality language for the ingestion bounded context."""

from collections import Counter
from enum import StrEnum
from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict, Field, model_validator


class QualityRuleCode(StrEnum):
    """Stable identifiers for deterministic ingestion quality rules."""

    REQUIRED_SCHEMA_PATH = "REQUIRED_SCHEMA_PATH"
    MISSING_REQUIRED_SOURCE_COLUMN = "MISSING_REQUIRED_SOURCE_COLUMN"
    SCHEMA_CONFIG_DRIFT = "SCHEMA_CONFIG_DRIFT"
    SOURCE_STRUCTURE_UNREADABLE = "SOURCE_STRUCTURE_UNREADABLE"
    CONFIG_VALIDATION = "CONFIG_VALIDATION"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    MALFORMED_ROW = "MALFORMED_ROW"
    INVALID_AMOUNT = "INVALID_AMOUNT"
    NEGATIVE_AMOUNT = "NEGATIVE_AMOUNT"
    INVALID_TIMESTAMP = "INVALID_TIMESTAMP"
    INVALID_STATUS = "INVALID_STATUS"
    EQUIVALENT_DUPLICATE = "EQUIVALENT_DUPLICATE"
    CONFLICTING_DUPLICATE = "CONFLICTING_DUPLICATE"


class QualityPhase(StrEnum):
    """Ingestion phase that observed a quality condition."""

    CONFIGURATION = "CONFIGURATION"
    FILE = "FILE"
    NORMALIZATION = "NORMALIZATION"
    VALIDATION = "VALIDATION"
    PERSISTENCE = "PERSISTENCE"


class QualitySeverity(StrEnum):
    """Severity independent from infrastructure retryability."""

    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    FATAL = "FATAL"


class QualityOutcome(StrEnum):
    """Outcome for one row or one file-level quality evaluation."""

    VALID = "VALID"
    WARNING = "WARNING"
    REJECT = "REJECT"
    EQUIVALENT_DUPLICATE = "EQUIVALENT_DUPLICATE"
    CONFLICTING_DUPLICATE = "CONFLICTING_DUPLICATE"
    BATCH_FATAL = "BATCH_FATAL"


class QualityDecision(StrEnum):
    """Aggregated domain decision for one source unit."""

    PASS = "PASS"
    REVIEW = "REVIEW"
    FAIL = "FAIL"


class QualityViolation(BaseModel):
    """Structured evidence emitted by a deterministic quality rule."""

    model_config = ConfigDict(extra="forbid")

    code: QualityRuleCode = QualityRuleCode.MALFORMED_ROW
    phase: QualityPhase = QualityPhase.NORMALIZATION
    severity: QualitySeverity = QualitySeverity.ERROR
    outcome: QualityOutcome = QualityOutcome.REJECT
    field: str | None = None
    message: str = "Quality validation failed."
    expected: Any = None
    actual: Any = None
    row: int | None = None
    trace: str | None = None
    config_version: str | None = None


class QualityEvaluation(BaseModel):
    """Domain result of evaluating one row or one file structure."""

    model_config = ConfigDict(extra="forbid")

    outcome: QualityOutcome = QualityOutcome.VALID
    violations: list[QualityViolation] = Field(default_factory=list)
    normalized_data: dict[str, Any] = Field(default_factory=dict)
    row_context: dict[str, Any] = Field(default_factory=dict)
    normalize_ms: float = 0.0
    validate_ms: float = 0.0

    @model_validator(mode="after")
    def infer_outcome(self) -> "QualityEvaluation":
        if not self.violations:
            return self
        if (
            any(
                item.outcome is QualityOutcome.BATCH_FATAL or item.severity is QualitySeverity.FATAL
                for item in self.violations
            )
            or self.outcome is QualityOutcome.BATCH_FATAL
        ):
            self.outcome = QualityOutcome.BATCH_FATAL
        elif (
            any(item.outcome is QualityOutcome.CONFLICTING_DUPLICATE for item in self.violations)
            or self.outcome is QualityOutcome.CONFLICTING_DUPLICATE
        ):
            self.outcome = QualityOutcome.CONFLICTING_DUPLICATE
        elif self.outcome is QualityOutcome.REJECT or any(
            item.outcome is QualityOutcome.REJECT for item in self.violations
        ):
            self.outcome = QualityOutcome.REJECT
        elif self.outcome is QualityOutcome.WARNING or any(
            item.outcome is QualityOutcome.WARNING or item.severity is QualitySeverity.WARNING
            for item in self.violations
        ):
            self.outcome = QualityOutcome.WARNING
        elif self.outcome is QualityOutcome.EQUIVALENT_DUPLICATE or all(
            item.outcome is QualityOutcome.EQUIVALENT_DUPLICATE for item in self.violations
        ):
            self.outcome = QualityOutcome.EQUIVALENT_DUPLICATE
        else:
            self.outcome = QualityOutcome.REJECT
        return self

    @property
    def is_valid(self) -> bool:
        return self.outcome in {
            QualityOutcome.VALID,
            QualityOutcome.WARNING,
            QualityOutcome.EQUIVALENT_DUPLICATE,
        }

    @property
    def decision(self) -> QualityDecision:
        return QualitySummary.from_evaluations([self]).decision


class QualitySummary(BaseModel):
    """Bounded domain aggregate without orchestration or transport concerns."""

    model_config = ConfigDict(extra="forbid")

    decision: QualityDecision = QualityDecision.PASS
    rule_counts: dict[str, int] = Field(default_factory=dict)
    outcome_counts: dict[str, int] = Field(default_factory=dict)
    top_rule_codes: list[str] = Field(default_factory=list)

    @classmethod
    def from_evaluations(
        cls,
        evaluations: Iterable[QualityEvaluation],
    ) -> "QualitySummary":
        rule_counts: Counter[str] = Counter()
        outcome_counts: Counter[str] = Counter()

        for evaluation in evaluations:
            outcome_counts[evaluation.outcome.value] += 1
            for violation in evaluation.violations:
                rule_counts[violation.code.value] += 1

        return cls.from_counts(rule_counts, outcome_counts)

    @classmethod
    def from_counts(
        cls,
        rule_counts: dict[str, int] | Counter[str],
        outcome_counts: dict[str, int] | Counter[str],
    ) -> "QualitySummary":
        """Build a disposition from cumulative bounded counters."""

        rule_counts = Counter(rule_counts)
        outcome_counts = Counter(outcome_counts)
        if outcome_counts[QualityOutcome.BATCH_FATAL.value] > 0:
            decision = QualityDecision.FAIL
        elif rule_counts[QualityRuleCode.CONFLICTING_DUPLICATE.value] > 0 or any(
            outcome_counts[outcome.value] > 0
            for outcome in (
                QualityOutcome.REJECT,
                QualityOutcome.WARNING,
                QualityOutcome.CONFLICTING_DUPLICATE,
            )
        ):
            decision = QualityDecision.REVIEW
        else:
            decision = QualityDecision.PASS

        top_rule_codes = [
            code
            for code, _count in sorted(
                rule_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )[:10]
        ]
        return cls(
            decision=decision,
            rule_counts=dict(rule_counts),
            outcome_counts=dict(outcome_counts),
            top_rule_codes=top_rule_codes,
        )

    @classmethod
    def from_violations(
        cls,
        violations: Iterable[QualityViolation],
        *,
        outcome: QualityOutcome | None = None,
    ) -> "QualitySummary":
        violations = list(violations)
        if not violations:
            return cls()
        return cls.from_evaluations(
            [
                QualityEvaluation(
                    outcome=outcome or QualityOutcome.VALID,
                    violations=violations,
                )
            ]
        )


def quality_violation(
    *,
    code: QualityRuleCode,
    phase: QualityPhase,
    severity: QualitySeverity,
    outcome: QualityOutcome,
    message: str,
    field: str | None = None,
    expected: Any = None,
    actual: Any = None,
    row: int | None = None,
    trace: str | None = None,
    config_version: str | None = None,
) -> QualityViolation:
    return QualityViolation(
        code=code,
        phase=phase,
        severity=severity,
        outcome=outcome,
        field=field,
        message=message,
        expected=expected,
        actual=actual,
        row=row,
        trace=trace,
        config_version=config_version,
    )


__all__ = [
    "QualityDecision",
    "QualityEvaluation",
    "QualityOutcome",
    "QualityPhase",
    "QualityRuleCode",
    "QualitySeverity",
    "QualitySummary",
    "QualityViolation",
    "quality_violation",
]
