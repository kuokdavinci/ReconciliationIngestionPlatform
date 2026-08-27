"""Tests for the canonical reconciliation-key helper."""

import pytest

from src.reconciliation.keys import normalize_reconciliation_key


@pytest.mark.parametrize(
    ("candidates", "expected"),
    [
        (("", "  ", "vsp-1", "partner-1"), "vsp-1"),
        (("  trace-1  ", "vsp-1", "partner-1"), "trace-1"),
        ((None, "", "partner-1"), "partner-1"),
        ((" ", None, ""), None),
    ],
)
def test_normalize_reconciliation_key_uses_trimmed_non_empty_fallback(
    candidates: tuple[object, ...], expected: str | None
) -> None:
    assert normalize_reconciliation_key(*candidates) == expected
