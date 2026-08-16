import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from bson import Decimal128

from src.api.dependencies import get_request_db as _get_db
from src.api.query_validation import (
    validate_date as _validate_date,
    validate_partner as _validate_partner,
)
from src.api.response_utils import camelize
from src.domain.partner_transaction.models import DataContainer
from src.infrastructure.partner_transaction.repository import DataContainerRepository
from src.infrastructure.ingestion.file_repository import ReconciliationFileRepository
from src.infrastructure.postgres.reconciliation_result_repository import ReconciliationResultRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/data")


def _serialize_dc(obj: DataContainer) -> dict:
    d = obj.model_dump(by_alias=True)
    d["_id"] = str(d["_id"])
    if "requestId" in d:
        d["requestId"] = str(d["requestId"])
    if "sourceFileId" in d:
        d["sourceFileId"] = str(d["sourceFileId"])
    if d.get("partnerData") and isinstance(d["partnerData"], dict):
        pd = d["partnerData"]
        if pd.get("amount") is not None:
            pd["amount"] = str(pd["amount"])
    return d


@router.get("/transactions")
async def list_transactions(
    request: Request,
    partner: Optional[str] = Query(default=None, description="Partner identifier"),
    date: Optional[str] = Query(default=None, description="Date (YYYY-MM-DD)"),
    trace: Optional[str] = Query(default=None, description="Transaction trace ID"),
    status: Optional[str] = Query(default=None, description="Transaction status"),
    amount_min: Optional[float] = Query(default=None, description="Minimum amount filter"),
    amount_max: Optional[float] = Query(default=None, description="Maximum amount filter"),
    date_from: Optional[str] = Query(default=None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(default=None, description="End date (YYYY-MM-DD)"),
    limit: int = Query(default=100, ge=1, le=1000, description="Max results (max 1000)"),
    offset: int = Query(default=0, ge=0, description="Number of results to skip"),
):
    try:
        partner = _validate_partner(partner)
        if date:
            date = _validate_date(date)
    except HTTPException:
        raise

    try:
        db = _get_db(request)
        query: dict = {}

        if partner:
            query["identify"] = partner

        if date:
            dt = datetime.strptime(date, "%Y-%m-%d")
            start = dt.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
            end = dt.replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=timezone.utc)
            query["reconciliationDate"] = {"$gte": start, "$lte": end}

        if trace:
            query["partnerData.trace"] = trace

        if status:
            query["partnerData.status"] = status

        if amount_min is not None or amount_max is not None:
            amt_filter: dict = {}
            if amount_min is not None:
                amt_filter["$gte"] = Decimal128(str(amount_min))
            if amount_max is not None:
                amt_filter["$lte"] = Decimal128(str(amount_max))
            query["partnerData.amount"] = amt_filter

        if date_from or date_to:
            dr_filter: dict = {}
            if date_from:
                dr_filter["$gte"] = datetime.strptime(date_from, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if date_to:
                dr_filter["$lte"] = datetime.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=timezone.utc)
            query["reconciliationDate"] = dr_filter

        repo = DataContainerRepository(db)
        records = await repo.find_many(query)

        total = len(records)
        page = records[offset:offset + limit]
        return {
            "transactions": [_serialize_dc(r) for r in page],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error listing transactions: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list transactions: {str(exc)}")


@router.get("/transactions/{transaction_id}")
async def get_transaction(request: Request, transaction_id: str):
    try:
        db = _get_db(request)
        transaction = await DataContainerRepository(db).find_by_id(transaction_id)
        if transaction is None:
            raise HTTPException(status_code=404, detail=f"Transaction '{transaction_id}' not found.")
        return _serialize_dc(transaction)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error fetching transaction {transaction_id}: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch transaction: {str(exc)}")


@router.get("/files")
async def list_files(
    request: Request,
    partner: Optional[str] = Query(default=None, description="Partner identifier"),
    date: Optional[str] = Query(default=None, description="Date (YYYY-MM-DD)"),
    status: Optional[str] = Query(default=None, description="Processing status"),
    limit: int = Query(default=100, ge=1, le=1000, description="Max results (max 1000)"),
    offset: int = Query(default=0, ge=0, description="Number of results to skip"),
):
    try:
        partner = _validate_partner(partner)
        if date:
            date = _validate_date(date)
    except HTTPException:
        raise

    try:
        db = _get_db(request)
        query: dict = {}

        if partner:
            query["partner"] = partner

        if date:
            dt = datetime.strptime(date, "%Y-%m-%d")
            start = dt.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
            end = dt.replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=timezone.utc)
            query["reconciliationDate"] = {"$gte": start, "$lte": end}

        if status:
            query["processingStatus"] = status

        repo = ReconciliationFileRepository(db)
        transaction_repo = DataContainerRepository(db)
        records = await repo.find_many(query)

        total = len(records)
        page_records = records[offset:offset + limit]
        files = []
        for r in page_records:
            d = r.model_dump(by_alias=True)
            if "_id" in d:
                d["_id"] = str(d["_id"])
            dc_count = await transaction_repo.count_by_source_file(d["_id"])
            file_partner = d.get("partner", "")
            file_date_raw = d.get("reconciliationDate")
            file_date_str = file_date_raw.strftime("%Y-%m-%d") if hasattr(file_date_raw, "strftime") else str(file_date_raw)[:10] if file_date_raw else None
            rr_count = 0
            if file_partner and file_date_str:
                rr_count = await ReconciliationResultRepository(
                    db
                ).count_by_partner_and_date(file_partner, file_date_str)
            record_count = max(dc_count, rr_count)
            d["recordsCount"] = record_count
            files.append(d)

        return {
            "files": files,
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error listing files: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list files: {str(exc)}")


@router.get("/files/{file_id}")
async def get_file(request: Request, file_id: str):
    try:
        db = _get_db(request)
        raw = await db["reconciliation_file"].find_one({"_id": file_id})
        if raw is None:
            raise HTTPException(status_code=404, detail=f"File '{file_id}' not found.")
        transaction_count = await DataContainerRepository(db).count_by_source_file(file_id)
        raw["_id"] = str(raw["_id"])
        return camelize({
            "file": raw,
            "transactionCount": transaction_count,
        })
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error fetching file {file_id}: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch file: {str(exc)}")


@router.get("/stats")
async def data_stats(
    request: Request,
    partner: Optional[str] = Query(default=None, description="Partner identifier"),
    date: Optional[str] = Query(default=None, description="Date (YYYY-MM-DD)"),
):
    try:
        partner = _validate_partner(partner)
        if date:
            date = _validate_date(date)
    except HTTPException:
        raise

    try:
        db = _get_db(request)

        dc_query: dict = {}
        rf_query: dict = {}
        if partner:
            dc_query["identify"] = partner
            rf_query["partner"] = partner
        if date:
            dt = datetime.strptime(date, "%Y-%m-%d")
            start = dt.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
            end = dt.replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=timezone.utc)
            dc_query["reconciliationDate"] = {"$gte": start, "$lte": end}
            rf_query["reconciliationDate"] = {"$gte": start, "$lte": end}

        transaction_repo = DataContainerRepository(db)
        total_transactions = await transaction_repo.count(dc_query)
        total_files = await db["reconciliation_file"].count_documents(rf_query)

        by_partner: dict[str, int] = {}
        if partner:
            by_partner[partner] = total_transactions
        else:
            by_partner = await transaction_repo.count_by_partner(dc_query)

        return camelize({
            "partner": partner or "*",
            "date": date or "*",
            "totalTransactions": total_transactions,
            "totalFiles": total_files,
            "byPartner": by_partner,
        })
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error fetching data stats: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch data stats: {str(exc)}")
