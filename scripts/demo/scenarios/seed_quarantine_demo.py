"""Seed a repeatable, partner-isolated quarantine operator demo."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
import os
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from motor.motor_asyncio import AsyncIOMotorClient
from sqlalchemy import delete

from src.config.settings import settings
from src.core.enums import FileType, ProcessingStatus, TransactionStatus
from src.core.types import FieldMapping, FieldMappingType
from src.domain.fetch_config.models import FetchConfig, FetchMethod, FileDropConfig
from src.domain.internal_transaction.models import InternalTransaction
from src.domain.ingestion.checkpoints import (
    CheckpointStatus,
    IngestionCheckpoint,
    IngestionMode,
    SourceUnitStatus,
    SourceUnitSummary,
)
from src.domain.ingestion.models import ReconciliationFile
from src.domain.ingestion.quarantine import (
    IngestionQuarantineRecord,
    QuarantineAction,
    QuarantinePhase,
    QuarantineResolutionEvent,
    QuarantineSeverity,
    QuarantineStatus,
)
from src.domain.ingestion.raw_pages import RawIngestionPage
from src.domain.mapping.models import MappingConfig, MappingConfigStatus
from src.domain.partner_transaction.models import DataContainer, PartnerData
from src.domain.partner_transaction.duplicates import fingerprint_payload
from src.infrastructure.postgres.internal_transaction_repository import (
    InternalTransactionRepository,
)
from src.infrastructure.partner_transaction.mappers import data_container_to_row
from src.infrastructure.partner_transaction.repository import DataContainerRepository
from src.infrastructure.persistence.mongo_repository import BaseRepository
from src.infrastructure.persistence.postgres_schema import (
    InternalTransactionTable,
    PartnerTransactionTable,
    ReconciliationResultTable,
)


DEMO_PARTNER = "DEMO"
DEMO1_PARTNER = "DEMO1"
DEMO_OPERATOR = "demo-operator"
DEMO_CONFIG_VERSION = "DEMO_v01"
DEMO1_CONFIG_VERSION = "DEMO1_v01"
DEMO_PARTNERS = (DEMO_PARTNER, DEMO1_PARTNER)
_DEMO_NAMESPACE = uuid5(NAMESPACE_URL, "reconciliation-ingestion-platform/quarantine-demo")


def _demo_uuid(name: str) -> UUID:
    return uuid5(_DEMO_NAMESPACE, name)


def _source_file_id(scenario_id: str) -> str:
    return str(_demo_uuid(f"source-file:{scenario_id}"))


def _event(
    *,
    from_status: QuarantineStatus,
    to_status: QuarantineStatus,
    action: QuarantineAction,
    actor: str,
    reason: str,
    attempt: int,
    action_id: str,
    outcome: str,
    timestamp: datetime,
    metadata: dict[str, Any] | None = None,
) -> QuarantineResolutionEvent:
    return QuarantineResolutionEvent(
        eventId=_demo_uuid(f"event:{action_id}"),
        fromStatus=from_status,
        toStatus=to_status,
        action=action,
        actor=actor,
        reason=reason,
        attempt=attempt,
        actionId=action_id,
        outcome=outcome,
        timestamp=timestamp,
        metadata=metadata or {},
    )


def _record(
    *,
    scenario_id: str,
    title: str,
    created_at: datetime,
    now: datetime,
    status: QuarantineStatus = QuarantineStatus.PENDING,
    phase: QuarantinePhase = QuarantinePhase.VALIDATION,
    severity: QuarantineSeverity = QuarantineSeverity.RECORD,
    error_code: str = "MISSING_REQUIRED_FIELD",
    row_number: int = 1,
    source_unit_key: str | None = None,
    source_file_id: str | None = None,
    claimed_by: str | None = None,
    claimed_at: datetime | None = None,
    claim_expires_at: datetime | None = None,
    attempt_count: int = 1,
    escalation_level: int = 0,
    escalated_at: datetime | None = None,
    escalated_by: str | None = None,
    last_action_id: str | None = None,
    existing_fingerprint: str | None = None,
    resolution_history: list[QuarantineResolutionEvent] | None = None,
    raw_row: dict[str, Any] | None = None,
    error_details: dict[str, Any] | None = None,
) -> IngestionQuarantineRecord:
    source_file_id = source_file_id or _source_file_id(scenario_id)
    source_unit_key = source_unit_key or f"demo-unit-{scenario_id.removeprefix('DEMO-').lower()}"
    default_raw_row: dict[str, Any] = {
        "id": f"{scenario_id}-TX",
        "trace": f"TRACE-{scenario_id}-TX",
        "amount": "125000",
        "currency": "VND",
        "status": "SUCCESS",
        "transDate": now.isoformat(),
    }
    if error_code == "INVALID_TIMESTAMP":
        default_raw_row["transDate"] = "27/08/2026"
    error = {
        "errorCode": error_code,
        "phase": phase.value,
        "severity": severity.value,
    }
    if error_details:
        error.update(error_details)
    return IngestionQuarantineRecord(
        _id=_demo_uuid(f"record:{scenario_id}"),
        sourceFileId=source_file_id,
        sourceUnitKey=source_unit_key,
        partner=DEMO_PARTNER,
        reconciliationDate=now.replace(hour=0, minute=0, second=0, microsecond=0),
        rowNumber=row_number,
        rawRow=raw_row or default_raw_row,
        ingestionKey=f"{scenario_id}-TX",
        existingFingerprint=existing_fingerprint,
        errors=[
            error
        ],
        phase=phase,
        severity=severity,
        configVersion=DEMO_CONFIG_VERSION,
        status=status,
        reviewDueAt=created_at + timedelta(hours=settings.ingestion_quarantine_review_sla_hours),
        escalationLevel=escalation_level,
        escalatedAt=escalated_at,
        escalatedBy=escalated_by,
        lastActionId=last_action_id,
        attemptCount=attempt_count,
        claimedBy=claimed_by,
        claimedAt=claimed_at,
        claimExpiresAt=claim_expires_at,
        resolutionMetadata={
            "demoScenarioId": scenario_id,
            "demoTitle": title,
            "demoPartner": DEMO_PARTNER,
        },
        resolutionHistory=resolution_history or [],
        createdAt=created_at,
        updatedAt=now,
    )


def _claimed_record(
    *,
    scenario_id: str,
    title: str,
    now: datetime,
    source_file_id: str,
    error_code: str,
    existing_fingerprint: str | None = None,
) -> IngestionQuarantineRecord:
    created_at = now - timedelta(hours=2)
    claimed_at = created_at + timedelta(minutes=5)
    claim_action_id = f"seed-claim-{scenario_id.removeprefix('DEMO-').lower()}"
    return _record(
        scenario_id=scenario_id,
        title=title,
        created_at=created_at,
        now=now,
        status=QuarantineStatus.REPROCESSING,
        error_code=error_code,
        source_unit_key=f"demo-unit-{scenario_id.removeprefix('DEMO-').lower()}",
        source_file_id=source_file_id,
        claimed_by=DEMO_OPERATOR,
        claimed_at=claimed_at,
        claim_expires_at=now + timedelta(minutes=30),
        attempt_count=2,
        existing_fingerprint=existing_fingerprint,
        last_action_id=claim_action_id,
        resolution_history=[
            _event(
                from_status=QuarantineStatus.PENDING,
                to_status=QuarantineStatus.REPROCESSING,
                action=QuarantineAction.REPROCESS,
                actor=DEMO_OPERATOR,
                reason="Seeded claim for the operator demo.",
                attempt=2,
                action_id=claim_action_id,
                outcome="CLAIMED",
                timestamp=claimed_at,
                metadata={
                    "claimedBy": DEMO_OPERATOR,
                    "priority": "HIGH" if error_code == "CONFLICTING_DUPLICATE" else "NORMAL",
                },
            )
        ],
    )


def _canonical_demo_transaction(
    *,
    transaction_id: str,
    source_file_id: UUID,
    reconciliation_date: datetime,
    amount: Decimal = Decimal("125000"),
    status: str = TransactionStatus.SUCCESS.value,
) -> DataContainer:
    return DataContainer(
        _id=_demo_uuid(f"transaction:{transaction_id}"),
        identify=DEMO_PARTNER,
        workflowType="UPC",
        reconciliationDate=reconciliation_date,
        sourceFileId=source_file_id,
        ingestionKey=transaction_id,
        partnerData=PartnerData(
            _id=transaction_id,
            trace=f"TRACE-{transaction_id}",
            status=status,
            amount=amount,
            currency="VND",
            transDate=reconciliation_date,
            extra={"demo": True},
        ),
        createdBy="demo-seed",
        lastModifiedBy="demo-seed",
    )


def build_demo_quarantine_records(now: datetime | None = None) -> list[IngestionQuarantineRecord]:
    """Build the seven stable records used by the Review Center demo."""
    now = (now or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
    reprocess_file_id = _source_file_id("DEMO-REPROCESS-001")
    accept_file_id = _source_file_id("DEMO-ACCEPT-001")
    recovery_file_id = _source_file_id("DEMO-RECOVERY-001")
    accepted_transaction = _canonical_demo_transaction(
        transaction_id="DEMO-ACCEPT-001-TX",
        source_file_id=UUID(accept_file_id),
        reconciliation_date=now,
    )
    existing_fingerprint = fingerprint_payload(data_container_to_row(accepted_transaction))

    escalated_created = now - timedelta(hours=48)
    escalated_events = [
        _event(
            from_status=QuarantineStatus.PENDING,
            to_status=QuarantineStatus.PENDING,
            action=QuarantineAction.ESCALATE,
            actor="seed-supervisor",
            reason="Initial demo escalation for an overdue case.",
            attempt=1,
            action_id="seed-escalate-demo-1",
            outcome="ESCALATED",
            timestamp=escalated_created + timedelta(hours=24),
            metadata={"escalationLevel": 1},
        ),
        _event(
            from_status=QuarantineStatus.PENDING,
            to_status=QuarantineStatus.PENDING,
            action=QuarantineAction.ESCALATE,
            actor="seed-supervisor",
            reason="Second escalation remains bounded at operator review.",
            attempt=1,
            action_id="seed-escalate-demo-2",
            outcome="ESCALATED",
            timestamp=escalated_created + timedelta(hours=36),
            metadata={"escalationLevel": 2},
        ),
    ]

    rejected_created = now - timedelta(hours=24)
    rejected_claim_id = "seed-claim-reject-001"
    rejected_action_id = "seed-reject-001"
    rejected_events = [
        _event(
            from_status=QuarantineStatus.PENDING,
            to_status=QuarantineStatus.REPROCESSING,
            action=QuarantineAction.REPROCESS,
            actor=DEMO_OPERATOR,
            reason="Seeded claim for the rejected demo case.",
            attempt=2,
            action_id=rejected_claim_id,
            outcome="CLAIMED",
            timestamp=rejected_created + timedelta(minutes=2),
            metadata={"claimedBy": DEMO_OPERATOR},
        ),
        _event(
            from_status=QuarantineStatus.REPROCESSING,
            to_status=QuarantineStatus.REJECTED,
            action=QuarantineAction.REJECT,
            actor=DEMO_OPERATOR,
            reason="Partner confirmed this row is not part of the settlement file.",
            attempt=2,
            action_id=rejected_action_id,
            outcome="REJECTED",
            timestamp=rejected_created + timedelta(minutes=6),
        ),
    ]

    return [
        _record(
            scenario_id="DEMO-INVALID-001",
            title="Missing required settlement status",
            created_at=now - timedelta(hours=1),
            now=now,
            error_code="MISSING_REQUIRED_FIELD",
            raw_row={
                "id": "DEMO-INVALID-001-TX",
                "trace": "TRACE-DEMO-INVALID-001",
                "amount": "125000",
                "currency": "VND",
            },
            error_details={
                "field": "status",
                "reason": "Required field 'status' is empty or missing.",
                "expected": "non-empty value",
                "actual": None,
            },
        ),
        _record(
            scenario_id="DEMO-DUPLICATE-001",
            title="Conflicting duplicate needs priority review",
            created_at=now - timedelta(hours=48),
            now=now,
            phase=QuarantinePhase.BATCH,
            error_code="CONFLICTING_DUPLICATE",
            severity=QuarantineSeverity.RECORD,
            error_details={
                "field": "ingestion_key",
                "reason": "Duplicate key has a conflicting payload.",
            },
        ),
        _claimed_record(
            scenario_id="DEMO-REPROCESS-001",
            title="Replay authoritative source row",
            now=now,
            source_file_id=reprocess_file_id,
            error_code="INVALID_TIMESTAMP",
        ),
        _claimed_record(
            scenario_id="DEMO-ACCEPT-001",
            title="Accept an already persisted equivalent transaction",
            now=now,
            source_file_id=accept_file_id,
            error_code="EQUIVALENT_DUPLICATE",
            existing_fingerprint=existing_fingerprint,
        ),
        _record(
            scenario_id="DEMO-REJECT-001",
            title="Previously rejected by partner operations",
            created_at=rejected_created,
            now=now,
            status=QuarantineStatus.REJECTED,
            error_code="MALFORMED_ROW",
            claimed_by=None,
            attempt_count=2,
            last_action_id=rejected_action_id,
            resolution_history=rejected_events,
        ),
        _record(
            scenario_id="DEMO-ESCALATED-001",
            title="Overdue required identifier review",
            created_at=escalated_created,
            now=now,
            error_code="MISSING_REQUIRED_FIELD",
            raw_row={
                "trace": "TRACE-DEMO-ESCALATED-001",
                "amount": "125000",
                "currency": "VND",
                "status": "SUCCESS",
            },
            error_details={
                "field": "id",
                "reason": "Required field 'id' is empty or missing.",
                "expected": "non-empty value",
                "actual": None,
            },
            escalation_level=2,
            escalated_at=escalated_events[-1].timestamp,
            escalated_by="seed-supervisor",
            last_action_id="seed-escalate-demo-2",
            resolution_history=escalated_events,
        ),
        _record(
            scenario_id="DEMO-RECOVERY-001",
            title="Held source unit ready for resume",
            created_at=now - timedelta(hours=3),
            now=now,
            phase=QuarantinePhase.BATCH,
            error_code="SOURCE_UNIT_RECOVERY_REQUIRED",
            source_unit_key="demo-unit-recovery-001",
            source_file_id=recovery_file_id,
        ),
    ]


def _demo_source_rows(now: datetime | None = None) -> list[dict[str, Any]]:
    """Return 20 rows with one conflict and one row-level missing amount case."""
    now = (now or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
    trans_date = now.isoformat()
    return [
        {
            "id": "DEMO-VALID-001-TX",
            "trace": "DEMO-VALID-001-TX",
            "amount": "125000",
            "currency": "VND",
            "status": "SUCCESS",
            "transDate": trans_date,
        },
        {
            "id": "DEMO-DUPLICATE-001-TX",
            "trace": "DEMO-DUPLICATE-001-TX",
            "amount": "87500",
            "currency": "VND",
            "status": "SUCCESS",
            "transDate": trans_date,
        },
        {
            "id": "DEMO-MISSING-AMOUNT-001-TX",
            "trace": "DEMO-MISSING-AMOUNT-001-TX",
            "currency": "VND",
            "status": "SUCCESS",
            "transDate": trans_date,
        },
        *[
            {
                "id": f"DEMO-VALID-{index:03d}-TX",
                "trace": f"DEMO-VALID-{index:03d}-TX",
                "amount": str(100000 + index * 2500),
                "currency": "VND",
                "status": "SUCCESS",
                "transDate": trans_date,
            }
            for index in range(2, 19)
        ],
    ]


def _demo_batch_fatal_source_rows(now: datetime | None = None) -> list[dict[str, Any]]:
    """Return a source shape missing required ``status`` before row processing."""
    now = (now or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
    return [
        {
            "id": f"DEMO1-BATCH-FATAL-{index:03d}-TX",
            "trace": f"DEMO1-BATCH-FATAL-{index:03d}-TX",
            "amount": str(90000 + index * 1000),
            "currency": "VND",
            "transDate": now.isoformat(),
        }
        for index in range(1, 21)
    ]


def _demo_internal_transactions(now: datetime) -> list[InternalTransaction]:
    """Seed internal source-of-truth rows for the reconciliation demo."""
    return [
        InternalTransaction(
            _id=f"INT_DEMO_{index:03d}",
            partner=DEMO_PARTNER,
            partnerTxnId=row["id"],
            amount=Decimal(row.get("amount", "125000")),
            currency=row["currency"],
            status=TransactionStatus.SUCCESS,
            transactionTime=now,
            createdAt=now,
            updatedAt=now,
        )
        for index, row in enumerate(_demo_source_rows(now), start=1)
    ]


def _mapping_config(
    *,
    partner: str = DEMO1_PARTNER,
    config_version: str = DEMO1_CONFIG_VERSION,
) -> MappingConfig:
    return MappingConfig(
        _id=_demo_uuid(f"mapping:{config_version}"),
        partner=partner,
        workflowType="UPC",
        fileType=FileType.SETTLEMENT,
        sheetName="Sheet1",
        startRow=1,
        configVersion=config_version,
        status=MappingConfigStatus.APPROVED,
        approvedAt=datetime.now(UTC),
        approvedBy="demo-seed",
        fieldMappings=[
            FieldMapping(path="id", sourceField="id", type=FieldMappingType.STRING, required=True),
            FieldMapping(path="trace", sourceField="trace", type=FieldMappingType.STRING),
            FieldMapping(path="amount", sourceField="amount", type=FieldMappingType.DECIMAL, required=True),
            FieldMapping(
                path="status",
                sourceField="status",
                type=FieldMappingType.MAPPING,
                required=True,
                mapping={"SUCCESS": "SUCCESS", "FAILED": "FAILED", "REVERSED": "REVERSED"},
            ),
            FieldMapping(path="transDate", sourceField="transDate", type=FieldMappingType.DATE),
            FieldMapping(path="currency", sourceField="currency", type=FieldMappingType.STRING, required=True),
        ],
        configHealth={"status": "APPROVED", "confidence": 1.0, "reasoning": "Deterministic local demo fixture."},
    )


def _fetch_config(
    config_id: str,
    *,
    partner: str = DEMO_PARTNER,
    schedule: str = "0 0 * * *",
) -> FetchConfig:
    return FetchConfig(
        _id=UUID(config_id),
        partner=partner,
        fetchMethod=FetchMethod.FILEDROP,
        enabled=True,
        schedule=schedule,
        localDownloadDir="mock_data/quarantine_demo",
        cleanupAfterIngest=False,
        filedrop=FileDropConfig(
            directory="./mock_data/quarantine_demo",
            pattern=f"settlement_{partner}_*.json",
        ),
    )


def _source_file(*, scenario_id: str, source_path: Path, fetch_config_id: str, now: datetime) -> ReconciliationFile:
    source_unit_key = f"demo-unit-{scenario_id.removeprefix('DEMO-').lower()}"
    return ReconciliationFile(
        _id=UUID(_source_file_id(scenario_id)),
        partner=DEMO_PARTNER,
        fileName=f"{scenario_id.lower()}.json",
        fileHash=f"demo-hash-{scenario_id.lower()}",
        fileType=FileType.SETTLEMENT,
        reconciliationDate=now,
        processingStatus=ProcessingStatus.PENDING,
        configVersion=DEMO_CONFIG_VERSION,
        fetchUnitKey=source_unit_key,
        fetchUnitMetadata={"sourceUnitKey": source_unit_key, "localPath": str(source_path)},
        sourceFilePath=str(source_path),
        uploadedAt=now,
    )


def _raw_page(*, scenario_id: str, source_path: Path, fetch_config_id: str, now: datetime) -> RawIngestionPage:
    source_unit_key = f"demo-unit-{scenario_id.removeprefix('DEMO-').lower()}"
    return RawIngestionPage(
        _id=_demo_uuid(f"raw-page:{scenario_id}"),
        stageKey=f"demo-stage-{scenario_id.lower()}",
        partner=DEMO_PARTNER,
        fetchConfigId=fetch_config_id,
        sourceType="API",
        streamKey="DEMO:API:scheduled:quarantine-demo",
        reconciliationDate=now,
        sourceUnitKey=source_unit_key,
        page=1,
        contentHash=f"demo-content-{scenario_id.lower()}",
        contentType="application/json",
        itemCount=1,
        hasMore=False,
        sampleRows=[{"id": f"{scenario_id}-TX"}],
        localPath=str(source_path),
        expiresAt=now + timedelta(days=7),
    )


def _checkpoint(*, source_unit_key: str, fetch_config_id: str, now: datetime) -> IngestionCheckpoint:
    return IngestionCheckpoint(
        _id=_demo_uuid("checkpoint:DEMO-RECOVERY-001"),
        partner=DEMO_PARTNER,
        fetchConfigId=fetch_config_id,
        sourceType="API",
        streamKey="DEMO:API:scheduled:quarantine-demo",
        mode=IngestionMode.SCHEDULED,
        currentUnitKey=source_unit_key,
        status=CheckpointStatus.FAILED,
        attemptCount=1,
        lastError="Source unit was held for operator review.",
        errorCode="quarantine_conflict_unresolved",
        retryable=True,
        configVersion=DEMO_CONFIG_VERSION,
        sourceEndpoint="http://demo-source.invalid/api/settlement",
        streamMetadata={"page": 1, "label": "Demo recovery page"},
        unitTimeline=[
            SourceUnitSummary(
                unitKey=source_unit_key,
                label="Demo recovery page",
                page=1,
                status=SourceUnitStatus.FAILED,
                attemptCount=1,
                lastError="Source unit was held for operator review.",
                errorCode="quarantine_conflict_unresolved",
                retryable=True,
            )
        ],
        updatedAt=now,
    )


async def _delete_demo_data(db: Any) -> None:
    for collection_name in (
        "ingestion_quarantine_record",
        "reconciliation_file",
        "raw_ingestion_page",
        "ingestion_checkpoint",
        "fetch_config",
        "reconciliation_mapping_config",
        "review_packet",
        "copilot_action",
        "post_approval_run",
        "partner_runtime_run",
    ):
        await db[collection_name].delete_many({"partner": {"$in": DEMO_PARTNERS}})
    await db["reconciliation_mapping_config_version_counters"].delete_many(
        {"_id": {"$in": DEMO_PARTNERS}}
    )
    await db["audit_event"].delete_many({"metadata.partner": {"$in": DEMO_PARTNERS}})

    transaction_repo = DataContainerRepository()
    async with transaction_repo.engine.begin() as connection:
        await connection.execute(
            delete(PartnerTransactionTable).where(PartnerTransactionTable.identify.in_(DEMO_PARTNERS))
        )
        await connection.execute(
            delete(InternalTransactionTable).where(InternalTransactionTable.partner.in_(DEMO_PARTNERS))
        )
        await connection.execute(
            delete(ReconciliationResultTable).where(ReconciliationResultTable.partner.in_(DEMO_PARTNERS))
        )


async def seed_demo() -> dict[str, Any]:
    now = datetime.now(UTC).replace(microsecond=0)
    data_dir = Path(os.environ.get("QUARANTINE_DEMO_DATA_DIR", "mock_data/quarantine_demo")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    for pattern in ("settlement_DEMO_*.json", "settlement_DEMO1_*.json"):
        for previous_source in data_dir.glob(pattern):
            previous_source.unlink()
    source_path = data_dir / f"settlement_DEMO_{now.strftime('%Y%m%d%H%M%S')}.json"
    fatal_source_path = data_dir / f"settlement_DEMO1_{now.strftime('%Y%m%d%H%M%S')}.json"
    source_rows = _demo_source_rows(now)
    source_path.write_text(json.dumps(source_rows, indent=2), encoding="utf-8")
    fatal_source_path.write_text(
        json.dumps(_demo_batch_fatal_source_rows(now), indent=2),
        encoding="utf-8",
    )

    client: AsyncIOMotorClient = AsyncIOMotorClient(settings.mongodb_url)
    db = client[settings.db_name]
    try:
        await _delete_demo_data(db)
        fetch_configs = [
            _fetch_config(str(_demo_uuid("fetch-config:DEMO")), partner=DEMO_PARTNER),
            _fetch_config(
                str(_demo_uuid("fetch-config:DEMO1")),
                partner=DEMO1_PARTNER,
                schedule="30 0 * * *",
            ),
        ]
        for fetch_config in fetch_configs:
            await db["fetch_config"].insert_one(
                BaseRepository._convert_special_types(fetch_config.model_dump(by_alias=True))
            )
        fatal_mapping = _mapping_config()
        await db["reconciliation_mapping_config"].insert_one(
            BaseRepository._convert_special_types(fatal_mapping.model_dump(by_alias=True))
        )
        existing_transaction = _canonical_demo_transaction(
            transaction_id="DEMO-DUPLICATE-001-TX",
            source_file_id=_demo_uuid("transaction-source:existing-conflict"),
            reconciliation_date=now,
            amount=Decimal("87501"),
        )
        await DataContainerRepository().insert_many([existing_transaction])
        await InternalTransactionRepository().insert_many(_demo_internal_transactions(now))
        return {
            "partner": DEMO_PARTNER,
            "records": len(source_rows),
            "internalRecords": len(source_rows),
            "conflictingDuplicateRecords": 1,
            "missingAmountRecords": 1,
            "expectedRowLevelQuarantineRecords": 2,
            "sourceFile": str(source_path),
            "fatalPartner": DEMO1_PARTNER,
            "fatalSourceFile": str(fatal_source_path),
            "fetchMethod": FetchMethod.FILEDROP.value,
            "nextStep": "Run DEMO from Schedules for the mapping/review flow, or run DEMO1 directly to demonstrate BATCH_FATAL.",
        }
    finally:
        client.close()


async def main(command: str) -> None:
    if command != "reset":
        raise ValueError("Only the reset command is supported")
    result = await seed_demo()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("reset",))
    args = parser.parse_args()
    asyncio.run(main(args.command))
