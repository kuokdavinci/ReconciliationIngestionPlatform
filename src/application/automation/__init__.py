"""Automation application boundary."""

from src.application.automation.contracts import (
    ExecuteStreamCommand,
    ExecuteStreamOutcome,
    ExecuteStreamResult,
    OrchestrationContext,
)
from src.application.automation.service import execute_stream

__all__ = [
    "ExecuteStreamCommand",
    "ExecuteStreamOutcome",
    "ExecuteStreamResult",
    "OrchestrationContext",
    "execute_stream",
]
