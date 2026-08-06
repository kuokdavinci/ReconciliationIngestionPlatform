"""Compatibility facade for copilot action models and adapters."""

from src.domain.review.models import CopilotAction, CopilotActionStatus, CopilotActionType
from src.infrastructure.review.repository import CopilotActionRepository

__all__ = [
    "CopilotAction",
    "CopilotActionRepository",
    "CopilotActionStatus",
    "CopilotActionType",
]
