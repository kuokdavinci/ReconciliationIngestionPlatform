"""Synchronous facade over httpx2's async ASGI transport for API tests."""

import asyncio
from collections.abc import Iterator
from contextlib import AbstractContextManager
from typing import Any

from httpx2 import ASGITransport, AsyncClient, Response


class TestClient(AbstractContextManager["TestClient"]):
    """Keep the familiar TestClient calls without AnyIO's blocking portal."""

    __test__ = False

    def __init__(self, app: Any, *, base_url: str = "http://testserver") -> None:
        self.app = app
        self.base_url = base_url

    def _run(self, method: str, url: str, **kwargs: Any) -> Response:
        async def request() -> Response:
            transport = ASGITransport(app=self.app)
            async with AsyncClient(
                transport=transport,
                base_url=self.base_url,
                follow_redirects=True,
            ) as client:
                return await client.request(method, url, **kwargs)

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(request())
        raise RuntimeError(
            "Sync ASGI TestClient cannot run inside an active event loop; "
            "use httpx2.AsyncClient directly in async tests."
        )

    def request(self, method: str, url: str, **kwargs: Any) -> Response:
        return self._run(method, url, **kwargs)

    def get(self, url: str, **kwargs: Any) -> Response:
        return self._run("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> Response:
        return self._run("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> Response:
        return self._run("PUT", url, **kwargs)

    def patch(self, url: str, **kwargs: Any) -> Response:
        return self._run("PATCH", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> Response:
        return self._run("DELETE", url, **kwargs)

    def __enter__(self) -> "TestClient":
        return self

    def __exit__(self, *args: Any) -> None:
        return None


def iter_client_methods() -> Iterator[str]:
    """Expose supported methods for a small architecture regression test."""

    yield from ("get", "post", "put", "patch", "delete")
