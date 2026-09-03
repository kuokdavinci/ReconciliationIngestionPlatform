"""Unit contracts for versioned timestamp evidence."""

import inspect
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from src.core.enums import FileType, ReconciliationScopeType
from src.core.types import FieldMapping, FieldMappingType
from src.domain.mapping.models import MappingConfig, ReconciliationPolicy
from src.domain.reconciliation.models import ReconciliationResult, TimestampStatus
from src.normalizer.normalizer import TransactionNormalizer
from src.reconciliation.postgres_executor import PostgresReconciliationExecutor


def _timestamp_normalizer(policy: ReconciliationPolicy | None = None):
    return TransactionNormalizer(
        [FieldMapping(path="transDate", column="C", type=FieldMappingType.DATE)],
        timestamp_policy=policy,
    )


def test_mapping_policy_defaults_to_business_timezone_and_300_seconds():
    config = MappingConfig(
        partner="MOMO",
        workflowType="UPC",
        fileType=FileType.SETTLEMENT,
        sheetName="Sheet1",
        fieldMappings=[FieldMapping(path="amount", type=FieldMappingType.DECIMAL)],
    )

    assert config.timestamp_policy.timestamp_tolerance_seconds == 300
    assert config.timestamp_policy.timestamp_timezone == "Asia/Ho_Chi_Minh"


def test_mapping_policy_supports_partner_override_and_rejects_unknown_timezone():
    policy = ReconciliationPolicy(timestampToleranceSeconds=30, timestampTimezone="UTC")
    assert policy.timestamp_tolerance_seconds == 30
    assert policy.timestamp_timezone == "UTC"

    with pytest.raises(ValidationError):
        ReconciliationPolicy(timestampTimezone="Not/AZone")


def test_policy_normalizes_naive_values_as_partner_local_time_and_marks_basis():
    result = _timestamp_normalizer(
        ReconciliationPolicy(timestampToleranceSeconds=300, timestampTimezone="Asia/Ho_Chi_Minh")
    ).normalize({"C": "2026-08-30 15:00:00"})

    assert result.errors == []
    assert result.data["transDate"] == datetime(2026, 8, 30, 8, tzinfo=UTC)
    assert result.data["timestampBasis"] == "CANONICAL_UTC"


def test_optional_policy_timestamp_accepts_null_and_blank_but_rejects_invalid():
    normalizer = _timestamp_normalizer(ReconciliationPolicy())
    assert normalizer.normalize({"C": None}).errors == []
    assert normalizer.normalize({"C": "  "}).errors == []
    assert normalizer.normalize({"C": "not-a-time"}).errors


def test_result_serializes_timestamp_evidence_fields():
    result = ReconciliationResult(
        _id="result-1",
        partner="MOMO",
        date="2026-08-30",
        partnerTxnId="key-1",
        reconciliationKey="key-1",
        reconciliationStatus="MATCHED",
        timestampStatus=TimestampStatus.MISMATCH,
        timestampDeltaSeconds=timedelta(minutes=6).total_seconds(),
        timestampToleranceSeconds=300,
        timestampTimezone="Asia/Ho_Chi_Minh",
        timestampBasis="CANONICAL_UTC",
    )

    data = result.model_dump(by_alias=True)
    assert data["timestampStatus"] == "MISMATCH"
    assert data["timestampDeltaSeconds"] == 360.0
    assert data["timestampBasis"] == "CANONICAL_UTC"


def test_scoped_delete_reuses_canonical_key_expression_and_sql_hardening():
    sql = PostgresReconciliationExecutor._delete_sql(
        "file-id", ReconciliationScopeType.INCREMENTAL_APPEND
    )
    assert "partner_trace" in sql
    assert "partner_metadata->>'vspTransId'" in sql
    assert "partner_id" in sql


def test_evidence_id_arrays_are_cast_to_jsonb_at_insert_boundary():
    executor_source = inspect.getsource(PostgresReconciliationExecutor.execute)

    # The INSERT is assembled inside execute; keep this contract focused on the
    # SQL expression that prevents PostgreSQL JSONB/array type mismatches.
    assert "to_jsonb(COALESCE(pg.record_ids, ARRAY[]::VARCHAR[]))" in executor_source
    assert "to_jsonb(COALESCE(ig.record_ids, ARRAY[]::VARCHAR[]))" in executor_source
    assert "to_jsonb(ARRAY[CAST(p.id AS VARCHAR)])" in executor_source
    assert "to_jsonb(ARRAY[CAST(i.id AS VARCHAR)])" in executor_source
