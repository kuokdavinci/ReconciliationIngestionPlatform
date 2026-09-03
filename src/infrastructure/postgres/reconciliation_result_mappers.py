"""Mapping between reconciliation result domain and persistence shapes."""

from typing import Any

from src.domain.reconciliation.models import ReconciliationResult
from src.infrastructure.persistence.mongo_values import normalize_document_aliases
from src.infrastructure.persistence.time import as_utc_naive


_RECONCILIATION_RESULT_ALIASES = {
    "_id": "id",
    "partnerTxnId": "partner_txn_id",
    "internalTxnId": "internal_txn_id",
    "partnerAmount": "partner_amount",
    "internalAmount": "internal_amount",
    "partnerStatus": "partner_status",
    "internalStatus": "internal_status",
    "reconciliationStatus": "reconciliation_status",
    "reconciliationRunId": "reconciliation_run_id",
    "sourceFileId": "source_file_id",
    "scopeType": "scope_type",
    "mappingVersion": "mapping_version",
    "partnerRecordId": "partner_record_id",
    "internalRecordId": "internal_record_id",
    "reconciliationKey": "reconciliation_key",
    "partnerTransDate": "partner_trans_date",
    "internalTransactionTime": "internal_transaction_time",
    "timestampStatus": "timestamp_status",
    "timestampDeltaSeconds": "timestamp_delta_seconds",
    "timestampToleranceSeconds": "timestamp_tolerance_seconds",
    "timestampTimezone": "timestamp_timezone",
    "timestampBasis": "timestamp_basis",
    "ambiguousPartnerRecordIds": "ambiguous_partner_record_ids",
    "ambiguousInternalRecordIds": "ambiguous_internal_record_ids",
    "createdAt": "created_at",
}


def reconciliation_result_to_row(doc: ReconciliationResult) -> dict[str, Any]:
    """Map a reconciliation result to PostgreSQL column names."""
    created_at = as_utc_naive(doc.created_at)
    return {
        "id": doc.id,
        "partner": doc.partner,
        "date": doc.date,
        "partner_txn_id": doc.partner_txn_id,
        "internal_txn_id": doc.internal_txn_id,
        "partner_amount": doc.partner_amount,
        "internal_amount": doc.internal_amount,
        "partner_status": doc.partner_status,
        "internal_status": doc.internal_status,
        "reconciliation_status": doc.reconciliation_status.value,
        "reconciliation_run_id": doc.reconciliation_run_id,
        "source_file_id": doc.source_file_id,
        "scope_type": doc.scope_type,
        "mapping_version": doc.mapping_version,
        "partner_record_id": doc.partner_record_id,
        "internal_record_id": doc.internal_record_id,
        "reconciliation_key": doc.reconciliation_key,
        "partner_trans_date": as_utc_naive(doc.partner_trans_date),
        "internal_transaction_time": as_utc_naive(doc.internal_transaction_time),
        "timestamp_status": doc.timestamp_status.value,
        "timestamp_delta_seconds": doc.timestamp_delta_seconds,
        "timestamp_tolerance_seconds": doc.timestamp_tolerance_seconds,
        "timestamp_timezone": doc.timestamp_timezone,
        "timestamp_basis": doc.timestamp_basis,
        "ambiguous_partner_record_ids": doc.ambiguous_partner_record_ids,
        "ambiguous_internal_record_ids": doc.ambiguous_internal_record_ids,
        "created_at": created_at,
    }


def row_to_reconciliation_result(row: Any) -> ReconciliationResult:
    """Map a PostgreSQL row to the reconciliation result domain model."""
    data = _row_to_dict(row)
    return ReconciliationResult(
        _id=data["id"],
        partner=data["partner"],
        date=data["date"],
        partnerTxnId=data["partner_txn_id"],
        internalTxnId=data["internal_txn_id"],
        partnerAmount=data["partner_amount"],
        internalAmount=data["internal_amount"],
        partnerStatus=data["partner_status"],
        internalStatus=data["internal_status"],
        reconciliationStatus=data["reconciliation_status"],
        reconciliationRunId=data["reconciliation_run_id"],
        sourceFileId=data["source_file_id"],
        scopeType=data["scope_type"],
        mappingVersion=data["mapping_version"],
        partnerRecordId=data["partner_record_id"],
        internalRecordId=data["internal_record_id"],
        reconciliationKey=data.get("reconciliation_key"),
        partnerTransDate=data.get("partner_trans_date"),
        internalTransactionTime=data.get("internal_transaction_time"),
        timestampStatus=data.get("timestamp_status", "NOT_EVALUATED"),
        timestampDeltaSeconds=data.get("timestamp_delta_seconds"),
        timestampToleranceSeconds=data.get("timestamp_tolerance_seconds"),
        timestampTimezone=data.get("timestamp_timezone"),
        timestampBasis=data.get("timestamp_basis", "LEGACY_STORED"),
        ambiguousPartnerRecordIds=data.get("ambiguous_partner_record_ids") or [],
        ambiguousInternalRecordIds=data.get("ambiguous_internal_record_ids") or [],
        createdAt=data["created_at"],
    )


def document_to_reconciliation_result(document: dict[str, Any]) -> ReconciliationResult:
    """Map a legacy Mongo-shaped document to the domain model."""
    normalized = normalize_document_aliases(
        document, _RECONCILIATION_RESULT_ALIASES
    )
    return ReconciliationResult.model_validate(normalized)


def _row_to_dict(row: Any) -> dict[str, Any]:
    if hasattr(row, "__table__"):
        return {column.name: getattr(row, column.name) for column in row.__table__.columns}
    return dict(row)
