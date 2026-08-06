"""Normalize, validate and build one canonical ingestion row."""

from dataclasses import dataclass, field
import time
from typing import Any

from src.domain.partner_transaction.models import (
    DataContainer,
    FastDataContainer,
    FastPartnerData,
    PartnerData,
)
from src.normalizer.normalizer import TransactionNormalizer
from src.validators.validator import Validator


@dataclass(frozen=True)
class RowProcessingResult:
    """Result of processing one source row."""

    data_container: Any | None = None
    ingestion_key: str | None = None
    errors: list[dict[str, Any]] = field(default_factory=list)
    failure_reason: str | None = None
    failure_trace: str = ""
    normalize_ms: float = 0.0
    validate_ms: float = 0.0

    @property
    def is_valid(self) -> bool:
        return self.data_container is not None


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

    def process(self, row_tuple: tuple[Any, ...], row_number: int) -> RowProcessingResult:
        normalize_started = time.perf_counter()
        normalized = self._normalizer.normalize(row_tuple, row_number)
        if normalized.errors:
            return RowProcessingResult(
                errors=[
                    {"row": error.row, "field": error.field, "reason": error.reason}
                    for error in normalized.errors
                ],
                failure_reason=normalized.errors[0].reason,
                failure_trace=f"row:{row_number}",
                normalize_ms=(time.perf_counter() - normalize_started) * 1000,
            )

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
            return RowProcessingResult(
                errors=[
                    {"row": error.row, "field": error.field, "reason": error.reason}
                    for error in build_errors
                ],
                failure_reason=build_errors[0].reason,
                failure_trace=f"row:{row_number}",
                normalize_ms=normalize_ms,
            )

        validate_started = time.perf_counter()
        if not self._fast_mode:
            validation = self._validator.validate(
                txn,
                row_number=row_number,
                trace=txn.trace,
            )
            validate_ms = (time.perf_counter() - validate_started) * 1000
            if not validation.is_valid:
                return RowProcessingResult(
                    errors=[
                        {
                            "row": error.row,
                            "field": error.field,
                            "reason": error.reason,
                            "trace": error.trace,
                        }
                        for error in validation.errors
                    ],
                    failure_reason=validation.errors[0].reason,
                    failure_trace=txn.trace or "",
                    normalize_ms=normalize_ms,
                    validate_ms=validate_ms,
                )
        else:
            validate_ms = 0.0

        ingestion_key = self.derive_ingestion_key(txn)
        data_container = self._build_data_container(txn, ingestion_key)
        return RowProcessingResult(
            data_container=data_container,
            ingestion_key=ingestion_key,
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
            extra=txn.extra,
        )
        return DataContainer(
            identify=self._partner,
            workflow_type=self._workflow_type,
            reconciliation_date=self._reconciliation_date,
            source_file_id=self._source_file_id,
            ingestion_key=ingestion_key,
            partner_data=partner_data,
        )
