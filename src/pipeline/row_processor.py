"""Normalize, validate and build one canonical ingestion row."""

from dataclasses import dataclass, field
import time
from typing import Any

from src.application.ingestion.contracts import serialize_quality_violation
from src.core.types import CanonicalTransaction
from src.domain.ingestion.quality import QualityOutcome, QualityViolation
from src.domain.partner_transaction.models import (
    DataContainer,
    FastDataContainer,
    FastPartnerData,
    PartnerData,
)
from src.normalizer.normalizer import TransactionNormalizer
from src.validators.validator import Validator


@dataclass(frozen=True)
class RowOutcome:
    """Bounded row result containing normalized data, quality and timing context."""

    normalized_data: dict[str, Any] = field(default_factory=dict)
    data_container: Any | None = None
    ingestion_key: str | None = None
    violations: list[QualityViolation] = field(default_factory=list)
    outcome: QualityOutcome = QualityOutcome.VALID
    row_context: dict[str, Any] = field(default_factory=dict)
    normalize_ms: float = 0.0
    validate_ms: float = 0.0

    @property
    def errors(self) -> list[dict[str, Any]]:
        return [serialize_quality_violation(violation) for violation in self.violations]

    @property
    def is_valid(self) -> bool:
        return self.outcome in {
            QualityOutcome.VALID,
            QualityOutcome.WARNING,
            QualityOutcome.EQUIVALENT_DUPLICATE,
        }

    @property
    def failure_reason(self) -> str | None:
        return self.violations[0].message if self.violations else None

    @property
    def failure_trace(self) -> str:
        return next((item.trace for item in self.violations if item.trace), "")


class RowProcessor:
    """Own row-level transformation; does not persist or update run state."""

    def __init__(
        self,
        *,
        normalizer: TransactionNormalizer,
        validator: Validator,
        fast_mode: bool,
        partner: str,
        workflow_type: str,
        reconciliation_date: Any,
        source_file_id: Any,
    ) -> None:
        self._normalizer = normalizer
        self._validator = validator
        self._fast_mode = fast_mode
        self._partner = partner
        self._workflow_type = workflow_type
        self._reconciliation_date = reconciliation_date
        self._source_file_id = source_file_id

    @staticmethod
    def derive_ingestion_key(txn: Any) -> str:
        if isinstance(txn, dict):
            txn_id, trace = txn.get("id"), txn.get("trace")
        else:
            txn_id, trace = getattr(txn, "id", None), getattr(txn, "trace", None)
        if txn_id:
            return str(txn_id)
        if trace:
            return str(trace)
        raise ValueError("Unable to derive ingestion_key from transaction payload")

    def process(self, row_tuple: Any, row_number: int) -> RowOutcome:
        normalize_started = time.perf_counter()
        normalized = self._normalizer.normalize(row_tuple, row_number)
        if normalized.errors:
            return RowOutcome(
                normalized_data=normalized.data,
                violations=normalized.errors,
                outcome=QualityOutcome.REJECT,
                row_context={"rowNumber": row_number},
                normalize_ms=(time.perf_counter() - normalize_started) * 1000,
            )

        txn: CanonicalTransaction | dict[str, Any] | None
        build_errors: list[QualityViolation]
        if self._fast_mode:
            txn, build_errors = TransactionNormalizer.build_fast_dict(
                normalized.data, [], row_number
            )
        else:
            txn, build_errors = TransactionNormalizer.build_canonical(
                normalized.data, [], row_number
            )

        normalize_ms = (time.perf_counter() - normalize_started) * 1000
        if txn is None:
            return RowOutcome(
                normalized_data=normalized.data,
                violations=build_errors,
                outcome=QualityOutcome.REJECT,
                row_context={"rowNumber": row_number},
                normalize_ms=normalize_ms,
            )

        validate_started = time.perf_counter()
        txn_trace = txn.get("trace") if isinstance(txn, dict) else txn.trace
        validation = self._validator.validate(
            txn,
            row_number=row_number,
            trace=txn_trace,
            include_context=False,
        )
        validate_ms = (time.perf_counter() - validate_started) * 1000
        if not validation.is_valid:
            return RowOutcome(
                normalized_data=normalized.data,
                violations=validation.violations,
                outcome=validation.outcome,
                row_context={"rowNumber": row_number, "trace": txn_trace},
                normalize_ms=normalize_ms,
                validate_ms=validate_ms,
            )

        ingestion_key = self.derive_ingestion_key(txn)
        data_container = self._build_data_container(txn, ingestion_key)
        return RowOutcome(
            normalized_data=normalized.data,
            data_container=data_container,
            ingestion_key=ingestion_key,
            violations=validation.violations,
            outcome=validation.outcome,
            row_context={"rowNumber": row_number, "trace": txn_trace},
            normalize_ms=normalize_ms,
            validate_ms=validate_ms,
        )

    def _build_data_container(self, txn: Any, ingestion_key: str) -> Any:
        if self._fast_mode:
            from datetime import datetime, timezone
            from uuid import uuid4

            now = datetime.now(timezone.utc)
            return FastDataContainer(
                id=uuid4(),
                request_id=uuid4(),
                identify=self._partner,
                workflow_type=self._workflow_type,
                reconciliation_date=self._reconciliation_date,
                operation_status="IN_PROGRESS",
                reconciliation_status="",
                connector_data="",
                extra_data="",
                source_file_id=self._source_file_id,
                ingestion_key=ingestion_key,
                partner_data=FastPartnerData(
                    id=txn["id"],
                    trace=txn["trace"],
                    status=txn["status"],
                    amount=txn["amount"],
                    currency=txn["currency"],
                    trans_date=txn["transDate"],
                    timestamp_basis=txn.get("timestampBasis", "LEGACY_STORED"),
                    extra=txn["extra"],
                ),
                created_by="system",
                created_date=now,
                last_modified_by="system",
                last_modified_date=now,
            )

        partner_data = PartnerData(
            **{"_id": txn.id},
            trace=txn.trace,
            status=txn.status.value,
            amount=txn.amount,
            currency=txn.currency,
            transDate=txn.transDate,
            timestampBasis=txn.timestampBasis,
            extra=txn.extra,
        )
        return DataContainer(
            identify=self._partner,
            workflowType=self._workflow_type,
            reconciliationDate=self._reconciliation_date,
            sourceFileId=self._source_file_id,
            ingestionKey=ingestion_key,
            partnerData=partner_data,
        )
