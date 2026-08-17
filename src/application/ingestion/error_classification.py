"""Shared classification helpers for ingestion failures.

Re-exports from contracts.py for backwards compatibility.
"""

from src.application.ingestion.contracts import is_missing_ingestion_key_failure

__all__ = ["is_missing_ingestion_key_failure"]
