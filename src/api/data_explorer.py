import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from src.models.data_container import DataContainer, DataContainerRepository
from src.models.reconciliation_file import ReconciliationFileRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/data")


def _validate_date(date_str: Optional[str]) -> str:
    if date_str is None:
        raise HTTPException(status_code=400, detail="Date parameter is required (YYYY-MM-DD format).")
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid date format: '{date_str}'. Expected YYYY-MM-DD.")
    return date_str


def _validate_partner(partner: Optional[str]) -> Optional[str]:
    if partner is not None and not partner.strip():
        raise HTTPException(status_code=400, detail="Partner identifier cannot be empty.")
    return partner.strip() if partner else None


def _get_db(request: Request):
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Database connection not available.")
    return db


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
        raw = await db["data_container"].find_one({"_id": transaction_id})
        if raw is None:
            raise HTTPException(status_code=404, detail=f"Transaction '{transaction_id}' not found.")
        obj = DataContainer.model_validate(raw)
        return _serialize_dc(obj)
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
        records = await repo.find_many(query)

        total = len(records)
        page_records = records[offset:offset + limit]
        files = []
        for r in page_records:
            d = r.model_dump(by_alias=True)
            if "_id" in d:
                d["_id"] = str(d["_id"])
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
        transaction_count = await db["data_container"].count_documents({"sourceFileId": file_id})
        raw["_id"] = str(raw["_id"])
        return {
            "file": raw,
            "transaction_count": transaction_count,
        }
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

        total_transactions = await db["data_container"].count_documents(dc_query)
        total_files = await db["reconciliation_file"].count_documents(rf_query)

        by_partner: dict[str, int] = {}
        if partner:
            by_partner[partner] = total_transactions
        else:
            pipeline = [
                {"$group": {"_id": "$identify", "count": {"$sum": 1}}},
            ]
            cursor = db["data_container"].aggregate(pipeline)
            async for doc in cursor:
                by_partner[str(doc["_id"])] = doc["count"]

        return {
            "partner": partner or "*",
            "date": date or "*",
            "total_transactions": total_transactions,
            "total_files": total_files,
            "by_partner": by_partner,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error fetching data stats: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch data stats: {str(exc)}")
