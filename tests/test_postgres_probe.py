import asyncio

import pytest

from tests.postgres_probe import postgres_dsn_if_available


def test_localhost_postgres_dsn_uses_numeric_loopback(monkeypatch):
    calls: list[tuple[str, int]] = []

    async def fake_open_connection(host: str, port: int):
        calls.append((host, port))

        class _Writer:
            def close(self):
                pass

            async def wait_closed(self):
                pass

        return object(), _Writer()

    monkeypatch.setattr(asyncio, "open_connection", fake_open_connection)

    dsn = asyncio.run(
        postgres_dsn_if_available(
            "postgresql+asyncpg://postgres:postgres@localhost:5432/reconciliation"
        )
    )

    assert calls == [("127.0.0.1", 5432)]
    assert dsn == "postgresql://postgres:postgres@127.0.0.1:5432/reconciliation"


@pytest.mark.asyncio
async def test_unavailable_postgres_returns_none_without_raising(monkeypatch):
    async def fake_open_connection(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(asyncio, "open_connection", fake_open_connection)

    result = await postgres_dsn_if_available(
        "postgresql+asyncpg://postgres:postgres@localhost:5432/reconciliation"
    )

    assert result is None
