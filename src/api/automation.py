"""Automation visibility endpoints for scheduler/admin views."""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from src.config.cache import ConfigCache
from src.config.loader import ConfigLoader
from src.config.validator import ConfigValidator
from src.models.fetch_config import FetchConfigRepository
from src.models.mapping_config import MappingConfigRepository
from src.models.review_packet import ReviewPacketRepository
from src.scheduler.jobs import run_fetch_config_once

router = APIRouter(prefix="/api/v1/automation")


def _get_db(request: Request):
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Database connection not available.")
    return db


@router.get("/jobs")
async def list_automation_jobs(request: Request):
    db = _get_db(request)
    fetch_repo = FetchConfigRepository(db)
    packet_repo = ReviewPacketRepository(db)
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
        })
    return {"jobs": jobs}


@router.post("/jobs/{partner}/run")
async def run_automation_job_now(request: Request, partner: str):
    db = _get_db(request)
    fetch_repo = FetchConfigRepository(db)
    config = await fetch_repo.find_by_partner(partner)
    if config is None:
        raise HTTPException(status_code=404, detail="Automation job not found for partner.")
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Automation job is disabled.")

    config_repo = MappingConfigRepository(db)
    config_loader = ConfigLoader(config_repo, ConfigCache(), ConfigValidator())
    result = await run_fetch_config_once(
        config=config,
        db=db,
        config_loader=config_loader,
        reconciliation_date=datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0),
        batch_size=100,
        structured_logger=None,
    )
    status_code = 200 if result.get("success") else 500
    if status_code != 200:
        raise HTTPException(status_code=status_code, detail=result.get("error") or "Run now failed.")
    return {"ok": True, "result": result}
