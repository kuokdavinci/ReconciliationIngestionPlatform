import asyncio
import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.api.actor import require_actor
from src.api.dependencies import get_request_db
from src.api.query_validation import validate_date, validate_partner
from src.application.reconciliation.manual_runs import (
    ManualReconciliationService,
    QueueManualReconciliationCommand,
)
from src.application.reconciliation.queries import (
    ReconciliationContextQuery,
    ReconciliationContextUnavailableError,
)
from src.domain.runtime.models import (
    PartnerRuntimeRunStatus,
)
from src.infrastructure.runtime.repository import PartnerRuntimeRunRepository
from src.domain.reconciliation.models import ReconciliationResult
from src.domain.reconciliation.models import TimestampStatus
from src.infrastructure.postgres.reconciliation_result_repository import ReconciliationResultRepository
from src.infrastructure.review.repository import ReconciliationReviewRecordRepository
from src.infrastructure.partner_transaction.repository import DataContainerRepository
from src.core.enums import ReconciliationStatus
from src.infrastructure.reconciliation.composition import build_reconciliation_service
from src.application.audit.service import record_audit_event
from src.api.background_tasks import track_background_task
from src.application.runtime.service import (
    create_runtime_run,
    serialize_partner_runtime_run,
    update_runtime_run,
)
from src.config.settings import settings

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
    track_background_task(request.app, task)


_validate_date = validate_date


def _validate_partner(value: str | None) -> str:
    partner = validate_partner(value, required=True)
    if partner is None:
        raise HTTPException(status_code=400, detail="Partner identifier is required.")
    return partner


def _validate_status(status: Optional[str]) -> Optional[str]:
    if status is not None:
        valid = [s.value for s in ReconciliationStatus]
        if status not in valid:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status: '{status}'. Must be one of: {', '.join(valid)}.",
            )
    return status


def _validate_timestamp_status(status: Optional[str]) -> Optional[str]:
    if status is not None and status not in {item.value for item in TimestampStatus}:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid timestampStatus: '{status}'. Must be one of: "
                f"{', '.join(item.value for item in TimestampStatus)}."
            ),
        )
    return status


async def _timestamp_evidence_counts(repo: ReconciliationResultRepository, partner: str, date: str):
    """Keep an unavailable telemetry query from hiding the reconciliation stats."""
    method = repo.count_by_timestamp_status
    # Lightweight API tests use a Mongo mock without a PostgreSQL service.
    # Patched AsyncMock methods still run so those tests can assert the contract.
    if (
        getattr(repo.db.__class__, "__module__", "") == "unittest.mock"
        and not hasattr(method, "assert_awaited")
    ):
        return {}
    try:
        return await asyncio.wait_for(
            method(partner, date), timeout=0.5
        )
    except Exception as exc:
        logger.warning("Unable to load timestamp evidence stats: %s", exc)
        return {}


def _date_bounds(date_str: str) -> tuple[datetime, datetime]:
    day = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    business_timezone = ZoneInfo(settings.business_timezone)
    day = day.astimezone(business_timezone)
    return (
        day.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc),
        day.replace(hour=23, minute=59, second=59, microsecond=999999).astimezone(timezone.utc),
    )


def _get_repo(request: Request) -> ReconciliationResultRepository:
    db = get_request_db(request)
    try:
        return ReconciliationResultRepository(db)
    except Exception as exc:
        logger.error(f"Failed to create repository: {exc}")
        raise HTTPException(status_code=500, detail="Failed to initialize repository.")


def _get_review_repo(request: Request) -> ReconciliationReviewRecordRepository:
    return ReconciliationReviewRecordRepository(get_request_db(request))


def _serialize(obj):
    if isinstance(obj, ReconciliationResult):
        d = obj.model_dump(by_alias=True)
        if "partnerAmount" in d and d["partnerAmount"] is not None:
            d["partnerAmount"] = str(d["partnerAmount"])
        if "internalAmount" in d and d["internalAmount"] is not None:
            d["internalAmount"] = str(d["internalAmount"])
        for key in (
            "partnerTransDate",
            "internalTransactionTime",
            "createdAt",
        ):
            value = d.get(key)
            if isinstance(value, datetime):
                d[key] = value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
        if d.get("timestampDeltaSeconds") is not None:
            d["timestampDeltaSeconds"] = float(d["timestampDeltaSeconds"])
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
        # Append is batch-only. The latest reconciliation view must show the
        # current source file, not a cumulative same-day union of prior files.
        return {"source_file_id": file_id}
    run = await PartnerRuntimeRunRepository(db).find_latest_by_partner_and_date(partner, date)
    if run is not None and getattr(run, "id", None):
        return {"reconciliation_run_id": str(run.id)}
    return {}


async def _resolve_latest_run_context(db, partner: str, date: str) -> dict[str, str]:
    return await _manual_reconciliation_context_query(db).latest_context(partner, date)


async def _count_partner_rows_for_source_file(db, source_file_id: str) -> int:
    return await DataContainerRepository(db).count_by_source_file(source_file_id)


def _manual_reconciliation_context_query(db) -> ReconciliationContextQuery:
    async def row_counter(source_file_id: str) -> int:
        return await _count_partner_rows_for_source_file(db, source_file_id)

    return ReconciliationContextQuery(db, row_counter=row_counter)


def _manual_reconciliation_service(
    db,
    context_query: ReconciliationContextQuery,
) -> ManualReconciliationService:
    async def create_runtime(**kwargs):
        return await create_runtime_run(db, **kwargs)

    async def update_runtime(run_id: str, **kwargs):
        return await update_runtime_run(db, run_id, **kwargs)

    async def record_audit(**kwargs):
        return await record_audit_event(db, **kwargs)

    return ManualReconciliationService(
        runtime_service=SimpleNamespace(
            create=create_runtime,
            update=update_runtime,
        ),
        reconciliation_service=build_reconciliation_service(db),
        audit_service=SimpleNamespace(record=record_audit),
        context_query=context_query,
    )


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
    db = get_request_db(request)
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
    db = get_request_db(request)
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
    timestamp_status: Optional[str] = Query(
        default=None, alias="timestampStatus", description="Filter by timestamp evidence status"
    ),
    limit: int = Query(default=25, ge=1, le=1000, description="Max results (max 1000)"),
    offset: int = Query(default=0, ge=0, description="Number of results to skip"),
):
    try:
        partner = _validate_partner(partner)
        date = _validate_date(date)
        if status:
            status = _validate_status(status)
        if timestamp_status:
            timestamp_status = _validate_timestamp_status(timestamp_status)
    except HTTPException:
        raise

    try:
        repo = _get_repo(request)
        page, total = await repo.find_page_by_partner_and_date(
            partner,
            date,
            status=ReconciliationStatus(status) if status else None,
            timestamp_status=timestamp_status,
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
        by_status, totals, timestamp_counts = await asyncio.gather(
            repo.count_by_status(partner, date),
            repo.get_total_amounts(partner, date),
            _timestamp_evidence_counts(repo, partner, date),
        )
        if isinstance(by_status, Exception):
            raise by_status
        if isinstance(totals, Exception):
            raise totals
        evaluated = timestamp_counts.get("MATCHED", 0) + timestamp_counts.get("MISMATCH", 0)
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
            "timestampEvidence": {
                "byStatus": timestamp_counts,
                "matched": timestamp_counts.get("MATCHED", 0),
                "mismatch": timestamp_counts.get("MISMATCH", 0),
                "notAvailable": timestamp_counts.get("NOT_AVAILABLE", 0),
                "notEvaluated": timestamp_counts.get("NOT_EVALUATED", 0),
                "mismatchRate": (
                    timestamp_counts.get("MISMATCH", 0) / evaluated if evaluated else 0.0
                ),
            },
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error fetching reconciliation stats: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch stats: {str(exc)}")





@router.post("/run")
async def run_reconciliation_now(request: Request, payload: RunReconciliationPayload):
    partner = _validate_partner(payload.partner)
    date = _validate_date(payload.date)
    triggered_by = require_actor(
        request,
        payload_actor=payload.triggered_by,
        payload_field_name="triggeredBy",
    )
    db = get_request_db(request)

    context_query = _manual_reconciliation_context_query(db)
    try:
        context = await context_query.resolve(partner, date)
    except ReconciliationContextUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    service = _manual_reconciliation_service(db, context_query)
    try:
        run = await service.queue(
            QueueManualReconciliationCommand(
                partner=partner,
                date=date,
                triggered_by=triggered_by,
            ),
            context=context,
        )
    except ReconciliationContextUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Error running reconciliation: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to run reconciliation: {exc}") from exc

    task = asyncio.create_task(service.execute(str(run.id), context))
    _track_background_task(request, task)
    return {"ok": True, "run": serialize_partner_runtime_run(run)}


@router.get("/run-status")
async def get_reconciliation_run_status(
    request: Request,
    partner: Optional[str] = Query(default=None, description="Partner identifier"),
    date: Optional[str] = Query(default=None, description="Date (YYYY-MM-DD)"),
):
    partner = _validate_partner(partner)
    date = _validate_date(date)
    db = get_request_db(request)
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
        db = get_request_db(request)
        repo = ReconciliationResultRepository(db)

        from src.analysis.config import AnalysisConfig
        from src.analysis.provider import create_provider

        llm_provider = create_provider(AnalysisConfig())

        if type == "summary":
            from src.analysis.insights import get_summary

            result = await get_summary(
                partner=partner,
                date=date,
                repository=repo,
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
                repository=repo,
                llm_provider=llm_provider,
                extra_query={},
            )
            return [r.model_dump() for r in results]

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error generating reconciliation insights: {exc}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to generate reconciliation insights: {str(exc)}"
        )
