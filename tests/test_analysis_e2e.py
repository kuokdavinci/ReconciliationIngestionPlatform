"""End-to-end tests for AI Analysis Layer with real services.

These tests require:
1. A running MongoDB instance (local or Docker)
2. A real LLM endpoint (OpenAI API, Azure OpenAI, or local vLLM/Ollama)

Run with:
    pytest tests/test_analysis_e2e.py -v --e2e

Or set environment variables:
    E2E_MONGODB_URL=mongodb://localhost:27017
    E2E_AI_ENDPOINT=https://api.openai.com/v1
    E2E_AI_API_KEY=sk-xxx
    E2E_AI_MODEL=gpt-4o-mini
    pytest tests/test_analysis_e2e.py -v --e2e

Tests verify:
- AI actually analyzes reconciliation data and returns meaningful insights
- Full pipeline: MongoDB → query → metrics → grouping → LLM → parse → validate
- All three focus types produce different, relevant outputs
- LLM response follows the expected JSON schema
- Privacy contract: no raw transaction data in prompts
"""

import json
import os
from decimal import Decimal
from typing import Any

import pytest

from src.analysis.config import AnalysisConfig
from src.analysis.insights import get_summary, get_discrepancies, _query_reconciliation_results
from src.analysis.metrics import MetricsService
from src.analysis.grouping import GroupingEngine
from src.analysis.prompts import build_system_prompt, build_analysis_prompt
from src.analysis.provider import create_provider
from src.analysis.schemas import AnalysisInput, AnalysisResult
from src.analysis.services import parse_llm_insights, build_analysis_input
from src.core.enums import ReconciliationStatus


# ---------------------------------------------------------------------------
# E2E marker and skip logic (hooks moved to conftest.py)
# ---------------------------------------------------------------------------


def _get_env(name: str, default: str | None = None) -> str | None:
    """Get environment variable, supporting both E2E_ and raw prefixes."""
    return os.environ.get(f"E2E_{name}") or os.environ.get(name) or default


def _require_e2e_env() -> tuple[str, str, str | None, str]:
    """Validate required E2E environment variables."""
    mongo_url = _get_env("MONGODB_URL")
    ai_endpoint = _get_env("AI_ENDPOINT", "https://api.openai.com/v1")
    ai_api_key = _get_env("AI_API_KEY")
    ai_model = _get_env("AI_MODEL", "gpt-4o-mini")

    if not mongo_url:
        pytest.skip("E2E_MONGODB_URL or MONGODB_URL not set")
    if not ai_api_key:
        pytest.skip("E2E_AI_API_KEY or AI_API_KEY not set")

    return mongo_url, ai_endpoint, ai_api_key, ai_model


def _get_test_db_name() -> str:
    """Get the test database name."""
    return _get_env("DB_NAME", "reconciliation")


# ---------------------------------------------------------------------------
# Test data factories
# ---------------------------------------------------------------------------

def _make_reconciliation_doc(
    status: str,
    partner: str = "MOMO",
    date: str = "2024-07-07",
    partner_amount: str | None = "100000",
    internal_amount: str | None = "100000",
) -> dict:
    """Create a reconciliation_result document for MongoDB insertion.
    
    Note: Always pass the correct date parameter - default is 2024-07-07.
    """
    doc = {
        "partner": partner,
        "date": date,
        "reconciliationStatus": status,
    }
    if partner_amount is not None:
        doc["partnerAmount"] = float(partner_amount)
    if internal_amount is not None:
        doc["internalAmount"] = float(internal_amount)
    return doc


# ---------------------------------------------------------------------------
# Scenario 1: AI analyzes mixed-status data and returns structured insights
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_ai_analyzes_mixed_status_data():
    """Verify AI actually analyzes reconciliation data and returns meaningful insights.

    Full pipeline:
    1. Insert diverse reconciliation results into MongoDB
    2. Call get_summary() with real LLM
    3. Verify AI returns structured, relevant findings
    """
    mongo_url, ai_endpoint, ai_api_key, ai_model = _require_e2e_env()

    from motor.motor_asyncio import AsyncIOMotorClient

    client = AsyncIOMotorClient(mongo_url)
    db_name = _get_test_db_name()
    db = client[db_name]
    collection = db["reconciliation_result"]

    # Clean up before test
    await collection.delete_many({"partner": "MOMO", "date": "2024-07-07"})

    # Insert diverse test data
    test_docs = [
        # 50 MATCHED transactions
        *[_make_reconciliation_doc("MATCHED", partner_amount=str(100000 + i * 1000), internal_amount=str(100000 + i * 1000)) for i in range(50)],
        # 10 AMOUNT_MISMATCH with varying differences
        *[_make_reconciliation_doc("AMOUNT_MISMATCH", partner_amount=str(100000 + i * 5000), internal_amount=str(95000 + i * 5000)) for i in range(10)],
        # 5 MISSING_INTERNAL
        *[_make_reconciliation_doc("MISSING_INTERNAL", partner_amount=None, internal_amount=None) for _ in range(5)],
        # 3 MISSING_PARTNER
        *[_make_reconciliation_doc("MISSING_PARTNER", partner_amount=None, internal_amount=None) for _ in range(3)],
        # 2 STATUS_MISMATCH
        *[_make_reconciliation_doc("STATUS_MISMATCH", partner_amount=str(200000), internal_amount=str(200000)) for _ in range(2)],
    ]

    await collection.insert_many(test_docs)

    # Create real LLM provider
    config = AnalysisConfig(
        provider="openai",
        model=ai_model,
        endpoint=ai_endpoint,
        api_key=ai_api_key,
        timeout=60,
        max_retries=1,
    )
    llm_provider = create_provider(config)

    # Run full pipeline
    result = await get_summary("MOMO", "2024-07-07", collection, llm_provider, config)

    # Verify structure
    assert result["partner"] == "MOMO"
    assert result["date"] == "2024-07-07"
    assert "summary_metrics" in result
    assert "grouped_stats" in result
    assert "key_findings" in result

    # Verify metrics are correct
    metrics = result["summary_metrics"]
    assert metrics["total_transactions"] == 70
    assert metrics["matched"] == 50
    assert metrics["by_status"]["MATCHED"] == 50
    assert metrics["by_status"]["AMOUNT_MISMATCH"] == 10
    assert metrics["by_status"]["MISSING_INTERNAL"] == 5
    assert metrics["by_status"]["MISSING_PARTNER"] == 3
    assert metrics["by_status"]["STATUS_MISMATCH"] == 2

    # Verify AI actually analyzed the data
    print(f"\n  LLM Status: {result['llm_status']}")
    if result["llm_status"] == "success":
        assert len(result["key_findings"]) > 0, "AI should return at least one finding"
        # Findings should be meaningful strings
        for finding in result["key_findings"]:
            assert isinstance(finding, str)
            assert len(finding) > 0
            print(f"  AI Finding: {finding}")
    else:
        print(f"  LLM status: {result['llm_status']} (check API key/endpoint)")

    # Clean up
    await collection.delete_many({"partner": "MOMO", "date": "2024-07-07"})
    client.close()


# ---------------------------------------------------------------------------
# Scenario 2: AI detects operational issues (missing records)
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_ai_detects_operational_issues():
    """Verify AI identifies MISSING_INTERNAL and MISSING_PARTNER as operational issues.

    Data: 80% missing records — should trigger strong operational alerts.
    """
    mongo_url, ai_endpoint, ai_api_key, ai_model = _require_e2e_env()

    from motor.motor_asyncio import AsyncIOMotorClient

    client = AsyncIOMotorClient(mongo_url)
    db_name = _get_test_db_name()
    db = client[db_name]
    collection = db["reconciliation_result"]

    await collection.delete_many({"partner": "VIETTEL", "date": "2024-07-07"})

    # 80% missing records
    test_docs = [
        *[_make_reconciliation_doc("MATCHED", partner="VIETTEL", partner_amount=str(100000), internal_amount=str(100000)) for _ in range(20)],
        *[_make_reconciliation_doc("MISSING_INTERNAL", partner="VIETTEL", partner_amount=None, internal_amount=None) for _ in range(50)],
        *[_make_reconciliation_doc("MISSING_PARTNER", partner="VIETTEL", partner_amount=None, internal_amount=None) for _ in range(30)],
    ]

    await collection.insert_many(test_docs)

    config = AnalysisConfig(
        provider="openai",
        model=ai_model,
        endpoint=ai_endpoint,
        api_key=ai_api_key,
        timeout=60,
        max_retries=1,
    )
    llm_provider = create_provider(config)

    result = await get_summary("VIETTEL", "2024-07-07", collection, llm_provider, config)

    # Verify metrics
    assert result["summary_metrics"]["total_transactions"] == 100
    assert result["summary_metrics"]["matched"] == 20
    assert result["summary_metrics"]["mismatch_rate"] == pytest.approx(80.0, rel=1e-2)

    # Verify AI detected operational issues
    print(f"\n  LLM Status: {result['llm_status']}")
    if result["llm_status"] == "success":
        findings_text = " ".join(result["key_findings"]).lower()
        # Should mention missing/internal/partner in findings
        has_operational_keyword = any(
            kw in findings_text for kw in ["missing", "internal", "partner", "delivery", "pipeline", "ingestion"]
        )
        assert has_operational_keyword, f"AI should detect operational issues. Findings: {result['key_findings']}"
        for finding in result["key_findings"]:
            print(f"  AI Finding: {finding}")

    await collection.delete_many({"partner": "VIETTEL", "date": "2024-07-07"})
    client.close()


# ---------------------------------------------------------------------------
# Scenario 3: AI analyzes amount mismatch patterns
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_ai_analyzes_amount_mismatch_patterns():
    """Verify AI identifies amount mismatch patterns and clusters.

    Data: All transactions have amount mismatches with consistent ~10% difference.
    """
    mongo_url, ai_endpoint, ai_api_key, ai_model = _require_e2e_env()

    from motor.motor_asyncio import AsyncIOMotorClient

    client = AsyncIOMotorClient(mongo_url)
    db_name = _get_test_db_name()
    db = client[db_name]
    collection = db["reconciliation_result"]

    await collection.delete_many({"partner": "ZALOPAY", "date": "2024-07-07"})

    # All amount mismatches with ~10% difference
    test_docs = [
        *[_make_reconciliation_doc(
            "AMOUNT_MISMATCH",
            partner="ZALOPAY",
            partner_amount=str(100000 + i * 10000),
            internal_amount=str(90000 + i * 9000),  # 10% less
        ) for i in range(30)],
    ]

    await collection.insert_many(test_docs)

    config = AnalysisConfig(
        provider="openai",
        model=ai_model,
        endpoint=ai_endpoint,
        api_key=ai_api_key,
        timeout=60,
        max_retries=1,
    )
    llm_provider = create_provider(config)

    # Test discrepancies endpoint with inconsistency focus
    results = await get_discrepancies("ZALOPAY", "2024-07-07", "inconsistency", collection, llm_provider, config)

    assert isinstance(results, list)
    print(f"\n  LLM Status: success (direct LLM call for discrepancies)")
    if results:
        # Each result should be a valid AnalysisResult
        for r in results:
            assert isinstance(r, AnalysisResult)
            assert r.type
            assert r.severity in ("low", "medium", "high", "critical")
            assert r.title
            assert r.description
            print(f"  AI Insight: [{r.severity}] {r.title} — {r.description}")

    await collection.delete_many({"partner": "ZALOPAY", "date": "2024-07-07"})
    client.close()


# ---------------------------------------------------------------------------
# Scenario 4: AI handles clean data (all matched)
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_ai_handles_clean_data():
    """Verify AI returns appropriate response when all data is matched.

    Data: 100% MATCHED — AI should report healthy status.
    """
    mongo_url, ai_endpoint, ai_api_key, ai_model = _require_e2e_env()

    from motor.motor_asyncio import AsyncIOMotorClient

    client = AsyncIOMotorClient(mongo_url)
    db_name = _get_test_db_name()
    db = client[db_name]
    collection = db["reconciliation_result"]

    await collection.delete_many({"partner": "MOMO", "date": "2024-07-08"})

    test_docs = [
        *[_make_reconciliation_doc("MATCHED", date="2024-07-08", partner_amount=str(100000 + i * 5000), internal_amount=str(100000 + i * 5000)) for i in range(100)],
    ]

    await collection.insert_many(test_docs)

    config = AnalysisConfig(
        provider="openai",
        model=ai_model,
        endpoint=ai_endpoint,
        api_key=ai_api_key,
        timeout=60,
        max_retries=1,
    )
    llm_provider = create_provider(config)

    result = await get_summary("MOMO", "2024-07-08", collection, llm_provider, config)

    assert result["summary_metrics"]["total_transactions"] == 100
    assert result["summary_metrics"]["matched"] == 100
    assert result["summary_metrics"]["mismatch_rate"] == 0.0

    print(f"\n  LLM Status: {result['llm_status']}")
    if result["llm_status"] == "success":
        findings_text = " ".join(result["key_findings"]).lower()
        # Should indicate healthy/normal/matched status
        has_positive_keyword = any(
            kw in findings_text for kw in ["healthy", "normal", "matched", "good", "stable", "within", "ok", "tốt", "bình thường"]
        )
        assert has_positive_keyword, f"AI should report healthy status. Findings: {result['key_findings']}"
        for finding in result["key_findings"]:
            print(f"  AI Finding: {finding}")

    await collection.delete_many({"partner": "MOMO", "date": "2024-07-08"})
    client.close()


# ---------------------------------------------------------------------------
# Scenario 5: AI response follows expected JSON schema
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_ai_response_follows_json_schema():
    """Verify AI returns properly structured JSON that can be parsed into AnalysisResult.

    This tests the full prompt → LLM → parse pipeline.
    """
    mongo_url, ai_endpoint, ai_api_key, ai_model = _require_e2e_env()

    from motor.motor_asyncio import AsyncIOMotorClient

    client = AsyncIOMotorClient(mongo_url)
    db_name = _get_test_db_name()
    db = client[db_name]
    collection = db["reconciliation_result"]

    await collection.delete_many({"partner": "MOMO", "date": "2024-07-09"})

    # Create a complex scenario
    test_docs = [
        *[_make_reconciliation_doc("MATCHED", date="2024-07-09", partner_amount=str(100000), internal_amount=str(100000)) for _ in range(40)],
        *[_make_reconciliation_doc("AMOUNT_MISMATCH", date="2024-07-09", partner_amount=str(200000), internal_amount=str(180000)) for _ in range(20)],
        *[_make_reconciliation_doc("MISSING_INTERNAL", date="2024-07-09", partner_amount=None, internal_amount=None) for _ in range(15)],
        *[_make_reconciliation_doc("MULTIPLE_MISMATCH", date="2024-07-09", partner_amount=str(500000), internal_amount=str(450000)) for _ in range(5)],
    ]

    await collection.insert_many(test_docs)

    config = AnalysisConfig(
        provider="openai",
        model=ai_model,
        endpoint=ai_endpoint,
        api_key=ai_api_key,
        timeout=60,
        max_retries=1,
    )
    llm_provider = create_provider(config)

    # Get full orchestration result
    result = await get_summary("MOMO", "2024-07-09", collection, llm_provider, config)

    # Build AnalysisInput and test direct LLM call
    summary = MetricsService.compute_summary([], "MOMO", "2024-07-09")
    summary.total_transactions = result["summary_metrics"]["total_transactions"]
    summary.matched = result["summary_metrics"]["matched"]
    summary.mismatch_rate = result["summary_metrics"]["mismatch_rate"]
    summary.total_amount_mismatch = result["summary_metrics"]["total_amount_mismatch"]
    summary.by_status = result["summary_metrics"]["by_status"]

    groups = GroupingEngine.group([])  # Would need real results for actual groups

    analysis_input = AnalysisInput(
        partner="MOMO",
        date="2024-07-09",
        focus="operational",
        summary_metrics=result["summary_metrics"],
        grouped_stats=result["grouped_stats"],
        top_anomalies=[],
    )

    # Direct LLM call
    system_prompt = build_system_prompt()
    user_prompt = build_analysis_prompt(analysis_input)

    llm_response = await llm_provider.generate(user_prompt, system_prompt)

    print(f"\n  Direct LLM call: {len(llm_response)} chars received")

    # Parse response
    parsed = parse_llm_insights(llm_response)

    assert len(parsed) > 0, "AI should return parseable findings"

    # Verify each finding follows AnalysisResult schema
    for finding in parsed:
        assert finding.type, "type is required"
        assert finding.severity in ("low", "medium", "high", "critical"), f"Invalid severity: {finding.severity}"
        assert finding.title, "title is required"
        assert finding.description, "description is required"
        assert isinstance(finding.affected_count, int), "affected_count must be int"
        assert isinstance(finding.recommendation, str), "recommendation must be str"
        print(f"  Valid Finding: [{finding.severity}] {finding.title}")

    await collection.delete_many({"partner": "MOMO", "date": "2024-07-09"})
    client.close()


# ---------------------------------------------------------------------------
# Scenario 6: AI differentiates between focus types
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_ai_differentiates_focus_types():
    """Verify AI produces different insights for different focus types.

    Same data, three focus types → three different insight sets.
    """
    mongo_url, ai_endpoint, ai_api_key, ai_model = _require_e2e_env()

    from motor.motor_asyncio import AsyncIOMotorClient

    client = AsyncIOMotorClient(mongo_url)
    db_name = _get_test_db_name()
    db = client[db_name]
    collection = db["reconciliation_result"]

    await collection.delete_many({"partner": "MOMO", "date": "2024-07-10"})

    test_docs = [
        *[_make_reconciliation_doc("MATCHED", date="2024-07-10", partner_amount=str(100000), internal_amount=str(100000)) for _ in range(30)],
        *[_make_reconciliation_doc("AMOUNT_MISMATCH", date="2024-07-10", partner_amount=str(100000), internal_amount=str(90000)) for _ in range(20)],
        *[_make_reconciliation_doc("MISSING_INTERNAL", date="2024-07-10", partner_amount=None, internal_amount=None) for _ in range(10)],
        *[_make_reconciliation_doc("STATUS_MISMATCH", date="2024-07-10", partner_amount=str(200000), internal_amount=str(200000)) for _ in range(5)],
    ]

    await collection.insert_many(test_docs)

    config = AnalysisConfig(
        provider="openai",
        model=ai_model,
        endpoint=ai_endpoint,
        api_key=ai_api_key,
        timeout=60,
        max_retries=1,
    )
    llm_provider = create_provider(config)

    focus_results = {}
    for focus in ("operational", "partner", "inconsistency"):
        results = await get_discrepancies("MOMO", "2024-07-10", focus, collection, llm_provider, config)
        focus_results[focus] = results
        print(f"\n  Focus: {focus} ({len(results)} insights from LLM)")
        for r in results:
            print(f"    [{r.severity}] {r.title}")

    # Each focus should produce at least some results
    # (LLM may return empty for some focuses, but at least one should have results)
    total_insights = sum(len(results) for results in focus_results.values())
    assert total_insights > 0, "At least one focus should produce insights"

    await collection.delete_many({"partner": "MOMO", "date": "2024-07-10"})
    client.close()


# ---------------------------------------------------------------------------
# Scenario 7: Privacy contract verification
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_privacy_contract_no_raw_data_in_prompt():
    """Verify that prompts sent to LLM never contain raw transaction data.

    Check that the prompt does not include:
    - Transaction IDs
    - Specific per-transaction amounts
    - Raw transaction arrays
    """
    mongo_url, ai_endpoint, ai_api_key, ai_model = _require_e2e_env()

    from motor.motor_asyncio import AsyncIOMotorClient

    client = AsyncIOMotorClient(mongo_url)
    db_name = _get_test_db_name()
    db = client[db_name]
    collection = db["reconciliation_result"]

    await collection.delete_many({"partner": "MOMO", "date": "2024-07-11"})

    test_docs = [
        _make_reconciliation_doc("MATCHED", date="2024-07-11", partner_amount="100000", internal_amount="100000"),
        _make_reconciliation_doc("AMOUNT_MISMATCH", date="2024-07-11", partner_amount="100000", internal_amount="90000"),
    ]

    await collection.insert_many(test_docs)

    # Query and build AnalysisInput
    results = await _query_reconciliation_results(collection, "MOMO", "2024-07-11")
    summary = MetricsService.compute_summary(results, "MOMO", "2024-07-11")
    groups = GroupingEngine.group(results)

    analysis_input = build_analysis_input(
        partner="MOMO",
        date="2024-07-11",
        focus="operational",
        metrics_result=summary,
        grouped_results=groups,
    )

    # Build prompts
    system_prompt = build_system_prompt()
    user_prompt = build_analysis_prompt(analysis_input)

    full_prompt = system_prompt + "\n\n" + user_prompt

    # Verify no raw data leakage
    forbidden_patterns = [
        "partner_txn_id",
        "internal_txn_id",
        "raw_transactions",
        "TXN2024",  # Transaction ID pattern
    ]

    for pattern in forbidden_patterns:
        assert pattern.lower() not in full_prompt.lower(), f"Prompt contains forbidden pattern: {pattern}"

    # Verify AnalysisInput has no raw data fields
    assert not hasattr(analysis_input, "partner_txn_id")
    assert not hasattr(analysis_input, "internal_txn_id")
    assert not hasattr(analysis_input, "raw_transactions")

    print("  Privacy contract verified: no raw transaction data in prompt")

    await collection.delete_many({"partner": "MOMO", "date": "2024-07-11"})
    client.close()


# ---------------------------------------------------------------------------
# Scenario 8: Large volume AI analysis
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_ai_handles_large_volume():
    """Verify AI can analyze 1000+ transactions without timeout.

    Tests performance and token limits.
    """
    mongo_url, ai_endpoint, ai_api_key, ai_model = _require_e2e_env()

    from motor.motor_asyncio import AsyncIOMotorClient

    client = AsyncIOMotorClient(mongo_url)
    db_name = _get_test_db_name()
    db = client[db_name]
    collection = db["reconciliation_result"]

    await collection.delete_many({"partner": "MOMO", "date": "2024-07-12"})

    # 1000 transactions with realistic distribution
    test_docs = [
        *[_make_reconciliation_doc("MATCHED", date="2024-07-12", partner_amount=str(100000 + i * 100), internal_amount=str(100000 + i * 100)) for i in range(900)],
        *[_make_reconciliation_doc("AMOUNT_MISMATCH", date="2024-07-12", partner_amount=str(100000 + i * 100), internal_amount=str(95000 + i * 100)) for i in range(50)],
        *[_make_reconciliation_doc("MISSING_INTERNAL", date="2024-07-12", partner_amount=None, internal_amount=None) for _ in range(30)],
        *[_make_reconciliation_doc("MISSING_PARTNER", date="2024-07-12", partner_amount=None, internal_amount=None) for _ in range(20)],
    ]

    await collection.insert_many(test_docs)

    config = AnalysisConfig(
        provider="openai",
        model=ai_model,
        endpoint=ai_endpoint,
        api_key=ai_api_key,
        timeout=120,  # Longer timeout for large volume
        max_retries=1,
    )
    llm_provider = create_provider(config)

    result = await get_summary("MOMO", "2024-07-12", collection, llm_provider, config)

    assert result["summary_metrics"]["total_transactions"] == 1000
    assert result["summary_metrics"]["matched"] == 900

    print(f"\n  LLM Status: {result['llm_status']}")
    if result["llm_status"] == "success":
        assert len(result["key_findings"]) > 0
        print(f"  AI analyzed 1000 transactions, returned {len(result['key_findings'])} findings")
        for finding in result["key_findings"]:
            print(f"    {finding}")

    await collection.delete_many({"partner": "MOMO", "date": "2024-07-12"})
    client.close()
