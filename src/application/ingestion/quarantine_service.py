"""Application orchestration for one quarantine record lifecycle."""

import inspect
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from src.application.ingestion.contracts import serialize_quarantine_counters
from src.application.ingestion.quarantine_reprocessing import (
    QuarantineReprocessMode,
    QuarantineReprocessRequest,
    resolve_reprocess_input,
)
from src.domain.ingestion.quarantine import (
    IngestionQuarantineRecord,
    QuarantineAction,
    QuarantineStatus,
)


@dataclass(frozen=True, slots=True)
class QuarantineResolutionResult:
    """Bounded outcome returned by the single-record resolution use case."""

    record_id: str
    success: bool
    status: QuarantineStatus | None
    outcome: str
    action: QuarantineAction
    reason: str | None = None
    errors: list[dict[str, Any]] = field(default_factory=list)
    quality_counters: dict[str, int] = field(default_factory=dict)
    failure_classification: str | None = None


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _action_for(mode: QuarantineReprocessMode) -> QuarantineAction:
    if mode is QuarantineReprocessMode.ACCEPT_EXISTING:
        return QuarantineAction.ACCEPT_EXISTING
    if mode is QuarantineReprocessMode.REJECT:
        return QuarantineAction.REJECT
    return QuarantineAction.REPROCESS


def _record_id(record: IngestionQuarantineRecord | None, request: QuarantineReprocessRequest) -> str:
    return str(getattr(record, "id", None) or request.record_id)


def _processing_error(value: Any) -> str:
    text = str(value).strip() if value is not None else ""
    return text[:500] if text else "Quarantine reprocess failed."


def _record_error_code(record: IngestionQuarantineRecord) -> str:
    for error in record.errors:
        if isinstance(error, Mapping):
            code = error.get("errorCode") or error.get("error_code") or error.get("code")
            if code:
                return str(code)
    return "UNSPECIFIED"


def _operation_counters(outcome: str) -> dict[str, int]:
    persisted, rejected, duplicate, failed = {
        "VALIDATION_FAILED": (0, 1, 0, 0),
        "CONFLICT_REMAINS": (0, 0, 1, 0),
        "EQUIVALENT_DUPLICATE": (0, 0, 1, 0),
        "ACCEPTED_EXISTING": (0, 0, 1, 0),
        "RETRYABLE_FAILURE": (0, 0, 0, 1),
        "REJECTED": (0, 1, 0, 0),
    }.get(outcome, (1, 0, 0, 0))
    return serialize_quarantine_counters(
        input_rows=1,
        persisted_rows=persisted,
        rejected_rows=rejected,
        duplicate_rows=duplicate,
        failed_rows=failed,
        quarantined_rows=0,
    )


class QuarantineResolutionService:
    """Claim, process, and resolve one quarantine record exactly once."""

    def __init__(
        self,
        quarantine_repo: Any,
        source_file_repo: Any,
        raw_page_repo: Any,
        *,
        row_processor: Any | None = None,
        row_processor_factory: Any | None = None,
        persist_row: Any | None = None,
        transaction_repo: Any | None = None,
        existing_fingerprint_reader: Any | None = None,
        audit_recorder: Any | None = None,
    ) -> None:
        self._quarantine_repo = quarantine_repo
        self._source_file_repo = source_file_repo
        self._raw_page_repo = raw_page_repo
        self._row_processor = row_processor
        self._row_processor_factory = row_processor_factory
        self._persist_row = persist_row
        self._transaction_repo = transaction_repo
        self._existing_fingerprint_reader = existing_fingerprint_reader
        self._audit_recorder = audit_recorder

    async def _emit_audit(
        self,
        action: str,
        record: IngestionQuarantineRecord,
        *,
        actor: str,
        reason: str,
    ) -> None:
        if self._audit_recorder is None:
            return
        bounded_reason = reason.strip()[:500]
        metadata = {
            "recordId": str(record.id),
            "partner": record.partner,
            "sourceFileId": record.source_file_id,
            "sourceUnitKey": record.source_unit_key,
            "errorCode": _record_error_code(record),
            "attempt": record.attempt_count,
            "actor": actor,
            "reason": bounded_reason,
        }
        await _maybe_await(
            self._audit_recorder(
                entity_type="INGESTION_QUARANTINE",
                entity_id=str(record.id),
                action=action,
                actor=actor,
                metadata=metadata,
            )
        )

    async def resolve(
        self,
        request: QuarantineReprocessRequest,
    ) -> QuarantineResolutionResult:
        action = _action_for(request.mode)
        if request.mode is QuarantineReprocessMode.REJECT and not (request.reason or "").strip():
            return QuarantineResolutionResult(
                record_id=request.record_id,
                success=False,
                status=None,
                outcome="REASON_REQUIRED",
                action=action,
                reason="Operator reason is required for rejection.",
            )

        claimed = await self._quarantine_repo.claim(
            request.record_id,
            request.operator_id,
        )
        if claimed is None:
            return QuarantineResolutionResult(
                record_id=request.record_id,
                success=False,
                status=None,
                outcome="CLAIM_NOT_ACQUIRED",
                action=action,
                reason="Quarantine record is not pending or is already claimed.",
            )

        await self._emit_audit(
            "QUARANTINE_CLAIMED",
            claimed,
            actor=request.operator_id,
            reason="Quarantine record claimed for resolution.",
        )

        if request.mode is QuarantineReprocessMode.REJECT:
            reason = (request.reason or "").strip()
            return await self._terminal_resolve(
                claimed,
                request,
                target=QuarantineStatus.REJECTED,
                action=QuarantineAction.REJECT,
                reason=reason,
                metadata={},
                outcome="REJECTED",
                failure_classification="TERMINAL_OPERATOR_REJECTION",
            )

        if request.mode is QuarantineReprocessMode.ACCEPT_EXISTING:
            return await self._accept_existing(claimed, request)

        try:
            resolved_input = await resolve_reprocess_input(
                claimed,
                request,
                self._source_file_repo,
                self._raw_page_repo,
            )
        except ValueError as exc:
            return await self._release(
                claimed,
                request,
                reason=str(exc),
                outcome="INPUT_UNAVAILABLE",
            )

        try:
            row_processor = self._row_processor
            if row_processor is None and self._row_processor_factory is not None:
                row_processor = await _maybe_await(
                    self._row_processor_factory(claimed, request)
                )
            processed = await self._process(
                resolved_input.row,
                resolved_input.row_number,
                row_processor=row_processor,
            )
        except Exception as exc:
            return await self._release(
                claimed,
                request,
                reason=_processing_error(exc),
                outcome="RETRYABLE_FAILURE",
                failure_classification="RETRYABLE_INFRASTRUCTURE",
            )

        valid, data_container, errors = self._processed_payload(processed)
        if not valid or data_container is None:
            reason = self._first_error(errors) or "Deterministic row validation failed."
            return await self._release(
                claimed,
                request,
                reason=reason,
                metadata={"errors": errors},
                outcome="VALIDATION_FAILED",
                errors=errors,
            )

        try:
            write_result = await self._persist(data_container)
        except Exception as exc:
            return await self._release(
                claimed,
                request,
                reason=_processing_error(exc),
                outcome="RETRYABLE_FAILURE",
                failure_classification="RETRYABLE_INFRASTRUCTURE",
            )

        conflicting = int(getattr(write_result, "conflicting_duplicates", 0) or 0)
        equivalent = int(getattr(write_result, "equivalent_duplicates", 0) or 0)
        if isinstance(write_result, Mapping):
            conflicting = int(write_result.get("conflicting_duplicates", 0) or 0)
            equivalent = int(write_result.get("equivalent_duplicates", 0) or 0)
        if conflicting > 0:
            return await self._release(
                claimed,
                request,
                reason="Reprocessed row still conflicts with an existing transaction.",
                metadata={"conflictingDuplicates": conflicting},
                outcome="CONFLICT_REMAINS",
            )
        if int(getattr(write_result, "failed", 0) or 0) > 0:
            return await self._release(
                claimed,
                request,
                reason="Transaction persistence reported a failed write.",
                outcome="RETRYABLE_FAILURE",
                failure_classification="RETRYABLE_INFRASTRUCTURE",
            )

        outcome = "EQUIVALENT_DUPLICATE" if equivalent > 0 else "RESOLVED"
        reason = (
            "Reprocess produced an equivalent existing transaction."
            if equivalent > 0
            else "Quarantine row reprocessed successfully."
        )
        return await self._terminal_resolve(
            claimed,
            request,
            target=QuarantineStatus.RESOLVED,
            action=QuarantineAction.REPROCESS,
            reason=reason,
            metadata={
                "origin": resolved_input.origin,
                "mappingVersion": resolved_input.mapping_version,
            },
            outcome=outcome,
        )

    async def _accept_existing(
        self,
        claimed: IngestionQuarantineRecord,
        request: QuarantineReprocessRequest,
    ) -> QuarantineResolutionResult:
        reader = self._existing_fingerprint_reader
        if reader is None and self._transaction_repo is not None:
            reader = getattr(self._transaction_repo, "find_existing_fingerprint", None)
        if reader is None:
            return await self._release(
                claimed,
                request,
                reason="Existing transaction fingerprint could not be verified.",
                outcome="FINGERPRINT_UNAVAILABLE",
            )
        try:
            current = await _maybe_await(reader(claimed))
        except Exception as exc:
            return await self._release(
                claimed,
                request,
                reason=_processing_error(exc),
                outcome="RETRYABLE_FAILURE",
                failure_classification="RETRYABLE_INFRASTRUCTURE",
            )
        if isinstance(current, Mapping):
            current = current.get("fingerprint") or current.get("existingFingerprint")
        if not current or current != claimed.existing_fingerprint:
            return await self._release(
                claimed,
                request,
                reason="Existing transaction fingerprint no longer matches quarantine evidence.",
                outcome="FINGERPRINT_MISMATCH",
            )
        return await self._terminal_resolve(
            claimed,
            request,
            target=QuarantineStatus.RESOLVED,
            action=QuarantineAction.ACCEPT_EXISTING,
            reason="Existing transaction fingerprint accepted by operator.",
            metadata={"existingFingerprint": current},
            outcome="ACCEPTED_EXISTING",
        )

    async def _process(
        self,
        row: Any,
        row_number: int | None,
        *,
        row_processor: Any | None = None,
    ) -> Any:
        processor_instance = row_processor or self._row_processor
        if processor_instance is None:
            raise RuntimeError("Quarantine reprocess has no shared row processor")
        processor = getattr(processor_instance, "process", processor_instance)
        return await _maybe_await(processor(row, row_number or 1))

    async def _persist(self, data_container: Any) -> Any:
        if self._persist_row is not None:
            return await _maybe_await(self._persist_row(data_container))
        if self._transaction_repo is None:
            raise RuntimeError("Quarantine reprocess has no transaction writer")
        return await self._transaction_repo.insert_many([data_container], ordered=True)

    @staticmethod
    def _processed_payload(processed: Any) -> tuple[bool, Any, list[dict[str, Any]]]:
        if isinstance(processed, Mapping):
            valid = bool(processed.get("is_valid", processed.get("valid", processed.get("success"))))
            data_container = processed.get("data_container", processed.get("dataContainer"))
            errors = list(processed.get("errors") or [])
            return valid, data_container, errors
        valid = bool(getattr(processed, "is_valid", False))
        data_container = getattr(processed, "data_container", None)
        errors = list(getattr(processed, "errors", []) or [])
        return valid, data_container, errors

    @staticmethod
    def _first_error(errors: list[Any]) -> str | None:
        for error in errors:
            if isinstance(error, Mapping):
                value = error.get("reason") or error.get("message") or error.get("error")
                if value:
                    return str(value)
            elif error:
                return str(error)
        return None

    async def _release(
        self,
        claimed: IngestionQuarantineRecord,
        request: QuarantineReprocessRequest,
        *,
        reason: str,
        metadata: dict[str, Any] | None = None,
        outcome: str,
        errors: list[dict[str, Any]] | None = None,
        failure_classification: str = "DETERMINISTIC_RESOLUTION_FAILURE",
    ) -> QuarantineResolutionResult:
        released = await self._quarantine_repo.release_for_retry(
            request.record_id,
            request.operator_id,
            reason,
            metadata or {},
        )
        if released:
            await self._emit_audit(
                "QUARANTINE_RETRY_SCHEDULED",
                claimed,
                actor=request.operator_id,
                reason=reason,
            )
        return QuarantineResolutionResult(
            record_id=_record_id(claimed, request),
            success=False,
            status=QuarantineStatus.PENDING if released else QuarantineStatus.REPROCESSING,
            outcome=outcome,
            action=_action_for(request.mode),
            reason=reason,
            errors=errors or [],
            quality_counters=_operation_counters(outcome),
            failure_classification=failure_classification,
        )

    async def _terminal_resolve(
        self,
        claimed: IngestionQuarantineRecord,
        request: QuarantineReprocessRequest,
        *,
        target: QuarantineStatus,
        action: QuarantineAction,
        reason: str,
        metadata: dict[str, Any],
        outcome: str,
        failure_classification: str | None = None,
        quality_counters: dict[str, int] | None = None,
    ) -> QuarantineResolutionResult:
        resolved = await self._quarantine_repo.resolve(
            request.record_id,
            target,
            request.operator_id,
            action,
            reason,
            metadata,
        )
        if resolved:
            audit_action = {
                QuarantineAction.REPROCESS: "QUARANTINE_REPROCESSED",
                QuarantineAction.ACCEPT_EXISTING: "QUARANTINE_ACCEPTED_EXISTING",
                QuarantineAction.REJECT: "QUARANTINE_REJECTED",
            }[action]
            await self._emit_audit(
                audit_action,
                claimed,
                actor=request.operator_id,
                reason=reason,
            )
        return QuarantineResolutionResult(
            record_id=_record_id(claimed, request),
            success=resolved,
            status=target if resolved else QuarantineStatus.REPROCESSING,
            outcome=outcome if resolved else "RESOLUTION_CONFLICT",
            action=action,
            reason=reason,
            quality_counters=quality_counters or _operation_counters(outcome),
            failure_classification=failure_classification,
        )


__all__ = ["QuarantineResolutionResult", "QuarantineResolutionService"]
