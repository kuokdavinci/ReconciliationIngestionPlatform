"""Dependency guardrails for Starlette's ASGI test client."""

import starlette.testclient


def test_starlette_testclient_uses_httpx2_instead_of_deprecated_httpx_fallback() -> None:
    """Starlette 1.3.x must not silently fall back to the legacy httpx package."""

    assert starlette.testclient.httpx.__name__ == "httpx2"
