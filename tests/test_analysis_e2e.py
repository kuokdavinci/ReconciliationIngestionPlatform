"""Opt-in PostgreSQL E2E coverage for the analysis orchestration."""

import json
import os
from decimal import Decimal
from typing import Optional

import pytest

from src.analysis.config import AnalysisConfig
from src.analysis.insights import get_discrepancies, get_summary
from src.analysis.provider import create_provider
from src.domain.reconciliation.models import ReconciliationResult
from src.infrastructure.postgres.reconciliation_result_repository import (
    ReconciliationResultRepository,
)


pytestmark = pytest.mark.e2e


class CapturingProvider:
    """Deterministic provider for exercising the real PostgreSQL analysis path."""

    model = "e2e-test-model"
    provider_name = "e2e-test"
    last_token_usage: Optional[dict[str, int]] = None

    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []

    async def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        self.prompts.append(f"{system_prompt or ''}\n{prompt}")
        return self.response


def _results_for(partner: str, date: str) -> list[ReconciliationResult]:
    statuses = [
        ("MATCHED", Decimal("100000"), Decimal("100000")),
        ("MATCHED", Decimal("120000"), Decimal("120000")),
        ("MATCHED", Decimal("140000"), Decimal("140000")),
        ("AMOUNT_MISMATCH", Decimal("200000"), Decimal("190000")),
        ("MISSING_INTERNAL", Decimal("300000"), None),
    ]
    return [
        ReconciliationResult(
            id=f"e2e-result-{partner}-{date}-{index}",
            partner=partner,
            date=date,
            partner_txn_id=f"E2E-TXN-{index}",
            internal_txn_id=(f"internal-{index}" if internal_amount is not None else None),
            partner_amount=partner_amount,
            internal_amount=internal_amount,
            reconciliation_status=status,
        )
        for index, (status, partner_amount, internal_amount) in enumerate(statuses)
    ]


def _valid_response(focus: str) -> str:
    return json.dumps(
        {
            "findings": [
                {
                    "type": "operational_gap" if focus == "operational" else "amount_mismatch",
                    "severity": "medium",
                    "title": "Reconciliation discrepancy detected",
                    "description": "A bounded discrepancy sample requires operator review.",
                    "affected_count": 1,
                    "recommendation": "Review the affected reconciliation group.",
                }
            ]
        }
    )


@pytest.mark.asyncio
async def test_analysis_summary_reads_postgres_results_and_keeps_prompt_aggregate_only(
    clean_postgres_tables,
):
    repository = ReconciliationResultRepository()
    await repository.insert_many(_results_for("MOMO", "2024-07-07"))
    provider = CapturingProvider(_valid_response("operational"))

    result = await get_summary(
        "MOMO",
        "2024-07-07",
        repository,
        provider,
        AnalysisConfig(cache_enabled=False),
    )

    metrics = result["summary_metrics"]
    assert metrics["total_transactions"] == 5
    assert metrics["matched"] == 3
    assert metrics["mismatch_rate"] == 40.0
    assert metrics["by_status"]["AMOUNT_MISMATCH"] == 1
    assert metrics["by_status"]["MISSING_INTERNAL"] == 1
    assert all(
        forbidden not in provider.prompts[0]
        for forbidden in ("partner_txn_id", "internal_txn_id", "raw_transactions", "E2E-TXN")
    )


@pytest.mark.asyncio
async def test_analysis_discrepancies_reads_postgres_samples(clean_postgres_tables):
    repository = ReconciliationResultRepository()
    await repository.insert_many(_results_for("ZALOPAY", "2024-07-08"))
    provider = CapturingProvider(_valid_response("inconsistency"))

    results = await get_discrepancies(
        "ZALOPAY",
        "2024-07-08",
        "inconsistency",
        repository,
        provider,
        AnalysisConfig(cache_enabled=False),
    )

    assert len(results) == 1
    assert results[0].affected_count == 1
    assert provider.prompts
    assert "E2E-TXN" not in provider.prompts[0]


def _real_provider_or_skip() -> tuple[object, AnalysisConfig]:
    api_key = os.getenv("E2E_AI_API_KEY") or os.getenv("AI_API_KEY")
    if not api_key:
        pytest.skip("E2E_AI_API_KEY or AI_API_KEY is not set")

    config = AnalysisConfig(
        provider=os.getenv("E2E_AI_PROVIDER") or "openai",
        model=os.getenv("E2E_AI_MODEL") or "gpt-4o-mini",
        endpoint=os.getenv("E2E_AI_ENDPOINT") or "https://api.openai.com/v1",
        api_key=api_key,
        timeout=60,
        max_retries=1,
        cache_enabled=False,
    )
    return create_provider(config), config


@pytest.mark.asyncio
async def test_real_llm_analysis_reads_postgres_results(clean_postgres_tables):
    repository = ReconciliationResultRepository()
    await repository.insert_many(_results_for("VNPAY", "2024-07-09"))
    provider, config = _real_provider_or_skip()

    result = await get_summary(
        "VNPAY",
        "2024-07-09",
        repository,
        provider,
        config,
    )

    assert result["summary_metrics"]["total_transactions"] == 5
    assert result["summary_metrics"]["matched"] == 3
    assert result["llm_status"] in {"success", "fallback"}
