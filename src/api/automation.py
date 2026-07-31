"""Automation visibility endpoints for scheduler/admin views."""

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from src.api.actor import require_actor
from src.config.cache import ConfigCache
from src.config.loader import ConfigLoader
from src.config.validator import ConfigValidator
from src.models.fetch_config import FetchConfigRepository
from src.models.mapping_config import MappingConfigRepository
from src.models.partner_runtime_run import (
    PartnerRuntimeRunRepository,
    PartnerRuntimeRunStatus,
)
from src.models.review_packet import ReviewPacketRepository
from src.scheduler.jobs import run_fetch_config_once
from src.services.runtime_runs import serialize_partner_runtime_run

router = APIRouter(prefix="/api/v1/automation")


def _get_db(request: Request):
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Database connection not available.")
    return db


def _track_background_task(request: Request, task: asyncio.Task) -> None:
    tasks = getattr(request.app.state, "background_tasks", None)
    if tasks is None:
        tasks = set()
        request.app.state.background_tasks = tasks
    tasks.add(task)
    task.add_done_callback(tasks.discard)


async def _run_fetch_job_in_background(db, config) -> None:
    config_repo = MappingConfigRepository(db)
    config_loader = ConfigLoader(config_repo, ConfigCache(), ConfigValidator())
    await run_fetch_config_once(
        config=config,
        db=db,
        config_loader=config_loader,
        reconciliation_date=datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0),
        batch_size=100,
        structured_logger=None,
    )


@router.get("/jobs")
async def list_automation_jobs(request: Request):
    db = _get_db(request)
    fetch_repo = FetchConfigRepository(db)
    packet_repo = ReviewPacketRepository(db)
    runtime_run_repo = PartnerRuntimeRunRepository(db)
    configs = await fetch_repo.find_enabled()
    packets = await packet_repo.find_many({})
    pending_by_partner: dict[str, int] = {}
    recent_packet_docs: dict[str, list[dict]] = {}
    for packet in packets:
        if packet.source_type.value != "SCHEDULER_JOB":
            continue
        if packet.status.value == "PENDING":
            pending_by_partner[packet.partner] = pending_by_partner.get(packet.partner, 0) + 1
        recent_packet_docs.setdefault(packet.partner, []).append({
            "_id": str(packet.id),
            "fileName": packet.file_name,
            "status": packet.status.value,
            "sourceType": packet.source_type.value,
            "decisionMode": packet.decision_mode.value if packet.decision_mode else None,
            "recommendedAction": packet.recommended_action,
            "parseStrategy": packet.parse_strategy,
            "riskSummary": packet.risk_summary,
            "createdAt": packet.created_at.isoformat(),
            "reviewedAt": packet.reviewed_at.isoformat() if packet.reviewed_at else None,
        })
    for partner_packets in recent_packet_docs.values():
        partner_packets.sort(key=lambda item: item["createdAt"], reverse=True)

    jobs = []
    for config in configs:
        method_config = config.get_method_config()
        destination = "-"
        if method_config is not None:
          if hasattr(method_config, "remote_path"):
              destination = getattr(method_config, "remote_path")
          elif hasattr(method_config, "base_url"):
              destination = getattr(method_config, "base_url")
          elif hasattr(method_config, "directory"):
              destination = getattr(method_config, "directory")
        latest_run = await runtime_run_repo.find_latest_by_partner(config.partner)
        latest_file_raw = await db["reconciliation_file"].find_one(
            {"partner": config.partner},
            sort=[("createdAt", -1)],
        )
        latest_file = None
        if latest_file_raw is not None:
            latest_file = {
                "id": str(latest_file_raw.get("_id")),
                "fileName": latest_file_raw.get("fileName"),
                "processingStatus": latest_file_raw.get("processingStatus"),
                "reconciliationDate": latest_file_raw.get("reconciliationDate").isoformat() if isinstance(latest_file_raw.get("reconciliationDate"), datetime) else str(latest_file_raw.get("reconciliationDate") or ""),
                "createdAt": latest_file_raw.get("createdAt").isoformat() if isinstance(latest_file_raw.get("createdAt"), datetime) else str(latest_file_raw.get("createdAt") or ""),
            }

        latest_run_data = serialize_partner_runtime_run(latest_run) if latest_run else None
        latest_run_stats = (latest_run_data or {}).get("stats") or {}
        duplicate_outcome = latest_run_stats.get("outcome")
        active_statuses = {
            PartnerRuntimeRunStatus.QUEUED.value,
            PartnerRuntimeRunStatus.FETCHING.value,
            PartnerRuntimeRunStatus.INGESTING.value,
            PartnerRuntimeRunStatus.WAITING_REVIEW.value,
            PartnerRuntimeRunStatus.WAITING_RECONCILE.value,
            PartnerRuntimeRunStatus.RECONCILING.value,
        }
        active_run = latest_run_data if latest_run_data and latest_run_data.get("status") in active_statuses else None
        has_pending_file = bool(
            latest_file
            and latest_file.get("processingStatus") == "COMPLETED"
            and (
                latest_run is None
                or latest_run.source_file_id != latest_file["id"]
                or latest_run.status == PartnerRuntimeRunStatus.WAITING_RECONCILE
            )
        )
        status = "HEALTHY"
        status_message = "No active runtime work."
        if active_run:
            status = active_run.get("status") or "RUNNING"
            status_message = active_run.get("message") or "Runtime flow is active."
        elif latest_run_data and latest_run_data.get("status") == PartnerRuntimeRunStatus.FAILED.value:
            status = "FAILED"
            status_message = latest_run_data.get("message") or "Latest runtime run failed."
        elif has_pending_file:
            status = "PENDING"
            status_message = "A partner file is available and waiting for reconciliation."
        elif duplicate_outcome in {"FILE_DUPLICATE", "FETCH_UNIT_REPLAY", "NO_NEW_FILE"}:
            status_message = latest_run_data.get("message") or "No new file was processed."
        jobs.append({
            "partner": config.partner,
            "fetchMethod": config.fetch_method.value,
            "schedule": config.schedule,
            "enabled": config.enabled,
            "localDownloadDir": config.local_download_dir,
            "destination": destination,
            "pendingReviewPackets": pending_by_partner.get(config.partner, 0),
            "updatedAt": config.updated_at.isoformat() if isinstance(config.updated_at, datetime) else str(config.updated_at),
            "recentPackets": recent_packet_docs.get(config.partner, [])[:3],
            "status": status,
            "statusMessage": status_message,
            "duplicateOutcome": duplicate_outcome,
            "duplicateMessage": (
                latest_run_data.get("message")
                if duplicate_outcome in {"FILE_DUPLICATE", "FETCH_UNIT_REPLAY", "NO_NEW_FILE"}
                else None
            ),
            "hasPendingFile": has_pending_file,
            "latestRuntimeRun": latest_run_data,
            "activeRuntimeRun": active_run,
            "latestFile": latest_file,
        })
    return {"jobs": jobs}


@router.post("/jobs/{partner}/run")
async def run_automation_job_now(request: Request, partner: str):
    actor = require_actor(request, payload_field_name="actor")
    db = _get_db(request)
    fetch_repo = FetchConfigRepository(db)
    config = await fetch_repo.find_by_partner(partner)
    if config is None:
        raise HTTPException(status_code=404, detail="Automation job not found for partner.")
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Automation job is disabled.")

    task = asyncio.create_task(_run_fetch_job_in_background(db, config))
    _track_background_task(request, task)
    return {
        "ok": True,
        "queued": True,
        "actor": actor,
        "partner": partner,
        "message": "Automation run queued. Watch runtime state for live progress.",
    }
