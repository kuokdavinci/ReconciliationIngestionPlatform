"""Application orchestration for one quarantine record lifecycle."""

import asyncio
import inspect
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
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
    QuarantinePriority,
    QuarantineResolutionEvent,
    QuarantineStatus,
)
from src.domain.ingestion.ports import (
    IngestionQuarantineRepositoryPort,
    QuarantineRowReader,
)


# ponytail: one process-wide lock per action; use a distributed reservation if workers span processes.
_ACTION_LOCKS: dict[tuple[int, str, str], asyncio.Lock] = {}
_ACTION_LOCKS_GUARD = threading.Lock()


def _action_lock(record_id: str, action_id: str) -> asyncio.Lock:
    key = (id(asyncio.get_running_loop()), record_id, action_id)
    with _ACTION_LOCKS_GUARD:
        return _ACTION_LOCKS.setdefault(key, asyncio.Lock())


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
    action_id: str | None = None
    previous_status: QuarantineStatus | None = None
    attempt_count: int | None = None
    source_evidence_available: bool | None = None
    escalation_level: int | None = None
    claimed_by: str | None = None
    priority: QuarantinePriority | None = None
    review_due_at: datetime | None = None


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
    del value
    return "Quarantine reprocess dependency failed."


def _record_error_code(record: IngestionQuarantineRecord) -> str:
    for error in record.errors:
        if isinstance(error, Mapping):
            code = error.get("errorCode") or error.get("error_code") or error.get("code")
            if code:
                return str(code)
    return "UNSPECIFIED"


def _claim_expired(record: IngestionQuarantineRecord) -> bool:
    expiration = record.claim_expires_at
    if not isinstance(expiration, datetime):
        return False
    if expiration.tzinfo is None:
        expiration = expiration.replace(tzinfo=UTC)
    return expiration.astimezone(UTC) <= datetime.now(UTC)


def _operation_counters(outcome: str) -> dict[str, int]:
    persisted, rejected, duplicate, failed = {
        "VALIDATION_FAILED": (0, 1, 0, 0),
        "CONFLICT_REMAINS": (0, 0, 1, 0),
        "EQUIVALENT_DUPLICATE": (0, 0, 1, 0),
        "ACCEPTED_EXISTING": (0, 0, 1, 0),
        "RETRYABLE_FAILURE": (0, 0, 0, 1),
        "SOURCE_EVIDENCE_UNAVAILABLE": (0, 0, 0, 1),
        "CORRECTED_ROW_REQUIRED": (0, 0, 0, 1),
        "FINGERPRINT_MISMATCH": (0, 0, 0, 1),
        "FINGERPRINT_UNAVAILABLE": (0, 0, 0, 1),
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


def _event_from_value(value: Any) -> QuarantineResolutionEvent | None:
    if isinstance(value, QuarantineResolutionEvent):
        return value
    if isinstance(value, Mapping):
        try:
            return QuarantineResolutionEvent.model_validate(value)
        except ValueError:
            return None
    return None


def _event_success(event: QuarantineResolutionEvent) -> bool:
    return event.to_status in {
        QuarantineStatus.RESOLVED,
        QuarantineStatus.REJECTED,
    } or event.outcome in {"CLAIMED", "ESCALATED"}


def _event_due_at(event: QuarantineResolutionEvent) -> datetime | None:
    if not isinstance(event.metadata, Mapping):
        return None
    value = event.metadata.get("reviewDueAt")
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _result_from_event(
    record_id: str,
    event: QuarantineResolutionEvent,
) -> "QuarantineResolutionResult":
    outcome = event.outcome or event.action.value
    return QuarantineResolutionResult(
        record_id=record_id,
        success=_event_success(event),
        status=event.to_status,
        outcome=outcome,
        action=event.action,
        reason=event.reason,
        quality_counters=(
            {}
            if outcome in {"CLAIMED", "ESCALATED"}
            else _operation_counters(outcome)
        ),
        action_id=event.action_id,
        previous_status=event.from_status,
        attempt_count=event.attempt,
        source_evidence_available=(
            event.metadata.get("sourceEvidenceAvailable")
            if isinstance(event.metadata, Mapping)
            else None
        ),
        escalation_level=(
            event.metadata.get("escalationLevel")
            if isinstance(event.metadata, Mapping)
            else None
        ),
        claimed_by=(
            event.metadata.get("claimedBy")
            if isinstance(event.metadata, Mapping)
            else None
        ),
        priority=(
            QuarantinePriority(event.metadata["priority"])
            if isinstance(event.metadata, Mapping)
            and event.metadata.get("priority") in {item.value for item in QuarantinePriority}
            else None
        ),
        review_due_at=_event_due_at(event),
    )


class QuarantineResolutionService:
    """Claim, process, and resolve one quarantine record exactly once."""

    def __init__(
        self,
        quarantine_repo: IngestionQuarantineRepositoryPort,
        source_file_repo: QuarantineRowReader,
        raw_page_repo: QuarantineRowReader,
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
        action_id: str | None = None,
        previous_status: QuarantineStatus | None = None,
        new_status: QuarantineStatus | None = None,
        outcome: str | None = None,
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
        if action_id is not None:
            metadata["actionId"] = action_id
        if previous_status is not None:
            metadata["previousStatus"] = previous_status.value
        if new_status is not None:
            metadata["newStatus"] = new_status.value
        if outcome is not None:
            metadata["outcome"] = outcome
        await _maybe_await(
            self._audit_recorder(
                entity_type="INGESTION_QUARANTINE",
                entity_id=str(record.id),
                action=action,
                actor=actor,
                metadata=metadata,
            )
        )

    async def _find_action(self, record_id: str, action_id: str) -> QuarantineResolutionEvent | None:
        finder = getattr(self._quarantine_repo, "find_action", None)
        if finder is None:
            return None
        return _event_from_value(await _maybe_await(finder(record_id, action_id)))

    async def _reserve_action(
        self,
        record_id: str,
        operator_id: str,
        action_id: str,
        action: QuarantineAction,
    ) -> str | None:
        reserver = getattr(self._quarantine_repo, "reserve_action", None)
        if not callable(reserver) or not inspect.iscoroutinefunction(reserver):
            return None
        return str(
            await reserver(
                record_id,
                operator_id,
                action_id,
                action,
            )
        )

    async def _replayed_action(
        self,
        record_id: str,
        action_id: str,
        operator_id: str,
        action: QuarantineAction,
        *,
        expected_outcome: str | None = None,
    ) -> QuarantineResolutionResult | None:
        event = await self._find_action(record_id, action_id)
        if event is None:
            return None
        action_mismatch = event.actor != operator_id or event.action is not action
        if expected_outcome is not None:
            action_mismatch = action_mismatch or event.outcome != expected_outcome
        elif action is QuarantineAction.REPROCESS and event.outcome == "CLAIMED":
            action_mismatch = True
        if action_mismatch:
            return QuarantineResolutionResult(
                record_id=record_id,
                success=False,
                status=event.to_status,
                outcome="ACTION_ID_REUSE_CONFLICT",
                action=action,
                reason="Action ID was already used by another operator action.",
                action_id=action_id,
                previous_status=event.from_status,
                attempt_count=event.attempt,
            )
        return _result_from_event(record_id, event)

    @staticmethod
    def _missing_record(record_id: str, action: QuarantineAction) -> QuarantineResolutionResult:
        return QuarantineResolutionResult(
            record_id=record_id,
            success=False,
            status=None,
            outcome="RECORD_NOT_FOUND",
            action=action,
            reason="Quarantine record was not found.",
        )

    @staticmethod
    def _stale_record(
        record: IngestionQuarantineRecord,
        action: QuarantineAction,
    ) -> QuarantineResolutionResult:
        return QuarantineResolutionResult(
            record_id=str(record.id),
            success=False,
            status=record.status,
            outcome="STALE_STATUS",
            action=action,
            reason="Quarantine record status no longer matches the expected status.",
            previous_status=record.status,
            attempt_count=record.attempt_count,
            escalation_level=record.escalation_level,
        )

    async def claim(
        self,
        record_id: str,
        operator_id: str,
        action_id: str,
        expected_status: QuarantineStatus,
    ) -> QuarantineResolutionResult:
        action = QuarantineAction.REPROCESS
        replayed = await self._replayed_action(
            record_id,
            action_id,
            operator_id,
            action,
            expected_outcome="CLAIMED",
        )
        if replayed is not None:
            return replayed

        current = await self._quarantine_repo.find_by_id(record_id)
        if current is None:
            return self._missing_record(record_id, action)
        if expected_status is not QuarantineStatus.PENDING:
            return self._stale_record(current, action)
        if current.status is not expected_status:
            reclaimed = None
            if (
                current.status is QuarantineStatus.REPROCESSING
                and _claim_expired(current)
            ):
                reclaimer = getattr(self._quarantine_repo, "reclaim_expired_claim", None)
                if callable(reclaimer):
                    reclaimed = await _maybe_await(reclaimer(record_id))
            if reclaimed is None or reclaimed.status is not QuarantineStatus.PENDING:
                return self._stale_record(current, action)
            current = reclaimed
        try:
            claimed = await self._quarantine_repo.claim(
                record_id,
                operator_id,
                action_id=action_id,
            )
        except TypeError:
            claimed = await self._quarantine_repo.claim(record_id, operator_id)
        if claimed is None:
            return QuarantineResolutionResult(
                record_id=record_id,
                success=False,
                status=QuarantineStatus.PENDING,
                outcome="CLAIM_NOT_ACQUIRED",
                action=action,
                reason="Quarantine record could not be claimed.",
                action_id=action_id,
                previous_status=QuarantineStatus.PENDING,
                attempt_count=current.attempt_count,
            )
        await self._emit_audit(
            "QUARANTINE_CLAIMED",
            claimed,
            actor=operator_id,
            reason="Quarantine record claimed for processing.",
            action_id=action_id,
            previous_status=QuarantineStatus.PENDING,
            new_status=QuarantineStatus.REPROCESSING,
            outcome="CLAIMED",
        )
        return QuarantineResolutionResult(
            record_id=record_id,
            success=True,
            status=QuarantineStatus.REPROCESSING,
            outcome="CLAIMED",
            action=action,
            action_id=action_id,
            previous_status=QuarantineStatus.PENDING,
            attempt_count=claimed.attempt_count,
            source_evidence_available=None,
            escalation_level=claimed.escalation_level,
            claimed_by=claimed.claimed_by,
            priority=claimed.priority,
            review_due_at=claimed.review_due_at,
        )

    async def resolve_claimed(
        self,
        request: QuarantineReprocessRequest,
    ) -> QuarantineResolutionResult:
        async with _action_lock(request.record_id, request.action_id):
            return await self._resolve_claimed(request)

    async def _resolve_claimed(
        self,
        request: QuarantineReprocessRequest,
    ) -> QuarantineResolutionResult:
        action = _action_for(request.mode)
        replayed = await self._replayed_action(
            request.record_id,
            request.action_id,
            request.operator_id,
            action,
        )
        if replayed is not None:
            return replayed

        claimed = await self._quarantine_repo.find_by_id(request.record_id)
        if claimed is None:
            return self._missing_record(request.record_id, action)
        if request.expected_status is not QuarantineStatus.REPROCESSING:
            return self._stale_record(claimed, action)
        if claimed.status is not request.expected_status:
            return self._stale_record(claimed, action)
        if claimed.claimed_by != request.operator_id:
            return QuarantineResolutionResult(
                record_id=request.record_id,
                success=False,
                status=claimed.status,
                outcome="WRONG_OWNER",
                action=action,
                reason="Quarantine record is claimed by another operator.",
                action_id=request.action_id,
                previous_status=claimed.status,
                attempt_count=claimed.attempt_count,
                escalation_level=claimed.escalation_level,
            )
        if _claim_expired(claimed):
            return QuarantineResolutionResult(
                record_id=request.record_id,
                success=False,
                status=claimed.status,
                outcome="CLAIM_EXPIRED",
                action=action,
                reason="The operator claim has expired and can no longer mutate the record.",
                action_id=request.action_id,
                previous_status=claimed.status,
                attempt_count=claimed.attempt_count,
                escalation_level=claimed.escalation_level,
            )

        if request.mode is QuarantineReprocessMode.REJECT:
            reason = (request.reason or "").strip()
            if not reason:
                return QuarantineResolutionResult(
                    record_id=request.record_id,
                    success=False,
                    status=claimed.status,
                    outcome="REASON_REQUIRED",
                    action=action,
                    reason="Operator reason is required for rejection.",
                    action_id=request.action_id,
                    previous_status=claimed.status,
                    attempt_count=claimed.attempt_count,
                    escalation_level=claimed.escalation_level,
                )

        reservation = await self._reserve_action(
            request.record_id,
            request.operator_id,
            request.action_id,
            action,
        )
        if reservation and reservation != "RESERVED":
            if reservation == "COMPLETED":
                replayed = await self._replayed_action(
                    request.record_id,
                    request.action_id,
                    request.operator_id,
                    action,
                )
                if replayed is not None:
                    return replayed
            return QuarantineResolutionResult(
                record_id=request.record_id,
                success=False,
                status=claimed.status,
                outcome=(
                    "ACTION_IN_PROGRESS"
                    if reservation == "IN_PROGRESS"
                    else "ACTION_ID_REUSE_CONFLICT"
                ),
                action=action,
                reason="The operator action is already being processed.",
                action_id=request.action_id,
                previous_status=claimed.status,
                attempt_count=claimed.attempt_count,
                escalation_level=claimed.escalation_level,
            )

        if request.mode is QuarantineReprocessMode.REJECT:
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
        except ValueError:
            outcome = (
                "CORRECTED_ROW_REQUIRED"
                if request.mode is QuarantineReprocessMode.CORRECTED_ROW
                else "SOURCE_EVIDENCE_UNAVAILABLE"
            )
            return await self._release(
                claimed,
                request,
                reason=(
                    "A corrected row is required for this resolution."
                    if outcome == "CORRECTED_ROW_REQUIRED"
                    else "Authoritative source evidence is unavailable for replay."
                ),
                outcome=outcome,
                source_evidence_available=False,
            )

        source_evidence_available = resolved_input.origin in {
            "AUTHORITATIVE_SOURCE_FILE",
            "STAGED_RAW_PAGE",
        }
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
                source_evidence_available=source_evidence_available,
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
                source_evidence_available=source_evidence_available,
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
                source_evidence_available=source_evidence_available,
            )

        conflicting = int(getattr(write_result, "conflicting_duplicates", 0) or 0)
        equivalent = int(getattr(write_result, "equivalent_duplicates", 0) or 0)
        failed = int(getattr(write_result, "failed", 0) or 0)
        if isinstance(write_result, Mapping):
            conflicting = int(write_result.get("conflicting_duplicates", 0) or 0)
            equivalent = int(write_result.get("equivalent_duplicates", 0) or 0)
            failed = int(write_result.get("failed", 0) or 0)
        if conflicting > 0:
            return await self._release(
                claimed,
                request,
                reason="Reprocessed row still conflicts with an existing transaction.",
                metadata={"conflictingDuplicates": conflicting},
                outcome="CONFLICT_REMAINS",
                source_evidence_available=source_evidence_available,
            )
        if failed > 0:
            return await self._release(
                claimed,
                request,
                reason="Transaction persistence reported a failed write.",
                outcome="RETRYABLE_FAILURE",
                failure_classification="RETRYABLE_INFRASTRUCTURE",
                source_evidence_available=source_evidence_available,
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
                "sourceEvidenceAvailable": source_evidence_available,
            },
            outcome=outcome,
            source_evidence_available=source_evidence_available,
        )

    async def escalate(
        self,
        record_id: str,
        operator_id: str,
        action_id: str,
        expected_status: QuarantineStatus,
        reason: str,
    ) -> QuarantineResolutionResult:
        action = QuarantineAction.ESCALATE
        replayed = await self._replayed_action(record_id, action_id, operator_id, action)
        if replayed is not None:
            return replayed
        record = await self._quarantine_repo.find_by_id(record_id)
        if record is None:
            return self._missing_record(record_id, action)
        if record.status is not expected_status or expected_status not in {
            QuarantineStatus.PENDING,
            QuarantineStatus.REPROCESSING,
        }:
            return self._stale_record(record, action)
        if record.status is QuarantineStatus.REPROCESSING and record.claimed_by != operator_id:
            return QuarantineResolutionResult(
                record_id=record_id,
                success=False,
                status=record.status,
                outcome="WRONG_OWNER",
                action=action,
                reason="Quarantine record is claimed by another operator.",
                action_id=action_id,
                previous_status=record.status,
                attempt_count=record.attempt_count,
                escalation_level=record.escalation_level,
            )
        if record.status is QuarantineStatus.REPROCESSING and _claim_expired(record):
            return QuarantineResolutionResult(
                record_id=record_id,
                success=False,
                status=record.status,
                outcome="CLAIM_EXPIRED",
                action=action,
                reason="The operator claim has expired and can no longer mutate the record.",
                action_id=action_id,
                previous_status=record.status,
                attempt_count=record.attempt_count,
                escalation_level=record.escalation_level,
            )
        if not reason.strip():
            return QuarantineResolutionResult(
                record_id=record_id,
                success=False,
                status=record.status,
                outcome="REASON_REQUIRED",
                action=action,
                reason="Operator reason is required for escalation.",
                action_id=action_id,
                previous_status=record.status,
                attempt_count=record.attempt_count,
                escalation_level=record.escalation_level,
            )
        escalated = await self._quarantine_repo.escalate(
            record_id,
            operator_id,
            action_id,
            expected_status,
            reason,
        )
        if escalated is None:
            return QuarantineResolutionResult(
                record_id=record_id,
                success=False,
                status=record.status,
                outcome="ESCALATION_CONFLICT",
                action=action,
                reason="Quarantine record could not be escalated.",
                action_id=action_id,
                previous_status=record.status,
                attempt_count=record.attempt_count,
                escalation_level=record.escalation_level,
            )
        level = getattr(escalated, "escalation_level", record.escalation_level + 1)
        await self._emit_audit(
            "QUARANTINE_ESCALATED",
            record,
            actor=operator_id,
            reason=reason,
            action_id=action_id,
            previous_status=record.status,
            new_status=record.status,
            outcome="ESCALATED",
        )
        return QuarantineResolutionResult(
            record_id=record_id,
            success=True,
            status=record.status,
            outcome="ESCALATED",
            action=action,
            reason=reason.strip()[:500],
            action_id=action_id,
            previous_status=record.status,
            attempt_count=record.attempt_count,
            escalation_level=level,
            claimed_by=escalated.claimed_by,
            priority=escalated.priority,
            review_due_at=escalated.review_due_at,
        )

    async def resolve(
        self,
        request: QuarantineReprocessRequest,
    ) -> QuarantineResolutionResult:
        claim_action_id = f"{request.action_id[:120]}:claim"
        claimed = await self.claim(
            request.record_id,
            request.operator_id,
            claim_action_id,
            request.expected_status,
        )
        if not claimed.success:
            return claimed
        return await self.resolve_claimed(
            request.model_copy(update={"expected_status": QuarantineStatus.REPROCESSING})
        )

    async def _accept_existing(
        self,
        claimed: IngestionQuarantineRecord,
        request: QuarantineReprocessRequest,
    ) -> QuarantineResolutionResult:
        if (
            request.expected_existing_fingerprint is not None
            and request.expected_existing_fingerprint != claimed.existing_fingerprint
        ):
            return await self._release(
                claimed,
                request,
                reason="Existing transaction fingerprint no longer matches quarantine evidence.",
                outcome="FINGERPRINT_MISMATCH",
            )
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
        source_evidence_available: bool | None = None,
    ) -> QuarantineResolutionResult:
        bounded_metadata = dict(metadata or {})
        if source_evidence_available is not None:
            bounded_metadata["sourceEvidenceAvailable"] = source_evidence_available
        try:
            released = await self._quarantine_repo.release_for_retry(
                request.record_id,
                request.operator_id,
                reason,
                bounded_metadata,
                action_id=request.action_id,
                outcome=outcome,
            )
        except TypeError:
            released = await self._quarantine_repo.release_for_retry(
                request.record_id,
                request.operator_id,
                reason,
                bounded_metadata,
            )
        if released:
            await self._emit_audit(
                "QUARANTINE_RETRY_SCHEDULED",
                claimed,
                actor=request.operator_id,
                reason=reason,
                action_id=request.action_id,
                previous_status=QuarantineStatus.REPROCESSING,
                new_status=QuarantineStatus.PENDING,
                outcome=outcome,
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
            action_id=request.action_id,
            previous_status=QuarantineStatus.REPROCESSING,
            attempt_count=claimed.attempt_count,
            source_evidence_available=source_evidence_available,
            escalation_level=claimed.escalation_level,
            priority=claimed.priority,
            review_due_at=claimed.review_due_at,
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
        source_evidence_available: bool | None = None,
    ) -> QuarantineResolutionResult:
        bounded_metadata = dict(metadata)
        if source_evidence_available is not None:
            bounded_metadata["sourceEvidenceAvailable"] = source_evidence_available
        try:
            resolved = await self._quarantine_repo.resolve(
                request.record_id,
                target,
                request.operator_id,
                action,
                reason,
                bounded_metadata,
                action_id=request.action_id,
                outcome=outcome,
            )
        except TypeError:
            resolved = await self._quarantine_repo.resolve(
                request.record_id,
                target,
                request.operator_id,
                action,
                reason,
                bounded_metadata,
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
                action_id=request.action_id,
                previous_status=QuarantineStatus.REPROCESSING,
                new_status=target,
                outcome=outcome,
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
            action_id=request.action_id,
            previous_status=QuarantineStatus.REPROCESSING,
            attempt_count=claimed.attempt_count,
            source_evidence_available=source_evidence_available,
            escalation_level=claimed.escalation_level,
            priority=claimed.priority,
            review_due_at=claimed.review_due_at,
        )


__all__ = ["QuarantineResolutionResult", "QuarantineResolutionService"]
