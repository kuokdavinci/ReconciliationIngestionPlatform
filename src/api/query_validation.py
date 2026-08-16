"""Shared validation for API query and payload values."""

from datetime import datetime

from fastapi import HTTPException


def validate_date(value: str | None) -> str:
    """Validate and return an API date in ``YYYY-MM-DD`` format."""
    if value is None:
        raise HTTPException(
            status_code=400,
            detail="Date parameter is required (YYYY-MM-DD format).",
        )
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid date format: '{value}'. Expected YYYY-MM-DD.",
        )
    return value


def validate_partner(value: str | None, *, required: bool = False) -> str | None:
    """Trim a partner identifier and preserve optional/required semantics."""
    if value is None:
        if required:
            raise HTTPException(status_code=400, detail="Partner identifier is required.")
        return None

    normalized = value.strip()
    if not normalized:
        detail = "Partner identifier is required." if required else "Partner identifier cannot be empty."
        raise HTTPException(status_code=400, detail=detail)
    return normalized
