"""Connection helpers for opt-in PostgreSQL integration tests."""

from __future__ import annotations

import asyncio
import os

from sqlalchemy.engine import make_url


def postgres_url_for_tests(configured_url: str) -> str:
    """Resolve the test URL for the current runner/network context.

    ``TEST_POSTGRES_URL`` is used by container/CI runners.  Host-local runs
    keep the configured URL but use a numeric loopback for ``localhost`` so a
    blocked DNS/socket path fails fast instead of leaving an async resolver
    thread behind during pytest event-loop teardown.
    """

    raw_url = os.getenv("TEST_POSTGRES_URL") or configured_url
    url = make_url(raw_url)
    if url.host == "localhost":
        url = url.set(host="127.0.0.1")
    return url.render_as_string(hide_password=False)


async def postgres_dsn_if_available(
    configured_url: str,
    *,
    timeout: float = 3.0,
) -> str | None:
    """Return a sync-driver DSN only when the configured TCP endpoint is open."""

    test_url = make_url(postgres_url_for_tests(configured_url))
    host = test_url.host or "127.0.0.1"
    port = test_url.port or 5432
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
    except (OSError, TimeoutError, ValueError):
        return None

    writer.close()
    try:
        await writer.wait_closed()
    except (OSError, RuntimeError):
        pass

    return test_url.set(drivername="postgresql").render_as_string(hide_password=False)
