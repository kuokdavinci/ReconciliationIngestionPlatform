"""Shared FastAPI dependencies used by API routers."""

from typing import Any

from fastapi import HTTPException, Request


def get_request_db(request: Request) -> Any:
    """Return the database attached to the application request state."""
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Database connection not available.")
    return db
