"""Helpers for resolving actor identity on mutating endpoints."""

from collections.abc import Mapping

from fastapi import HTTPException, Request


def require_actor(
    request: Request,
    *,
    payload_actor: str | None = None,
    payload_field_name: str = "reviewedBy",
) -> str:
    actor = (payload_actor or "").strip()
    if actor:
        return actor

    headers = getattr(request, "headers", None)
    if isinstance(headers, Mapping):
        actor = str(headers.get("x-actor", "") or headers.get("X-Actor", "")).strip()
        if actor:
            return actor

    raise HTTPException(
        status_code=400,
        detail=(
            f"Actor is required. Provide '{payload_field_name}' in the request body "
            "or 'X-Actor' in the request headers."
        ),
    )
