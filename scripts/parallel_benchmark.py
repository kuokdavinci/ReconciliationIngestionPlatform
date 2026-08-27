#!/usr/bin/env python3
"""Benchmark grid search for parallel ingestion and reconciliation.

Tests batch sizes, worker counts, and ordered vs unordered inserts.
Prints a compact matrix and recommends the best configuration.
"""

import asyncio
import io
import time
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from motor.motor_asyncio import AsyncIOMotorClient
from src.config.settings import settings
from src.infrastructure.ingestion.composition import build_ingestion_pipeline
from src.infrastructure.partner_transaction.repository import DataContainerRepository
from src.infrastructure.postgres.reconciliation_result_repository import ReconciliationResultRepository
from src.reconciliation.engine import ReconciliationEngine
from src.config.loader import ConfigLoader
from src.infrastructure.mapping.config_repository import MappingConfigRepository
from src.config.cache import ConfigCache
from src.config.validator import ConfigValidator
from src.core.enums import FileType
from scripts.seeding.seed_zalopay_100k import (
    AMOUNT_MISMATCH_INDICES,
    MISSING_PARTNER_INDICES,
    _partner_file_path_for_day,
    _write_partner_file,
    _seed_internal,
    _cleanup_existing_run_data,
    _ensure_mapping_config,
    _ensure_fetch_config,
)

PARTNER = "ZALOPAY"
NUM_RECORDS = 100000
EXPECTED_PARTNER_ROWS = NUM_RECORDS - len(MISSING_PARTNER_INDICES)
EXPECTED_RECON_RESULTS = NUM_RECORDS

BATCH_SIZES = [5000, 10000, 20000, 50000, 100000]
WORKERS = [1, 2, 4]
ORDERED_OPTIONS = [True, False]


def _parse_perf_log(log_output: str, prefix: str) -> dict[str, float | str]:
    data: dict[str, float | str] = {}
    for line in log_output.split("\n"):
        if prefix in line:
            for part in line.split():
                if "=" in part:
                    k, v = part.split("=", 1)
                    try:
                        data[k] = float(v)
                    except ValueError:
                        data[k] = v
    return data


def _print_matrix(results: list[dict]):
    print()
    print("=" * 130)
    print("BENCHMARK RESULTS MATRIX")
    print("=" * 130)
    header = (
        f"{'Stage':<28} | {'Batch':>7} | {'Workers':>7} | {'Ordered':>7}"
        f" | {'Runtime':>8} | {'Rec/s':>9} | {'DB Write':>9} | {'Slowest':>8}"
        f" | {'Errors':>6} | {'Dups':>5} | {'Correct':>7}"
    )
    print(header)
    print("-" * 130)
    for r in results:
        print(
            f"{r['stage']:<28} | {r['batch_size']:>7} | {r['workers']:>7}"
            f" | {'yes' if r['ordered'] else 'no':>7}"
            f" | {r['runtime']:>8.3f}s | {r['rate']:>9.1f}"
            f" | {r['db_write_ms']:>7.1f}ms | {r['slowest_batch_ms']:>6.1f}ms"
            f" | {r['errors']:>6} | {r['duplicates']:>5}"
            f" | {'YES' if r['correct'] else 'NO':>7}"
        )


def _recommend(results: list[dict]) -> dict:
    stages = set(r["stage"] for r in results)
    best = {}
    for stage in stages:
        candidates = [r for r in results if r["stage"] == stage and r["correct"]]
        if not candidates:
            continue
        candidates.sort(key=lambda x: x["runtime"])
        best[stage] = candidates[0]
    return best


async def benchmark_matrix():
    client = AsyncIOMotorClient(settings.mongodb_url)
    db = client[settings.db_name]
    day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    print("=== SEEDING DATABASE FOR BENCHMARK ===")
    print(
        f"Scenario: internal={NUM_RECORDS}, partner_rows={EXPECTED_PARTNER_ROWS}, "
        f"missing_partner={len(MISSING_PARTNER_INDICES)}, "
        f"amount_mismatch={len(AMOUNT_MISMATCH_INDICES)}, "
        f"expected_reconciliation_results={EXPECTED_RECON_RESULTS}"
    )
    path = _partner_file_path_for_day(day)
    _write_partner_file(path, day, NUM_RECORDS)
    await _cleanup_existing_run_data(db)
    await _ensure_mapping_config(db)
    await db["reconciliation_mapping_config"].update_one(
        {"_id": "88888888-8888-8888-8888-888888888888"},
        {"$set": {"status": "APPROVED"}},
    )
    await _ensure_fetch_config(db)
    await _seed_internal(db, day, NUM_RECORDS)

    config_loader = ConfigLoader(
        MappingConfigRepository(db),
        ConfigCache(),
        ConfigValidator(),
    )
    config = await config_loader.load_by_partner_type(PARTNER, "UPC", FileType.SETTLEMENT)
    transaction_repository = DataContainerRepository()
    result_repository = ReconciliationResultRepository()

    results = []

    # === INGESTION BENCHMARK ===
    print("\n--- Benchmarking Ingestion Insert ---")
    for batch_size in BATCH_SIZES:
        for worker in WORKERS:
            for ordered in ORDERED_OPTIONS:
                print(
                    f"  Ingestion: batch={batch_size}, workers={worker}, ordered={ordered} ...",
                    end=" ",
                    flush=True,
                )
                await transaction_repository.delete_by_partner(PARTNER)
                await db["reconciliation_file"].delete_many({"partner": PARTNER})

                pipeline = build_ingestion_pipeline(
                    db=db,
                    config_loader=config_loader,
                    batch_size=batch_size,
                    fast_mode=True,
                    write_workers=worker,
                    ordered_insert=ordered,
                )

                old_stdout = sys.stdout
                sys.stdout = buf = io.StringIO()

                t0 = time.perf_counter()
                res = await pipeline.process_file(
                    file_path=str(path),
                    partner=PARTNER,
                    workflow_type="UPC",
                    file_type=FileType.SETTLEMENT,
                    reconciliation_date=day,
                    config_version=config.config_version,
                    enable_config_health_check=False,
                )
                runtime = time.perf_counter() - t0
                sys.stdout = old_stdout

                perf = _parse_perf_log(buf.getvalue(), "PERF_INGEST")
                rate = res.stats.total_rows / runtime if runtime > 0 else 0
                correct = res.stats.total_rows == EXPECTED_PARTNER_ROWS
                errors = res.stats.failed_rows

                results.append(
                    {
                        "stage": "ingestion_insert",
                        "batch_size": batch_size,
                        "workers": worker,
                        "ordered": ordered,
                        "runtime": runtime,
                        "rate": rate,
                        "db_write_ms": perf.get("db_insert_ms", 0),
                        "slowest_batch_ms": perf.get("slowest_batch_ms", 0),
                        "errors": errors,
                        "duplicates": 0,
                        "correct": correct,
                        "inserted": res.stats.success_rows,
                    }
                )
                print(
                    f"ok ({runtime:.2f}s, {rate:.0f} rec/s)"
                    if correct
                    else f"FAIL (correct={correct})"
                )

    # Re-seed with best ingestion config for reconciliation sweep
    best_ingest = _recommend(results).get("ingestion_insert")
    if best_ingest:
        print(f"\nRe-seeding with best ingest config for reconciliation: batch={best_ingest['batch_size']}, workers={best_ingest['workers']}")
        await transaction_repository.delete_by_partner(PARTNER)
        await db["reconciliation_file"].delete_many({"partner": PARTNER})
        pipeline = build_ingestion_pipeline(
            db=db,
            config_loader=config_loader,
            batch_size=best_ingest["batch_size"],
            fast_mode=True,
            write_workers=best_ingest["workers"],
            ordered_insert=best_ingest["ordered"],
        )
        ingest_res = await pipeline.process_file(
            file_path=str(path),
            partner=PARTNER,
            workflow_type="UPC",
            file_type=FileType.SETTLEMENT,
            reconciliation_date=day,
            config_version=config.config_version,
            enable_config_health_check=False,
        )
    else:
        print("\nNo correct ingestion config found — using defaults for reconciliation sweep")
        ingest_res = res

    # === RECONCILIATION BENCHMARK ===
    print("\n--- Benchmarking PostgreSQL Reconciliation ---")
    await result_repository.delete_by_partner_and_date(PARTNER, day.date().isoformat())
    engine = ReconciliationEngine(db=db)
    t0 = time.perf_counter()
    recon_results = await engine.reconcile(
        partner=PARTNER,
        reconciliation_date=day,
        source_file_id=str(ingest_res.file_record.id),
        reconciliation_run_id="bench_run_parallel",
        mapping_version=config.config_version,
    )
    runtime = time.perf_counter() - t0
    rate = len(recon_results) / runtime if runtime > 0 else 0
    correct = len(recon_results) == EXPECTED_RECON_RESULTS
    txn_ids = [result.partner_txn_id for result in recon_results]
    duplicates = len(txn_ids) - len(set(txn_ids))
    print(
        f"  Reconciliation: {'ok' if correct else 'FAIL'} "
        f"({runtime:.2f}s, {rate:.0f} rec/s, duplicates={duplicates})"
    )

    # === PRINT RESULTS ===
    _print_matrix(results)

    # === RECOMMENDATION ===
    best = _recommend(results)
    print()
    print("=" * 60)
    print("RECOMMENDED PRODUCTION DEFAULTS")
    print("=" * 60)

    if "ingestion_insert" in best:
        b = best["ingestion_insert"]
        print(f"  Ingestion:            batch_size={b['batch_size']}, workers={b['workers']}, ordered={b['ordered']}")
        print(f"    Runtime: {b['runtime']:.3f}s, Rate: {b['rate']:.0f} rec/s")
    else:
        print("  Ingestion:            NO CORRECT CONFIG FOUND")



if __name__ == "__main__":
    asyncio.run(benchmark_matrix())
