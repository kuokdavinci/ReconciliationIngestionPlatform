"""Transport-neutral errors raised by review application workflows."""


class ReviewError(Exception):
    """Base error for review workflow failures."""


class ReviewNotFoundError(ReviewError):
    """A requested review resource does not exist."""


class ReviewConflictError(ReviewError):
    """A review action conflicts with the current workflow state."""


class ReviewValidationError(ReviewError):
    """Review input or a required workflow invariant is invalid."""


class ReviewUnavailableError(ReviewError):
    """A required review dependency is unavailable."""
