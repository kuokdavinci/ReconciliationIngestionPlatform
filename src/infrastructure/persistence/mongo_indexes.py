"""MongoDB index definitions and startup application adapter."""

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, IndexModel


INDEXES: dict[str, list[IndexModel]] = {
    "reconciliation_file": [
        IndexModel("fileHash", unique=True, name="idx_file_hash_unique"),
        IndexModel("fetchUnitKey", unique=True, sparse=True, name="idx_fetch_unit_key_unique"),
        IndexModel(
            [("partner", ASCENDING), ("reconciliationDate", ASCENDING)],
            name="idx_partner_date",
        ),
        IndexModel(
            [("processingStatus", ASCENDING), ("createdAt", DESCENDING)],
            name="idx_file_processing_status_created",
        ),
    ],
    "ingestion_quarantine_record": [
        IndexModel(
            [("sourceFileId", ASCENDING), ("rowNumber", ASCENDING)],
            name="idx_quarantine_source_file_row",
        ),
        IndexModel(
            [("partner", ASCENDING), ("status", ASCENDING), ("createdAt", ASCENDING)],
            name="idx_quarantine_partner_status_created",
        ),
        IndexModel(
            [("status", ASCENDING), ("updatedAt", DESCENDING)],
            name="idx_quarantine_status_updated",
        ),
    ],
    "reconciliation_mapping_config": [
        IndexModel(
            [("partner", ASCENDING), ("workflowType", ASCENDING), ("fileType", ASCENDING)],
            name="idx_partner_workflow_type",
        ),
        IndexModel(
            [("partner", ASCENDING), ("workflowType", ASCENDING), ("fileType", ASCENDING), ("status", ASCENDING)],
            unique=True,
            partialFilterExpression={"status": "APPROVED"},
            name="idx_partner_workflow_type_single_approved",
        ),
    ],
    "copilot_action": [
        IndexModel(
            [("status", ASCENDING), ("type", ASCENDING), ("partner", ASCENDING)],
            name="idx_copilot_action_status_type_partner",
        ),
    ],
    "review_packet": [
        IndexModel(
            [("status", ASCENDING), ("partner", ASCENDING), ("createdAt", ASCENDING)],
            name="idx_review_packet_status_partner_created",
        ),
        IndexModel([("draftMappingId", ASCENDING)], name="idx_review_packet_draft_mapping"),
    ],
    "post_approval_run": [
        IndexModel(
            [("packetId", ASCENDING), ("createdAt", ASCENDING)],
            name="idx_post_approval_run_packet_created",
        ),
        IndexModel(
            [("status", ASCENDING), ("updatedAt", ASCENDING)],
            name="idx_post_approval_run_status_updated",
        ),
    ],
    "partner_runtime_run": [
        IndexModel(
            [("partner", ASCENDING), ("date", ASCENDING), ("createdAt", ASCENDING)],
            name="idx_partner_runtime_run_partner_date_created",
        ),
        IndexModel(
            [("status", ASCENDING), ("updatedAt", ASCENDING)],
            name="idx_partner_runtime_run_status_updated",
        ),
        IndexModel(
            [("sourceFileId", ASCENDING), ("createdAt", ASCENDING)],
            name="idx_partner_runtime_run_source_file_created",
        ),
    ],
    "reconciliation_run": [
        IndexModel(
            [("partner", ASCENDING), ("date", ASCENDING), ("createdAt", ASCENDING)],
            name="idx_reconciliation_run_partner_date_created",
        ),
    ],
    "audit_event": [
        IndexModel(
            [("entityType", ASCENDING), ("entityId", ASCENDING), ("createdAt", DESCENDING)],
            name="idx_audit_entity_created",
        ),
        IndexModel(
            [("action", ASCENDING), ("createdAt", DESCENDING)],
            name="idx_audit_action_created",
        ),
    ],
    "reconciliation_review_record": [
        IndexModel(
            [("partner", ASCENDING), ("date", ASCENDING), ("recordKey", ASCENDING)],
            unique=True,
            name="idx_recon_review_partner_date_key",
        ),
    ],
}


async def apply_indexes(db: AsyncIOMotorDatabase) -> None:
    """Create all MongoDB indexes and normalize legacy mapping documents."""

    for collection_name, indexes in INDEXES.items():
        await db[collection_name].create_indexes(indexes)

    await db["reconciliation_mapping_config"].update_many(
        {"status": {"$exists": False}},
        {"$set": {"status": "APPROVED"}},
    )
