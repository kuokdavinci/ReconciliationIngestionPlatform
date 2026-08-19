"""Types and validation for configurable quality profiles."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class QualityProfileSpec:
    """Schema and type contract consumed by the generic profiler."""

    name: str
    expected_columns: tuple[str, ...]
    required_columns: frozenset[str]
    primary_key: str
    identifier_columns: frozenset[str] = frozenset()
    categorical_columns: frozenset[str] = frozenset()
    numeric_columns: frozenset[str] = frozenset()
    datetime_columns: frozenset[str] = frozenset()
    amount_column: str | None = None
    timestamp_column: str | None = None


def validate_spec(spec: QualityProfileSpec) -> None:
    if not spec.expected_columns:
        raise ValueError("expected_columns must not be empty")
    if len(set(spec.expected_columns)) != len(spec.expected_columns):
        raise ValueError("expected_columns must not contain duplicates")
    if spec.primary_key not in spec.expected_columns:
        raise ValueError("primary_key must be an expected column")
    if not spec.required_columns <= set(spec.expected_columns):
        raise ValueError("required_columns must be expected columns")
    for configured_column in (spec.amount_column, spec.timestamp_column):
        if configured_column is not None and configured_column not in spec.expected_columns:
            raise ValueError("configured value columns must be expected columns")
