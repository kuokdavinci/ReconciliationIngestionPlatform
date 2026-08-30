"""Mapping between partner transaction domain and persistence shapes."""

from typing import Any

from src.domain.partner_transaction.models import (
    DataContainer,
    FastDataContainer,
    PartnerData,
)
from src.domain.mapping.models import ReconciliationPolicy
from src.infrastructure.persistence.mongo_values import normalize_document_aliases
from src.infrastructure.persistence.time import as_utc_naive
from src.normalizer.timestamps import normalize_transaction_timestamp


_DATA_CONTAINER_ALIASES = {
    "_id": "id",
    "requestId": "request_id",
    "workflowType": "workflow_type",
    "reconciliationDate": "reconciliation_date",
    "operationStatus": "operation_status",
    "reconciliationStatus": "reconciliation_status",
    "connectorData": "connector_data",
    "extraData": "extra_data",
    "sourceFileId": "source_file_id",
    "ingestionKey": "ingestion_key",
    "partnerData": "partner_data",
    "createdBy": "created_by",
    "createdDate": "created_date",
    "lastModifiedBy": "last_modified_by",
    "lastModifiedDate": "last_modified_date",
}
_PARTNER_DATA_ALIASES = {"_id": "id", "transDate": "trans_date"}


def data_container_to_row(
    doc: DataContainer | FastDataContainer,
    *,
    timestamp_policy: ReconciliationPolicy | None = None,
) -> dict[str, Any]:
    """Map a domain transaction to PostgreSQL column names."""
    pd = doc.partner_data
    partner_trans_date = pd.trans_date
    if timestamp_policy is not None and partner_trans_date is not None:
        partner_trans_date = normalize_transaction_timestamp(
            partner_trans_date, timestamp_policy.timestamp_timezone
        )
    return {
        "id": doc.id,
        "request_id": doc.request_id,
        "identify": doc.identify,
        "workflow_type": doc.workflow_type,
        "reconciliation_date": as_utc_naive(doc.reconciliation_date),
        "operation_status": doc.operation_status,
        "reconciliation_status": doc.reconciliation_status,
        "connector_data": doc.connector_data,
        "extra_data": doc.extra_data,
        "source_file_id": doc.source_file_id,
        "ingestion_key": doc.ingestion_key,
        "partner_id": pd.id,
        "partner_trace": pd.trace,
        "partner_status": pd.status,
        "partner_amount": pd.amount,
        "partner_currency": pd.currency,
        "partner_trans_date": as_utc_naive(partner_trans_date),
        "timestamp_basis": (
            "CANONICAL_UTC" if timestamp_policy is not None else pd.timestamp_basis
        ),
        "partner_metadata": pd.extra or {},
        "created_by": doc.created_by,
        "created_date": as_utc_naive(doc.created_date),
        "last_modified_by": doc.last_modified_by,
        "last_modified_date": as_utc_naive(doc.last_modified_date),
    }


def row_to_data_container(row: Any) -> DataContainer:
    """Map a PostgreSQL row to the partner transaction domain model."""
    data = _row_to_dict(row)
    return DataContainer(
        _id=data["id"],
        requestId=data["request_id"],
        identify=data["identify"],
        workflowType=data["workflow_type"],
        reconciliationDate=data["reconciliation_date"],
        operationStatus=data["operation_status"],
        reconciliationStatus=data["reconciliation_status"],
        connectorData=data["connector_data"],
        extraData=data["extra_data"],
        sourceFileId=data["source_file_id"],
        ingestionKey=data.get("ingestion_key", data.get("ingestionKey", "")),
        partnerData=PartnerData(
            _id=data["partner_id"],
            trace=data["partner_trace"],
            status=data["partner_status"],
            amount=data["partner_amount"],
            currency=data["partner_currency"],
            transDate=data["partner_trans_date"],
            timestampBasis=data.get("timestamp_basis", "LEGACY_STORED"),
            extra=data["partner_metadata"] or {},
        ),
        createdBy=data["created_by"],
        createdDate=data["created_date"],
        lastModifiedBy=data["last_modified_by"],
        lastModifiedDate=data["last_modified_date"],
    )


def document_to_data_container(document: dict[str, Any]) -> DataContainer:
    """Map a legacy Mongo-shaped document to the domain model."""
    normalized = normalize_document_aliases(document, _DATA_CONTAINER_ALIASES)
    partner_data = normalized.get("partner_data")
    if isinstance(partner_data, dict):
        normalized["partner_data"] = normalize_document_aliases(
            partner_data, _PARTNER_DATA_ALIASES
        )
    return DataContainer.model_validate(normalized)


def _row_to_dict(row: Any) -> dict[str, Any]:
    if hasattr(row, "__table__"):
        return {column.name: getattr(row, column.name) for column in row.__table__.columns}
    return dict(row)
