#!/usr/bin/env python3
"""Benchmark 1M-row reconciliation behavior for current vs baseline paths.

This script:
1. Seeds a synthetic 1,000,000-row partner dataset and matching internal set
   with the same reconciliation status ratios observed in the 100k VNPAY case.
2. Runs an optimized reconciliation simulation (streamed partner batches +
   projected internal query + chunked writes).
3. Runs a baseline reconciliation simulation (full materialization of partner,
   internal, and result lists before one bulk insert flow).
4. Benchmarks current vs baseline query/data-prep paths on the resulting 1M
   reconciliation results.

It writes benchmark result documents into:
- reconciliation_result            (optimized)
- reconciliation_result_baseline_tmp (baseline)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID
from typing import Any

from bson.decimal128 import Decimal128
from pymongo import MongoClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.domain.internal_transaction.models import InternalTransaction
from src.core.enums import TransactionStatus
from src.infrastructure.postgres.internal_transaction_repository import (
    InternalTransactionRepository,
)
from src.reconciliation.keys import normalize_reconciliation_key


PARTNER = "VNPAY_1M_BENCH"
DATE_STR = "2026-06-16"
SOURCE_FILE_ID = str(UUID(int=9_999_999))
WORKFLOW_TYPE = "UPC"
CREATED_BY = "benchmark_1m"
PARTNER_BATCH_SIZE = 5000
WRITE_BATCH_SIZE = 5000
BASE_AMOUNTS = [50_000, 100_000, 150_000, 200_000, 300_000, 500_000, 1_000_000]


STATUS_COUNTS_1M = {
    "MATCHED": 70,
    "STATUS_MISMATCH": 10,
    "MISSING_INTERNAL": 144_370,
    "AMOUNT_MISMATCH": 658_660,
    "MULTIPLE_MISMATCH": 196_890,
}


@dataclass
class BenchmarkResult:
    avg_s: float
    min_s: float
    max_s: float
    output: dict


def uuid_str(n: int) -> str:
    return str(UUID(int=n))


def iso_day_bounds(date_str: str) -> tuple[datetime, datetime]:
    day = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    end = day.replace(hour=23, minute=59, second=59, microsecond=999999)
    return start, end


def amount_for_idx(idx: int) -> int:
    return BASE_AMOUNTS[idx % len(BASE_AMOUNTS)] + (idx % 997)


def status_for_idx(idx: int) -> str:
    return "SUCCESS" if idx % 11 else "FAILED"


def mismatch_status_for(partner_status: str) -> str:
    return "FAILED" if partner_status == "SUCCESS" else "SUCCESS"


def build_partner_doc(idx: int, trace: str, amount: int, status: str, recon_date: datetime) -> dict:
    return {
        "_id": uuid_str(idx),
        "requestId": uuid_str(2_000_000 + idx),
        "identify": PARTNER,
        "workflowType": WORKFLOW_TYPE,
        "reconciliationDate": recon_date,
        "operationStatus": "COMPLETED",
        "reconciliationStatus": "",
        "connectorData": "",
        "extraData": "",
        "sourceFileId": SOURCE_FILE_ID,
        "partnerData": {
            "_id": f"P{idx:07d}",
            "trace": trace,
            "status": status,
            "amount": Decimal128(str(amount)),
            "currency": "VND",
            "transDate": recon_date,
            "extra": {"provider": "VNPAY", "seed": "benchmark_1m"},
        },
        "createdBy": CREATED_BY,
        "createdDate": recon_date,
        "lastModifiedBy": CREATED_BY,
        "lastModifiedDate": recon_date,
    }


def build_internal_doc(
    idx: int, trace: str, amount: int, status: str, recon_date: datetime
) -> InternalTransaction:
    return InternalTransaction(
        _id=f"INT_{idx:07d}",
        partner=PARTNER,
        partnerTxnId=trace,
        amount=Decimal(amount),
        currency="VND",
        status=TransactionStatus(status),
        transactionTime=recon_date,
        createdAt=recon_date,
        updatedAt=recon_date,
    )


def load_internal_records(start: datetime, end: datetime) -> list[dict[str, Any]]:
    """Load source-of-truth internal transactions through PostgreSQL."""

    async def _load() -> list[dict[str, Any]]:
        repository = InternalTransactionRepository()
        records = await repository.find_by_partner_and_date_range(PARTNER, start, end)
        return [
            {
                "_id": record.id,
                "partnerTxnId": record.partner_txn_id,
                "amount": record.amount,
                "status": record.status,
                "updatedAt": record.updated_at,
            }
            for record in records
        ]

    return asyncio.run(_load())


def seed_dataset(db) -> dict:
    start_of_day, _ = iso_day_bounds(DATE_STR)
    dc = db["data_container"]
    recon = db["reconciliation_result"]
    baseline_recon = db["reconciliation_result_baseline_tmp"]
    runs = db["partner_runtime_run"]

    dc.delete_many({"identify": PARTNER, "reconciliationDate": {"$gte": start_of_day, "$lte": start_of_day.replace(hour=23, minute=59, second=59, microsecond=999999)}})
    recon.delete_many({"partner": PARTNER, "date": DATE_STR})
    baseline_recon.delete_many({"partner": PARTNER, "date": DATE_STR})
    runs.delete_many({"partner": PARTNER, "date": DATE_STR})

    partner_batch: list[dict] = []
    internal_batch: list[InternalTransaction] = []
    internal_repository = InternalTransactionRepository()
    asyncio.run(internal_repository.delete_by_partner(PARTNER))
    counts: defaultdict[str, int] = defaultdict(int)
    idx = 1

    def flush():
        nonlocal partner_batch, internal_batch
        if partner_batch:
            dc.insert_many(partner_batch, ordered=False)
            partner_batch = []
        if internal_batch:
            asyncio.run(internal_repository.insert_many(internal_batch))
            internal_batch = []

    for status_name, count in STATUS_COUNTS_1M.items():
        for _ in range(count):
            trace = f"VNPAY1M{idx:07d}"
            amount = amount_for_idx(idx)
            partner_status = status_for_idx(idx)
            partner_batch.append(build_partner_doc(idx, trace, amount, partner_status, start_of_day))
            counts["partner_rows"] += 1

            if status_name == "MATCHED":
                internal_batch.append(build_internal_doc(idx, trace, amount, partner_status, start_of_day))
                counts["internal_rows"] += 1
            elif status_name == "STATUS_MISMATCH":
                internal_batch.append(build_internal_doc(idx, trace, amount, mismatch_status_for(partner_status), start_of_day))
                counts["internal_rows"] += 1
            elif status_name == "AMOUNT_MISMATCH":
                internal_batch.append(build_internal_doc(idx, trace, amount + 1000, partner_status, start_of_day))
                counts["internal_rows"] += 1
            elif status_name == "MULTIPLE_MISMATCH":
                internal_batch.append(build_internal_doc(idx, trace, amount + 1000, mismatch_status_for(partner_status), start_of_day))
                counts["internal_rows"] += 1
            elif status_name == "MISSING_INTERNAL":
                pass

            if len(partner_batch) >= WRITE_BATCH_SIZE or len(internal_batch) >= WRITE_BATCH_SIZE:
                flush()
            idx += 1

    flush()
    return dict(counts)


def normalize_status(status_str: object) -> str:
    status_lower = str(status_str).strip().lower()
    if status_lower in ("success", "thành công", "matched"):
        return "SUCCESS"
    if status_lower in ("fail", "failed", "thất bại"):
        return "FAILED"
    if status_lower in ("reversed", "hoàn tiền"):
        return "REVERSED"
    return "PENDING"


def is_finalized_internal_status(status: object) -> bool:
    return normalize_status(status) in {"SUCCESS", "FAILED", "REVERSED"}


def resolve_partner_txn_id(doc: dict) -> str | None:
    pd = doc.get("partnerData") or {}
    extra = pd.get("extra") or {}
    return normalize_reconciliation_key(
        pd.get("trace"),
        extra.get("vspTransId"),
        pd.get("id"),
    )


def pre_check(doc: dict) -> tuple[bool, str]:
    pd = doc.get("partnerData")
    if pd is None:
        return False, "empty_partner_data"
    if pd.get("amount") is None:
        return False, "missing_amount"
    status = pd.get("status")
    if status is None or (isinstance(status, str) and status.strip() == ""):
        return False, "missing_status"
    return True, ""


def result_doc(
    *,
    partner_txn_id: str,
    reconciliation_status: str,
    partner_amount=None,
    internal_amount=None,
    partner_status=None,
    internal_status=None,
    partner_record_id=None,
    internal_record_id=None,
) -> dict:
    doc: dict[str, Any] = {
        "_id": partner_txn_id,
        "partner": PARTNER,
        "date": DATE_STR,
        "partnerTxnId": partner_txn_id,
        "reconciliationStatus": reconciliation_status,
        "sourceFileId": None,
        "scopeType": "FULL_SNAPSHOT",
        "createdAt": datetime.now(timezone.utc),
    }
    if partner_amount is not None:
        doc["partnerAmount"] = Decimal128(str(partner_amount))
    if internal_amount is not None:
        doc["internalAmount"] = Decimal128(str(internal_amount))
    if partner_status is not None:
        doc["partnerStatus"] = partner_status
    if internal_status is not None:
        doc["internalStatus"] = internal_status
    if partner_record_id is not None:
        doc["partnerRecordId"] = partner_record_id
    if internal_record_id is not None:
        doc["internalRecordId"] = internal_record_id
        doc["internalTxnId"] = internal_record_id
    return doc


def _updated_at(record: dict[str, Any]) -> datetime:
    value = record.get("updatedAt")
    return value if isinstance(value, datetime) else datetime.min.replace(tzinfo=timezone.utc)


def optimized_reconcile(db) -> dict:
    start_of_day, end_of_day = iso_day_bounds(DATE_STR)
    partner_query = {"identify": PARTNER, "reconciliationDate": {"$gte": start_of_day, "$lte": end_of_day}}
    dc = db["data_container"]
    recon = db["reconciliation_result"]
    recon.delete_many({"partner": PARTNER, "date": DATE_STR})

    internal_by_key: dict[str, dict[str, Any]] = {}
    for raw in load_internal_records(start_of_day, end_of_day):
        partner_txn_id = str(raw.get("partnerTxnId") or "").strip()
        if not partner_txn_id or not is_finalized_internal_status(raw.get("status")):
            continue
        existing = internal_by_key.get(partner_txn_id)
        if existing is None or _updated_at(raw) > _updated_at(existing):
            internal_by_key[partner_txn_id] = raw

    matched_internal_keys: set[str] = set()
    result_buffer: list[dict] = []
    inserted = 0
    status_counts: defaultdict[str, int] = defaultdict(int)

    def flush():
        nonlocal result_buffer, inserted
        if result_buffer:
            recon.insert_many(result_buffer, ordered=False)
            inserted += len(result_buffer)
            result_buffer = []

    cursor = dc.find(partner_query).batch_size(PARTNER_BATCH_SIZE)
    for partner_record in cursor:
        is_valid, _ = pre_check(partner_record)
        if not is_valid:
            invalid_partner_txn_id = str(partner_record["_id"])
            result_buffer.append(result_doc(
                partner_txn_id=invalid_partner_txn_id,
                reconciliation_status="UNMAPPED_SKIPPED",
                partner_record_id=str(partner_record["_id"]),
            ))
            status_counts["UNMAPPED_SKIPPED"] += 1
            if len(result_buffer) >= WRITE_BATCH_SIZE:
                flush()
            continue

        resolved_partner_txn_id = resolve_partner_txn_id(partner_record)
        if not resolved_partner_txn_id:
            continue
        partner_txn_id = resolved_partner_txn_id

        partner_amount_raw = partner_record["partnerData"]["amount"]
        partner_amount = partner_amount_raw.to_decimal() if hasattr(partner_amount_raw, "to_decimal") else Decimal(str(partner_amount_raw))
        partner_status = partner_record["partnerData"]["status"]
        internal_record = internal_by_key.get(partner_txn_id)

        if internal_record:
            matched_internal_keys.add(partner_txn_id)
            internal_amount_raw = internal_record["amount"]
            internal_amount = internal_amount_raw.to_decimal() if hasattr(internal_amount_raw, "to_decimal") else Decimal(str(internal_amount_raw))
            internal_status = internal_record["status"]

            norm_partner_status = normalize_status(partner_status)
            norm_internal_status = normalize_status(internal_status)
            amounts_match = partner_amount == internal_amount
            statuses_match = norm_partner_status == norm_internal_status

            if amounts_match and statuses_match:
                recon_status = "MATCHED"
            elif not amounts_match and not statuses_match:
                recon_status = "MULTIPLE_MISMATCH"
            elif not amounts_match:
                recon_status = "AMOUNT_MISMATCH"
            else:
                recon_status = "STATUS_MISMATCH"

            result_buffer.append(result_doc(
                partner_txn_id=partner_txn_id,
                reconciliation_status=recon_status,
                partner_amount=partner_amount,
                internal_amount=internal_amount,
                partner_status=partner_status,
                internal_status=internal_status,
                partner_record_id=str(partner_record["_id"]),
                internal_record_id=str(internal_record["_id"]),
            ))
            status_counts[recon_status] += 1
        else:
            result_buffer.append(result_doc(
                partner_txn_id=partner_txn_id,
                reconciliation_status="MISSING_INTERNAL",
                partner_amount=partner_amount,
                partner_status=partner_status,
                partner_record_id=str(partner_record["_id"]),
            ))
            status_counts["MISSING_INTERNAL"] += 1

        if len(result_buffer) >= WRITE_BATCH_SIZE:
            flush()

    for partner_txn_id, internal_record in internal_by_key.items():
        if partner_txn_id not in matched_internal_keys:
            internal_amount_raw = internal_record["amount"]
            internal_amount = internal_amount_raw.to_decimal() if hasattr(internal_amount_raw, "to_decimal") else Decimal(str(internal_amount_raw))
            result_buffer.append(result_doc(
                partner_txn_id=partner_txn_id,
                reconciliation_status="MISSING_PARTNER",
                internal_amount=internal_amount,
                internal_status=internal_record["status"],
                internal_record_id=str(internal_record["_id"]),
            ))
            status_counts["MISSING_PARTNER"] += 1
            if len(result_buffer) >= WRITE_BATCH_SIZE:
                flush()

    flush()
    return {"inserted": inserted, "status_counts": dict(status_counts), "internal_index_size": len(internal_by_key)}


def baseline_reconcile(db) -> dict:
    start_of_day, end_of_day = iso_day_bounds(DATE_STR)
    partner_query = {"identify": PARTNER, "reconciliationDate": {"$gte": start_of_day, "$lte": end_of_day}}
    dc = db["data_container"]
    recon = db["reconciliation_result_baseline_tmp"]
    recon.delete_many({"partner": PARTNER, "date": DATE_STR})

    partner_records = list(dc.find(partner_query))
    internal_records = load_internal_records(start_of_day, end_of_day)
    finalized_internal = [record for record in internal_records if is_finalized_internal_status(record.get("status"))]

    internal_by_key: dict[str, dict[str, Any]] = {}
    for record in finalized_internal:
        key = str(record.get("partnerTxnId") or "").strip()
        if not key:
            continue
        existing = internal_by_key.get(key)
        if existing is None or _updated_at(record) > _updated_at(existing):
            internal_by_key[key] = record

    results: list[dict] = []
    matched_internal_keys: set[str] = set()
    status_counts: defaultdict[str, int] = defaultdict(int)

    for partner_record in partner_records:
        is_valid, _ = pre_check(partner_record)
        if not is_valid:
            result = result_doc(
                partner_txn_id=str(partner_record["_id"]),
                reconciliation_status="UNMAPPED_SKIPPED",
                partner_record_id=str(partner_record["_id"]),
            )
            results.append(result)
            status_counts["UNMAPPED_SKIPPED"] += 1
            continue

        partner_txn_id = resolve_partner_txn_id(partner_record)
        if not partner_txn_id:
            continue

        partner_amount_raw = partner_record["partnerData"]["amount"]
        partner_amount = partner_amount_raw.to_decimal() if hasattr(partner_amount_raw, "to_decimal") else Decimal(str(partner_amount_raw))
        partner_status = partner_record["partnerData"]["status"]
        internal_record = internal_by_key.get(partner_txn_id)

        if internal_record:
            matched_internal_keys.add(partner_txn_id)
            internal_amount_raw = internal_record["amount"]
            internal_amount = internal_amount_raw.to_decimal() if hasattr(internal_amount_raw, "to_decimal") else Decimal(str(internal_amount_raw))
            internal_status = internal_record["status"]

            norm_partner_status = normalize_status(partner_status)
            norm_internal_status = normalize_status(internal_status)
            amounts_match = partner_amount == internal_amount
            statuses_match = norm_partner_status == norm_internal_status

            if amounts_match and statuses_match:
                recon_status = "MATCHED"
            elif not amounts_match and not statuses_match:
                recon_status = "MULTIPLE_MISMATCH"
            elif not amounts_match:
                recon_status = "AMOUNT_MISMATCH"
            else:
                recon_status = "STATUS_MISMATCH"

            results.append(result_doc(
                partner_txn_id=partner_txn_id,
                reconciliation_status=recon_status,
                partner_amount=partner_amount,
                internal_amount=internal_amount,
                partner_status=partner_status,
                internal_status=internal_status,
                partner_record_id=str(partner_record["_id"]),
                internal_record_id=str(internal_record["_id"]),
            ))
            status_counts[recon_status] += 1
        else:
            results.append(result_doc(
                partner_txn_id=partner_txn_id,
                reconciliation_status="MISSING_INTERNAL",
                partner_amount=partner_amount,
                partner_status=partner_status,
                partner_record_id=str(partner_record["_id"]),
            ))
            status_counts["MISSING_INTERNAL"] += 1

    for partner_txn_id, internal_record in internal_by_key.items():
        if partner_txn_id not in matched_internal_keys:
            internal_amount_raw = internal_record["amount"]
            internal_amount = internal_amount_raw.to_decimal() if hasattr(internal_amount_raw, "to_decimal") else Decimal(str(internal_amount_raw))
            results.append(result_doc(
                partner_txn_id=partner_txn_id,
                reconciliation_status="MISSING_PARTNER",
                internal_amount=internal_amount,
                internal_status=internal_record["status"],
                internal_record_id=str(internal_record["_id"]),
            ))
            status_counts["MISSING_PARTNER"] += 1

    if results:
        recon.insert_many(results, ordered=False)
    return {"inserted": len(results), "status_counts": dict(status_counts), "internal_index_size": len(internal_by_key)}


def to_results(docs: list[dict]) -> list[SimpleNamespace]:
    from types import SimpleNamespace
    results: list[SimpleNamespace] = []
    for doc in docs:
        result = SimpleNamespace()
        result.partner = doc.get("partner", PARTNER)
        result.date = doc.get("date", DATE_STR)
        pa = doc.get("partnerAmount")
        ia = doc.get("internalAmount")
        if isinstance(pa, Decimal128):
            pa = pa.to_decimal()
        if isinstance(ia, Decimal128):
            ia = ia.to_decimal()
        result.partner_amount = pa
        result.internal_amount = ia
        result.reconciliation_status = SimpleNamespace(value=doc.get("reconciliationStatus", "MATCHED"))
        results.append(result)
    return results


def build_summary_from_aggregate(col) -> dict:
    pipeline = [
        {"$match": {"partner": PARTNER, "date": DATE_STR}},
        {
            "$group": {
                "_id": "$reconciliationStatus",
                "count": {"$sum": 1},
                "mismatch_amount": {
                    "$sum": {
                        "$cond": [
                            {"$in": ["$reconciliationStatus", ["AMOUNT_MISMATCH", "MULTIPLE_MISMATCH", "STATUS_MISMATCH"]]},
                            {"$abs": {"$subtract": ["$partnerAmount", "$internalAmount"]}},
                            0,
                        ]
                    }
                },
            }
        },
    ]
    by_status: dict[str, int] = {}
    total_transactions = 0
    matched = 0
    total_amount_mismatch = 0.0
    for doc in col.aggregate(pipeline):
        status = str(doc["_id"])
        count = int(doc["count"])
        by_status[status] = count
        total_transactions += count
        if status in ("MATCHED", "MATCHED_FAILED", "MATCHED_REVERSED"):
            matched += count
        mismatch_amount = doc.get("mismatch_amount")
        if mismatch_amount is not None:
            total_amount_mismatch += float(mismatch_amount.to_decimal() if hasattr(mismatch_amount, "to_decimal") else mismatch_amount)
    mismatch_count = max(0, total_transactions - matched)
    mismatch_rate = round((mismatch_count * 100 / total_transactions), 2) if total_transactions else 0.0
    return {
        "partner": PARTNER,
        "date": DATE_STR,
        "total_transactions": total_transactions,
        "matched": matched,
        "mismatch_rate": mismatch_rate,
        "total_amount_mismatch": total_amount_mismatch,
        "by_status": by_status,
    }


def bench(fn, repeats: int = 1) -> BenchmarkResult:
    times = []
    output: dict[str, Any] = {}
    for _ in range(repeats):
        started = time.perf_counter()
        output = fn()
        times.append(time.perf_counter() - started)
    return BenchmarkResult(
        avg_s=round(sum(times) / len(times), 4),
        min_s=round(min(times), 4),
        max_s=round(max(times), 4),
        output=output,
    )


def results_query_bench(col, optimized: bool) -> BenchmarkResult:
    def run():
        query = {"partner": PARTNER, "date": DATE_STR}
        if optimized:
            total = col.count_documents(query)
            docs = list(col.find(query).sort("_id", 1).skip(0).limit(25))
            return {"total": total, "page_rows": len(docs)}
        docs = list(col.find(query))
        total = len(docs)
        page = docs[:25]
        return {"total": total, "page_rows": len(page)}
    return bench(run, repeats=3)


def summary_prep_bench(col, optimized: bool) -> BenchmarkResult:
    from src.analysis.metrics import MetricsService
    from src.analysis.grouping import GroupingEngine
    from src.analysis.services import build_analysis_input
    from src.analysis.insights import _build_group_results_from_summary
    from src.analysis.schemas import SummaryResult

    def run():
        if optimized:
            summary_dict = build_summary_from_aggregate(col)
            summary = SummaryResult(**summary_dict)
            groups = _build_group_results_from_summary(summary)
            analysis_input = build_analysis_input(PARTNER, DATE_STR, "operational", summary, groups, selected_error_signals=[])
            return {"total_transactions": summary.total_transactions, "groups": len(groups), "grouped_stats": len(analysis_input.grouped_stats)}
        docs = list(col.find({"partner": PARTNER, "date": DATE_STR}))
        results = to_results(docs)
        summary = MetricsService.compute_summary(results, PARTNER, DATE_STR)
        groups = GroupingEngine.group(results)
        analysis_input = build_analysis_input(PARTNER, DATE_STR, "operational", summary, groups)
        return {"total_transactions": summary.total_transactions, "groups": len(groups), "grouped_stats": len(analysis_input.grouped_stats)}
    return bench(run, repeats=3)


def discrepancy_prep_bench(col, optimized: bool, focus: str) -> BenchmarkResult:
    from src.analysis.metrics import MetricsService
    from src.analysis.grouping import GroupingEngine
    from src.analysis.services import build_analysis_input, rule_based_pre_process
    from src.analysis.insights import _build_selected_error_signals
    from src.analysis.schemas import SummaryResult

    def run():
        if optimized:
            summary = SummaryResult(**build_summary_from_aggregate(col))
            selected_docs = []
            for status in ("MISSING_INTERNAL", "MISSING_PARTNER", "AMOUNT_MISMATCH", "MULTIPLE_MISMATCH", "STATUS_MISMATCH", "UNMAPPED_SKIPPED"):
                selected_docs.extend(list(col.find({"partner": PARTNER, "date": DATE_STR, "reconciliationStatus": status}).limit(50)))
            results = to_results(selected_docs)
            groups = GroupingEngine.group(results)
            summary_metrics_dict = {
                "total_transactions": summary.total_transactions,
                "matched": summary.matched,
                "mismatch_rate": summary.mismatch_rate,
                "total_amount_mismatch": summary.total_amount_mismatch,
                "by_status": summary.by_status,
                "partner": PARTNER,
            }
            anomalies = rule_based_pre_process(results, focus, summary_metrics_dict)
            selected_error_signals = _build_selected_error_signals(results)
            analysis_input = build_analysis_input(PARTNER, DATE_STR, focus, summary, groups, anomalies=anomalies, selected_error_signals=selected_error_signals)
            return {"rows": len(results), "groups": len(groups), "anomalies": len(analysis_input.top_anomalies), "signals": len(analysis_input.selected_error_signals)}
        docs = list(col.find({"partner": PARTNER, "date": DATE_STR}))
        results = to_results(docs)
        summary = MetricsService.compute_summary(results, PARTNER, DATE_STR)
        groups = GroupingEngine.group(results)
        summary_metrics_dict = {
            "total_transactions": summary.total_transactions,
            "matched": summary.matched,
            "mismatch_rate": summary.mismatch_rate,
            "total_amount_mismatch": summary.total_amount_mismatch,
            "by_status": summary.by_status,
            "partner": PARTNER,
        }
        anomalies = rule_based_pre_process(results, focus, summary_metrics_dict)
        analysis_input = build_analysis_input(PARTNER, DATE_STR, focus, summary, groups, anomalies=anomalies)
        return {"rows": len(results), "groups": len(groups), "anomalies": len(analysis_input.top_anomalies), "signals": len(analysis_input.selected_error_signals)}
    return bench(run, repeats=3)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mongo-url", default="mongodb://admin:admin123@localhost:27017/reconciliation?authSource=admin")
    parser.add_argument("--skip-seed", action="store_true")
    args = parser.parse_args()

    client = MongoClient(args.mongo_url)
    db = client["reconciliation"]

    seed_info = BenchmarkResult(avg_s=0.0, min_s=0.0, max_s=0.0, output={"skipped": True})
    if not args.skip_seed:
        seed_info = bench(lambda: seed_dataset(db), repeats=1)
    optimized = bench(lambda: optimized_reconcile(db), repeats=1)
    baseline = bench(lambda: baseline_reconcile(db), repeats=1)

    optimized_col = db["reconciliation_result"]
    report = {
        "seed": seed_info.__dict__,
        "optimized_reconcile_full": optimized.__dict__,
        "baseline_reconcile_full": baseline.__dict__,
        "results_current_1m": results_query_bench(optimized_col, optimized=True).__dict__,
        "results_baseline_1m": results_query_bench(optimized_col, optimized=False).__dict__,
        "summary_current_1m": summary_prep_bench(optimized_col, optimized=True).__dict__,
        "summary_baseline_1m": summary_prep_bench(optimized_col, optimized=False).__dict__,
        "discrepancy_current_operational_1m": discrepancy_prep_bench(optimized_col, optimized=True, focus="operational").__dict__,
        "discrepancy_baseline_operational_1m": discrepancy_prep_bench(optimized_col, optimized=False, focus="operational").__dict__,
        "discrepancy_current_partner_1m": discrepancy_prep_bench(optimized_col, optimized=True, focus="partner").__dict__,
        "discrepancy_baseline_partner_1m": discrepancy_prep_bench(optimized_col, optimized=False, focus="partner").__dict__,
        "discrepancy_current_inconsistency_1m": discrepancy_prep_bench(optimized_col, optimized=True, focus="inconsistency").__dict__,
        "discrepancy_baseline_inconsistency_1m": discrepancy_prep_bench(optimized_col, optimized=False, focus="inconsistency").__dict__,
    }
    print(json.dumps(report, default=str, indent=2))


if __name__ == "__main__":
    main()
