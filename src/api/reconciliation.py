import asyncio
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from src.models.reconciliation_result import (
    ReconciliationResult,
    ReconciliationResultRepository,
)
from src.core.enums import ReconciliationStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/reconciliation")


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


@router.get("/results")
async def list_results(
    request: Request,
    partner: Optional[str] = Query(default=None, description="Partner identifier"),
    date: Optional[str] = Query(default=None, description="Date (YYYY-MM-DD)"),
    status: Optional[str] = Query(default=None, description="Filter by reconciliation status"),
    limit: int = Query(default=100, ge=1, le=1000, description="Max results (max 1000)"),
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
        if status:
            records = await repo.find_by_partner_date_and_status(
                partner, date, ReconciliationStatus(status)
            )
        else:
            records = await repo.find_by_partner_and_date(partner, date)

        total = len(records)
        page = records[offset:offset + limit]
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



