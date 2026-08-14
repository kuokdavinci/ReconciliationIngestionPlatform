"""Typed errors raised by mapping application workflows."""


class MappingApplicationError(Exception):
    """Base error for mapping application services."""


class MappingNotFoundError(MappingApplicationError):
    """The requested mapping or review artifact does not exist."""


class MappingConflictError(MappingApplicationError):
    """The requested mapping transition is not allowed in the current state."""


class MappingValidationError(MappingApplicationError):
    """The mapping input or source file cannot be processed."""
