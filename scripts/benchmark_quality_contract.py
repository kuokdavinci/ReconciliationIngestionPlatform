"""Reproducible CPU/memory benchmark for the Workstream B quality contract.

Database query-shape guarantees are covered by repository acceptance tests.
This benchmark isolates clean-row quality accounting and duplicate fingerprint
costs with bounded, generated input so the 10k/100k/1M matrix is repeatable.
"""

from __future__ import annotations

import argparse
import gc
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from functools import partial
from pathlib import Path
from statistics import median
import sys
import time
import tracemalloc
from typing import Callable
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.enums import TransactionStatus
from src.core.types import FieldMapping, FieldMappingType
from src.domain.partner_transaction.duplicates import fingerprint_payload
from src.normalizer.normalizer import TransactionNormalizer
from src.pipeline.row_processor import RowProcessor
from src.pipeline.run_state import IngestionRunState
from src.validators.validator import Validator


DEFAULT_SIZES = (10_000, 100_000, 1_000_000)
DEFAULT_BATCH_SIZE = 10_000
SCENARIOS = ("clean", "equivalent_duplicate", "conflicting_duplicate")
MAX_CLEAN_REGRESSION_PERCENT = 10.0
_AMOUNT = Decimal("100.00")


@dataclass(frozen=True)
class BenchmarkConfig:
    sizes: tuple[int, ...]
    batch_size: int
    repeats: int


@dataclass(frozen=True)
class Measurement:
    seconds: float
    rows_per_second: float
    peak_bytes: int
    checksum: int


def build_benchmark_config(
    *,
    sizes: tuple[int, ...] = DEFAULT_SIZES,
    batch_size: int = DEFAULT_BATCH_SIZE,
    repeats: int = 3,
) -> BenchmarkConfig:
    if not sizes or any(size < 1 for size in sizes):
        raise ValueError("sizes must contain positive row counts")
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if repeats < 1:
        raise ValueError("repeats must be positive")
    return BenchmarkConfig(sizes=sizes, batch_size=batch_size, repeats=repeats)


def _processor() -> RowProcessor:
    mappings = [
        FieldMapping(
            path="id",
            column=1,
            type=FieldMappingType.STRING,
            required=True,
        ),
        FieldMapping(
            path="amount",
            column=2,
            type=FieldMappingType.DECIMAL,
            required=True,
        ),
        FieldMapping(
            path="currency",
            column=3,
            type=FieldMappingType.STRING,
            required=True,
        ),
        FieldMapping(
            path="status",
            type=FieldMappingType.CONSTANT,
            constant=TransactionStatus.SUCCESS.value,
            required=True,
        ),
    ]
    return RowProcessor(
        normalizer=TransactionNormalizer(mappings),
        validator=Validator(),
        fast_mode=True,
        partner="QUALITY_BENCHMARK",
        workflow_type="BENCHMARK",
        reconciliation_date=datetime(2026, 8, 20, tzinfo=UTC),
        source_file_id=uuid4(),
    )


def _clean_baseline(size: int) -> int:
    processor = _processor()
    ingestion_keys: list[str] = []
    for index in range(size):
        outcome = processor.process(
            (f"txn-{index}", _AMOUNT, "VND"),
            row_number=index + 2,
        )
        if outcome.is_valid:
            ingestion_keys.append(outcome.ingestion_key or "")
    return len(ingestion_keys)


def _clean_quality_runtime(size: int) -> int:
    processor = _processor()
    state = IngestionRunState()
    for index in range(size):
        row_number = state.record_row() + 1
        outcome = processor.process(
            (f"txn-{index}", _AMOUNT, "VND"),
            row_number=row_number,
        )
        state.record_row_outcome(outcome)
    return state.total_rows + len(state.ingestion_keys)


def _duplicate_payload(*, conflicting: bool) -> dict[str, object]:
    return {
        "partner_id": "duplicate-key",
        "partner_trace": "duplicate-trace",
        "partner_status": "SUCCESS",
        "partner_amount": Decimal("101.00") if conflicting else _AMOUNT,
        "partner_currency": "VND",
        "partner_trans_date": datetime(2026, 8, 20, tzinfo=UTC),
        "partner_metadata": {"channel": "app"},
    }


def _duplicate_baseline(size: int, *, conflicting: bool) -> int:
    checksum = 0
    for _index in range(size):
        payload = _duplicate_payload(conflicting=conflicting)
        checksum += len(str(payload["partner_id"]))
    return checksum


def _duplicate_quality_runtime(
    size: int,
    *,
    conflicting: bool,
    batch_size: int,
) -> int:
    classified = 0
    for batch_start in range(0, size, batch_size):
        existing = _duplicate_payload(conflicting=False)
        existing_fingerprint = fingerprint_payload(existing)
        batch_end = min(batch_start + batch_size, size)
        for _index in range(batch_start, batch_end):
            incoming = _duplicate_payload(conflicting=conflicting)
            incoming_fingerprint = fingerprint_payload(incoming)
            classified += int(incoming_fingerprint == existing_fingerprint)
    return classified


def _measure(size: int, operation: Callable[[], int], repeats: int) -> Measurement:
    durations: list[float] = []
    peaks: list[int] = []
    checksums: list[int] = []
    for _ in range(repeats):
        gc.collect()
        tracemalloc.start()
        started = time.perf_counter()
        checksum = operation()
        duration = time.perf_counter() - started
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        durations.append(duration)
        peaks.append(peak)
        checksums.append(checksum)
    duration = median(durations)
    return Measurement(
        seconds=duration,
        rows_per_second=size / duration,
        peak_bytes=max(peaks),
        checksum=checksums[-1],
    )


def run_benchmark(config: BenchmarkConfig) -> dict[str, object]:
    cases: list[dict[str, object]] = []
    clean_acceptance: list[bool] = []
    for size in config.sizes:
        for scenario in SCENARIOS:
            conflicting = scenario == "conflicting_duplicate"
            if scenario == "clean":
                baseline_operation = partial(_clean_baseline, size)
                quality_operation = partial(_clean_quality_runtime, size)
                lookup_queries = 0
            else:
                baseline_operation = partial(
                    _duplicate_baseline,
                    size,
                    conflicting=conflicting,
                )
                quality_operation = partial(
                    _duplicate_quality_runtime,
                    size,
                    conflicting=conflicting,
                    batch_size=config.batch_size,
                )
                lookup_queries = (size + config.batch_size - 1) // config.batch_size

            baseline = _measure(size, baseline_operation, config.repeats)
            quality = _measure(size, quality_operation, config.repeats)
            regression_percent = (
                (baseline.rows_per_second - quality.rows_per_second)
                / baseline.rows_per_second
                * 100
            )
            case = {
                "size": size,
                "scenario": scenario,
                "baseline": asdict(baseline),
                "workstreamB": asdict(quality),
                "throughputRegressionPercent": regression_percent,
                "existingPayloadLookupQueries": lookup_queries,
                "maxLookupQueriesPerBatch": 0 if scenario == "clean" else 1,
            }
            if scenario == "clean":
                passed = regression_percent <= MAX_CLEAN_REGRESSION_PERCENT
                case["cleanThroughputAcceptancePassed"] = passed
                clean_acceptance.append(passed)
            cases.append(case)

    return {
        "benchmarkVersion": 1,
        "generatedAt": datetime.now(UTC).isoformat(),
        "config": {
            "sizes": list(config.sizes),
            "batchSize": config.batch_size,
            "repeats": config.repeats,
            "scenarios": list(SCENARIOS),
        },
        "acceptance": {
            "maxCleanThroughputRegressionPercent": MAX_CLEAN_REGRESSION_PERCENT,
            "cleanThroughputPassed": all(clean_acceptance),
            "cleanLookupQueries": 0,
            "conflictLookupQueriesPerBatch": 1,
        },
        "cases": cases,
    }


def _parse_sizes(value: str) -> tuple[int, ...]:
    try:
        sizes = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("sizes must be comma-separated integers") from exc
    if not sizes or any(size < 1 for size in sizes):
        raise argparse.ArgumentTypeError("sizes must contain positive integers")
    return sizes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=_parse_sizes, default=DEFAULT_SIZES)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    config = build_benchmark_config(
        sizes=args.sizes,
        batch_size=args.batch_size,
        repeats=args.repeats,
    )
    report = run_benchmark(config)
    rendered = json.dumps(report, indent=2)
    if args.output is not None:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    acceptance = report["acceptance"]
    if not isinstance(acceptance, dict):
        return 1
    return 0 if acceptance.get("cleanThroughputPassed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
