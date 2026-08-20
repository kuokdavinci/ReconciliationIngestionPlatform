"""Tests for the reproducible Workstream B benchmark harness."""

import pytest

from scripts.benchmark_quality_contract import (
    SCENARIOS,
    build_benchmark_config,
    run_benchmark,
)


def test_quality_benchmark_config_validates_tuning():
    assert build_benchmark_config(sizes=(10,), batch_size=5, repeats=1).sizes == (10,)
    with pytest.raises(ValueError, match="sizes"):
        build_benchmark_config(sizes=())
    with pytest.raises(ValueError, match="batch_size"):
        build_benchmark_config(sizes=(10,), batch_size=0)
    with pytest.raises(ValueError, match="repeats"):
        build_benchmark_config(sizes=(10,), repeats=0)


def test_quality_benchmark_smoke_covers_every_scenario():
    report = run_benchmark(build_benchmark_config(sizes=(20,), batch_size=10, repeats=1))

    assert {case["scenario"] for case in report["cases"]} == set(SCENARIOS)
    clean, equivalent, conflict = report["cases"]
    assert clean["existingPayloadLookupQueries"] == 0
    assert equivalent["existingPayloadLookupQueries"] == 2
    assert conflict["maxLookupQueriesPerBatch"] == 1
    assert len(report["cases"]) == 3
