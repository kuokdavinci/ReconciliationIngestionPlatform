"""Benchmark the current Fraud Detection Dataset at the ingestion boundary."""

from __future__ import annotations

import argparse
import asyncio
import cProfile
import hashlib
import io
import json
import multiprocessing
import os
import re
import resource
import sys
import statistics
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorClient

# Keep direct execution consistent with the repository's existing benchmark scripts.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config.cache import ConfigCache
from src.config.loader import ConfigLoader
from src.config.settings import settings
from src.config.validator import ConfigValidator
from src.core.enums import FileType
from src.domain.mapping.models import MappingConfig
from src.infrastructure.ingestion.composition import build_ingestion_pipeline
from src.infrastructure.mapping.config_repository import MappingConfigRepository
from src.infrastructure.partner_transaction.mappers import data_container_to_row
from src.infrastructure.partner_transaction.repository import DataContainerRepository
from src.normalizer.normalizer import TransactionNormalizer
from src.pipeline.row_processor import RowProcessor
from src.readers.csv_reader import CSVStreamReader
from src.validators.validator import Validator


DEFAULT_INPUT = Path(
    "data/eda/fraud_detection/raw/Fraud Detection Dataset.csv"
)
DEFAULT_OUTPUT_JSON = Path(
    "data/eda/fraud_detection/profiles/benchmark_results_workstream_c.json"
)
DEFAULT_OUTPUT_MARKDOWN = Path(
    "docs/phase-2/sprint-3-workstream-c.md"
)
DEFAULT_REVIEW_OUTPUT_JSON = Path(
    "data/eda/fraud_detection/profiles/benchmark_review_100k.json"
)
DEFAULT_REVIEW_OUTPUT_MARKDOWN = Path(
    "docs/phase-2/sprint-4-benchmark-review-100k.md"
)
DEFAULT_AB_OUTPUT_JSON = Path(
    "data/eda/fraud_detection/profiles/benchmark_ab_100k.json"
)
DEFAULT_AB_OUTPUT_MARKDOWN = Path(
    "docs/phase-2/sprint-4-benchmark-ab-100k.md"
)
DEFAULT_SQL_PROFILE_OUTPUT_JSON = Path(
    "data/eda/fraud_detection/profiles/benchmark_sql_profile_100k.json"
)
DEFAULT_OPT2_REVIEW_OUTPUT_JSON = Path(
    "data/eda/fraud_detection/profiles/benchmark_review_100k_opt2.json"
)
DEFAULT_OPT2_AB_OUTPUT_JSON = Path(
    "data/eda/fraud_detection/profiles/benchmark_ab_100k_opt2.json"
)
DEFAULT_OPT2_MARKDOWN = Path(
    "docs/phase-2/sprint-4-benchmark-optimization-2.md"
)
BENCHMARK_PARTNER = "SPRINT3_FRAUD_EDA_BASELINE"
BENCHMARK_WORKFLOW = "SPRINT3_BASELINE"
BENCHMARK_CONFIG_VERSION = "sprint3-fraud-detection-v2"
BENCHMARK_BATCH_SIZE = 20_000
BENCHMARK_WORKERS = 1
BENCHMARK_ORDERED_INSERT = False
BENCHMARK_CASES = (10_000, 100_000, None)
EVALUATION_ROWS = 100_000
MEASURED_SAMPLES = 5
WARMUP_SAMPLES = 1
RSS_CAP_BYTES = 1024 * 1024 * 1024
MONGO_PING_TIMEOUT_SECONDS = 5.0
POSTGRES_PREFLIGHT_TIMEOUT_SECONDS = 5.0
VARIANT_MATRIX = (
    {"name": "control-20k-w1", "batch_size": 20_000, "write_workers": 1, "fast_mode": False},
    {"name": "current-20k-w2", "batch_size": 20_000, "write_workers": 2, "fast_mode": False},
    {"name": "small-10k-w2", "batch_size": 10_000, "write_workers": 2, "fast_mode": False},
    {"name": "large-40k-w2", "batch_size": 40_000, "write_workers": 2, "fast_mode": False},
    {"name": "large-80k-w2", "batch_size": 80_000, "write_workers": 2, "fast_mode": False},
    {"name": "fast-20k-w2", "batch_size": 20_000, "write_workers": 2, "fast_mode": True},
)
_MONGODB_CREDENTIALS_PATTERN = re.compile(
    r"(?P<scheme>mongodb(?:\+srv)?://)(?P<credentials>[^@\s]+)@",
    re.IGNORECASE,
)


def _redact_mongodb_credentials(value: object) -> str:
    """Remove MongoDB URI userinfo before an error reaches an artifact."""
    return _MONGODB_CREDENTIALS_PATTERN.sub(r"\g<scheme>***:***@", str(value))


def _describe_exception(error: BaseException) -> str:
    message = str(error).strip()
    return f"{type(error).__name__}: {message}" if message else type(error).__name__


@dataclass(frozen=True)
class BenchmarkConfig:
    """Tuning and case selection for one reproducible benchmark run."""

    batch_size: int
    write_workers: int
    cases: tuple[int | None, ...]


def peak_rss_bytes() -> int:
    """Return process peak RSS in bytes using the platform resource counter."""
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value * 1024 if sys.platform.startswith("linux") else value


def median_absolute_deviation(values: list[float]) -> float:
    """Return the median absolute deviation for a non-empty numeric sample."""
    if not values:
        return 0.0
    center = statistics.median(values)
    return statistics.median([abs(value - center) for value in values])


def aggregate_samples(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate raw samples while retaining every measured value."""
    latency_ms = [
        float(sample.get("wall_clock_ms", sample.get("elapsed_seconds", 0.0) * 1000))
        for sample in samples
    ]
    throughput = [float(sample.get("throughput_rows_per_second", 0.0)) for sample in samples]
    rss = [
        int(sample.get("peak_rss_bytes", sample.get("rss_peak_bytes", 0)))
        for sample in samples
    ]
    component_values: dict[str, list[float]] = {}
    for sample in samples:
        for key, value in (sample.get("batch_metrics") or {}).items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                component_values.setdefault(key, []).append(float(value))
    return {
        "sample_count": len(samples),
        "wall_clock_ms": {
            "median": statistics.median(latency_ms) if latency_ms else 0.0,
            "mad": median_absolute_deviation(latency_ms),
            "samples": latency_ms,
        },
        "throughput_rows_per_second": {
            "median": statistics.median(throughput) if throughput else 0.0,
            "mad": median_absolute_deviation(throughput),
            "samples": throughput,
        },
        "peak_rss_bytes": {
            "median": statistics.median(rss) if rss else 0,
            "mad": median_absolute_deviation([float(value) for value in rss]),
            "max": max(rss) if rss else 0,
            "samples": rss,
        },
        "batch_metrics": {
            key: {
                "median": statistics.median(values),
                "mad": median_absolute_deviation(values),
                "samples": values,
            }
            for key, values in sorted(component_values.items())
        },
    }


def sample_meets_acceptance(
    sample: dict[str, Any], *, rss_cap_bytes: int = RSS_CAP_BYTES
) -> bool:
    """Require correctness counters and the hard RSS cap for every sample."""
    if "peak_rss_bytes" not in sample:
        return False
    return _case_meets_acceptance(sample) and int(
        sample.get("peak_rss_bytes", sample.get("rss_peak_bytes", 0))
    ) <= rss_cap_bytes


def all_samples_meet_acceptance(
    samples: list[dict[str, Any]], *, rss_cap_bytes: int = RSS_CAP_BYTES
) -> bool:
    return bool(samples) and all(
        sample_meets_acceptance(sample, rss_cap_bytes=rss_cap_bytes) for sample in samples
    )


def optimization_gate(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Apply the requested 5% latency / 10% RSS improvement gate."""
    before_latency = float(before["wall_clock_ms"]["median"])
    after_latency = float(after["wall_clock_ms"]["median"])
    before_rss = int(before["peak_rss_bytes"]["median"])
    after_rss = int(after["peak_rss_bytes"]["median"])
    latency_change = (after_latency / before_latency - 1) if before_latency else 0.0
    latency_reduction = (1 - after_latency / before_latency) if before_latency else 0.0
    rss_reduction = (1 - after_rss / before_rss) if before_rss else 0.0
    latency_pass = latency_reduction >= 0.05
    rss_pass = rss_reduction >= 0.10 and latency_change <= 0.02
    return {
        "passed": latency_pass or rss_pass,
        "latency_reduction": latency_reduction,
        "rss_reduction": rss_reduction,
        "latency_pass": latency_pass,
        "rss_pass": rss_pass,
    }


def rotate_variants(variants: tuple[dict[str, Any], ...], round_index: int) -> list[dict[str, Any]]:
    """Return a deterministic rotation used to avoid fixed matrix ordering bias."""
    if not variants:
        return []
    offset = round_index % len(variants)
    return list(variants[offset:]) + list(variants[:offset])


async def _ping_mongodb(client: Any) -> None:
    """Bound driver/server discovery so a blocked benchmark produces a report."""
    await asyncio.wait_for(
        client.admin.command("ping"), timeout=MONGO_PING_TIMEOUT_SECONDS
    )


async def _find_active_postgres_writes() -> list[dict[str, Any]]:
    """Find active DML so a benchmark never competes with a live ingestion."""
    from sqlalchemy import text

    repository = DataContainerRepository()
    connection = await asyncio.wait_for(
        repository.engine.connect(), timeout=POSTGRES_PREFLIGHT_TIMEOUT_SECONDS
    )
    try:
        result = await asyncio.wait_for(
            connection.execute(
                text(
                    "SELECT pid, EXTRACT(EPOCH FROM now() - query_start)::bigint, "
                    "substring(query from '[[:alpha:]]+') "
                    "FROM pg_stat_activity "
                    "WHERE datname = current_database() "
                    "AND pid <> pg_backend_pid() "
                    "AND state = 'active' "
                    "AND query ~* '^\\s*(insert|update|delete|merge|alter|create|drop|truncate|copy)' "
                    "ORDER BY query_start LIMIT 5"
                )
            ),
            timeout=POSTGRES_PREFLIGHT_TIMEOUT_SECONDS,
        )
        return [
            {"pid": int(pid), "age_seconds": int(age or 0), "command": command}
            for pid, age, command in result.fetchall()
        ]
    finally:
        await connection.close()


async def _ensure_postgres_quiet(report: dict[str, Any]) -> bool:
    """Record a bounded, actionable failure when PostgreSQL is busy."""
    try:
        active_writes = await _find_active_postgres_writes()
    except Exception as exc:  # pragma: no cover - environment dependent
        report["status"] = "blocked_by_environment"
        report["error"] = f"PostgreSQL unavailable: {_describe_exception(exc)}"
        return False
    report["postgresql"]["active_writes"] = active_writes
    if active_writes:
        details = ", ".join(
            f"pid={item['pid']} age={item['age_seconds']}s command={item['command']}"
            for item in active_writes
        )
        report["status"] = "blocked_by_environment"
        report["error"] = f"PostgreSQL busy with active write(s): {details}"
        return False
    return True


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


def redact_mongodb_url(value: str) -> str:
    """Hide MongoDB credentials before a benchmark report is persisted."""
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        if not hostname:
            return value
        host = f"[{hostname}]" if ":" in hostname else hostname
        if parsed.port is not None:
            host = f"{host}:{parsed.port}"
        username = quote(parsed.username, safe="") if parsed.username else ""
        userinfo = username
        if parsed.password is not None:
            userinfo = f"{userinfo}:***" if userinfo else "***"
        netloc = f"{userinfo}@{host}" if userinfo else host
        return urlunsplit(
            (parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment)
        )
    except ValueError:
        return value


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
        and case.get("quarantined_rows", 0) == 0
        and case.get("correctness", {}).get("counter_invariant", True)
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
    fast_mode: bool = False,
    ordered_insert: bool = BENCHMARK_ORDERED_INSERT,
    measure_memory: bool = False,
    profile: bool = False,
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
        fast_mode=fast_mode,
        write_workers=benchmark_config.write_workers,
        ordered_insert=ordered_insert,
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
    profiler = cProfile.Profile() if profile else None
    if profiler is not None:
        profiler.enable()
    memory_peak_bytes = 0
    if measure_memory:
        import tracemalloc

        tracemalloc.start()
    started = time.perf_counter()
    try:
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
    finally:
        elapsed = time.perf_counter() - started
        if measure_memory:
            _, memory_peak_bytes = tracemalloc.get_traced_memory()
            tracemalloc.stop()
        if profiler is not None:
            profiler.disable()
    stats = result.stats
    stage_summary = (
        result.file_record.stage_summary if result.file_record is not None else {}
    )
    batch_metrics = stage_summary.get("batchMetrics", {})
    quality_counters = result.quality_counters
    rss_peak = peak_rss_bytes()
    counter_invariant = quality_counters.get("inputRows", stats.total_rows) == (
        quality_counters.get("persistedRows", stats.success_rows)
        + quality_counters.get("rejectedRows", 0)
        + quality_counters.get("duplicateRows", stats.duplicate_rows)
        + quality_counters.get("persistenceFailedRows", 0)
    )
    case = {
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
        "wall_clock_ms": elapsed * 1000,
        "wallClockMs": elapsed * 1000,
        "peak_rss_bytes": rss_peak,
        "rss_peak_bytes": rss_peak,
        "stageSummary": stage_summary,
        "stage_summary": stage_summary,
        "batchMetrics": batch_metrics,
        "batch_metrics": batch_metrics,
        "throughput_rows_per_second": round(
            stats.total_rows / elapsed, 3
        )
        if elapsed > 0
        else 0.0,
        "quality_counters": quality_counters,
        "correctness": {
            "counter_invariant": counter_invariant,
            "persisted_rows_match": stats.success_rows == stats.total_rows,
        },
        "errors": result.errors[:5],
        "file_record_id": str(result.file_record.id)
        if result.file_record is not None
        else None,
    }
    if measure_memory:
        case["tracemalloc_peak_bytes"] = memory_peak_bytes
    if profiler is not None:
        import pstats

        profile_stream = io.StringIO()
        pstats.Stats(profiler, stream=profile_stream).sort_stats("cumulative").print_stats(30)
        case["profile"] = profile_stream.getvalue()
    return case


async def _collect_postgres_evidence() -> dict[str, Any]:
    """Collect read-only persistence and representative query-plan evidence."""
    from sqlalchemy import text

    repository = DataContainerRepository()
    try:
        async with repository.engine.connect() as connection:
            persistence = await connection.execute(
                text(
                    "SELECT CASE relpersistence WHEN 'u' THEN 'UNLOGGED' "
                    "ELSE 'LOGGED' END FROM pg_class WHERE relname = 'partner_transaction'"
                )
            )
            plan = await connection.execute(
                text(
                    "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "
                    "SELECT identify, ingestion_key FROM partner_transaction "
                    "WHERE identify = :identify AND reconciliation_date = :date "
                    "LIMIT 100"
                ),
                {"identify": BENCHMARK_PARTNER, "date": datetime(2025, 1, 1)},
            )
            plan_value = plan.scalar()
            if isinstance(plan_value, str):
                plan_value = json.loads(plan_value)
            return {
                "table_persistence": persistence.scalar() or "not-found",
                "explain_analyze_buffers": plan_value,
                "read_only": True,
            }
    except Exception as exc:  # pragma: no cover - depends on local PostgreSQL
        return {
            "table_persistence": "unavailable",
            "read_only": True,
            "error": _redact_mongodb_credentials(_describe_exception(exc)),
        }


def _write_report(report: dict[str, Any], output_json: Path, output_markdown: Path, markdown: str) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_markdown.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    output_markdown.write_text(markdown, encoding="utf-8")


def _write_json_report(report: dict[str, Any], output_json: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _prepare_sql_profile_rows(input_path: Path, config: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build the SQL profile batch through the same mapping path as ingestion."""
    started = time.perf_counter()
    processor = RowProcessor(
        normalizer=TransactionNormalizer(
            config.field_mappings,
            timestamp_policy=config.timestamp_policy,
        ),
        validator=Validator(),
        fast_mode=False,
        partner=BENCHMARK_PARTNER,
        workflow_type=BENCHMARK_WORKFLOW,
        reconciliation_date=datetime(2025, 1, 1, tzinfo=UTC),
        source_file_id=uuid4(),
    )
    rows: list[dict[str, Any]] = []
    rejected_rows = 0
    with CSVStreamReader.from_mapping_config(input_path, config) as reader:
        for row_number, row in enumerate(reader.iter_rows(), start=config.start_row):
            outcome = processor.process(row, row_number)
            if outcome.is_valid and outcome.data_container is not None:
                rows.append(data_container_to_row(outcome.data_container))
            else:
                rejected_rows += 1
    return rows, {
        "input_rows": len(rows) + rejected_rows,
        "valid_rows": len(rows),
        "rejected_rows": rejected_rows,
        "mapping_ms": (time.perf_counter() - started) * 1000,
    }


def _parse_explain_json(records: Any) -> dict[str, Any]:
    """Decode asyncpg's one-row FORMAT JSON EXPLAIN result."""
    value = records[0][0]
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    parsed = json.loads(value) if isinstance(value, str) else value
    if isinstance(parsed, list):
        return parsed[0] if parsed else {}
    return parsed


def summarize_explain_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Return bounded, decision-oriented evidence from one PostgreSQL plan."""
    nodes: list[dict[str, Any]] = []
    buffer_totals = {
        "shared_read_blocks": 0,
        "shared_written_blocks": 0,
        "temp_read_blocks": 0,
        "temp_written_blocks": 0,
        "local_read_blocks": 0,
        "local_written_blocks": 0,
    }

    def visit(node: dict[str, Any], path: str) -> None:
        node_type = str(node.get("Node Type", "unknown"))
        loops = float(node.get("Actual Loops", 1) or 1)
        actual_total_ms = float(node.get("Actual Total Time", 0) or 0) * loops
        node_evidence = {
            "path": path,
            "node_type": node_type,
            "actual_total_ms": actual_total_ms,
            "actual_rows": node.get("Actual Rows"),
            "actual_loops": node.get("Actual Loops"),
            "shared_read_blocks": int(node.get("Shared Read Blocks", 0) or 0),
            "shared_written_blocks": int(node.get("Shared Written Blocks", 0) or 0),
            "temp_read_blocks": int(node.get("Temp Read Blocks", 0) or 0),
            "temp_written_blocks": int(node.get("Temp Written Blocks", 0) or 0),
            "local_read_blocks": int(node.get("Local Read Blocks", 0) or 0),
            "local_written_blocks": int(node.get("Local Written Blocks", 0) or 0),
        }
        nodes.append(node_evidence)
        for key in buffer_totals:
            value = node_evidence.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                buffer_totals[key] += int(value)
        for index, child in enumerate(node.get("Plans", [])):
            visit(child, f"{path}/{index}")

    root = plan.get("Plan")
    if isinstance(root, dict):
        visit(root, "0")
    operation_nodes = {
        category: [
            node for node in nodes
            if category in node["node_type"].lower()
        ]
        for category in ("sort", "hash", "materialize")
    }
    slowest = max(nodes, key=lambda node: node["actual_total_ms"], default=None)
    return {
        "planning_time_ms": float(plan.get("Planning Time", 0) or 0),
        "execution_time_ms": float(plan.get("Execution Time", 0) or 0),
        "buffer_totals": buffer_totals,
        "operation_nodes": operation_nodes,
        "slowest_operation": slowest,
        "nodes": nodes,
    }


async def run_sql_profile(
    input_path: Path = DEFAULT_INPUT,
    output_json: Path = DEFAULT_SQL_PROFILE_OUTPUT_JSON,
) -> dict[str, Any]:
    """Profile the runtime COPY/classification SQL inside a rolled-back transaction."""
    from sqlalchemy import text

    if not input_path.is_file():
        raise FileNotFoundError(f"Dataset file not found: {input_path}")
    report = _evaluation_report_base(
        input_path=input_path, kind="sql-profile", rss_cap_bytes=RSS_CAP_BYTES
    )
    report["configuration"] = {
        "config_version": BENCHMARK_CONFIG_VERSION,
        "batch_size": BENCHMARK_BATCH_SIZE,
        "write_workers": BENCHMARK_WORKERS,
        "fast_mode": False,
        "ordered_insert": False,
    }
    report["transaction"] = {
        "begin": True,
        "rollback": True,
        "persistent_rows_written": False,
    }
    try:
        if not await _ensure_postgres_quiet(report):
            return report
        repository = DataContainerRepository()
        with TemporaryDirectory(
            prefix="sprint4-sql-profile-",
            dir="data/eda/fraud_detection/interim",
        ) as temporary_dir:
            profile_input = Path(temporary_dir) / "fraud_detection_20000.csv"
            write_prefix_csv(input_path, profile_input, BENCHMARK_BATCH_SIZE)
            report["dataset"]["evaluation_sha256"] = _sha256(profile_input)
            config = MappingConfig.model_validate(build_mapping_document())
            rows, preparation = _prepare_sql_profile_rows(profile_input, config)
            report["batch"] = preparation
            if len(rows) != BENCHMARK_BATCH_SIZE:
                raise RuntimeError(
                    f"SQL profile prepared {len(rows)} valid rows, expected {BENCHMARK_BATCH_SIZE}"
                )

            from src.infrastructure.partner_transaction.repository import (
                _STAGE_COLUMNS,
                _row_to_copy_tuple,
                build_partner_transaction_classify_sql,
                build_partner_transaction_stage_sql,
            )

            stage_table = "partner_transaction_stage"
            stage_sql = build_partner_transaction_stage_sql(stage_table)
            classify_sql = build_partner_transaction_classify_sql(stage_table)
            timings: dict[str, float] = {}
            tuple_started = time.perf_counter()
            tuples = [
                _row_to_copy_tuple(row, incoming_ordinal)
                for incoming_ordinal, row in enumerate(rows)
            ]
            timings["tuple_materialization_ms"] = (
                time.perf_counter() - tuple_started
            ) * 1000
            transaction_started = time.perf_counter()
            async with repository.engine.connect() as connection:
                transaction = await connection.begin()
                try:
                    stage_started = time.perf_counter()
                    await connection.execute(text(stage_sql))
                    timings["stage_setup_ms"] = (time.perf_counter() - stage_started) * 1000
                    raw_connection = await connection.get_raw_connection()
                    asyncpg_connection = raw_connection.driver_connection
                    copy_started = time.perf_counter()
                    await asyncpg_connection.copy_records_to_table(
                        stage_table,
                        columns=_STAGE_COLUMNS,
                        records=tuples,
                    )
                    timings["copy_ms"] = (time.perf_counter() - copy_started) * 1000
                    explain_started = time.perf_counter()
                    explain_records = await asyncpg_connection.fetch(
                        "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)\n" + classify_sql
                    )
                    timings["classify_explain_wall_ms"] = (
                        time.perf_counter() - explain_started
                    ) * 1000
                    plan = _parse_explain_json(explain_records)
                finally:
                    await transaction.rollback()
            timings["transaction_ms"] = (time.perf_counter() - transaction_started) * 1000
            plan_summary = summarize_explain_plan(plan)
            report["sql"] = {
                "stage_table_sql": stage_sql,
                "classify_sql": classify_sql,
                "shared_with_runtime": True,
                "explain": plan,
                "summary": plan_summary,
            }
            report["metrics"] = {
                **timings,
                "planning_time_ms": plan_summary["planning_time_ms"],
                "execution_time_ms": plan_summary["execution_time_ms"],
                "classify_ms": plan_summary["execution_time_ms"],
            }
            async with repository.engine.connect() as connection:
                remaining = await connection.execute(
                    text(
                        "SELECT COUNT(*) FROM partner_transaction "
                        "WHERE identify = :identify"
                    ),
                    {"identify": BENCHMARK_PARTNER},
                )
                report["transaction"]["remaining_partner_rows"] = int(
                    remaining.scalar() or 0
                )
        report["postgresql"].update(await _collect_postgres_evidence())
    except Exception as exc:  # pragma: no cover - environment dependent
        report["status"] = "benchmark_failed"
        report["error"] = _redact_mongodb_credentials(_describe_exception(exc))
    finally:
        report["cleanup"] = "SQL transaction rolled back; no MongoDB writes"
        _write_json_report(report, output_json)
    return report


def _isolated_case_worker(payload: dict[str, Any], pipe: Any) -> None:
    """Run exactly one sample in a fresh process and return bounded evidence."""

    async def run() -> dict[str, Any]:
        client: Any = AsyncIOMotorClient(
            settings.mongodb_url,
            serverSelectionTimeoutMS=3000,
        )
        try:
            await _ping_mongodb(client)
            db = client[settings.db_name]
            config = BenchmarkConfig(
                batch_size=int(payload["batch_size"]),
                write_workers=int(payload["write_workers"]),
                cases=(None,),
            )
            return await _run_case(
                db=db,
                input_path=Path(payload["input_path"]),
                requested_rows=EVALUATION_ROWS,
                case_index=int(payload["sample_index"]),
                benchmark_config=config,
                fast_mode=bool(payload["fast_mode"]),
                ordered_insert=False,
                measure_memory=bool(payload.get("measure_memory", False)),
                profile=bool(payload.get("profile", False)),
            )
        finally:
            client.close()

    try:
        pipe.send({"ok": True, "sample": asyncio.run(run())})
    except BaseException as exc:  # pragma: no cover - child/process failure
        pipe.send({"ok": False, "error": _redact_mongodb_credentials(_describe_exception(exc))})
    finally:
        pipe.close()


def run_isolated_sample(
    *,
    input_path: Path,
    variant: dict[str, Any],
    sample_index: int,
    measure_memory: bool = False,
    profile: bool = False,
    timeout_seconds: int = 900,
) -> dict[str, Any]:
    """Run a benchmark sample in a new process for an independent RSS peak."""
    context = multiprocessing.get_context("spawn")
    parent_pipe, child_pipe = context.Pipe(duplex=False)
    process = context.Process(
        target=_isolated_case_worker,
        args=(
            {
                "input_path": str(input_path),
                "batch_size": variant["batch_size"],
                "write_workers": variant["write_workers"],
                "fast_mode": variant["fast_mode"],
                "sample_index": sample_index,
                "measure_memory": measure_memory,
                "profile": profile,
            },
            child_pipe,
        ),
    )
    process.start()
    child_pipe.close()
    deadline = time.monotonic() + timeout_seconds
    response: dict[str, Any] | None = None
    while process.is_alive() and time.monotonic() < deadline:
        if parent_pipe.poll(0.2):
            response = parent_pipe.recv()
            break
        process.join(0.2)
    if response is None and parent_pipe.poll():
        response = parent_pipe.recv()
    process.join(1)
    if process.is_alive():
        process.terminate()
        process.join(5)
        raise TimeoutError(f"benchmark sample exceeded {timeout_seconds}s")
    if response is None:
        raise RuntimeError(f"benchmark sample exited without a result (code={process.exitcode})")
    parent_pipe.close()
    if not response.get("ok"):
        raise RuntimeError(response.get("error", "benchmark sample failed"))
    return response["sample"]


def _evaluation_report_base(
    *, input_path: Path, kind: str, rss_cap_bytes: int
) -> dict[str, Any]:
    return {
        "benchmark_version": 3,
        "kind": kind,
        "status": "completed",
        "boundary": "IngestionPipeline.process_file",
        "dataset": {
            "path": str(input_path),
            "sha256": _sha256(input_path),
            "size_bytes": input_path.stat().st_size,
            "evaluation_rows": EVALUATION_ROWS,
        },
        "environment": {
            "mongodb_url": redact_mongodb_url(
                os.environ.get("MONGODB_URL", settings.mongodb_url)
            ),
            "db_name": settings.db_name,
            "postgres_persistence_expected": "LOGGED",
        },
        "measurement": {
            "warmup_samples": WARMUP_SAMPLES,
            "measured_samples": MEASURED_SAMPLES,
            "process_per_sample": True,
            "tracemalloc_in_latency_timer": False,
            "peak_rss_cap_bytes": rss_cap_bytes,
        },
        "postgresql": {"table_persistence": "not_checked", "read_only": True},
    }


def render_review_markdown(report: dict[str, Any]) -> str:
    baseline = report.get("baseline", {})
    aggregate = baseline.get("aggregate", {})
    latency = aggregate.get("wall_clock_ms", {})
    rss = aggregate.get("peak_rss_bytes", {})
    lines = [
        "# Sprint 4 — Review baseline: Fraud Detection 100k",
        "",
        f"- Status: **{report.get('status')}**",
        f"- Dataset SHA-256: `{report['dataset']['sha256']}`",
        f"- Boundary: `{report['boundary']}`",
        "- PostgreSQL table persistence: **LOGGED** (expected; verify evidence below)",
        "- Latency timer: `process_file()` only; `tracemalloc` is excluded",
        "",
        "## Baseline",
        "",
        f"- Variant: `{baseline.get('variant', {})}`",
        f"- Samples: `{aggregate.get('sample_count', 0)}`",
        f"- Wall-clock median/MAD: `{latency.get('median', 0):.3f}/{latency.get('mad', 0):.3f} ms`",
        f"- Peak RSS median/max: `{rss.get('median', 0):.0f}/{rss.get('max', 0):.0f} bytes`",
        "",
        "## Components",
        "",
        "| Component | Median (ms) |",
        "|---|---:|",
    ]
    component_values: dict[str, list[float]] = {}
    for sample in baseline.get("samples", []):
        for key, value in sample.get("batch_metrics", {}).items():
            if isinstance(value, (int, float)):
                component_values.setdefault(key, []).append(float(value))
    for key, values in sorted(component_values.items()):
        lines.append(f"| `{key}` | {statistics.median(values):.3f} |")
    if report.get("error"):
        lines.extend(["", f"- Error: `{report['error']}`"])
    lines.extend(
        [
            "",
            "## Measurement notes",
            "",
            "`db_insert_ms` remains the backward-compatible persistence window; it is not SQL-only time.",
            "The raw samples and correctness counters are retained in the JSON artifact.",
        ]
    )
    if report.get("optimization_gate"):
        gate = report["optimization_gate"]
        lines.extend(
            [
                "",
                "## Optimization gate",
                "",
                f"- Passed: `{gate.get('passed')}`",
                f"- Latency reduction: `{gate.get('latency_reduction', 0):.3%}`",
                f"- RSS reduction: `{gate.get('rss_reduction', 0):.3%}`",
            ]
        )
    return "\n".join(lines) + "\n"


def render_ab_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Sprint 4 — Fraud Detection 100k A/B benchmark",
        "",
        f"- Status: **{report.get('status')}**",
        f"- Dataset SHA-256: `{report['dataset']['sha256']}`",
        "- Boundary: `IngestionPipeline.process_file`",
        "- PostgreSQL persistence: **LOGGED**; no UNLOGGED/schema/index change",
        "",
        "| Variant | Median ms | MAD ms | RSS max | Valid | Promote |",
        "|---|---:|---:|---:|---|---|",
    ]
    for name, evidence in report.get("variants", {}).items():
        aggregate = evidence.get("aggregate", {})
        latency = aggregate.get("wall_clock_ms", {})
        rss = aggregate.get("peak_rss_bytes", {})
        lines.append(
            f"| `{name}` | {latency.get('median', 0):.3f} | {latency.get('mad', 0):.3f} | "
            f"{rss.get('max', 0):.0f} | {evidence.get('valid')} | {evidence.get('promotable')} |"
        )
    lines.extend(
        [
            "",
            f"- Winner: `{report.get('winner') or 'none'}`",
            "- `fast_mode=true` is diagnostic-only and is never promoted.",
            "- Full MOMO validation is recorded separately from A/B latency ranking.",
        ]
    )
    if report.get("error"):
        lines.extend(["", f"- Error: `{report['error']}`"])
    return "\n".join(lines) + "\n"


async def run_review_benchmark(
    input_path: Path = DEFAULT_INPUT,
    output_json: Path = DEFAULT_REVIEW_OUTPUT_JSON,
    output_markdown: Path = DEFAULT_REVIEW_OUTPUT_MARKDOWN,
    *,
    warmup_samples: int = WARMUP_SAMPLES,
    measured_samples: int = MEASURED_SAMPLES,
    rss_cap_bytes: int = RSS_CAP_BYTES,
    memory_profile: bool = False,
    profile: bool = True,
    baseline_artifact: Path | None = None,
) -> dict[str, Any]:
    """Run a clean 100k baseline with one fresh process per sample."""
    if not input_path.is_file():
        raise FileNotFoundError(f"Dataset file not found: {input_path}")
    if warmup_samples < 0 or measured_samples < 1:
        raise ValueError("warmup_samples must be non-negative and measured_samples positive")
    report = _evaluation_report_base(
        input_path=input_path, kind="review", rss_cap_bytes=rss_cap_bytes
    )
    report["baseline_before"] = {
        "artifact": str(baseline_artifact)
        if baseline_artifact is not None
        else "data/eda/fraud_detection/profiles/benchmark_results_workstream_c.json",
        "measurement_compatible": baseline_artifact is not None,
        "reason": (
            "Comparison uses the prior isolated 100k review artifact."
            if baseline_artifact is not None
            else "Sprint 3 used in-process timing and a different full-file row count; not a baseline for this gate."
        ),
    }
    report["optimization"] = {
        "runtime_optimization_applied": baseline_artifact is not None,
        "candidate": "stream-copy-generator" if baseline_artifact is not None else None,
        "reason": (
            "Measured the stream-copy candidate against the prior review artifact."
            if baseline_artifact is not None
            else "Instrumentation and bounded tracing only; no runtime change is promoted without the measurement gate."
        ),
    }
    report["configuration"] = {
        "config_version": BENCHMARK_CONFIG_VERSION,
        "batch_size": BENCHMARK_BATCH_SIZE,
        "write_workers": BENCHMARK_WORKERS,
        "fast_mode": False,
        "ordered_insert": False,
    }
    report["measurement"]["warmup_samples"] = warmup_samples
    report["measurement"]["measured_samples"] = measured_samples
    report["baseline"] = {
        "variant": dict(VARIANT_MATRIX[0]),
        "warmup_samples": [],
        "samples": [],
        "aggregate": aggregate_samples([]),
        "valid": False,
    }
    report["baseline_after_optimize"] = {
        "artifact": str(output_json),
        "aggregate": aggregate_samples([]),
        "valid": False,
    }
    client: Any = AsyncIOMotorClient(settings.mongodb_url, serverSelectionTimeoutMS=3000)
    db: Any | None = None
    try:
        try:
            await _ping_mongodb(client)
        except Exception as exc:  # pragma: no cover - environment dependent
            report["status"] = "blocked_by_environment"
            report["error"] = _redact_mongodb_credentials(
                f"MongoDB unavailable: {_describe_exception(exc)}"
            )
            return report
        if not await _ensure_postgres_quiet(report):
            return report
        db = client[settings.db_name]
        await _install_mapping(db)
        with TemporaryDirectory(
            prefix="sprint4-review-", dir="data/eda/fraud_detection/interim"
        ) as temporary_dir:
            evaluation_path = Path(temporary_dir) / "fraud_detection_100000.csv"
            write_prefix_csv(input_path, evaluation_path, EVALUATION_ROWS)
            report["dataset"]["evaluation_sha256"] = _sha256(evaluation_path)
            variant = VARIANT_MATRIX[0]
            for index in range(warmup_samples):
                report["baseline"]["warmup_samples"].append(
                    run_isolated_sample(
                        input_path=evaluation_path,
                        variant=variant,
                        sample_index=index,
                    )
                )
            for index in range(measured_samples):
                report["baseline"]["samples"].append(
                    run_isolated_sample(
                        input_path=evaluation_path,
                        variant=variant,
                        sample_index=warmup_samples + index,
                    )
                )
            report["baseline"]["aggregate"] = aggregate_samples(
                report["baseline"]["samples"]
            )
            report["baseline"]["valid"] = all_samples_meet_acceptance(
                report["baseline"]["samples"], rss_cap_bytes=rss_cap_bytes
            )
            report["baseline_after_optimize"] = {
                "artifact": str(output_json),
                "aggregate": report["baseline"]["aggregate"],
                "valid": report["baseline"]["valid"],
            }
            if baseline_artifact is not None and baseline_artifact.is_file():
                previous = json.loads(baseline_artifact.read_text(encoding="utf-8"))
                previous_aggregate = previous.get("baseline", {}).get("aggregate")
                if previous_aggregate:
                    gate = optimization_gate(
                        previous_aggregate, report["baseline"]["aggregate"]
                    )
                    gate["passed"] = bool(
                        gate["passed"] and report["baseline"]["valid"]
                    )
                    report["optimization_gate"] = gate
            if profile:
                profile_sample = run_isolated_sample(
                    input_path=evaluation_path,
                    variant=variant,
                    sample_index=warmup_samples + measured_samples,
                    profile=True,
                )
                report["profile"] = profile_sample.get("profile")
            if memory_profile:
                report["memory_profile"] = run_isolated_sample(
                    input_path=evaluation_path,
                    variant=variant,
                    sample_index=warmup_samples + measured_samples + 1,
                    measure_memory=True,
                )
        report["postgresql"].update(await _collect_postgres_evidence())
        if not report["baseline"]["valid"]:
            report["status"] = "benchmark_failed"
    except Exception as exc:  # pragma: no cover - environment dependent
        report["status"] = "benchmark_failed"
        report["error"] = _redact_mongodb_credentials(_describe_exception(exc))
    finally:
        if db is not None:
            try:
                await _clear_benchmark_data(db)
                await _remove_mapping(db)
                report["cleanup"] = "benchmark records and mapping removed"
            except Exception as exc:  # pragma: no cover - environment dependent
                report["cleanup"] = "failed"
                report["cleanup_error"] = _redact_mongodb_credentials(
                    _describe_exception(exc)
                )
        client.close()
        _write_report(report, output_json, output_markdown, render_review_markdown(report))
    return report


def _variant_evidence(
    variant: dict[str, Any], warmups: list[dict[str, Any]], samples: list[dict[str, Any]], rss_cap_bytes: int
) -> dict[str, Any]:
    valid = all_samples_meet_acceptance(samples, rss_cap_bytes=rss_cap_bytes)
    return {
        "configuration": dict(variant),
        "warmup_samples": warmups,
        "samples": samples,
        "aggregate": aggregate_samples(samples),
        "valid": valid,
        "promotable": False,
    }


async def run_ab_benchmark(
    input_path: Path = DEFAULT_INPUT,
    output_json: Path = DEFAULT_AB_OUTPUT_JSON,
    output_markdown: Path = DEFAULT_AB_OUTPUT_MARKDOWN,
    *,
    warmup_samples: int = WARMUP_SAMPLES,
    measured_samples: int = MEASURED_SAMPLES,
    rss_cap_bytes: int = RSS_CAP_BYTES,
    baseline_artifact: Path | None = None,
) -> dict[str, Any]:
    """Run the fixed, serial, deterministically rotated 100k A/B matrix."""
    if not input_path.is_file():
        raise FileNotFoundError(f"Dataset file not found: {input_path}")
    if warmup_samples < 0 or measured_samples < 1:
        raise ValueError("warmup_samples must be non-negative and measured_samples positive")
    report = _evaluation_report_base(
        input_path=input_path, kind="ab", rss_cap_bytes=rss_cap_bytes
    )
    report["measurement"]["warmup_samples"] = warmup_samples
    report["measurement"]["measured_samples"] = measured_samples
    report["matrix"] = [dict(variant) for variant in VARIANT_MATRIX]
    report["configuration"] = {
        "config_version": BENCHMARK_CONFIG_VERSION,
        "ordered_insert": False,
    }
    report["variants"] = {
        variant["name"]: {
            "configuration": dict(variant),
            "warmup_samples": [],
            "samples": [],
            "aggregate": aggregate_samples([]),
            "valid": False,
            "promotable": False,
        }
        for variant in VARIANT_MATRIX
    }
    report["execution_order"] = []
    report["winner"] = None
    report["promotion_gate"] = {
        "control": "control-20k-w1",
        "minimum_latency_reduction": 0.05,
        "fast_mode_promotable": False,
        "passed": False,
    }
    report["full_momo_validation"] = {
        "status": "not_run",
        "ranking_excluded": True,
        "reason": "No valid winner was available; run the existing MOMO 100k E2E after A/B.",
    }
    report["optimization_baseline"] = {
        "artifact": str(baseline_artifact) if baseline_artifact is not None else None,
        "candidate": "stream-copy-generator" if baseline_artifact is not None else None,
    }
    client: Any = AsyncIOMotorClient(settings.mongodb_url, serverSelectionTimeoutMS=3000)
    db: Any | None = None
    try:
        try:
            await _ping_mongodb(client)
        except Exception as exc:  # pragma: no cover - environment dependent
            report["status"] = "blocked_by_environment"
            report["error"] = _redact_mongodb_credentials(
                f"MongoDB unavailable: {_describe_exception(exc)}"
            )
            return report
        if not await _ensure_postgres_quiet(report):
            return report
        db = client[settings.db_name]
        await _install_mapping(db)
        with TemporaryDirectory(
            prefix="sprint4-ab-", dir="data/eda/fraud_detection/interim"
        ) as temporary_dir:
            evaluation_path = Path(temporary_dir) / "fraud_detection_100000.csv"
            write_prefix_csv(input_path, evaluation_path, EVALUATION_ROWS)
            report["dataset"]["evaluation_sha256"] = _sha256(evaluation_path)
            sample_index = 0
            for round_index in range(warmup_samples):
                for variant in rotate_variants(VARIANT_MATRIX, round_index):
                    report["execution_order"].append(
                        {"phase": "warmup", "round": round_index, "variant": variant["name"]}
                    )
                    report["variants"][variant["name"]]["warmup_samples"].append(
                        run_isolated_sample(
                            input_path=evaluation_path,
                            variant=variant,
                            sample_index=sample_index,
                        )
                    )
                    sample_index += 1
            for round_index in range(measured_samples):
                for variant in rotate_variants(VARIANT_MATRIX, round_index + warmup_samples):
                    report["execution_order"].append(
                        {"phase": "measured", "round": round_index, "variant": variant["name"]}
                    )
                    report["variants"][variant["name"]]["samples"].append(
                        run_isolated_sample(
                            input_path=evaluation_path,
                            variant=variant,
                            sample_index=sample_index,
                        )
                    )
                    sample_index += 1
        for variant in VARIANT_MATRIX:
            name = variant["name"]
            current = report["variants"][name]
            report["variants"][name] = _variant_evidence(
                variant,
                current["warmup_samples"],
                current["samples"],
                rss_cap_bytes,
            )
        control = report["variants"]["control-20k-w1"]
        control_latency = control["aggregate"]["wall_clock_ms"]["median"]
        candidates = []
        if control["valid"]:
            for variant in VARIANT_MATRIX:
                name = variant["name"]
                evidence = report["variants"][name]
                latency = evidence["aggregate"]["wall_clock_ms"]["median"]
                evidence["promotable"] = (
                    evidence["valid"]
                    and not variant["fast_mode"]
                    and name != "control-20k-w1"
                    and latency <= control_latency * 0.95
                )
                if evidence["promotable"]:
                    candidates.append((latency, name))
        report["winner"] = min(candidates)[1] if candidates else None
        report["promotion_gate"] = {
            "control": "control-20k-w1",
            "minimum_latency_reduction": 0.05,
            "fast_mode_promotable": False,
            "passed": report["winner"] is not None,
        }
        report["full_momo_validation"] = {
            "status": "not_run",
            "ranking_excluded": True,
            "reason": "Run the existing MOMO 100k E2E after a winner is selected.",
        }
        report["postgresql"].update(await _collect_postgres_evidence())
        if not all(
            evidence["valid"] for evidence in report["variants"].values()
        ):
            report["status"] = "benchmark_failed"
    except Exception as exc:  # pragma: no cover - environment dependent
        report["status"] = "benchmark_failed"
        report["error"] = _redact_mongodb_credentials(_describe_exception(exc))
    finally:
        if db is not None:
            try:
                await _clear_benchmark_data(db)
                await _remove_mapping(db)
                report["cleanup"] = "benchmark records and mapping removed"
            except Exception as exc:  # pragma: no cover - environment dependent
                report["cleanup"] = "failed"
                report["cleanup_error"] = _redact_mongodb_credentials(
                    _describe_exception(exc)
                )
        client.close()
        _write_report(report, output_json, output_markdown, render_ab_markdown(report))
    return report


def render_optimization_markdown(
    sql_profile: dict[str, Any], review: dict[str, Any], ab: dict[str, Any]
) -> str:
    """Render the opt2 handoff without duplicating raw evidence in Markdown."""
    review_aggregate = review.get("baseline", {}).get("aggregate", {})
    review_latency = review_aggregate.get("wall_clock_ms", {})
    review_rss = review_aggregate.get("peak_rss_bytes", {})
    candidate_gate_passed = review.get("optimization_gate", {}).get("passed", False)
    lines = [
        "# Sprint 4 — Benchmark optimization 2: SQL trước, memory sau",
        "",
        f"- SQL profile status: **{sql_profile.get('status')}**",
        f"- Review status: **{review.get('status')}**",
        f"- A/B status: **{ab.get('status')}**",
        f"- Runtime candidate: `stream-copy-generator` ({'retained' if candidate_gate_passed else 'rejected; baseline retained'})",
        "- Production defaults: unchanged; `fast_mode=true` remains diagnostic-only",
        "",
        "## SQL evidence",
        "",
        "- Report: `data/eda/fraud_detection/profiles/benchmark_sql_profile_100k.json`",
        f"- Plan available: `{bool(sql_profile.get('sql'))}`",
        "- SQL rewrite: skipped unless EXPLAIN identifies a concrete safe bottleneck.",
        "",
        "## Candidate review",
        "",
        f"- Wall-clock median/MAD: `{review_latency.get('median', 0):.3f}/{review_latency.get('mad', 0):.3f} ms`",
        f"- Peak RSS median/max: `{review_rss.get('median', 0):.0f}/{review_rss.get('max', 0):.0f} bytes`",
        f"- Valid: `{review.get('baseline', {}).get('valid', False)}`",
        f"- Optimization gate: `{review.get('optimization_gate', {}).get('passed', False)}`",
        "",
        "## A/B matrix",
        "",
        "| Variant | Median ms | MAD ms | RSS max | Valid | Promote |",
        "|---|---:|---:|---:|---|---|",
    ]
    for name, evidence in ab.get("variants", {}).items():
        aggregate = evidence.get("aggregate", {})
        latency = aggregate.get("wall_clock_ms", {})
        rss = aggregate.get("peak_rss_bytes", {})
        lines.append(
            f"| `{name}` | {latency.get('median', 0):.3f} | {latency.get('mad', 0):.3f} | "
            f"{rss.get('max', 0):.0f} | {evidence.get('valid')} | {evidence.get('promotable')} |"
        )
    lines.extend(
        [
            "",
            f"- Winner: `{ab.get('winner') or 'none'}`",
            "- Full MOMO ingestion + reconciliation is run only after a valid `fast_mode=false` winner.",
            "- Raw samples, medians, MAD, RSS and correctness counters remain in the JSON reports.",
        ]
    )
    return "\n".join(lines) + "\n"


async def run_optimization_2(
    input_path: Path = DEFAULT_INPUT,
    *,
    warmup_samples: int = WARMUP_SAMPLES,
    measured_samples: int = MEASURED_SAMPLES,
    rss_cap_bytes: int = RSS_CAP_BYTES,
) -> dict[str, Any]:
    """Run opt2 review and A/B artifacts without replacing earlier reports."""
    sql_profile = await run_sql_profile(input_path=input_path)
    review = await run_review_benchmark(
        input_path=input_path,
        output_json=DEFAULT_OPT2_REVIEW_OUTPUT_JSON,
        output_markdown=DEFAULT_OPT2_MARKDOWN,
        warmup_samples=warmup_samples,
        measured_samples=measured_samples,
        rss_cap_bytes=rss_cap_bytes,
        baseline_artifact=DEFAULT_REVIEW_OUTPUT_JSON,
    )
    ab = await run_ab_benchmark(
        input_path=input_path,
        output_json=DEFAULT_OPT2_AB_OUTPUT_JSON,
        output_markdown=DEFAULT_OPT2_MARKDOWN,
        warmup_samples=warmup_samples,
        measured_samples=measured_samples,
        rss_cap_bytes=rss_cap_bytes,
        baseline_artifact=DEFAULT_REVIEW_OUTPUT_JSON,
    )
    candidate_gate = review.get("optimization_gate")
    if candidate_gate is not None:
        ab["candidate_gate"] = candidate_gate
        if not candidate_gate.get("passed", False):
            ab["winner"] = None
            ab["promotion_gate"]["passed"] = False
            ab["promotion_gate"]["blocked_by_candidate_gate"] = True
            for evidence in ab["variants"].values():
                evidence["promotable"] = False
            _write_report(
                ab,
                DEFAULT_OPT2_AB_OUTPUT_JSON,
                DEFAULT_OPT2_MARKDOWN,
                render_ab_markdown(ab),
            )
    DEFAULT_OPT2_MARKDOWN.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_OPT2_MARKDOWN.write_text(
        render_optimization_markdown(sql_profile, review, ab), encoding="utf-8"
    )
    return {"sql_profile": sql_profile, "review": review, "ab": ab}


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
        lines.extend(
            [f"- Error: `{_redact_mongodb_credentials(report['error'])}`", ""]
        )
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
            "mongodb_url": redact_mongodb_url(
                os.environ.get("MONGODB_URL", settings.mongodb_url)
            ),
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
            await _ping_mongodb(client)
        except Exception as exc:
            report["status"] = "blocked_by_environment"
            report["error"] = _redact_mongodb_credentials(
                f"MongoDB unavailable: {_describe_exception(exc)}"
            )
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
                report["cleanup_error"] = _redact_mongodb_credentials(
                    _describe_exception(exc)
                )
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
        "--review", action="store_true", help="Run the isolated 100k review baseline."
    )
    parser.add_argument(
        "--ab", action="store_true", help="Run the serial rotated 100k A/B matrix."
    )
    parser.add_argument(
        "--sql-profile",
        action="store_true",
        help="Profile the runtime COPY/classification SQL in a rolled-back transaction.",
    )
    parser.add_argument(
        "--optimization-2",
        action="store_true",
        help="Run opt2 review and A/B artifacts without replacing prior reports.",
    )
    parser.add_argument("--warmup-samples", type=int, default=WARMUP_SAMPLES)
    parser.add_argument("--samples", type=int, default=MEASURED_SAMPLES)
    parser.add_argument("--rss-cap-bytes", type=int, default=RSS_CAP_BYTES)
    parser.add_argument(
        "--memory-profile",
        action="store_true",
        help="Run tracemalloc separately from throughput measurements (review mode).",
    )
    parser.add_argument(
        "--no-profile",
        action="store_true",
        help="Skip the separate cProfile/pstats review sample.",
    )
    parser.add_argument(
        "--full-only",
        action="store_true",
        help="Run only the full source file instead of the default scale cases.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if sum((args.review, args.ab, args.sql_profile, args.optimization_2)) > 1:
        raise SystemExit(
            "--review, --ab, --sql-profile and --optimization-2 are mutually exclusive"
        )
    if args.sql_profile:
        output_json = (
            args.output_json
            if args.output_json != DEFAULT_OUTPUT_JSON
            else DEFAULT_SQL_PROFILE_OUTPUT_JSON
        )
        report = asyncio.run(
            run_sql_profile(
                input_path=args.input,
                output_json=output_json,
            )
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["status"] == "completed" else 2
    if args.optimization_2:
        reports = asyncio.run(
            run_optimization_2(
                input_path=args.input,
                warmup_samples=args.warmup_samples,
                measured_samples=args.samples,
                rss_cap_bytes=args.rss_cap_bytes,
            )
        )
        print(json.dumps(reports, ensure_ascii=False, indent=2))
        return 0 if all(report["status"] == "completed" for report in reports.values()) else 2
    if args.review:
        output_json = (
            args.output_json
            if args.output_json != DEFAULT_OUTPUT_JSON
            else DEFAULT_REVIEW_OUTPUT_JSON
        )
        output_markdown = (
            args.output_markdown
            if args.output_markdown != DEFAULT_OUTPUT_MARKDOWN
            else DEFAULT_REVIEW_OUTPUT_MARKDOWN
        )
        report = asyncio.run(
            run_review_benchmark(
                input_path=args.input,
                output_json=output_json,
                output_markdown=output_markdown,
                warmup_samples=args.warmup_samples,
                measured_samples=args.samples,
                rss_cap_bytes=args.rss_cap_bytes,
                memory_profile=args.memory_profile,
                profile=not args.no_profile,
            )
        )
    elif args.ab:
        output_json = (
            args.output_json
            if args.output_json != DEFAULT_OUTPUT_JSON
            else DEFAULT_AB_OUTPUT_JSON
        )
        output_markdown = (
            args.output_markdown
            if args.output_markdown != DEFAULT_OUTPUT_MARKDOWN
            else DEFAULT_AB_OUTPUT_MARKDOWN
        )
        report = asyncio.run(
            run_ab_benchmark(
                input_path=args.input,
                output_json=output_json,
                output_markdown=output_markdown,
                warmup_samples=args.warmup_samples,
                measured_samples=args.samples,
                rss_cap_bytes=args.rss_cap_bytes,
            )
        )
    else:
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
