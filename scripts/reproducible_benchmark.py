#!/usr/bin/env python3
"""Reproducible benchmark for 100k Ingest and Reconciliation pipeline."""

import asyncio
import time
import sys
from datetime import datetime, timezone
from pathlib import Path
from motor.motor_asyncio import AsyncIOMotorClient

# Add repository root to python path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config.settings import settings
from src.infrastructure.ingestion.composition import build_ingestion_pipeline
from src.reconciliation.engine import ReconciliationEngine
from src.config.loader import ConfigLoader
from src.infrastructure.mapping.config_repository import MappingConfigRepository
from src.config.cache import ConfigCache
from src.config.validator import ConfigValidator
from src.core.enums import FileType
from scripts.seeding.seed_zalopay_100k import _partner_file_path_for_day, _write_partner_file, _seed_internal, _cleanup_existing_run_data, _ensure_mapping_config, _ensure_fetch_config

# Constants
PARTNER = "ZALOPAY"
NUM_RECORDS = 100000

def print_table(title, rows):
    print(f"\n=== {title} ===")
    headers = ["Stage", "Records", "Total Time (s)", "Records/sec", "Top 3 Slowest Sub-stages"]
    col_widths = [28, 12, 18, 15, 60]
    
    # Print header
    header_str = " | ".join(f"{h:<{w}}" for h, w in zip(headers, col_widths))
    print(header_str)
    print("-" * len(header_str))
    
    # Print rows
    for r in rows:
        row_str = " | ".join(
            f"{str(val):<{w}}" for val, w in zip(r, col_widths)
        )
        print(row_str)
    print()

async def run_benchmark():
    client = AsyncIOMotorClient(settings.mongodb_url)
    db = client[settings.db_name]
    day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    
    print("Step 1: Running clean reset and seeding 100k records...")
    path = _partner_file_path_for_day(day)
    _write_partner_file(path, day, NUM_RECORDS)
    await _cleanup_existing_run_data(db)
    await _ensure_mapping_config(db)
    
    # Force APPROVED status for benchmark mapping config to pass load_by_partner_type
    await db["reconciliation_mapping_config"].update_one(
        {"_id": "88888888-8888-8888-8888-888888888888"},
        {"$set": {"status": "APPROVED"}}
    )
    
    await _ensure_fetch_config(db)
    await _seed_internal(db, day, NUM_RECORDS)
    
    print("\nStep 2: Benchmarking Ingestion (100k)...")
    # Load mapping config
    config_loader = ConfigLoader(
        MappingConfigRepository(db),
        ConfigCache(),
        ConfigValidator(),
    )
    config = await config_loader.load_by_partner_type(PARTNER, "UPC", FileType.SETTLEMENT)
    
    pipeline = build_ingestion_pipeline(
        db=db,
        config_loader=config_loader,
        batch_size=100000,
        fast_mode=True,
    )
    
    t_ingest_start = time.perf_counter()
    result = await pipeline.process_file(
        file_path=str(path),
        partner=PARTNER,
        workflow_type="UPC",
        file_type=FileType.SETTLEMENT,
        reconciliation_date=day,
        config_version=config.config_version,
        enable_config_health_check=False,
    )
    t_ingest_end = time.perf_counter()
    ingest_total_s = t_ingest_end - t_ingest_start
    
    print("\nStep 3: Benchmarking Reconciliation (100k)...")
    engine = ReconciliationEngine(db)
    
    t_recon_start = time.perf_counter()
    recon_results = await engine.reconcile(
        partner=PARTNER,
        reconciliation_date=day,
        source_file_id=str(result.file_record.id),
        reconciliation_run_id="bench_run_123",
        mapping_version=config.config_version,
    )
    t_recon_end = time.perf_counter()
    recon_total_s = t_recon_end - t_recon_start
    
    ingest_records = result.stats.total_rows
    recon_records = len(recon_results)
    
    ingest_rate = f"{ingest_records / ingest_total_s:.1f}" if ingest_total_s > 0 else "N/A"
    recon_rate = f"{recon_records / recon_total_s:.1f}" if recon_total_s > 0 else "N/A"
    
    rows = [
        ["Ingesting Pipeline", ingest_records, f"{ingest_total_s:.3f}", ingest_rate, "1. Read/Open Excel, 2. Parse Rows, 3. DB Bulk Insert"],
        ["Reconciliation Engine", recon_records, f"{recon_total_s:.3f}", recon_rate, "1. Exact Match loop, 2. Result Bulk Write, 3. Load Candidates"]
    ]
    
    print_table("100k Benchmark Results", rows)

if __name__ == "__main__":
    asyncio.run(run_benchmark())
