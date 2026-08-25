"""Benchmark the current Fraud Detection Dataset at the ingestion boundary."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ServerSelectionTimeoutError

# Keep direct execution consistent with the repository's existing benchmark scripts.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config.cache import ConfigCache
from src.config.loader import ConfigLoader
from src.config.settings import settings
from src.config.validator import ConfigValidator
from src.core.enums import FileType
from src.infrastructure.ingestion.composition import build_ingestion_pipeline
from src.infrastructure.mapping.config_repository import MappingConfigRepository
from src.infrastructure.partner_transaction.repository import DataContainerRepository


DEFAULT_INPUT = Path(
    "data/eda/fraud_detection/raw/Fraud Detection Dataset.csv"
)
DEFAULT_OUTPUT_JSON = Path(
    "data/eda/fraud_detection/profiles/benchmark_results_workstream_c.json"
)
DEFAULT_OUTPUT_MARKDOWN = Path(
    "docs/phase-2/sprint-3-workstream-c-baseline.md"
)
BENCHMARK_PARTNER = "SPRINT3_FRAUD_EDA_BASELINE"
BENCHMARK_WORKFLOW = "SPRINT3_BASELINE"
BENCHMARK_CONFIG_VERSION = "sprint3-fraud-detection-v2"
BENCHMARK_BATCH_SIZE = 20_000
BENCHMARK_WORKERS = 1
BENCHMARK_ORDERED_INSERT = False
BENCHMARK_CASES = (10_000, 100_000, None)


@dataclass(frozen=True)
class BenchmarkConfig:
    """Tuning and case selection for one reproducible benchmark run."""

    batch_size: int
    write_workers: int
    cases: tuple[int | None, ...]


def build_benchmark_config(
    *,
    batch_size: int = BENCHMARK_BATCH_SIZE,
    write_workers: int = BENCHMARK_WORKERS,
    full_only: bool = False,
) -> BenchmarkConfig:
    """Build validated benchmark tuning without changing the baseline defaults."""

    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if write_workers < 1:
        raise ValueError("write_workers must be positive")
    return BenchmarkConfig(
        batch_size=batch_size,
        write_workers=write_workers,
        cases=(None,) if full_only else BENCHMARK_CASES,
    )


def build_mapping_document(
    *,
    partner: str = BENCHMARK_PARTNER,
    config_version: str = BENCHMARK_CONFIG_VERSION,
) -> dict[str, Any]:
    """Return the explicit benchmark mapping used for every prefix."""

    mappings = [
        {"path": "id", "column": 1, "type": "STRING", "required": True},
        {"path": "transDate", "column": 2, "type": "DATE", "required": True},
        {"path": "extra.customerId", "column": 3, "type": "STRING"},
        {"path": "extra.cardId", "column": 4, "type": "STRING"},
        {"path": "extra.deviceId", "column": 5, "type": "STRING"},
        {"path": "extra.ipAddress", "column": 6, "type": "STRING"},
        {"path": "extra.merchantId", "column": 7, "type": "STRING"},
        {"path": "extra.merchantCategory", "column": 8, "type": "STRING"},
        {"path": "extra.merchantCountry", "column": 9, "type": "STRING"},
        {"path": "extra.merchantCity", "column": 10, "type": "STRING"},
        {"path": "extra.merchantLatitude", "column": 11, "type": "STRING"},
        {"path": "extra.merchantLongitude", "column": 12, "type": "STRING"},
        {"path": "extra.transactionType", "column": 13, "type": "STRING"},
        {"path": "amount", "column": 14, "type": "DECIMAL", "required": True},
        {"path": "currency", "column": 15, "type": "STRING", "required": True},
        {"path": "extra.isFraud", "column": 16, "type": "STRING"},
        {"path": "status", "constant": "SUCCESS", "type": "CONSTANT"},
    ]
    return {
        "_id": f"{partner.lower()}-mapping",
        "partner": partner,
        "workflowType": BENCHMARK_WORKFLOW,
        "fileType": FileType.SETTLEMENT.value,
        "sheetName": "CSV",
        "startRow": 2,
        "fieldMappings": mappings,
        "configVersion": config_version,
        "status": "APPROVED",
        "approvedAt": datetime.now(UTC),
        "approvedBy": "sprint3-baseline",
        "createdAt": datetime.now(UTC),
    }


def write_prefix_csv(source: Path, output: Path, row_limit: int) -> int:
    """Copy the header and a deterministic number of data lines."""

    if row_limit < 1:
        raise ValueError("row_limit must be positive")
    output.parent.mkdir(parents=True, exist_ok=True)
    rows_written = 0
    with source.open("r", encoding="utf-8", newline="") as source_file:
        header = source_file.readline()
        if not header:
            raise ValueError(f"Dataset file is empty: {source}")
        with output.open("w", encoding="utf-8", newline="") as output_file:
            output_file.write(header)
            for line in source_file:
                output_file.write(line)
                rows_written += 1
                if rows_written >= row_limit:
                    break
    if rows_written != row_limit:
        raise ValueError(
            f"Requested {row_limit} rows but source only has {rows_written}"
        )
    return rows_written


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


async def _clear_benchmark_data(db: Any) -> None:
    """Delete only records created under the unique benchmark partner tag."""

    await DataContainerRepository().delete_by_partner(BENCHMARK_PARTNER)
    await db["reconciliation_file"].delete_many(
        {"partner": BENCHMARK_PARTNER}
    )
    await db["ingestion_quarantine_record"].delete_many(
        {"partner": BENCHMARK_PARTNER}
    )


async def _install_mapping(db: Any) -> None:
    collection = db["reconciliation_mapping_config"]
    await collection.delete_many({"partner": BENCHMARK_PARTNER})
    await collection.insert_one(build_mapping_document())


async def _remove_mapping(db: Any) -> None:
    await db["reconciliation_mapping_config"].delete_many(
        {"partner": BENCHMARK_PARTNER}
    )


def _case_meets_acceptance(case: dict[str, Any]) -> bool:
    """Return whether a benchmark case proves clean ingestion."""

    return (
        case["input_rows"] > 0
        and case["persisted_rows"] == case["input_rows"]
        and case["failed_rows"] == 0
        and case["duplicate_rows"] == 0
        and case["quality_decision"] == "PASS"
        and case["orchestration_action"] == "CONTINUE"
        and case["outcome"] == "INGESTED"
    )


async def _run_case(
    *,
    db: Any,
    input_path: Path,
    requested_rows: int | None,
    case_index: int,
    benchmark_config: BenchmarkConfig,
) -> dict[str, Any]:
    await _clear_benchmark_data(db)
    config_loader = ConfigLoader(
        MappingConfigRepository(db),
        ConfigCache(),
        ConfigValidator(),
    )
    config = await config_loader.load_by_partner_type(
        BENCHMARK_PARTNER,
        BENCHMARK_WORKFLOW,
        FileType.SETTLEMENT,
    )
    pipeline = build_ingestion_pipeline(
        db=db,
        config_loader=config_loader,
        batch_size=benchmark_config.batch_size,
        fast_mode=False,
        write_workers=benchmark_config.write_workers,
        ordered_insert=BENCHMARK_ORDERED_INSERT,
    )
    reconciliation_date = datetime(2025, 1, 1, tzinfo=UTC) + timedelta(
        days=case_index
    )
    fetch_unit_metadata = {
        "benchmarkTag": BENCHMARK_PARTNER,
        "caseRows": str(requested_rows or "full"),
        "sourceEndpoint": "sprint3://fraud-detection",
        "page": case_index + 1,
    }
    started = time.perf_counter()
    result = await pipeline.process_file(
        file_path=str(input_path),
        partner=BENCHMARK_PARTNER,
        workflow_type=BENCHMARK_WORKFLOW,
        file_type=FileType.SETTLEMENT,
        reconciliation_date=reconciliation_date,
        config_version=config.config_version,
        fetch_unit_metadata=fetch_unit_metadata,
        enable_config_health_check=False,
    )
    elapsed = time.perf_counter() - started
    stats = result.stats
    return {
        "requested_rows": requested_rows or "full",
        "input_rows": stats.total_rows,
        "persisted_rows": stats.success_rows,
        "duplicate_rows": stats.duplicate_rows,
        "failed_rows": stats.failed_rows,
        "quarantined_rows": result.quality_counters.get("quarantinedRows", 0),
        "quality_decision": result.quality_decision.value,
        "orchestration_action": result.orchestration_action.value,
        "outcome": result.outcome,
        "elapsed_seconds": round(elapsed, 6),
        "throughput_rows_per_second": round(
            stats.total_rows / elapsed, 3
        )
        if elapsed > 0
        else 0.0,
        "quality_counters": result.quality_counters,
        "errors": result.errors[:5],
        "file_record_id": str(result.file_record.id)
        if result.file_record is not None
        else None,
    }


def render_markdown(report: dict[str, Any]) -> str:
    """Render benchmark evidence without hiding environment failures."""

    lines = [
        "# Sprint 3 — Fraud Detection Dataset ingestion benchmark",
        "",
        f"- Status: **{report['status']}**",
        f"- Dataset: `{report['dataset']['path']}`",
        f"- Dataset SHA-256: `{report['dataset']['sha256']}`",
        f"- MongoDB: `{report['environment']['mongodb']}`",
        f"- Database: `{report['environment']['db_name']}`",
        f"- Cleanup: `{report.get('cleanup', 'not-run')}`",
        "- Boundary: `IngestionPipeline.process_file`",
        f"- Mapping: `{report['configuration']['config_version']}`",
        f"- Configuration: `batch_size={report['configuration']['batch_size']:,}`, "
        f"`write_workers={report['configuration']['write_workers']}`, "
        "`ordered_insert=false`, `fast_mode=false`",
        "",
    ]
    if report.get("error"):
        lines.extend([f"- Error: `{report['error']}`", ""])
    if report.get("cases"):
        lines.extend(
            [
                "## Results",
                "",
                "| Input | Persisted | Duplicate | Failed | Elapsed (s) | Rows/s | Outcome |",
                "|---:|---:|---:|---:|---:|---:|---|",
            ]
        )
        for case in report["cases"]:
            lines.append(
                f"| {case['input_rows']:,} | {case['persisted_rows']:,} | "
                f"{case['duplicate_rows']:,} | {case['failed_rows']:,} | "
                f"{case['elapsed_seconds']:.3f} | "
                f"{case['throughput_rows_per_second']:,.1f} | "
                f"{case['outcome']} |"
            )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "This is ingestion-boundary evidence, not reconciliation or statistical evidence.",
            "Source column 2 maps to canonical `transDate`; offset-bearing values "
            "normalize to UTC-aware canonical timestamps and the existing PostgreSQL "
            "mapper persists them using the UTC-naive convention.",
            "The conditional-empty `fraud_type` source column remains intentionally "
            "unmapped and outside canonical quality rejection.",
            "",
            "## Limitations",
            "",
            "- Prefix preparation time is excluded from elapsed ingestion time.",
            "- MongoDB/service startup and reconciliation are excluded.",
            "- Results are comparable only when dataset checksum, mapping, database "
            "and configuration match.",
        ]
    )
    return "\n".join(lines) + "\n"


async def run_benchmark(
    input_path: Path = DEFAULT_INPUT,
    output_json: Path = DEFAULT_OUTPUT_JSON,
    output_markdown: Path = DEFAULT_OUTPUT_MARKDOWN,
    benchmark_config: BenchmarkConfig | None = None,
) -> dict[str, Any]:
    """Run the selected ingestion benchmark cases."""

    if not input_path.is_file():
        raise FileNotFoundError(f"Dataset file not found: {input_path}")
    config = benchmark_config or build_benchmark_config()
    report: dict[str, Any] = {
        "benchmark_version": 2,
        "status": "completed",
        "dataset": {
            "path": str(input_path),
            "sha256": _sha256(input_path),
            "size_bytes": input_path.stat().st_size,
        },
        "environment": {
            "mongodb": "configured",
            "db_name": settings.db_name,
        },
        "configuration": {
            "config_version": BENCHMARK_CONFIG_VERSION,
            "batch_size": config.batch_size,
            "write_workers": config.write_workers,
            "ordered_insert": BENCHMARK_ORDERED_INSERT,
            "fast_mode": False,
            "cases": list(config.cases),
        },
        "cases": [],
    }
    client: Any = AsyncIOMotorClient(
        settings.mongodb_url,
        serverSelectionTimeoutMS=3000,
    )
    db: Any | None = None
    try:
        try:
            await client.admin.command("ping")
        except ServerSelectionTimeoutError as exc:
            report["status"] = "blocked_by_environment"
            report["error"] = f"MongoDB unavailable: {exc}"
            return report

        db = client[settings.db_name]
        await _install_mapping(db)
        with TemporaryDirectory(
            prefix="sprint3-benchmark-",
            dir="data/eda/fraud_detection/interim",
        ) as temporary_dir:
            temporary_path = Path(temporary_dir)
            for case_index, requested_rows in enumerate(config.cases):
                case_path = input_path
                if requested_rows is not None:
                    case_path = temporary_path / f"fraud_detection_{requested_rows}.csv"
                    write_prefix_csv(input_path, case_path, requested_rows)
                report["cases"].append(
                    await _run_case(
                        db=db,
                        input_path=case_path,
                        requested_rows=requested_rows,
                        case_index=case_index,
                        benchmark_config=config,
                    )
                )
        if not all(_case_meets_acceptance(case) for case in report["cases"]):
            report["status"] = "benchmark_failed"
    finally:
        if db is not None:
            try:
                await _clear_benchmark_data(db)
                await _remove_mapping(db)
                report["cleanup"] = "benchmark records and mapping removed"
            except Exception as exc:  # pragma: no cover - environment cleanup
                report["cleanup"] = "failed"
                report["cleanup_error"] = str(exc)
        client.close()
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_markdown.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        output_markdown.write_text(
            render_markdown(report),
            encoding="utf-8",
        )
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument(
        "--output-markdown",
        type=Path,
        default=DEFAULT_OUTPUT_MARKDOWN,
    )
    parser.add_argument("--batch-size", type=int, default=BENCHMARK_BATCH_SIZE)
    parser.add_argument("--write-workers", type=int, default=BENCHMARK_WORKERS)
    parser.add_argument(
        "--full-only",
        action="store_true",
        help="Run only the full source file instead of the default scale cases.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    report = asyncio.run(
        run_benchmark(
            input_path=args.input,
            output_json=args.output_json,
            output_markdown=args.output_markdown,
            benchmark_config=build_benchmark_config(
                batch_size=args.batch_size,
                write_workers=args.write_workers,
                full_only=args.full_only,
            ),
        )
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
