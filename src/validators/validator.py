"""Core Validator service for CanonicalTransaction validation.

Validates CanonicalTransaction objects against business rules:
- Required field checks (id, amount, currency, status)
- Decimal validation (non-negative)
- Date validation (type integrity)
- Status validation (enum membership)
- Duplicate detection (transaction-level and file-level)

Collects ALL errors — never fail-fast.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from src.core.enums import TransactionStatus
from src.core.types import CanonicalTransaction, ValidationError

if TYPE_CHECKING:
    from src.infrastructure.partner_transaction.repository import DataContainerRepository
    from src.infrastructure.ingestion.file_repository import ReconciliationFileRepository


@dataclass
class ValidationResult:
    """Result of validating a CanonicalTransaction.

    Attributes:
        is_valid: True if no validation errors were found.
        errors: All validation errors encountered during validation.
    """

    is_valid: bool = True
    errors: list[ValidationError] = field(default_factory=list)


class Validator:
    """Validates CanonicalTransaction objects against business rules.

    Never raises exceptions — all errors are collected as ValidationError
    objects. Multiple errors are collected (not fail-fast).

    Optional repository injection is retained for the legacy
    ``validate_with_duplicates`` compatibility API. The active ingestion
    pipeline uses ``validate`` only; duplicate authority is the atomic
    database write.
    """

    def __init__(
        self,
        data_container_repo: Optional["DataContainerRepository"] = None,
        reconciliation_file_repo: Optional["ReconciliationFileRepository"] = None,
    ):
        """Initialize Validator with optional repositories for duplicate detection.

        Args:
            data_container_repo: Repository for transaction duplicate checks.
            reconciliation_file_repo: Repository for file duplicate checks.
        """
        self._data_container_repo = data_container_repo
        self._reconciliation_file_repo = reconciliation_file_repo

    def validate(
        self,
        txn: CanonicalTransaction,
        row_number: Optional[int] = None,
        trace: Optional[str] = None,
    ) -> ValidationResult:
        """Validate a CanonicalTransaction against all business rules.

        Args:
            txn: The canonical transaction to validate.
            row_number: Optional row number for error context.
            trace: Optional trace identifier for error context.

        Returns:
            ValidationResult with is_valid flag and collected errors.
        """
        result = ValidationResult(is_valid=True, errors=[])

        self._validate_required_fields(txn, result, row_number, trace)
        self._validate_decimal(txn, result, row_number, trace)
        self._validate_date(txn, result, row_number, trace)
        self._validate_status(txn, result, row_number, trace)

        result.is_valid = len(result.errors) == 0
        return result

    async def validate_with_duplicates(
        self,
        txn: CanonicalTransaction,
        identify: str,
        reconciliation_date: datetime,
        file_hash: Optional[str] = None,
        row_number: Optional[int] = None,
        trace: Optional[str] = None,
    ) -> ValidationResult:
        """Legacy validation API that also performs duplicate lookups.

        Runs core validation first, then checks for duplicates if repositories
        are available. The active ingestion pipeline does not call this
        method; database conflict handling is its duplicate authority.

        Args:
            txn: The canonical transaction to validate.
            identify: Partner identifier for duplicate lookup.
            reconciliation_date: Reconciliation date for duplicate lookup.
            file_hash: Optional SHA256 hash of the source file.
            row_number: Optional row number for error context.
            trace: Optional trace identifier for error context.

        Returns:
            ValidationResult with all collected errors (core + duplicate).
        """
        # Run core validation first
        result = self.validate(txn, row_number, trace)

        # Check duplicates if repositories are available
        txn_dup = await self._check_transaction_duplicate(
            identify, reconciliation_date, trace, row_number
        )
        if txn_dup is not None:
            result.errors.append(txn_dup)

        file_dup = await self._check_file_duplicate(file_hash)
        if file_dup is not None:
            result.errors.append(file_dup)

        result.is_valid = len(result.errors) == 0
        return result

    async def _check_transaction_duplicate(
        self,
        identify: str,
        reconciliation_date: datetime,
        trace: Optional[str],
        row_number: Optional[int],
    ) -> Optional[ValidationError]:
        """Check if a transaction with the same key already exists.

        Args:
            identify: Partner identifier.
            reconciliation_date: Reconciliation date.
            trace: Transaction trace identifier.
            row_number: Row number for error context.

        Returns:
            ValidationError if duplicate found, None otherwise.
        """
        if self._data_container_repo is None or trace is None:
            return None

        existing = await self._data_container_repo.find_by_duplicate_key(
            identify, reconciliation_date, trace
        )
        if existing is not None:
            return ValidationError(
                field="duplicate",
                reason="transaction already exists in partner_transaction",
                row=row_number,
                trace=trace,
            )
        return None

    async def _check_file_duplicate(
        self,
        file_hash: Optional[str],
    ) -> Optional[ValidationError]:
        """Check if a file with the same hash was already processed.

        Args:
            file_hash: SHA256 hash of the source file.

        Returns:
            ValidationError if duplicate found, None otherwise.
        """
        if self._reconciliation_file_repo is None or file_hash is None:
            return None

        existing = await self._reconciliation_file_repo.find_by_file_hash(file_hash)
        if existing is not None:
            return ValidationError(
                field="file_duplicate",
                reason=f"file already processed (hash: {file_hash[:16]}...)",
            )
        return None

    def _validate_required_fields(
        self,
        txn: CanonicalTransaction,
        result: ValidationResult,
        row_number: Optional[int],
        trace: Optional[str],
    ) -> None:
        """Check that all required fields are present and non-empty.

        Required fields: id (non-empty string), amount (present),
        currency (non-empty string), status (present).
        """
        # Validate id — must be non-empty string
        if txn.id is None or txn.id.strip() == "":
            result.errors.append(ValidationError(
                field="id",
                reason="required field 'id' is empty or missing",
                row=row_number,
                trace=trace,
            ))

        # Validate currency — must be non-empty string
        if txn.currency is None or txn.currency.strip() == "":
            result.errors.append(ValidationError(
                field="currency",
                reason="required field 'currency' is empty or missing",
                row=row_number,
                trace=trace,
            ))

    def _validate_decimal(
        self,
        txn: CanonicalTransaction,
        result: ValidationResult,
        row_number: Optional[int],
        trace: Optional[str],
    ) -> None:
        """Validate amount business rules.

        - Amount must be non-negative (zero is valid for refunds/zero-value txns).
        - Type correctness already enforced by CanonicalTransaction pydantic model.
        """
        if txn.amount is None:
            result.errors.append(ValidationError(
                field="amount",
                reason="required field 'amount' is missing",
                row=row_number,
                trace=trace,
            ))
            return

        if txn.amount < 0:
            result.errors.append(ValidationError(
                field="amount",
                reason=f"amount must be non-negative, got {txn.amount}",
                row=row_number,
                trace=trace,
            ))

    def _validate_date(
        self,
        txn: CanonicalTransaction,
        result: ValidationResult,
        row_number: Optional[int],
        trace: Optional[str],
    ) -> None:
        """Validate transDate type integrity.

        - transDate is Optional[datetime] — if None, skip (it's optional).
        - If present, confirm it's a datetime instance (defensive type check).
        """
        if txn.transDate is not None:
            if not isinstance(txn.transDate, datetime):
                result.errors.append(ValidationError(
                    field="transDate",
                    reason="transDate must be a datetime object",
                    row=row_number,
                    trace=trace,
                ))

    def _validate_status(
        self,
        txn: CanonicalTransaction,
        result: ValidationResult,
        row_number: Optional[int],
        trace: Optional[str],
    ) -> None:
        """Validate status is a valid TransactionStatus enum member.

        Since CanonicalTransaction already coerces to TransactionStatus enum
        via pydantic, this is a defensive check. In practice this should never
        fail after CanonicalTransaction construction, but validates the contract.
        """
        if txn.status not in TransactionStatus:
            result.errors.append(ValidationError(
                field="status",
                reason=f"invalid status value '{txn.status}' — must be one of {', '.join(s.value for s in TransactionStatus)}",
                row=row_number,
                trace=trace,
            ))
