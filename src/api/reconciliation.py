import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.api.actor import require_actor
from src.domain.runtime.models import (
    PartnerRuntimeRunStatus,
    PartnerRuntimeTriggerType,
)
from src.infrastructure.runtime.repository import PartnerRuntimeRunRepository
from src.core.error_formatting import summarize_runtime_error
from src.domain.reconciliation.models import ReconciliationResult
from src.infrastructure.postgres.reconciliation_result_repository import ReconciliationResultRepository
from src.infrastructure.review.repository import ReconciliationReviewRecordRepository
from src.infrastructure.partner_transaction.repository import DataContainerRepository
from src.core.enums import ReconciliationStatus
from src.application.reconciliation.service import ReconciliationCommand
from src.infrastructure.reconciliation.composition import build_reconciliation_service
from src.reconciliation.engine import ReconciliationEngine  # noqa: F401 - legacy patch seam
from src.services.audit import record_audit_event
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
    note: Optional[str] = None


class RunReconciliationPayload(BaseModel):
    partner: str
    date: str
    triggered_by: Optional[str] = Field(default=None, alias="triggeredBy")


def _track_background_task(request: Request, task: asyncio.Task) -> None:
    tasks = getattr(request.app.state, "background_tasks", None)
    if tasks is None:
        tasks = set()
        request.app.state.background_tasks = tasks
    tasks.add(task)
    task.add_done_callback(tasks.discard)


def _validate_date(date_str: Optional[str]) -> str:
    if date_str is None:
        raise HTTPException(
            status_code=400, detail="Date parameter is required (YYYY-MM-DD format)."
        )
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=400, detail=f"Invalid date format: '{date_str}'. Expected YYYY-MM-DD."
        )
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


def _date_bounds(date_str: str) -> tuple[datetime, datetime]:
    day = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return (
        day.replace(hour=0, minute=0, second=0, microsecond=0),
        day.replace(hour=23, minute=59, second=59, microsecond=999999),
    )


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


async def _resolve_latest_run_filters(db, partner: str, date: str) -> dict[str, object]:
    context = await _resolve_latest_run_context(db, partner, date)
    if context.get("source_file_id"):
        file_id = context["source_file_id"]
        file_doc = await db["reconciliation_file"].find_one({"_id": file_id})
        if file_doc and file_doc.get("scopeType") == "INCREMENTAL_APPEND":
            start_of_day, end_of_day = _date_bounds(date)
            cursor = db["reconciliation_file"].find(
                {
                    "partner": partner,
                    "reconciliationDate": {"$gte": start_of_day, "$lte": end_of_day},
                    "createdAt": {"$lte": file_doc["createdAt"]},
                }
            )
            file_ids = []
            async for f in cursor:
                file_ids.append(str(f["_id"]))
            if file_ids:
                return {"source_file_id": {"$in": file_ids}}
        return {"source_file_id": file_id}
    run = await PartnerRuntimeRunRepository(db).find_latest_by_partner_and_date(partner, date)
    if run is not None and getattr(run, "id", None):
        return {"reconciliation_run_id": str(run.id)}
    return {}


async def _resolve_latest_run_context(db, partner: str, date: str) -> dict[str, str]:
    context: dict[str, str] = {}
    start_of_day, end_of_day = _date_bounds(date)
    latest_post_approval_run = await db["post_approval_run"].find_one(
        {
            "partner": partner,
            "date": date,
            "$or": [
                {"outputFileId": {"$nin": [None, ""]}},
                {"sourceFileId": {"$nin": [None, ""]}},
            ],
        },
        sort=[("updatedAt", -1), ("createdAt", -1)],
    )

    latest_scoped_run = await db["partner_runtime_run"].find_one(
        {
            "partner": partner,
            "date": date,
            "sourceFileId": {"$nin": [None, ""]},
        },
        sort=[("createdAt", -1)],
    )

    latest_file = await db["reconciliation_file"].find_one(
        {"partner": partner, "reconciliationDate": {"$gte": start_of_day, "$lte": end_of_day}},
        sort=[("createdAt", -1)],
    )

    candidates = []
    if latest_post_approval_run is not None:
        ts = latest_post_approval_run.get("updatedAt") or latest_post_approval_run.get("createdAt")
        candidates.append((ts, "post_approval_run", latest_post_approval_run))

    if latest_scoped_run is not None:
        ts = latest_scoped_run.get("updatedAt") or latest_scoped_run.get("createdAt")
        candidates.append((ts, "partner_runtime_run", latest_scoped_run))

    if latest_file is not None:
        ts = latest_file.get("createdAt")
        candidates.append((ts, "reconciliation_file", latest_file))

    if not candidates:
        return context

    # Sort candidates by timestamp (newest first)
    # Since they are MongoDB UTC datetimes, we can compare them directly.
    candidates.sort(key=lambda x: x[0], reverse=True)
    newest_type = candidates[0][1]
    newest_doc = candidates[0][2]

    if newest_type == "post_approval_run":
        output_file_id = newest_doc.get("outputFileId")
        source_file_id = newest_doc.get("sourceFileId")
        if output_file_id:
            context["source_file_id"] = str(output_file_id)
        elif source_file_id:
            context["source_file_id"] = str(source_file_id)
    elif newest_type == "partner_runtime_run":
        if newest_doc.get("sourceFileId"):
            context["source_file_id"] = str(newest_doc["sourceFileId"])
        if newest_doc.get("mappingVersion"):
            context["mapping_version"] = str(newest_doc["mappingVersion"])
    elif newest_type == "reconciliation_file":
        if newest_doc.get("_id"):
            context["source_file_id"] = str(newest_doc["_id"])

    return context


async def _count_partner_rows_for_source_file(db, source_file_id: str) -> int:
    return await DataContainerRepository(db).count_by_source_file(source_file_id)


async def _resolve_display_run(db, partner: str, date: str):
    latest_context = await _resolve_latest_run_context(db, partner, date)
    latest_source_file_id = latest_context.get("source_file_id")
    if latest_source_file_id:
        latest_context_run_raw = await db["partner_runtime_run"].find_one(
            {
                "partner": partner,
                "date": date,
                "sourceFileId": latest_source_file_id,
            },
            sort=[("createdAt", -1)],
        )
        if latest_context_run_raw is not None:
            return PartnerRuntimeRunRepository(db)._from_mongo(latest_context_run_raw)

    active_statuses = [
        PartnerRuntimeRunStatus.WAITING_REVIEW.value,
        PartnerRuntimeRunStatus.WAITING_RECONCILE.value,
        PartnerRuntimeRunStatus.RECONCILING.value,
        PartnerRuntimeRunStatus.INGESTING.value,
        PartnerRuntimeRunStatus.FETCHING.value,
        PartnerRuntimeRunStatus.QUEUED.value,
    ]
    active_run_raw = await db["partner_runtime_run"].find_one(
        {"partner": partner, "date": date, "status": {"$in": active_statuses}},
        sort=[("createdAt", -1)],
    )
    if active_run_raw is not None:
        return PartnerRuntimeRunRepository(db)._from_mongo(active_run_raw)

    latest_scoped_run_raw = await db["partner_runtime_run"].find_one(
        {
            "partner": partner,
            "date": date,
            "sourceFileId": {"$nin": [None, ""]},
        },
        sort=[("createdAt", -1)],
    )
    if latest_scoped_run_raw is not None:
        return PartnerRuntimeRunRepository(db)._from_mongo(latest_scoped_run_raw)

    return await PartnerRuntimeRunRepository(db).find_latest_by_partner_and_date(partner, date)


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
    actor = require_actor(request, payload_field_name="actor")
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
                "reviewedBy": actor,
                "updatedAt": now,
            },
            "$push": {
                "notes": {
                    "time": _review_note_timestamp(),
                    "event": f"{actor}: {note}",
                }
            },
        },
        upsert=True,
    )
    db = getattr(request.app.state, "db", None)
    if db is not None:
        await record_audit_event(
            db,
            entity_type="DISCREPANCY_REVIEW",
            entity_id=record_key,
            action="COMMENTED",
            metadata={
                "partner": partner,
                "date": date,
                "recordKey": record_key,
                "note": note,
                "actor": actor,
            },
        )
    record = await repo.find_one({"partner": partner, "date": date, "recordKey": record_key})
    return {"ok": True, "record": _serialize_review_record(record)}


@router.post("/review-records/{record_key}/resolve")
async def resolve_review_record(request: Request, record_key: str, payload: ResolveReviewPayload):
    actor = require_actor(request, payload_field_name="actor")
    partner = _validate_partner(payload.partner)
    date = _validate_date(payload.date)
    note = (payload.note or "").strip()
    now = datetime.now(timezone.utc)
    repo = _get_review_repo(request)

    update_doc = {
        "$setOnInsert": {
            "_id": record_key,
            "partner": partner,
            "date": date,
            "recordKey": record_key,
            "createdAt": now,
        },
        "$set": {
            "reviewed": True,
            "reviewedBy": actor,
            "resolvedBy": actor,
            "resolvedStatus": payload.resolved_status,
            "updatedAt": now,
        },
    }
    if note:
        update_doc["$push"] = {
            "notes": {
                "time": _review_note_timestamp(),
                "event": f"{actor}: {note}",
            }
        }

    await repo.collection.update_one(
        {"partner": partner, "date": date, "recordKey": record_key},
        update_doc,
        upsert=True,
    )
    db = getattr(request.app.state, "db", None)
    if db is not None:
        await record_audit_event(
            db,
            entity_type="DISCREPANCY_REVIEW",
            entity_id=record_key,
            action="RESOLVED",
            metadata={
                "partner": partner,
                "date": date,
                "recordKey": record_key,
                "resolvedStatus": payload.resolved_status,
                "actor": actor,
                **({"note": note} if note else {}),
            },
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
            **(
                await _resolve_latest_run_filters(
                    getattr(request.app.state, "db", None), partner, date
                )
            ),
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
        obj = await repo.find_by_id(result_id)
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
        scope_filters = await _resolve_latest_run_filters(
            getattr(request.app.state, "db", None), partner, date
        )
        by_status, totals = await asyncio.gather(
            repo.count_by_status(partner, date, **scope_filters),
            repo.get_total_amounts(partner, date, **scope_filters),
        )
        total = sum(by_status.values())
        return {
            "partner": partner,
            "date": date,
            "total": total,
            "byStatus": by_status,
            "totalPartnerAmount": str(totals["total_partner_amount"])
            if totals["total_partner_amount"] is not None
            else None,
            "totalInternalAmount": str(totals["total_internal_amount"])
            if totals["total_internal_amount"] is not None
            else None,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error fetching reconciliation stats: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch stats: {str(exc)}")


async def _run_reconciliation_in_background(
    db,
    run_id: str,
    partner: str,
    date: str,
    source_file_id: str | None = None,
    mapping_version: str | None = None,
) -> None:
    started_at = datetime.now(timezone.utc)
    await update_runtime_run(
        db,
        run_id,
        status=PartnerRuntimeRunStatus.RECONCILING,
        message="Reconciling records for the selected partner/date.",
        started_at=started_at,
        source_file_id=source_file_id,
        mapping_version=mapping_version,
    )
    try:
        recon_date = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        results = await build_reconciliation_service(
            db,
            fast_mode=True,
            # Keep the API-level engine seam injectable for manual-run tests.
            engine_factory=ReconciliationEngine,
        ).execute(
            ReconciliationCommand(
                partner=partner,
                reconciliation_date=recon_date,
                source_file_id=source_file_id,
                reconciliation_run_id=run_id,
                mapping_version=mapping_version,
            )
        )
        finished_at = datetime.now(timezone.utc)
        await update_runtime_run(
            db,
            run_id,
            status=PartnerRuntimeRunStatus.COMPLETED,
            message="Reconciliation completed successfully.",
            validation_state="NOT_RUN",
            stats={"resultCount": len(results)},
            reconciliation_count=len(results),
            finished_at=finished_at,
        )
        run_doc = await db["partner_runtime_run"].find_one({"_id": run_id})
        await record_audit_event(
            db,
            entity_type="RECONCILIATION_RUN",
            entity_id=run_id,
            action="COMPLETED",
            metadata={
                "partner": partner,
                "date": date,
                "status": PartnerRuntimeRunStatus.COMPLETED.value,
                "reference": run_id,
                "sourceFileId": run_doc.get("sourceFileId") if run_doc else None,
                "mappingVersion": run_doc.get("mappingVersion") if run_doc else None,
                "reconciliationCount": len(results),
            },
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
        run_doc = await db["partner_runtime_run"].find_one({"_id": run_id})
        await record_audit_event(
            db,
            entity_type="RECONCILIATION_RUN",
            entity_id=run_id,
            action="FAILED",
            metadata={
                "partner": partner,
                "date": date,
                "status": PartnerRuntimeRunStatus.FAILED.value,
                "reference": run_id,
                "sourceFileId": run_doc.get("sourceFileId") if run_doc else None,
                "mappingVersion": run_doc.get("mappingVersion") if run_doc else None,
                "error": summarize_runtime_error(exc),
            },
        )


@router.post("/run")
async def run_reconciliation_now(request: Request, payload: RunReconciliationPayload):
    try:
        partner = _validate_partner(payload.partner)
        date = _validate_date(payload.date)
        triggered_by = require_actor(
            request,
            payload_actor=payload.triggered_by,
            payload_field_name="triggeredBy",
        )
    except HTTPException:
        raise

    try:
        db = getattr(request.app.state, "db", None)
        if db is None:
            raise HTTPException(status_code=503, detail="Database connection not available.")
        latest_context = await _resolve_latest_run_context(db, partner, date)
        source_file_id = latest_context.get("source_file_id")
        if not source_file_id:
            raise HTTPException(
                status_code=409,
                detail="No partner file context is available for this date. Run ingestion first or finish the review flow before reconciling.",
            )
        partner_row_count = await _count_partner_rows_for_source_file(db, source_file_id)
        if partner_row_count <= 0:
            raise HTTPException(
                status_code=409,
                detail="The latest partner file has not been ingested yet. Complete approval/ingestion before running reconciliation.",
            )
        run = await create_runtime_run(
            db,
            partner=partner,
            date=date,
            trigger_type=PartnerRuntimeTriggerType.MANUAL_RECONCILIATION,
            triggered_by=triggered_by,
            status=PartnerRuntimeRunStatus.QUEUED,
            message="Reconciliation is queued.",
            validation_state="NOT_RUN",
        )
        if latest_context.get("source_file_id"):
            await update_runtime_run(
                db,
                str(run.id),
                source_file_id=source_file_id,
                mapping_version=latest_context.get("mapping_version"),
            )
        task = asyncio.create_task(
            _run_reconciliation_in_background(
                db,
                str(run.id),
                partner,
                date,
                source_file_id=source_file_id,
                mapping_version=latest_context.get("mapping_version"),
            )
        )
        _track_background_task(request, task)
        queued_run = await PartnerRuntimeRunRepository(db).find_one({"_id": str(run.id)})
        return {"ok": True, "run": serialize_partner_runtime_run(queued_run or run)}
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
    run = await _resolve_display_run(db, partner, date)
    if run is None:
        raise HTTPException(status_code=404, detail="Reconciliation run not found.")
    return {"run": serialize_partner_runtime_run(run)}


@router.get("/insights")
async def reconciliation_insights(
    request: Request,
    partner: Optional[str] = Query(default=None, description="Partner identifier"),
    date: Optional[str] = Query(default=None, description="Date (YYYY-MM-DD)"),
    type: Optional[str] = Query(
        default="summary",
        description="Insight type: summary | anomalies | patterns | recommendations",
    ),
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
        repo = ReconciliationResultRepository(db)

        from src.analysis.config import AnalysisConfig
        from src.analysis.provider import create_provider

        llm_provider = create_provider(AnalysisConfig())

        if type == "summary":
            from src.analysis.insights import get_summary

            result = await get_summary(
                partner=partner,
                date=date,
                collection=repo,
                llm_provider=llm_provider,
                extra_query=await _resolve_latest_run_filters(db, partner, date),
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
                collection=repo,
                llm_provider=llm_provider,
                extra_query=await _resolve_latest_run_filters(db, partner, date),
            )
            return [r.model_dump() for r in results]

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error generating reconciliation insights: {exc}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to generate reconciliation insights: {str(exc)}"
        )
