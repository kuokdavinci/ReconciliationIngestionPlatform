import argparse
import asyncio
from datetime import datetime, timedelta, timezone

from motor.motor_asyncio import AsyncIOMotorClient

from src.config.settings import settings


PARTNER = "VNPAY"
SEED_PREFIX = "seed-audit-vnpay"
DEFAULT_DATE = "2026-06-17"


def _parse_args():
    parser = argparse.ArgumentParser(
        description="Seed 20 fresh VNPAY audit-flow records for UI testing."
    )
    parser.add_argument(
        "--date",
        default=DEFAULT_DATE,
        help="Reconciliation date in YYYY-MM-DD format.",
    )
    return parser.parse_args()


def _day_start(date_text: str) -> datetime:
    return datetime.strptime(date_text, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _ts(day: datetime, minutes: int) -> datetime:
    return day.replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(minutes=minutes)


def _packet_doc(
    packet_id: str,
    mapping_id: str,
    mapping_version: str,
    file_id: str,
    date_text: str,
    created_at: datetime,
) -> dict:
    return {
        "_id": packet_id,
        "sourceType": "SCHEDULER_JOB",
        "partner": PARTNER,
        "fileName": f"settlement_{PARTNER}_{date_text.replace('-', '')}.xlsx",
        "fileTypeDetected": "SETTLEMENT",
        "draftMappingId": mapping_id,
        "draftMappingVersion": mapping_version,
        "sourceFileId": file_id,
        "reconciliationDate": _day_start(date_text),
        "scopeType": "FULL_SNAPSHOT",
        "scopeConfidence": 0.97,
        "scopeReason": ["seeded audit flow"],
        "scopeSignals": {"seedTag": SEED_PREFIX},
        "recommendedAction": {"type": "APPROVE"},
        "parseStrategy": {"sheetName": "Sheet1", "startRow": 2},
        "validationGates": [],
        "samplePreview": [],
        "riskSummary": {"level": "LOW"},
        "runtimeDecisionHint": "APPROVE_ACTIVATE_NEXT_RUNTIME",
        "status": "APPROVED",
        "decisionMode": "APPROVE_ACTIVATE_NEXT_RUNTIME",
        "createdAt": created_at,
        "reviewedAt": created_at,
        "reviewedBy": "seed-bot",
    }


def _mapping_doc(mapping_id: str, version: str, created_at: datetime) -> dict:
    return {
        "_id": mapping_id,
        "partner": PARTNER,
        "workflowType": "UPC",
        "fileType": "SETTLEMENT",
        "sheetName": "Sheet1",
        "startRow": 2,
        "fieldMappings": [
            {"path": "id", "column": 1, "type": "STRING", "required": True},
            {"path": "trace", "column": 2, "type": "STRING"},
            {"path": "amount", "column": 3, "type": "DECIMAL"},
            {"path": "status", "column": 4, "type": "STRING"},
        ],
        "configVersion": version,
        "configHealth": {"status": "SEEDED", "seedTag": SEED_PREFIX},
        "status": "SUPERSEDED",
        "approvedAt": created_at,
        "approvedBy": "seed-bot",
        "createdAt": created_at,
    }


def _runtime_doc(run_id: str, file_id: str, version: str, date_text: str, created_at: datetime) -> dict:
    return {
        "_id": run_id,
        "partner": PARTNER,
        "date": date_text,
        "triggerType": "POST_APPROVAL_REPROCESS",
        "status": "COMPLETED",
        "message": "Seeded audit runtime completed.",
        "sourceFileId": file_id,
        "fileName": f"settlement_{PARTNER}_{date_text.replace('-', '')}.xlsx",
        "mappingVersion": version,
        "validationState": "NOT_RUN",
        "stats": {"resultCount": 20, "seedTag": SEED_PREFIX},
        "reconciliationCount": 20,
        "startedAt": created_at,
        "finishedAt": created_at,
        "createdAt": created_at,
        "updatedAt": created_at,
    }


def _file_doc(file_id: str, version: str, date_text: str, created_at: datetime) -> dict:
    recon_date = _day_start(date_text)
    compact_date = date_text.replace("-", "")
    return {
        "_id": file_id,
        "partner": PARTNER,
        "fileName": f"settlement_{PARTNER}_{compact_date}.xlsx",
        "fileHash": f"{SEED_PREFIX}-{compact_date}-{file_id}",
        "fileType": "SETTLEMENT",
        "reconciliationDate": recon_date,
        "processingStatus": "COMPLETED",
        "totalRows": 20,
        "successRows": 20,
        "failedRows": 0,
        "configVersion": version,
        "scopeType": "FULL_SNAPSHOT",
        "scopeConfidence": 0.97,
        "scopeReason": ["seeded audit flow"],
        "scopeSignals": {"seedTag": SEED_PREFIX},
        "uploadedAt": created_at,
        "createdBy": SEED_PREFIX,
        "createdAt": created_at,
    }


def _audit_doc(
    event_id: str,
    entity_type: str,
    entity_id: str,
    action: str,
    date_text: str,
    created_at: datetime,
    metadata: dict,
) -> dict:
    return {
        "_id": event_id,
        "entityType": entity_type,
        "entityId": entity_id,
        "action": action,
        "actor": "seed-bot",
        "metadata": metadata,
        "createdAt": created_at,
    }


async def main():
    args = _parse_args()
    date_text = args.date
    day = _day_start(date_text)

    client = AsyncIOMotorClient(settings.mongodb_url, serverSelectionTimeoutMS=5000)
    db = client[settings.db_name]
    await client.admin.command("ping")

    await db["audit_event"].delete_many({"metadata.seedTag": SEED_PREFIX, "metadata.date": date_text})
    await db["review_packet"].delete_many({"partner": PARTNER, "scopeSignals.seedTag": SEED_PREFIX, "reconciliationDate": day})
    await db["reconciliation_mapping_config"].delete_many({"partner": PARTNER, "configHealth.seedTag": SEED_PREFIX})
    await db["partner_runtime_run"].delete_many({"partner": PARTNER, "stats.seedTag": SEED_PREFIX, "date": date_text})
    await db["reconciliation_file"].delete_many({"partner": PARTNER, "createdBy": SEED_PREFIX, "reconciliationDate": day})

    audit_events = []
    packets = []
    mappings = []
    runs = []
    files = []

    for index in range(1, 6):
        slot = _ts(day, index * 3)
        suffix = f"{date_text.replace('-', '')}-{index:02d}"
        packet_id = f"{SEED_PREFIX}-packet-{suffix}"
        mapping_id = f"{SEED_PREFIX}-map-{suffix}"
        run_id = f"{SEED_PREFIX}-run-{suffix}"
        file_id = f"{SEED_PREFIX}-file-{suffix}"
        version = f"VNPAY_v9{index:02d}"

        files.append(_file_doc(file_id, version, date_text, slot))
        mappings.append(_mapping_doc(mapping_id, version, slot))
        packets.append(_packet_doc(packet_id, mapping_id, version, file_id, date_text, slot))
        runs.append(_runtime_doc(run_id, file_id, version, date_text, slot))

        audit_events.extend(
            [
                _audit_doc(
                    event_id=f"{SEED_PREFIX}-event-packet-{suffix}",
                    entity_type="REVIEW_PACKET",
                    entity_id=packet_id,
                    action="APPROVE_ACTIVATE_NEXT_RUNTIME",
                    date_text=date_text,
                    created_at=slot,
                    metadata={
                        "partner": PARTNER,
                        "date": date_text,
                        "reference": version,
                        "status": "APPROVED",
                        "draftMappingId": mapping_id,
                        "draftMappingVersion": version,
                        "sourceFileId": file_id,
                        "seedTag": SEED_PREFIX,
                    },
                ),
                _audit_doc(
                    event_id=f"{SEED_PREFIX}-event-mapping-{suffix}",
                    entity_type="MAPPING_CONFIG",
                    entity_id=mapping_id,
                    action="APPROVED",
                    date_text=date_text,
                    created_at=slot,
                    metadata={
                        "partner": PARTNER,
                        "date": date_text,
                        "reference": version,
                        "status": "APPROVED",
                        "mappingVersion": version,
                        "seedTag": SEED_PREFIX,
                    },
                ),
                _audit_doc(
                    event_id=f"{SEED_PREFIX}-event-run-{suffix}",
                    entity_type="RECONCILIATION_RUN",
                    entity_id=run_id,
                    action="COMPLETED",
                    date_text=date_text,
                    created_at=slot,
                    metadata={
                        "partner": PARTNER,
                        "date": date_text,
                        "reference": run_id,
                        "status": "COMPLETED",
                        "mappingVersion": version,
                        "sourceFileId": file_id,
                        "reconciliationCount": 20,
                        "seedTag": SEED_PREFIX,
                    },
                ),
                _audit_doc(
                    event_id=f"{SEED_PREFIX}-event-packet-reject-{suffix}",
                    entity_type="REVIEW_PACKET",
                    entity_id=f"{packet_id}-rejected",
                    action="REJECT",
                    date_text=date_text,
                    created_at=slot,
                    metadata={
                        "partner": PARTNER,
                        "date": date_text,
                        "reference": f"{version}-reject",
                        "status": "REJECTED",
                        "draftMappingId": mapping_id,
                        "draftMappingVersion": version,
                        "sourceFileId": file_id,
                        "seedTag": SEED_PREFIX,
                    },
                ),
            ]
        )

    rejected_packets = []
    for index in range(1, 6):
        slot = _ts(day, 30 + index * 3)
        suffix = f"{date_text.replace('-', '')}-{index:02d}"
        rejected_packet_id = f"{SEED_PREFIX}-packet-{suffix}-rejected"
        rejected_packets.append(
            {
                **_packet_doc(
                    rejected_packet_id,
                    f"{SEED_PREFIX}-map-{suffix}",
                    f"VNPAY_v9{index:02d}",
                    f"{SEED_PREFIX}-file-{suffix}",
                    date_text,
                    slot,
                ),
                "status": "REJECTED",
                "decisionMode": "REJECT",
                "runtimeDecisionHint": "REJECT",
            }
        )
    packets.extend(rejected_packets)

    await db["reconciliation_file"].insert_many(files)
    await db["reconciliation_mapping_config"].insert_many(mappings)
    await db["review_packet"].insert_many(packets)
    await db["partner_runtime_run"].insert_many(runs)
    await db["audit_event"].insert_many(audit_events)

    print(
        f"Seeded {len(audit_events)} audit events for {PARTNER} on {date_text} "
        f"across {len(files)} files, {len(mappings)} mappings, {len(runs)} runs, {len(packets)} packets."
    )

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
