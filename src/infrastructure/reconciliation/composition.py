"""Composition root for the reconciliation use case."""

from typing import Any

from src.reconciliation.engine import ReconciliationEngine


def build_reconciliation_service(db: Any) -> ReconciliationEngine:
    """Build the PostgreSQL-backed reconciliation use case."""
    return ReconciliationEngine(db)
