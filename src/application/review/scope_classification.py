"""Application workflow for reviewer-facing reconciliation scope evidence."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import inspect
import json
import logging
import re
from collections.abc import Awaitable, Callable, Iterable
from typing import Any
from uuid import UUID

from src.analysis.config import AnalysisConfig
from src.analysis.provider import create_provider
from src.application.review.evidence import build_internal_review_evidence, business_day_bounds
from src.application.review.raw_stream import resolve_review_source_file
from src.core.enums import ReconciliationScopeType
from src.reconciliation.scope import classify_key_scope

logger = logging.getLogger(__name__)
_SCOPE_LLM_TIMEOUT_SECONDS = 8.0
_VALID_SCOPES = {"FULL_SNAPSHOT", "INCREMENTAL_APPEND", "REPLACEMENT"}


def _scope_probabilities(*, internal_count: int, received_count: int) -> tuple[dict[str, float], str, str]:
    if received_count <= 0:
        return (
            {"FULL_SNAPSHOT": 0.34, "INCREMENTAL_APPEND": 0.33, "REPLACEMENT": 0.33},
            "FULL_SNAPSHOT",
            "No reliable row-count signal was available, so the suggestion stays conservative.",
        )
    if internal_count <= 0:
        return (
            {"FULL_SNAPSHOT": 0.9, "INCREMENTAL_APPEND": 0.07, "REPLACEMENT": 0.03},
            "FULL_SNAPSHOT",
            "There are no same-day internal rows yet, so the incoming file is most likely the day snapshot.",
        )

    larger = max(internal_count, received_count)
    diff = abs(internal_count - received_count)
    diff_ratio = diff / larger if larger > 0 else 0.0
    tolerance = max(10, int(larger * 0.05))
    if diff <= tolerance or diff_ratio <= 0.05:
        return (
            {"FULL_SNAPSHOT": 0.82, "INCREMENTAL_APPEND": 0.14, "REPLACEMENT": 0.04},
            "FULL_SNAPSHOT",
            "Received and internal counts are close enough that a few missing or mismatched rows still fit a full snapshot scenario.",
        )
    if received_count < internal_count * 0.8:
        return (
            {"FULL_SNAPSHOT": 0.18, "INCREMENTAL_APPEND": 0.72, "REPLACEMENT": 0.1},
            "INCREMENTAL_APPEND",
            "The incoming file is materially smaller than the same-day internal population, which is more consistent with a partial append batch.",
        )
    return (
        {"FULL_SNAPSHOT": 0.62, "INCREMENTAL_APPEND": 0.28, "REPLACEMENT": 0.1},
        "FULL_SNAPSHOT",
        "The file does not show strong incremental or replacement signals, so the default recommendation leans toward a full-day snapshot.",
    )


def _normalize_scope_probabilities(raw: object) -> dict[str, float]:
    default = {"FULL_SNAPSHOT": 0.34, "INCREMENTAL_APPEND": 0.33, "REPLACEMENT": 0.33}
    if not isinstance(raw, dict):
        return default
    normalized = {
        scope: float(raw.get(scope, 0.0) or 0.0)
        for scope in ("FULL_SNAPSHOT", "INCREMENTAL_APPEND", "REPLACEMENT")
    }
    total = sum(max(value, 0.0) for value in normalized.values())
    if total <= 0:
        return default
    return {scope: max(value, 0.0) / total for scope, value in normalized.items()}


def _apply_scope_guardrails(
    *,
    ai_scope: str,
    ai_probabilities: dict[str, float],
    ai_reasoning: str,
    heuristic_scope: str,
    heuristic_probabilities: dict[str, float],
    heuristic_reasoning: str,
    internal_count: int,
    received_count: int,
) -> tuple[dict[str, float], str, str, str]:
    larger = max(internal_count, received_count, 1)
    diff = abs(internal_count - received_count)
    diff_ratio = diff / larger
    if ai_scope == "INCREMENTAL_APPEND" and (
        (larger >= 10_000 and diff_ratio <= 0.05)
        or (larger >= 100_000 and diff <= max(10, int(larger * 0.01)))
    ):
        return (
            heuristic_probabilities,
            heuristic_scope,
            (
                f"{ai_reasoning} Guardrail override applied: count gap is too small relative to file size "
                "to treat this as a confident append-only batch."
            ).strip(),
            "guardrail_override_small_gap",
        )
    return ai_probabilities, ai_scope, ai_reasoning, "llm"


def _column_index(column: object) -> int | None:
    if isinstance(column, int):
        return column - 1 if column > 0 else None
    if not isinstance(column, str):
        return None
    value = column.strip().upper()
    if value.isdigit():
        number = int(value)
        return number - 1 if number > 0 else None
    if not value.isalpha():
        return None
    index = 0
    for character in value:
        index = index * 26 + ord(character) - ord("A") + 1
    return index - 1


def _scope_mapping_columns(config: object, structure_signature: dict | None = None) -> dict[str, object] | None:
    mappings = getattr(config, "field_mappings", None) or []
    columns: dict[str, object] = {}
    for mapping in mappings:
        path = str(getattr(mapping, "path", "")).strip().lower()
        field_name = path.rsplit(".", 1)[-1]
        if field_name not in {"id", "trace", "vsptransid"}:
            continue
        column = getattr(mapping, "column", None)
        if column is not None:
            columns[field_name] = column
    if columns:
        return columns

    headers = (structure_signature or {}).get("headers") or []
    preferred_tokens = (
        "mstransid",
        "transactionid",
        "transid",
        "trace",
        "partnerid",
        "invoice",
        "reference",
    )
    for index, header in enumerate(headers):
        normalized = "".join(character for character in str(header).lower() if character.isalnum())
        if any(token in normalized for token in preferred_tokens):
            return {"trace": index + 1}
    return None


def _extract_scope_keys(
    rows: Iterable[Any],
    config: object,
    structure_signature: dict | None = None,
) -> tuple[int, set[str]]:
    columns = _scope_mapping_columns(config, structure_signature)
    received_count = 0
    keys: set[str] = set()
    for row in rows:
        received_count += 1
        if columns is None:
            continue
        values: dict[str, str] = {}
        for name, column in columns.items():
            if isinstance(row, dict):
                value = row.get(column)
                if value is None and isinstance(column, int):
                    value = row.get(str(column))
                if value is None and isinstance(column, str) and column.isdigit():
                    value = row.get(int(column))
            else:
                index = _column_index(column)
                value = row[index] if index is not None and index < len(row) else None
            if value is not None and str(value).strip():
                values[name] = str(value).strip()
        key = values.get("trace") or values.get("vsptransid") or values.get("id")
        if key:
            keys.add(key)
    return received_count, keys


async def _default_received_evidence(db, packet) -> tuple[int, set[str]]:
    if packet.raw_stage_key:
        try:
            cursor = db["raw_ingestion_page"].find(
                {
                    "partner": packet.partner,
                    "stageKey": packet.raw_stage_key,
                    "status": {"$in": ["STAGED", "CONSUMED"]},
                },
                projection={"itemCount": 1},
            )
            documents = await cursor.to_list(length=None)
            if documents:
                return sum(int(document.get("itemCount") or 0) for document in documents), set()
        except Exception:
            logger.debug("Could not load raw stage count", exc_info=True)

    try:
        source_path = resolve_review_source_file(packet)
        config = None
        if packet.draft_mapping_id:
            from src.infrastructure.mapping.config_repository import MappingConfigRepository
            from src import readers

            config = await MappingConfigRepository(db).find_one({"_id": packet.draft_mapping_id})
        if config is not None:
            with readers.create_reader(source_path, config) as reader:
                return _extract_scope_keys(
                    reader.iter_rows(), config, packet.structure_signature
                )
        sample_rows = (packet.structure_signature or {}).get("sampleRows") or []
        return len(sample_rows), set()
    except Exception:
        logger.warning("Could not inspect review source file", exc_info=True)
        sample_rows = (packet.structure_signature or {}).get("sampleRows") or []
        return len(sample_rows), set()


async def _default_existing_keys(db, packet, start_of_day, end_of_day, incoming_keys: set[str]) -> set[str]:
    if not incoming_keys:
        return set()
    source_file_id = None
    if packet.source_file_id:
        try:
            source_file_id = UUID(str(packet.source_file_id))
        except (ValueError, TypeError):
            logger.warning("Ignoring invalid review packet source_file_id=%s", packet.source_file_id)
    try:
        from src.infrastructure.partner_transaction.repository import DataContainerRepository

        return await DataContainerRepository(db).find_reconciliation_keys_by_date_range(
            packet.partner,
            start_of_day,
            end_of_day,
            exclude_source_file_id=source_file_id,
        )
    except Exception:
        logger.warning("Could not load existing reconciliation keys", exc_info=True)
        return set()


async def _default_prior_file_count(db, packet, start_of_day, end_of_day) -> int:
    try:
        result = db["reconciliation_file"].count_documents(
            {
                "partner": packet.partner,
                "reconciliationDate": {"$gte": start_of_day, "$lte": end_of_day},
            }
        )
        return int(await result if hasattr(result, "__await__") else result)
    except Exception:
        logger.warning("Could not count prior reconciliation files", exc_info=True)
        return 0


@dataclass(frozen=True)
class ScopeClassificationCommand:
    packet_id: str
    force: bool = False


class ScopeClassificationService:
    """Classify scope using deterministic key evidence and optional LLM reasoning."""

    def __init__(
        self,
        *,
        db,
        packet_repo,
        internal_count_loader: Callable[..., Awaitable[int]] | None = None,
        internal_evidence_builder: Callable[..., Awaitable[dict[str, Any]]] = build_internal_review_evidence,
        received_evidence_loader: Callable[..., Awaitable[tuple[int, set[str]]]] | None = None,
        existing_keys_loader: Callable[..., Awaitable[set[str]]] | None = None,
        prior_file_count_loader: Callable[..., Awaitable[int]] | None = None,
        llm_provider_factory: Callable[[AnalysisConfig], Any] = create_provider,
        analysis_config: AnalysisConfig | None = None,
        llm_timeout_seconds: float = _SCOPE_LLM_TIMEOUT_SECONDS,
    ) -> None:
        self.db = db
        self.packet_repo = packet_repo
        self.internal_count_loader = internal_count_loader or self._default_internal_count
        self.internal_evidence_builder = internal_evidence_builder
        self.received_evidence_loader = received_evidence_loader or (
            lambda packet: _default_received_evidence(self.db, packet)
        )
        self.existing_keys_loader = existing_keys_loader or (
            lambda packet, start, end, keys: _default_existing_keys(
                self.db, packet, start, end, keys
            )
        )
        self.prior_file_count_loader = prior_file_count_loader or (
            lambda packet, start, end: _default_prior_file_count(self.db, packet, start, end)
        )
        self.llm_provider_factory = llm_provider_factory
        self.analysis_config = analysis_config or AnalysisConfig()
        self.llm_timeout_seconds = llm_timeout_seconds

    async def classify(self, command: ScopeClassificationCommand) -> dict[str, Any]:
        packet = await self.packet_repo.find_one({"_id": command.packet_id})
        if packet is None:
            raise ValueError("Review packet not found.")

        reconciliation_date = self._resolve_date(packet)
        start_of_day, end_of_day = business_day_bounds(reconciliation_date)
        internal_count = await self.internal_count_loader(
            packet.partner, start_of_day, end_of_day
        )
        internal_evidence = await self.internal_evidence_builder(
            self.db,
            partner=packet.partner,
            reconciliation_date=reconciliation_date,
            record_count=internal_count,
            repository=self._internal_repository()(self.db),
        )
        persist_result = self.packet_repo.update_scope_evidence(
            packet_id=command.packet_id,
            internal_record_count=internal_evidence["recordCount"],
            internal_preview=internal_evidence["sample"],
        )
        if inspect.isawaitable(persist_result):
            await persist_result

        received_count, incoming_keys = await self.received_evidence_loader(packet)
        existing_keys = await self.existing_keys_loader(
            packet, start_of_day, end_of_day, incoming_keys
        )
        duplicate_keys = incoming_keys & existing_keys
        new_keys = incoming_keys - existing_keys
        incoming_key_count = len(incoming_keys)
        duplicate_ratio = len(duplicate_keys) / incoming_key_count if incoming_key_count else 0.0
        prior_file_count = await self.prior_file_count_loader(
            packet, start_of_day, end_of_day
        )
        key_scope = classify_key_scope(
            incoming_keys=incoming_keys,
            historical_keys=existing_keys,
            prior_file_count=prior_file_count,
        )
        key_scope_type = key_scope["scopeType"]
        deterministic = bool(incoming_keys) and key_scope_type != ReconciliationScopeType.UNCONFIRMED.value
        heuristic_probabilities, heuristic_scope, heuristic_reasoning = _scope_probabilities(
            internal_count=internal_count,
            received_count=received_count,
        )
        if deterministic:
            heuristic_scope = key_scope_type
            heuristic_reasoning = key_scope["scopeReason"][0]
            heuristic_probabilities = {
                scope: 1.0 if scope == key_scope_type else 0.0
                for scope in _VALID_SCOPES
            }

        resolution = "rule_based_key_evidence" if deterministic else "rule_based"
        probabilities = heuristic_probabilities
        suggested_scope = heuristic_scope
        reasoning = heuristic_reasoning
        if not deterministic:
            provider = self.llm_provider_factory(self.analysis_config)
            if provider is not None:
                response_text, llm_resolution = await self._generate_llm(
                    provider,
                    packet,
                    internal_count,
                    received_count,
                    incoming_key_count,
                    len(duplicate_keys),
                    len(new_keys),
                    heuristic_scope,
                    heuristic_reasoning,
                )
                if llm_resolution:
                    resolution = llm_resolution
                if response_text:
                    probabilities, suggested_scope, reasoning, resolution = self._parse_llm(
                        response_text=response_text,
                        heuristic_scope=heuristic_scope,
                        heuristic_probabilities=heuristic_probabilities,
                        heuristic_reasoning=heuristic_reasoning,
                        internal_count=internal_count,
                        received_count=received_count,
                    )

        return {
            "ok": True,
            "internalDbRecordCount": internal_count,
            "internalPreview": internal_evidence["sample"],
            "receivedRecordCount": received_count,
            "probabilities": probabilities,
            "suggestedScope": suggested_scope,
            "reasoning": reasoning,
            "resolution": resolution,
            "scopeEvidence": {
                "incomingUniqueBusinessKeyCount": incoming_key_count,
                "duplicateBusinessKeyCount": len(duplicate_keys),
                "newBusinessKeyCount": len(new_keys),
                "duplicateRatio": duplicate_ratio,
                "historicalCoverage": key_scope["scopeSignals"].get("historicalCoverage", 0.0),
                "newRatio": key_scope["scopeSignals"].get("newRatio", 0.0),
                "ruleBasedScope": key_scope_type,
                "available": bool(incoming_keys),
            },
            "heuristicBaseline": {
                "suggestedScope": heuristic_scope,
                "probabilities": heuristic_probabilities,
                "reasoning": heuristic_reasoning,
            },
        }

    async def _default_internal_count(self, partner, start_of_day, end_of_day) -> int:
        return await self._internal_repository()(self.db).count_by_partner_and_date_range(
            partner, start_of_day, end_of_day
        )

    @staticmethod
    def _internal_repository():
        from src.infrastructure.postgres.internal_transaction_repository import InternalTransactionRepository

        return InternalTransactionRepository

    async def _generate_llm(
        self,
        provider,
        packet,
        internal_count: int,
        received_count: int,
        incoming_key_count: int,
        duplicate_key_count: int,
        new_key_count: int,
        heuristic_scope: str,
        heuristic_reasoning: str,
    ) -> tuple[str | None, str | None]:
        prompt = f"""Decide the most likely reconciliation file scope.

Valid classes: FULL_SNAPSHOT, INCREMENTAL_APPEND, REPLACEMENT.
Use business-key overlap and historical coverage as primary evidence.
Partner: {packet.partner}
Received Record Count: {received_count}
Internal DB Record Count: {internal_count}
Incoming Unique Business Key Count: {incoming_key_count}
Keys Already Present In DB: {duplicate_key_count}
New Business Keys: {new_key_count}
Heuristic Baseline Suggestion: {heuristic_scope}
Heuristic Baseline Reasoning: {heuristic_reasoning}

Return JSON with probabilities, suggested_scope, and reasoning."""
        try:
            return await asyncio.wait_for(
                provider.generate(
                    prompt=prompt,
                    system_prompt=(
                        "You are an expert reconciliation analyst. "
                        "Classify file scope for review workflow. Return valid JSON only."
                    ),
                ),
                timeout=min(float(self.analysis_config.timeout), self.llm_timeout_seconds),
            ), None
        except asyncio.TimeoutError:
            logger.warning("Scope classification LLM timed out; returning heuristic result")
            return None, "rule_based_timeout"

    @staticmethod
    def _parse_llm(
        *,
        response_text: str,
        heuristic_scope: str,
        heuristic_probabilities: dict[str, float],
        heuristic_reasoning: str,
        internal_count: int,
        received_count: int,
    ) -> tuple[dict[str, float], str, str, str]:
        try:
            clean_text = response_text.strip()
            if clean_text.startswith("```"):
                parts = clean_text.split("```")
                if len(parts) >= 3:
                    clean_text = parts[1]
                    if clean_text.startswith("json"):
                        clean_text = clean_text[4:]
            parsed = json.loads(clean_text.strip())
            probabilities = _normalize_scope_probabilities(parsed.get("probabilities"))
            suggested_scope = str(parsed.get("suggested_scope") or heuristic_scope).strip().upper()
            if suggested_scope not in _VALID_SCOPES:
                suggested_scope = heuristic_scope
            reasoning = str(parsed.get("reasoning") or heuristic_reasoning).strip()
            return _apply_scope_guardrails(
                ai_scope=suggested_scope,
                ai_probabilities=probabilities,
                ai_reasoning=reasoning,
                heuristic_scope=heuristic_scope,
                heuristic_probabilities=heuristic_probabilities,
                heuristic_reasoning=heuristic_reasoning,
                internal_count=internal_count,
                received_count=received_count,
            )
        except Exception as exc:
            logger.warning("Scope classification JSON parse failed: %s", exc)
            return heuristic_probabilities, heuristic_scope, heuristic_reasoning, "rule_based_parse_error"

    @staticmethod
    def _resolve_date(packet) -> datetime:
        reconciliation_date = getattr(packet, "reconciliation_date", None)
        if reconciliation_date:
            return reconciliation_date
        match = re.search(r"(\d{4})[-_]?([0-9]{2})[-_]?([0-9]{2})", packet.file_name)
        if match:
            try:
                return datetime.strptime(
                    f"{match.group(1)}-{match.group(2)}-{match.group(3)}",
                    "%Y-%m-%d",
                ).replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        return datetime.now(timezone.utc)
