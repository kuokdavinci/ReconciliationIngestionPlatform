"""Insight Generator — orchestration layer for AI Analysis.

Entry point for summary and discrepancies endpoints.
Orchestration flow:
1. Query MongoDB for reconciliation results
2. Compute metrics via MetricsService
3. Group results via GroupingEngine
4. Build AnalysisInput via services helpers
5. Check TTL cache → call LLM (with fallback chain) → parse structured response
6. Return results with observability data

Fallback chain: primary provider → fallback provider → rule-based
"""

import logging
import time
from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorCollection

from src.analysis.cache import build_cache_key, get_insight_cache
from src.analysis.config import AnalysisConfig
from src.analysis.grouping import GroupingEngine
from src.analysis.metrics import MetricsService
from src.analysis.prompts import build_analysis_prompt, build_system_prompt
from src.analysis.provider import AIProviderRouter, LLMProvider
from src.analysis.providers.openai_compat import OpenAICompatProvider
from src.analysis.schemas import (
    AIObservation,
    AnalysisInput,
    AnalysisResult,
    GroupResult,
    SelectedErrorSignal,
    SummaryResult,
)
from src.analysis.guardrails import validate_insights
from src.analysis.services import (
    build_analysis_input,
    format_findings,
    parse_structured_insight,
    rule_based_pre_process,
)
from src.core.enums import ReconciliationStatus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MongoDB query helper
# ---------------------------------------------------------------------------

async def _query_reconciliation_results(
    collection: AsyncIOMotorCollection,
    partner: str,
    date: str,
    *,
    mismatch_only: bool = False,
    limit: int | None = None,
) -> list[Any]:
    """Query reconciliation results from MongoDB for a partner on a date.

    Args:
        collection: Motor collection for reconciliation_result.
        partner: Partner identifier to filter by.
        date: Date string (YYYY-MM-DD) to filter by.

    Returns:
        List of reconciliation result objects (as SimpleNamespace-like dicts).
    """
    query: dict[str, Any] = {"partner": partner, "date": date}
    if mismatch_only:
        query["reconciliationStatus"] = {
            "$in": [
                ReconciliationStatus.AMOUNT_MISMATCH.value,
                ReconciliationStatus.STATUS_MISMATCH.value,
                ReconciliationStatus.MULTIPLE_MISMATCH.value,
                ReconciliationStatus.MISSING_INTERNAL.value,
                ReconciliationStatus.MISSING_PARTNER.value,
                ReconciliationStatus.UNMAPPED_SKIPPED.value,
            ]
        }

    cursor = collection.find(query)
    if limit is not None:
        cursor = cursor.limit(limit)
    docs = await cursor.to_list(length=limit)
    return _docs_to_results(docs, partner, date)


def _docs_to_results(docs: list[dict[str, Any]], partner: str, date: str) -> list[Any]:
    from types import SimpleNamespace

    results = []
    for doc in docs:
        result = SimpleNamespace()
        result.partner = doc.get("partner", partner)
        result.date = doc.get("date", date)
        result.partner_amount = doc.get("partnerAmount") if "partnerAmount" in doc else doc.get("partner_amount")
        result.internal_amount = doc.get("internalAmount") if "internalAmount" in doc else doc.get("internal_amount")
        status_str = doc.get("reconciliationStatus") if "reconciliationStatus" in doc else doc.get("reconciliation_status", "MATCHED")
        try:
            result.reconciliation_status = ReconciliationStatus(status_str)
        except ValueError:
            result.reconciliation_status = ReconciliationStatus.MATCHED
        results.append(result)
    return results


async def _query_summary_metrics(
    collection: AsyncIOMotorCollection,
    partner: str,
    date: str,
) -> SummaryResult:
    pipeline = [
        {"$match": {"partner": partner, "date": date}},
        {
            "$group": {
                "_id": "$reconciliationStatus",
                "count": {"$sum": 1},
                "mismatch_amount": {
                    "$sum": {
                        "$cond": [
                            {"$in": ["$reconciliationStatus", [
                                ReconciliationStatus.AMOUNT_MISMATCH.value,
                                ReconciliationStatus.MULTIPLE_MISMATCH.value,
                                ReconciliationStatus.STATUS_MISMATCH.value,
                            ]]},
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
    cursor = collection.aggregate(pipeline)
    async for doc in cursor:
        status = str(doc["_id"])
        count = int(doc["count"])
        by_status[status] = count
        total_transactions += count
        if status in (
            ReconciliationStatus.MATCHED.value,
            ReconciliationStatus.MATCHED_FAILED.value,
            ReconciliationStatus.MATCHED_REVERSED.value,
        ):
            matched += count
        mismatch_amount = doc.get("mismatch_amount")
        if mismatch_amount is not None:
            try:
                total_amount_mismatch += float(
                    mismatch_amount.to_decimal() if hasattr(mismatch_amount, "to_decimal") else mismatch_amount
                )
            except Exception:
                pass

    mismatch_count = max(0, total_transactions - matched)
    mismatch_rate = round((mismatch_count * 100 / total_transactions), 2) if total_transactions else 0.0
    return SummaryResult(
        partner=partner,
        date=date,
        total_transactions=total_transactions,
        matched=matched,
        mismatch_rate=mismatch_rate,
        total_amount_mismatch=total_amount_mismatch,
        by_status=by_status,
    )


def _build_group_results_from_summary(summary: SummaryResult) -> list[GroupResult]:
    total = summary.total_transactions or 0
    groups: list[GroupResult] = []
    for status, count in summary.by_status.items():
        percentage = round((count / total) * 100, 2) if total else 0.0
        groups.append(
            GroupResult(
                key=status,
                count=count,
                percentage=percentage,
                total_amount=0.0,
                details={},
            )
        )
    return groups


def _compute_summary_hash(summary: SummaryResult) -> str:
    import hashlib

    ordered_counts = "|".join(f"{status}:{summary.by_status[status]}" for status in sorted(summary.by_status.keys()))
    payload = f"{summary.partner}|{summary.date}|{summary.total_transactions}|{summary.matched}|{summary.mismatch_rate}|{summary.total_amount_mismatch}|{ordered_counts}"
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


async def _query_selected_error_results(
    collection: AsyncIOMotorCollection,
    partner: str,
    date: str,
    per_status_limit: int = 50,
) -> list[Any]:
    selected_docs: list[dict[str, Any]] = []
    status_order = [
        ReconciliationStatus.MISSING_INTERNAL.value,
        ReconciliationStatus.MISSING_PARTNER.value,
        ReconciliationStatus.AMOUNT_MISMATCH.value,
        ReconciliationStatus.MULTIPLE_MISMATCH.value,
        ReconciliationStatus.STATUS_MISMATCH.value,
        ReconciliationStatus.UNMAPPED_SKIPPED.value,
    ]
    for status in status_order:
        cursor = collection.find(
            {"partner": partner, "date": date, "reconciliationStatus": status}
        ).limit(per_status_limit)
        docs = await cursor.to_list(length=per_status_limit)
        selected_docs.extend(docs)
    return _docs_to_results(selected_docs, partner, date)


def _format_amount_band(amount: float) -> str:
    if amount < 100_000:
        return "0-100k"
    if amount < 1_000_000:
        return "100k-1M"
    return "1M+"


def _build_selected_error_signals(results: list[Any]) -> list[SelectedErrorSignal]:
    grouped: dict[str, list[Any]] = {}
    for result in results:
        status = result.reconciliation_status.value if hasattr(result.reconciliation_status, "value") else str(result.reconciliation_status)
        grouped.setdefault(status, []).append(result)

    signals: list[SelectedErrorSignal] = []
    for status, items in grouped.items():
        amount_range = "N/A"
        pattern_hint = "Sampled bounded error records"
        if status in {
            ReconciliationStatus.AMOUNT_MISMATCH.value,
            ReconciliationStatus.MULTIPLE_MISMATCH.value,
        }:
            diffs: list[float] = []
            for item in items:
                partner_amount = getattr(item, "partner_amount", None)
                internal_amount = getattr(item, "internal_amount", None)
                if partner_amount is None or internal_amount is None:
                    continue
                try:
                    diffs.append(abs(float(partner_amount) - float(internal_amount)))
                except Exception:
                    continue
            if diffs:
                avg_diff = sum(diffs) / len(diffs)
                amount_range = _format_amount_band(avg_diff)
                pattern_hint = "Selected from amount-difference mismatches"
        elif status == ReconciliationStatus.STATUS_MISMATCH.value:
            pattern_hint = "Selected from status mapping inconsistencies"
        elif status == ReconciliationStatus.MISSING_INTERNAL.value:
            pattern_hint = "Selected from partner-only records"
        elif status == ReconciliationStatus.MISSING_PARTNER.value:
            pattern_hint = "Selected from internal-only records"
        elif status == ReconciliationStatus.UNMAPPED_SKIPPED.value:
            pattern_hint = "Selected from skipped unmapped partner rows"

        signals.append(
            SelectedErrorSignal(
                status=status,
                sample_count=len(items),
                amount_range=amount_range,
                pattern_hint=pattern_hint,
            )
        )
    return signals


# ---------------------------------------------------------------------------
# Observability helper
# ---------------------------------------------------------------------------

def _build_observation(
    partner: str,
    date: str,
    focus: str,
    start_time: float,
    provider: Optional[LLMProvider] = None,
    cache_hit: bool = False,
    cache_key: str = "",
    schema_valid: bool = True,
    resolution: str = "llm",
    guardrail_result: dict | None = None,
) -> AIObservation:
    """Build an AIObservation from generation context.

    Args:
        partner: Partner identifier.
        date: Date string.
        focus: Analysis focus.
        start_time: Monotonic start time.
        provider: Provider used (if any).
        cache_hit: Whether result came from cache.
        cache_key: Cache key used.
        schema_valid: Whether schema validation passed.
        resolution: Resolution path.
        guardrail_result: Guardrail validation result dict (optional).

    Returns:
        AIObservation with populated fields.
    """
    latency_ms = round((time.monotonic() - start_time) * 1000, 2)
    provider_name = getattr(provider, "provider_name", "") if provider else ""
    model_name = getattr(provider, "model", "") if provider else ""
    usage = getattr(provider, "last_token_usage", None) if provider else None

    prompt_tokens = (usage or {}).get("prompt_tokens", 0)
    completion_tokens = (usage or {}).get("completion_tokens", 0)
    total_tokens = (usage or {}).get("total_tokens", 0)
    estimated_cost = OpenAICompatProvider.estimate_cost_for_usage(
        model_name, prompt_tokens, completion_tokens
    ) if model_name else 0.0

    return AIObservation(
        partner=partner,
        date=date,
        focus=focus,
        provider=provider_name,
        model=model_name,
        latency_ms=latency_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        estimated_cost_usd=estimated_cost,
        cache_hit=cache_hit,
        cache_key=cache_key,
        schema_valid=schema_valid,
        resolution=resolution,
        guardrail_result=guardrail_result,
    )


def _log_observation(obs: AIObservation) -> None:
    """Log an AIObservation as a structured log line.

    Args:
        obs: AIObservation to log.
    """
    logger.info(
        f"AI insight generated: {obs.resolution} | "
        f"{obs.latency_ms}ms | {obs.total_tokens}tokens | ${obs.estimated_cost_usd:.6f}",
        extra={
            "event": "ai_insight_observation",
            "ai_partner": obs.partner,
            "ai_date": obs.date,
            "ai_focus": obs.focus,
            "ai_provider": obs.provider,
            "ai_model": obs.model,
            "ai_latency_ms": obs.latency_ms,
            "ai_prompt_tokens": obs.prompt_tokens,
            "ai_completion_tokens": obs.completion_tokens,
            "ai_total_tokens": obs.total_tokens,
            "ai_estimated_cost_usd": obs.estimated_cost_usd,
            "ai_cache_hit": obs.cache_hit,
            "ai_schema_valid": obs.schema_valid,
            "ai_resolution": obs.resolution,
        },
    )


def _compute_results_hash(results: list[Any]) -> str:
    import hashlib
    # Compute a unique fingerprint for the results list
    result_fingerprints = []
    for r in results:
        txn_id = getattr(r, "partner_txn_id", "") or getattr(r, "internal_txn_id", "") or ""
        status = getattr(r, "reconciliation_status", "") or ""
        result_fingerprints.append(f"{txn_id}:{status}")
    result_fingerprints.sort()
    
    fingerprint_str = ",".join(result_fingerprints)
    return hashlib.md5(fingerprint_str.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# get_summary — orchestration for summary endpoint
# ---------------------------------------------------------------------------

async def get_summary(
    partner: str,
    date: str,
    collection: AsyncIOMotorCollection,
    llm_provider: LLMProvider,
    config: Optional[AnalysisConfig] = None,
) -> dict[str, Any]:
    """Generate summary insights for a partner on a given date.

    Orchestration flow:
    1. Query MongoDB → reconciliation results
    2. MetricsService.compute_summary() → SummaryResult
    3. GroupingEngine.group() → list[GroupResult]
    4. Build AnalysisInput → check cache → LLM for key_findings
    5. Return {summary_metrics, grouped_stats, key_findings, observation}

    Args:
        partner: Partner identifier.
        date: Date string (YYYY-MM-DD).
        collection: Motor collection for reconciliation_result.
        llm_provider: LLM provider instance (AIProviderRouter).
        config: Optional AnalysisConfig (uses defaults if not provided).

    Returns:
        Dict with summary_metrics, grouped_stats, key_findings, and metadata.
    """
    start_time = time.monotonic()
    cfg = config or AnalysisConfig()

    # Step 1: Query aggregated metrics from MongoDB
    summary = await _query_summary_metrics(collection, partner, date)
    logger.info(
        f"Queried aggregated reconciliation metrics for {partner} on {date}",
        extra={"event": "ai_insight_query", "partner": partner, "date": date, "count": summary.total_transactions},
    )

    # Step 2: Build grouped stats from aggregated status counts only
    groups = _build_group_results_from_summary(summary)

    # Step 4: Build AnalysisInput for summary (operational focus)
    analysis_input = build_analysis_input(
        partner=partner,
        date=date,
        focus="operational",
        metrics_result=summary,
        grouped_results=groups,
        selected_error_signals=[],
    )

    # Step 5: Check cache if enabled
    cache_enabled = cfg.cache_enabled
    model_name = _get_model_name(llm_provider)
    results_hash = _compute_summary_hash(summary)
    cache_key = build_cache_key(partner, date, "operational", model_name, reconciliation_run_id=results_hash)
    insight_cache = get_insight_cache() if cache_enabled and model_name else None

    cached_results = insight_cache.get(cache_key) if insight_cache else None
    cache_hit = cached_results is not None

    if cache_hit:
        parsed_results, schema_valid = cached_results
        guardrail_result = None
        logger.info(
            f"Cache hit for {cache_key}",
            extra={"event": "ai_insight_cache_hit", "cache_key": cache_key},
        )
    else:
        # Step 6: LLM enrichment for key_findings (with fallback chain)
        parsed_results, schema_valid, guardrail_result = await _generate_insights_with_fallback(
            analysis_input, llm_provider, start_time
        )

        # Cache result if cache is enabled and schema passed
        if insight_cache and schema_valid and parsed_results:
            insight_cache.set(cache_key, (parsed_results, schema_valid))

    key_findings = format_findings(parsed_results) if parsed_results else []
    resolution = _resolve_resolution(llm_provider, parsed_results, schema_valid)

    # Step 7: Build response
    grouped_stats = [
        {
            "key": g.key,
            "count": g.count,
            "percentage": g.percentage,
            "total_amount": g.total_amount,
            "details": g.details,
        }
        for g in groups
    ]

    elapsed_ms = round((time.monotonic() - start_time) * 1000, 2)

    # Build and log observation
    provider_used = _get_last_provider(llm_provider)
    observation = _build_observation(
        partner=partner,
        date=date,
        focus="operational",
        start_time=start_time,
        provider=provider_used,
        cache_hit=cache_hit,
        cache_key=cache_key,
        schema_valid=schema_valid,
        resolution=resolution,
        guardrail_result=guardrail_result,
    )
    _log_observation(observation)

    logger.info(
        f"Summary generated in {elapsed_ms}ms for {partner} on {date}",
        extra={
            "event": "ai_insight_summary_complete",
            "partner": partner,
            "date": date,
            "latency_ms": elapsed_ms,
            "llm_status": _llm_status(resolution),
        },
    )

    return {
        "partner": partner,
        "date": date,
        "summary_metrics": {
            "total_transactions": summary.total_transactions,
            "matched": summary.matched,
            "mismatch_rate": summary.mismatch_rate,
            "total_amount_mismatch": summary.total_amount_mismatch,
            "by_status": summary.by_status,
        },
        "grouped_stats": grouped_stats,
        "key_findings": key_findings,
        "guardrail_result": guardrail_result,
        "generated_at": date,
        "llm_status": _llm_status(resolution),
        "ai_observation": observation.model_dump(),
    }


# ---------------------------------------------------------------------------
# get_discrepancies — orchestration for discrepancies endpoint
# ---------------------------------------------------------------------------

async def get_discrepancies(
    partner: str,
    date: str,
    focus: str,
    collection: AsyncIOMotorCollection,
    llm_provider: LLMProvider,
    config: Optional[AnalysisConfig] = None,
) -> list[AnalysisResult]:
    """Generate discrepancy insights for a partner on a given date.

    Orchestration flow:
    1. Query MongoDB → reconciliation results
    2. MetricsService.compute_summary() → SummaryResult
    3. GroupingEngine.group() → list[GroupResult]
    4. Rule-based pre-process → anomalies
    5. Build AnalysisInput → check cache → generate insights
    6. Return list[AnalysisResult]

    Args:
        partner: Partner identifier.
        date: Date string (YYYY-MM-DD).
        focus: Analysis focus (operational | partner | inconsistency).
        collection: Motor collection for reconciliation_result.
        llm_provider: LLM provider instance (AIProviderRouter).
        config: Optional AnalysisConfig.

    Returns:
        List of AnalysisResult objects (LLM-enriched or rule-based fallback).
    """
    start_time = time.monotonic()
    cfg = config or AnalysisConfig()

    # Step 1: Query MongoDB
    summary = await _query_summary_metrics(collection, partner, date)
    results = await _query_selected_error_results(
        collection,
        partner,
        date,
        per_status_limit=50,
    )
    logger.info(
        f"Queried {len(results)} results for discrepancies ({focus}) for {partner} on {date}",
        extra={"event": "ai_insight_discrepancy_query", "partner": partner, "date": date, "focus": focus, "count": len(results)},
    )

    # Step 3: Group results
    groups = GroupingEngine.group(results)

    # Step 4: Rule-based pre-process
    summary_metrics_dict = {
        "total_transactions": summary.total_transactions,
        "matched": summary.matched,
        "mismatch_rate": summary.mismatch_rate,
        "total_amount_mismatch": summary.total_amount_mismatch,
        "by_status": summary.by_status,
        "partner": partner,
    }
    anomalies = rule_based_pre_process(results, focus, summary_metrics_dict)
    selected_error_signals = _build_selected_error_signals(results)

    # Step 5: Build AnalysisInput
    analysis_input = build_analysis_input(
        partner=partner,
        date=date,
        focus=focus,
        metrics_result=summary,
        grouped_results=groups,
        anomalies=anomalies,
        selected_error_signals=selected_error_signals,
    )

    # Step 6: Check cache if enabled
    cache_enabled = cfg.cache_enabled
    model_name = _get_model_name(llm_provider)
    results_hash = _compute_results_hash(results)
    cache_key = build_cache_key(partner, date, focus, model_name, reconciliation_run_id=results_hash)
    insight_cache = get_insight_cache() if cache_enabled and model_name else None

    cached_results = insight_cache.get(cache_key) if insight_cache else None
    cache_hit = cached_results is not None

    if cache_hit:
        insights, schema_valid = cached_results
        guardrail_result = None
        logger.info(
            f"Cache hit for {cache_key}",
            extra={"event": "ai_insight_cache_hit", "cache_key": cache_key},
        )
    else:
        insights, schema_valid, guardrail_result = await _generate_insights_with_fallback(
            analysis_input, llm_provider, start_time
        )

        if insight_cache and schema_valid and insights:
            insight_cache.set(cache_key, (insights, schema_valid))

    resolution = _resolve_resolution(llm_provider, insights, schema_valid)

    elapsed_ms = round((time.monotonic() - start_time) * 1000, 2)

    # Build and log observation
    provider_used = _get_last_provider(llm_provider)
    observation = _build_observation(
        partner=partner,
        date=date,
        focus=focus,
        start_time=start_time,
        provider=provider_used,
        cache_hit=cache_hit,
        cache_key=cache_key,
        schema_valid=schema_valid,
        resolution=resolution,
        guardrail_result=guardrail_result,
    )
    _log_observation(observation)

    logger.info(
        f"Discrepancies generated in {elapsed_ms}ms for {partner} on {date} (focus={focus})",
        extra={
            "event": "ai_insight_discrepancy_complete",
            "partner": partner,
            "date": date,
            "focus": focus,
            "latency_ms": elapsed_ms,
            "insight_count": len(insights),
            "ai_resolution": resolution,
        },
    )

    return insights


# ---------------------------------------------------------------------------
# generate_insights — internal helper with cache bypass
# ---------------------------------------------------------------------------

async def generate_insights(
    analysis_input: AnalysisInput,
    llm_provider: LLMProvider,
) -> list[AnalysisResult]:
    """Generate insights from AnalysisInput using rule-based + LLM enrichment.

    Legacy API — prefer _generate_insights_with_fallback for new code.
    This function exists for backward compatibility with existing callers.

    Args:
        analysis_input: Structured input with metrics, groups, anomalies.
        llm_provider: LLM provider instance.

    Returns:
        List of AnalysisResult objects (LLM-enriched or rule-based fallback).
    """
    results, _, _ = await _generate_insights_with_fallback(analysis_input, llm_provider, time.monotonic())
    return results


def _sanitize_mismatch_rate(
    results: list[AnalysisResult],
    actual_rate: float,
) -> list[AnalysisResult]:
    """Ensure any mismatch rate mentioned in LLM output matches the actual computed value.

    The LLM sometimes recomputes its own mismatch rate percentage from grouped counts
    rather than using the authoritative mismatch_rate from MetricsService. This sanitizer
    detects such discrepancies and corrects them.

    Args:
        results: List of AnalysisResult from the LLM.
        actual_rate: The authoritative mismatch_rate from MetricsService.

    Returns:
        List of AnalysisResult with corrected mismatch rate percentages.
    """
    import re

    sanitized = []
    for r in results:
        title = r.title
        desc = r.description

        def _fix_mismatch_percentage(text: str) -> str:
            if not text:
                return text
            # Match patterns like "mismatch rate at 35%", "mismatch rate of 35%",
            # "35% mismatch rate", "35.0% mismatch rate", "rate is 35%"
            text = re.sub(
                r"(\d+[\.\d]*)\s*%\s*mismatch\s+rate",
                f"{actual_rate}% mismatch rate",
                text,
                flags=re.IGNORECASE,
            )
            text = re.sub(
                r"mismatch\s+rate\s+(?:is|at|of)\s+(\d+[\.\d]*)\s*%",
                f"mismatch rate is {actual_rate}%",
                text,
                flags=re.IGNORECASE,
            )
            return text

        new_title = _fix_mismatch_percentage(title)
        new_desc = _fix_mismatch_percentage(desc)

        if new_title != title or new_desc != desc:
            logger.info(
                f"Sanitized mismatch rate in insight: '{title}' -> '{new_title}'",
                extra={
                    "event": "ai_insight_mismatch_rate_sanitized",
                    "actual_rate": actual_rate,
                    "original_title": title,
                },
            )

        sanitized.append(
            AnalysisResult(
                type=r.type,
                severity=r.severity,
                title=new_title,
                description=new_desc,
                affected_count=r.affected_count,
                recommendation=r.recommendation,
            )
        )

    return sanitized


async def _generate_insights_with_fallback(
    analysis_input: AnalysisInput,
    llm_provider: LLMProvider,
    start_time: float,
) -> tuple[list[AnalysisResult], bool, dict | None]:
    """Generate insights with structured output, fallback chain, and schema validation.

    Flow:
    1. Build prompts
    2. Call LLM via provider (AIProviderRouter handles fallback chain)
    3. Parse with structured AIInsight schema validation
    4. Run guardrail validation
    5. Fallback: if schema fails, return rule-based results

    Args:
        analysis_input: Structured input with metrics, groups, anomalies.
        llm_provider: LLM provider (plain provider or AIProviderRouter).
        start_time: Monotonic start time for latency tracking.

    Returns:
        Tuple of (list of AnalysisResult, schema_valid boolean, guardrail_result dict or None).
    """
    try:
        system_prompt = build_system_prompt()
        user_prompt = build_analysis_prompt(analysis_input)

        logger.info(
            f"Calling LLM for {analysis_input.partner} on {analysis_input.date} (focus={analysis_input.focus})",
            extra={
                "event": "ai_insight_request",
                "partner": analysis_input.partner,
                "date": analysis_input.date,
                "focus": analysis_input.focus,
            },
        )

        # If provider is AIProviderRouter, it handles fallback internally.
        # If it's a plain LLMProvider (backward compat), call generate directly.
        if isinstance(llm_provider, AIProviderRouter):
            llm_response = await llm_provider.generate(user_prompt, system_prompt)
        else:
            llm_response = await llm_provider.generate(user_prompt, system_prompt)

        if not llm_response:
            logger.warning("LLM returned no response, falling back to rule-based")
            return _rule_based_fallback(analysis_input), False, None

        # Parse with structured schema validation
        parsed_results, schema_valid = parse_structured_insight(llm_response)

        if not parsed_results:
            logger.warning("LLM returned no parseable findings, falling back to rule-based")
            return _rule_based_fallback(analysis_input), False, None

        # Run guardrail validation: cross-reference LLM claims against input data
        guardrail = validate_insights(analysis_input, parsed_results)
        guardrail_dict: dict | None = guardrail.to_dict() if guardrail.findings else None

        if not guardrail.is_valid:
            logger.warning(
                f"Guardrail rejected {len(guardrail.unsupported_claims)} unsupported claims, "
                f"falling back to rule-based. Risk: {guardrail.risk_level}",
                extra={
                    "event": "ai_insight_guardrail_reject",
                    "unsupported_count": len(guardrail.unsupported_claims),
                    "risk_level": guardrail.risk_level,
                },
            )
            return _rule_based_fallback(analysis_input), schema_valid, guardrail_dict

        if guardrail.warnings:
            logger.info(
                f"Guardrail warnings: {len(guardrail.warnings)}",
                extra={
                    "event": "ai_insight_guardrail_warning",
                    "warning_count": len(guardrail.warnings),
                    "risk_level": guardrail.risk_level,
                },
            )

        # Sanitize: ensure mismatch rate percentages match the computed value
        actual_rate = analysis_input.summary_metrics.get("mismatch_rate", 0)
        parsed_results = _sanitize_mismatch_rate(parsed_results, actual_rate)

        return parsed_results, schema_valid, guardrail_dict

    except Exception as exc:
        logger.warning(
            f"LLM call failed, falling back to rule-based: {exc}",
            extra={"event": "ai_insight_llm_error", "error": str(exc)},
        )
        return _rule_based_fallback(analysis_input), False, None


# ---------------------------------------------------------------------------
# Rule-based fallback — generates insights without LLM
# ---------------------------------------------------------------------------

def _rule_based_fallback(analysis_input: AnalysisInput) -> list[AnalysisResult]:
    """Generate rule-based insights when LLM is unavailable.

    Creates basic AnalysisResult objects from the aggregated data
    without natural language enrichment.

    Args:
        analysis_input: Structured input with metrics, groups, anomalies.

    Returns:
        List of AnalysisResult objects (rule-based only).
    """
    results = []
    metrics = analysis_input.summary_metrics
    focus = analysis_input.focus

    mismatch_rate = metrics.get("mismatch_rate", 0)
    if mismatch_rate > 0:
        severity = "critical" if mismatch_rate > 20 else "high" if mismatch_rate > 10 else "medium" if mismatch_rate > 5 else "low"
        results.append(
            AnalysisResult(
                type="mismatch_rate",
                severity=severity,
                title=f"Mismatch rate: {mismatch_rate}%",
                description=f"Overall mismatch rate is {mismatch_rate}% for {analysis_input.partner} on {analysis_input.date}.",
                affected_count=metrics.get("total_transactions", 0) - metrics.get("matched", 0),
                recommendation="Review mismatched transactions for patterns.",
            )
        )

    for anomaly in analysis_input.top_anomalies:
        severity = "high" if anomaly.count > 10 else "medium" if anomaly.count > 5 else "low"
        results.append(
            AnalysisResult(
                type=anomaly.type,
                severity=severity,
                title=f"Anomalies: {anomaly.count} {anomaly.type.replace('_', ' ')}",
                description=f"Found {anomaly.count} {anomaly.type} anomalies"
                + (f" for partners: {', '.join(anomaly.partners_affected)}" if anomaly.partners_affected else "")
                + (f" in amount range {anomaly.amount_range}" if anomaly.amount_range else ""),
                affected_count=anomaly.count,
                recommendation=f"Investigate {anomaly.type} pattern.",
            )
        )

    by_status = metrics.get("by_status", {})
    missing_internal = by_status.get("MISSING_INTERNAL", 0)
    if missing_internal > 0:
        results.append(
            AnalysisResult(
                type="missing_internal",
                severity="medium" if missing_internal > 5 else "low",
                title=f"Missing Internal: {missing_internal} records",
                description=f"{missing_internal} transactions are MISSING_INTERNAL — internal system has not received data.",
                affected_count=missing_internal,
                recommendation="Check ingestion pipeline for data delivery delays.",
            )
        )

    missing_partner = by_status.get("MISSING_PARTNER", 0)
    if missing_partner > 0:
        results.append(
            AnalysisResult(
                type="missing_partner",
                severity="medium" if missing_partner > 5 else "low",
                title=f"Missing Partner: {missing_partner} records",
                description=f"{missing_partner} transactions are MISSING_PARTNER — partner has not provided data.",
                affected_count=missing_partner,
                recommendation="Contact partner to verify data delivery.",
            )
        )

    return results


# ---------------------------------------------------------------------------
# Provider helpers
# ---------------------------------------------------------------------------

def _get_model_name(llm_provider: LLMProvider) -> str:
    """Get model name from a provider, handling AIProviderRouter wrapper.

    Args:
        llm_provider: LLM provider or AIProviderRouter.

    Returns:
        Model name string, or empty string if unavailable.
    """
    if hasattr(llm_provider, "_primary"):
        return getattr(llm_provider._primary, "model", "")
    return getattr(llm_provider, "model", "")


def _get_last_provider(llm_provider: LLMProvider) -> Optional[LLMProvider]:
    """Get the last used provider from router or return provider directly.

    Args:
        llm_provider: LLM provider or AIProviderRouter.

    Returns:
        LLMProvider instance or None.
    """
    if isinstance(llm_provider, AIProviderRouter):
        return llm_provider.last_provider
    return llm_provider


# Backward-compatible status map for the llm_status response field
_LLM_STATUS_MAP = {
    "llm": "success",
    "llm_fallback": "success",
    "schema_fallback": "fallback",
    "rule_based": "fallback",
}


def _llm_status(resolution: str) -> str:
    """Map internal resolution to backward-compatible llm_status.

    Args:
        resolution: Internal resolution string.

    Returns:
        Backward-compatible status: "success" or "fallback".
    """
    return _LLM_STATUS_MAP.get(resolution, "fallback")


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------

def _resolve_resolution(
    llm_provider: LLMProvider,
    insights: list[AnalysisResult],
    schema_valid: bool,
) -> str:
    """Determine the resolution path for the insight generation.

    Args:
        llm_provider: LLM provider instance.
        insights: Generated insights.
        schema_valid: Whether schema validation passed.

    Returns:
        Resolution string: llm | llm_fallback | schema_fallback | rule_based.
    """
    if not insights:
        return "rule_based"

    if isinstance(llm_provider, AIProviderRouter):
        resolution = llm_provider.resolution
        if resolution in ("llm", "llm_fallback") and not schema_valid:
            return "schema_fallback"
        return resolution

    if not schema_valid:
        return "schema_fallback"

    return "llm"


# ---------------------------------------------------------------------------
# Cache invalidation helper
# ---------------------------------------------------------------------------

async def invalidate_insight_cache(
    partner: str,
    date: str,
    focus: Optional[str] = None,
) -> int:
    """Invalidate AI insight cache entries for a partner.

    Called after re-reconciliation to ensure fresh analysis.

    Args:
        partner: Partner identifier.
        date: Date string.
        focus: Optional focus type to narrow invalidation.

    Returns:
        Number of invalidated entries.
    """
    cache = get_insight_cache()
    if focus:
        key_prefix = f"{partner}:{date}:{focus}:"
        count = 0
        for k in list(cache._store.keys()):
            if k.startswith(key_prefix):
                cache.invalidate(k)
                count += 1
        return count
    return cache.invalidate_by_partner(partner)
