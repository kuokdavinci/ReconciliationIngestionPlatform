"""Commands and transport-neutral errors for automation job operations."""

from dataclasses import dataclass


class AutomationApplicationError(Exception):
    """Base error for automation application workflows."""


class AutomationNotFoundError(AutomationApplicationError):
    """The requested automation configuration does not exist."""


class AutomationConflictError(AutomationApplicationError):
    """The requested operation conflicts with current runtime state."""


class AutomationValidationError(AutomationApplicationError):
    """The requested automation operation is invalid."""


class AutomationUnavailableError(AutomationApplicationError):
    """The workflow provider or persistence dependency is unavailable."""


@dataclass(frozen=True)
class RunAutomationJobCommand:
    partner: str
    actor: str


@dataclass(frozen=True)
class RetryAutomationJobCommand:
    partner: str
    actor: str


@dataclass(frozen=True)
class ResolveAutomationRecoveryCommand:
    partner: str
    actor: str
    action: str
    reason: str
