"""Production-like contract test for the complete ingestion topology.

The test is intentionally strict: it must run against the Compose topology
and is never allowed to silently downgrade to mocked repositories.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from time import monotonic
from urllib.parse import quote

import httpx
import pytest
from motor.motor_asyncio import AsyncIOMotorClient
from sqlalchemy import func, select

from scripts.demo.sprint2.seed import (
    MAPPING_CONFIG_ID,
    _build_internal_transactions,
    _fetch_config,
    _mapping_document,
    _today_utc,
    _wipe_mongo,
    _wipe_postgres,
)
from src.config.settings import settings
from src.infrastructure.fetch_config.repository import FetchConfigRepository
from src.infrastructure.postgres.internal_transaction_repository import (
    InternalTransactionRepository,
)
from src.infrastructure.persistence.postgres_connection import get_pg_engine
from src.infrastructure.persistence.postgres_schema import PartnerTransactionTable


pytestmark = pytest.mark.e2e

PARTNER = "VIETTELPAY"
API_URL = os.getenv("TOPOLOGY_API_URL", "http://127.0.0.1:8000")
SOURCE_URL = os.getenv("TOPOLOGY_SOURCE_URL", "http://127.0.0.1:8001")
AIRFLOW_URL = os.getenv("TOPOLOGY_AIRFLOW_URL", "http://127.0.0.1:8080")
SFTP_HOST = os.getenv("TOPOLOGY_SFTP_HOST", "127.0.0.1")
SFTP_PORT = int(os.getenv("TOPOLOGY_SFTP_PORT", "2222"))
RUNTIME_TIMEOUT_SECONDS = float(os.getenv("TOPOLOGY_RUNTIME_TIMEOUT_SECONDS", "120"))
AIRFLOW_DAG_ID = os.getenv("APP_AIRFLOW_DAG_ID", settings.airflow_dag_id)
AIRFLOW_USERNAME = os.getenv("APP_AIRFLOW_USERNAME", settings.airflow_username or "airflow")
AIRFLOW_PASSWORD = os.getenv("APP_AIRFLOW_PASSWORD", settings.airflow_password or "airflow")


async def _wait_for_topology_readiness(client: httpx.AsyncClient) -> None:
    """Wait for dependencies that Compose cannot fully health-check."""

    deadline = monotonic() + RUNTIME_TIMEOUT_SECONDS
    last_error = "unknown readiness error"
    while monotonic() < deadline:
        try:
            for url in (
                f"{API_URL}/openapi.json",
                f"{SOURCE_URL}/health",
                f"{AIRFLOW_URL}/api/v2/monitor/health",
            ):
                response = await client.get(url)
                response.raise_for_status()

            token_response = await client.post(
                f"{AIRFLOW_URL}/auth/token",
                json={"username": AIRFLOW_USERNAME, "password": AIRFLOW_PASSWORD},
            )
            token_response.raise_for_status()
            token = token_response.json().get("access_token")
            if not isinstance(token, str) or not token:
                raise AssertionError("Airflow readiness returned no access token")
            dag_response = await client.get(
                f"{AIRFLOW_URL}/api/v2/dags/{quote(AIRFLOW_DAG_ID, safe='')}",
                headers={"Authorization": f"Bearer {token}"},
            )
            dag_response.raise_for_status()

            _, writer = await asyncio.wait_for(
                asyncio.open_connection(SFTP_HOST, SFTP_PORT), timeout=5
            )
            writer.close()
            await writer.wait_closed()
            return
        except (AssertionError, OSError, httpx.HTTPError, asyncio.TimeoutError) as exc:
            last_error = str(exc) or type(exc).__name__
            await asyncio.sleep(2)

    raise AssertionError(
        f"Topology dependencies did not become ready within {RUNTIME_TIMEOUT_SECONDS}s; "
        f"last error={last_error}"
    )


async def _wait_for_runtime_status(
    client: httpx.AsyncClient,
    runtime_run_id: str,
    expected_status: str,
) -> dict:
    deadline = monotonic() + RUNTIME_TIMEOUT_SECONDS
    last_runtime: dict | None = None
    while monotonic() < deadline:
        response = await client.get(f"{API_URL}/api/v1/automation/jobs")
        response.raise_for_status()
        job = next(
            (item for item in response.json()["jobs"] if item["partner"] == PARTNER),
            None,
        )
        if job is not None:
            runtime = job.get("latestRuntimeRun") or {}
            if runtime.get("_id") == runtime_run_id:
                last_runtime = runtime
                task_state = (runtime.get("orchestration") or {}).get("taskState")
                if runtime.get("status") == "FAILED":
                    raise AssertionError(f"Topology runtime failed: {runtime}")
                if task_state in {"failed", "upstream_failed"}:
                    raise AssertionError(f"Airflow task failed: {runtime}")
                if runtime.get("status") == expected_status and (
                    expected_status != "WAITING_REVIEW" or task_state == "success"
                ):
                    return runtime
        await asyncio.sleep(2)
    raise AssertionError(
        f"Topology runtime did not complete within {RUNTIME_TIMEOUT_SECONDS}s; "
        f"last runtime={last_runtime}"
    )


async def _seed_approved_demo_mapping() -> None:
    client = AsyncIOMotorClient(settings.mongodb_url)
    try:
        db = client[settings.db_name]
        await _wipe_mongo(db)
        await db["raw_ingestion_page"].delete_many({"partner": "VIETTELPAY"})
        await _wipe_postgres()
        now = datetime.now(UTC)
        await FetchConfigRepository(db).create(_fetch_config(now))
        await InternalTransactionRepository().insert_many(
            _build_internal_transactions(_today_utc())
        )
        mapping = _mapping_document(now)
        mapping.update(
            {
                "status": "APPROVED",
                "approvedAt": now,
                "approvedBy": "ci-topology-contract",
            }
        )
        await db["reconciliation_mapping_config"].insert_one(mapping)
    finally:
        client.close()


async def _arm_happy_path_source(client: httpx.AsyncClient) -> None:
    """Consume the mock's bounded page-2 failures without touching its files."""

    for _ in range(4):
        response = await client.get(
            f"{SOURCE_URL}/viettelpay/settlement?page=2&cursor=cursor-1"
        )
        if response.status_code == 200:
            return
        assert response.status_code == 504, response.text
    raise AssertionError("ViettelPay mock did not reach the happy path")


async def _wait_for_post_approval_completion(client: httpx.AsyncClient) -> dict:
    deadline = monotonic() + RUNTIME_TIMEOUT_SECONDS
    last_runtime: dict | None = None
    while monotonic() < deadline:
        response = await client.get(f"{API_URL}/api/v1/automation/jobs")
        response.raise_for_status()
        job = next(
            (item for item in response.json()["jobs"] if item["partner"] == PARTNER),
            None,
        )
        if job is not None:
            runtime = job.get("latestRuntimeRun") or {}
            if runtime.get("triggerType") == "POST_APPROVAL_REPROCESS":
                last_runtime = runtime
                if runtime.get("status") == "FAILED":
                    raise AssertionError(f"Post-approval runtime failed: {runtime}")
                if runtime.get("status") == "COMPLETED":
                    return runtime
        await asyncio.sleep(2)
    raise AssertionError(
        f"Post-approval runtime did not complete within {RUNTIME_TIMEOUT_SECONDS}s; "
        f"last runtime={last_runtime}"
    )


@pytest.mark.asyncio
async def test_full_ingestion_topology_contract() -> None:
    """Prove the API, Airflow, source, Mongo and PostgreSQL paths work together."""

    async with httpx.AsyncClient(timeout=15) as client:
        await _wait_for_topology_readiness(client)

        mongo = AsyncIOMotorClient(settings.mongodb_url, serverSelectionTimeoutMS=5000)
        try:
            await mongo.admin.command("ping")
        finally:
            mongo.close()

        await _arm_happy_path_source(client)
        await _seed_approved_demo_mapping()
        response = await client.post(
            f"{API_URL}/api/v1/automation/jobs/{PARTNER}/run",
            headers={"X-Actor": "ci-topology-contract"},
        )
        response.raise_for_status()
        runtime_run_id = response.json()["runtimeRunId"]
        await _wait_for_runtime_status(client, runtime_run_id, "WAITING_REVIEW")

        review_client = AsyncIOMotorClient(settings.mongodb_url)
        try:
            db = review_client[settings.db_name]
            packet = await db["review_packet"].find_one(
                {"partner": PARTNER, "status": "PENDING", "rawStageKey": {"$exists": True}},
                sort=[("createdAt", -1)],
            )
            assert packet is not None
            await db["review_packet"].update_one(
                {"_id": packet["_id"]},
                {
                    "$set": {
                        "draftMappingId": MAPPING_CONFIG_ID,
                        "draftMappingVersion": "sprint2-v1",
                    }
                },
            )
            packet_id = str(packet["_id"])
        finally:
            review_client.close()

        validation = await client.post(
            f"{API_URL}/api/v1/review-packets/{packet_id}/validate-runtime"
        )
        validation.raise_for_status()
        assert validation.json()["ok"] is True
        approval = await client.post(
            f"{API_URL}/api/v1/review-packets/{packet_id}/approve-keep-current",
            headers={"X-Actor": "ci-topology-contract"},
            json={
                "reviewedBy": "ci-topology-contract",
                "scopeType": "FULL_SNAPSHOT",
            },
        )
        approval.raise_for_status()
        await _wait_for_post_approval_completion(client)

    verification_client = AsyncIOMotorClient(settings.mongodb_url)
    try:
        db = verification_client[settings.db_name]
        checkpoint = await db["ingestion_checkpoint"].find_one({"partner": PARTNER})
        assert checkpoint is not None
        # A replayed scheduled stream remains DISCOVERED as the safe duplicate
        # guard; streamEnded is the terminal marker for this checkpoint model.
        assert checkpoint["status"] == "DISCOVERED"
        assert checkpoint["streamEnded"] is True
        assert checkpoint["lastCompletedUnitKey"]
        assert checkpoint["recoveryEvents"][-1]["status"] == "COMPLETED"
        assert (
            await db["raw_ingestion_page"].count_documents({"partner": PARTNER}) == 3
        )
    finally:
        verification_client.close()

    engine = get_pg_engine()
    async with engine.connect() as connection:
        partner_rows = await connection.scalar(
            select(func.count())
            .select_from(PartnerTransactionTable)
            .where(PartnerTransactionTable.identify == PARTNER)
        )
    assert partner_rows == 6
