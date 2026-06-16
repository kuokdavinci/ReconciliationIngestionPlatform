import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.models.partner_runtime_run import (
    PartnerRuntimeRunRepository,
    PartnerRuntimeRunStatus,
    PartnerRuntimeTriggerType,
)
from src.core.error_formatting import summarize_runtime_error
from src.models.reconciliation_result import (
    ReconciliationResult,
    ReconciliationResultRepository,
)
from src.models.reconciliation_review_record import ReconciliationReviewRecordRepository
from src.core.enums import ReconciliationStatus
from src.reconciliation.engine import ReconciliationEngine
from src.services.runtime_runs import (
    create_runtime_run,
    serialize_partner_runtime_run,
    update_runtime_run,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/reconciliation")


class ReviewNotePayload(BaseModel):
    partner: str
    date: str
    note: str


class ResolveReviewPayload(BaseModel):
    partner: str
    date: str
    resolved_status: str = Field(alias="resolvedStatus")


class RunReconciliationPayload(BaseModel):
    partner: str
    date: str


def _track_background_task(request: Request, task: asyncio.Task) -> None:
    tasks = getattr(request.app.state, "background_tasks", None)
    if tasks is None:
        tasks = set()
        request.app.state.background_tasks = tasks
    tasks.add(task)
    task.add_done_callback(tasks.discard)


def _validate_date(date_str: Optional[str]) -> str:
    if date_str is None:
        raise HTTPException(status_code=400, detail="Date parameter is required (YYYY-MM-DD format).")
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid date format: '{date_str}'. Expected YYYY-MM-DD.")
    return date_str


def _validate_partner(partner: Optional[str]) -> str:
    if not partner or not partner.strip():
        raise HTTPException(status_code=400, detail="Partner identifier is required.")
    return partner.strip()


def _validate_status(status: Optional[str]) -> Optional[str]:
    if status is not None:
        valid = [s.value for s in ReconciliationStatus]
        if status not in valid:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status: '{status}'. Must be one of: {', '.join(valid)}.",
            )
    return status


def _get_repo(request: Request) -> ReconciliationResultRepository:
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Database connection not available.")
    try:
        return ReconciliationResultRepository(db)
    except Exception as exc:
        logger.error(f"Failed to create repository: {exc}")
        raise HTTPException(status_code=500, detail="Failed to initialize repository.")


def _get_review_repo(request: Request) -> ReconciliationReviewRecordRepository:
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Database connection not available.")
    return ReconciliationReviewRecordRepository(db)


def _serialize(obj):
    if isinstance(obj, ReconciliationResult):
        d = obj.model_dump(by_alias=True)
        if "partnerAmount" in d and d["partnerAmount"] is not None:
            d["partnerAmount"] = str(d["partnerAmount"])
        if "internalAmount" in d and d["internalAmount"] is not None:
            d["internalAmount"] = str(d["internalAmount"])
        return d
    if isinstance(obj, dict):
        return {k: str(v) if hasattr(v, "to_decimal") else v for k, v in obj.items()}
    return obj


def _serialize_review_record(obj) -> dict:
    data = obj.model_dump(by_alias=True)
    data["_id"] = str(data["_id"])
    return data


def _review_note_timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


@router.get("/review-records")
async def list_review_records(
    request: Request,
    partner: Optional[str] = Query(default=None, description="Partner identifier"),
    date: Optional[str] = Query(default=None, description="Date (YYYY-MM-DD)"),
):
    partner = _validate_partner(partner)
    date = _validate_date(date)
    records = await _get_review_repo(request).find_by_partner_and_date(partner, date)
    return {"records": [_serialize_review_record(record) for record in records]}


@router.post("/review-records/{record_key}/note")
async def add_review_note(request: Request, record_key: str, payload: ReviewNotePayload):
    partner = _validate_partner(payload.partner)
    date = _validate_date(payload.date)
    note = (payload.note or "").strip()
    if not note:
        raise HTTPException(status_code=400, detail="Review note cannot be empty.")

    now = datetime.now(timezone.utc)
    repo = _get_review_repo(request)
    await repo.collection.update_one(
        {"partner": partner, "date": date, "recordKey": record_key},
        {
            "$setOnInsert": {
                "_id": record_key,
                "partner": partner,
                "date": date,
                "recordKey": record_key,
                "createdAt": now,
            },
            "$set": {
                "reviewed": True,
                "updatedAt": now,
            },
            "$push": {
                "notes": {
                    "time": _review_note_timestamp(),
                    "event": f"User Review Note: {note}",
                }
            },
        },
        upsert=True,
    )
    record = await repo.find_one({"partner": partner, "date": date, "recordKey": record_key})
    return {"ok": True, "record": _serialize_review_record(record)}


@router.post("/review-records/{record_key}/resolve")
async def resolve_review_record(request: Request, record_key: str, payload: ResolveReviewPayload):
    partner = _validate_partner(payload.partner)
    date = _validate_date(payload.date)
    now = datetime.now(timezone.utc)
    repo = _get_review_repo(request)
    await repo.collection.update_one(
        {"partner": partner, "date": date, "recordKey": record_key},
        {
            "$setOnInsert": {
                "_id": record_key,
                "partner": partner,
                "date": date,
                "recordKey": record_key,
                "createdAt": now,
            },
            "$set": {
                "reviewed": True,
                "resolvedStatus": payload.resolved_status,
                "updatedAt": now,
            },
        },
        upsert=True,
    )
    record = await repo.find_one({"partner": partner, "date": date, "recordKey": record_key})
    return {"ok": True, "record": _serialize_review_record(record)}


@router.get("/results")
async def list_results(
    request: Request,
    partner: Optional[str] = Query(default=None, description="Partner identifier"),
    date: Optional[str] = Query(default=None, description="Date (YYYY-MM-DD)"),
    status: Optional[str] = Query(default=None, description="Filter by reconciliation status"),
    limit: int = Query(default=25, ge=1, le=1000, description="Max results (max 1000)"),
    offset: int = Query(default=0, ge=0, description="Number of results to skip"),
):
    try:
        partner = _validate_partner(partner)
        date = _validate_date(date)
        if status:
            status = _validate_status(status)
    except HTTPException:
        raise

    try:
        repo = _get_repo(request)
        page, total = await repo.find_page_by_partner_and_date(
            partner,
            date,
            status=ReconciliationStatus(status) if status else None,
            limit=limit,
            offset=offset,
        )
        return {
            "results": [_serialize(r) for r in page],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error listing reconciliation results: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list results: {str(exc)}")


@router.get("/results/{result_id}")
async def get_result(request: Request, result_id: str):
    try:
        repo = _get_repo(request)
        obj = await repo.find_one({"_id": result_id})
        if obj is None:
            raise HTTPException(status_code=404, detail=f"Result '{result_id}' not found.")
        return _serialize(obj)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error fetching result {result_id}: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch result: {str(exc)}")


@router.get("/stats")
async def reconciliation_stats(
    request: Request,
    partner: Optional[str] = Query(default=None, description="Partner identifier"),
    date: Optional[str] = Query(default=None, description="Date (YYYY-MM-DD)"),
):
    try:
        partner = _validate_partner(partner)
        date = _validate_date(date)
    except HTTPException:
        raise

    try:
        repo = _get_repo(request)
        by_status, totals = await asyncio.gather(
            repo.count_by_status(partner, date),
            repo.get_total_amounts(partner, date),
        )
        total = sum(by_status.values())
        return {
            "partner": partner,
            "date": date,
            "total": total,
            "by_status": by_status,
            "total_partner_amount": str(totals["total_partner_amount"]) if totals["total_partner_amount"] is not None else None,
            "total_internal_amount": str(totals["total_internal_amount"]) if totals["total_internal_amount"] is not None else None,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error fetching reconciliation stats: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch stats: {str(exc)}")


async def _run_reconciliation_in_background(db, run_id: str, partner: str, date: str) -> None:
    started_at = datetime.now(timezone.utc)
    await update_runtime_run(
        db,
        run_id,
        status=PartnerRuntimeRunStatus.RECONCILING,
        message="Reconciling records for the selected partner/date.",
        started_at=started_at,
    )
    try:
        recon_date = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        results = await ReconciliationEngine(db).reconcile(partner, recon_date)
        finished_at = datetime.now(timezone.utc)
        await update_runtime_run(
            db,
            run_id,
            status=PartnerRuntimeRunStatus.COMPLETED,
            message="Reconciliation completed successfully.",
            reconciliation_count=len(results),
            finished_at=finished_at,
        )
    except Exception as exc:
        finished_at = datetime.now(timezone.utc)
        await update_runtime_run(
            db,
            run_id,
            status=PartnerRuntimeRunStatus.FAILED,
            message=f"Reconciliation failed: {summarize_runtime_error(exc)}",
            finished_at=finished_at,
        )


@router.post("/run")
async def run_reconciliation_now(request: Request, payload: RunReconciliationPayload):
    try:
        partner = _validate_partner(payload.partner)
        date = _validate_date(payload.date)
    except HTTPException:
        raise

    try:
        db = getattr(request.app.state, "db", None)
        if db is None:
            raise HTTPException(status_code=503, detail="Database connection not available.")
        run = await create_runtime_run(
            db,
            partner=partner,
            date=date,
            trigger_type=PartnerRuntimeTriggerType.MANUAL_RECONCILIATION,
            status=PartnerRuntimeRunStatus.QUEUED,
            message="Reconciliation is queued.",
        )
        task = asyncio.create_task(_run_reconciliation_in_background(db, str(run.id), partner, date))
        _track_background_task(request, task)
        return {"ok": True, "run": serialize_partner_runtime_run(run)}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error running reconciliation: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to run reconciliation: {str(exc)}")


@router.get("/run-status")
async def get_reconciliation_run_status(
    request: Request,
    partner: Optional[str] = Query(default=None, description="Partner identifier"),
    date: Optional[str] = Query(default=None, description="Date (YYYY-MM-DD)"),
):
    partner = _validate_partner(partner)
    date = _validate_date(date)
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Database connection not available.")
    run = await PartnerRuntimeRunRepository(db).find_latest_by_partner_and_date(partner, date)
    if run is None:
        raise HTTPException(status_code=404, detail="Reconciliation run not found.")
    return {"run": serialize_partner_runtime_run(run)}


@router.get("/insights")
async def reconciliation_insights(
    request: Request,
    partner: Optional[str] = Query(default=None, description="Partner identifier"),
    date: Optional[str] = Query(default=None, description="Date (YYYY-MM-DD)"),
    type: Optional[str] = Query(default="summary", description="Insight type: summary | anomalies | patterns | recommendations"),
):
    """Get reconciliation insights (Summary, Anomalies, Patterns, Recommendations)."""
    try:
        partner = _validate_partner(partner)
        date = _validate_date(date)
    except HTTPException:
        raise

    valid_types = ("summary", "anomalies", "patterns", "recommendations")
    if type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid insight type: '{type}'. Must be one of: {', '.join(valid_types)}.",
        )

    try:
        db = getattr(request.app.state, "db", None)
        if db is None:
            raise HTTPException(status_code=503, detail="Database connection not available.")
        collection = db["reconciliation_result"]

        from src.analysis.config import AnalysisConfig
        from src.analysis.provider import create_provider
        llm_provider = create_provider(AnalysisConfig())

        if type == "summary":
            from src.analysis.insights import get_summary
            result = await get_summary(
                partner=partner,
                date=date,
                collection=collection,
                llm_provider=llm_provider,
            )
            result["generated_at"] = datetime.now().isoformat()
            return result
        else:
            from src.analysis.insights import get_discrepancies
            focus_map = {
                "anomalies": "inconsistency",
                "patterns": "partner",
                "recommendations": "operational",
            }
            focus = focus_map[type]
            results = await get_discrepancies(
                partner=partner,
                date=date,
                focus=focus,
                collection=collection,
                llm_provider=llm_provider,
            )
            return [r.model_dump() for r in results]

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error generating reconciliation insights: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to generate reconciliation insights: {str(exc)}")
