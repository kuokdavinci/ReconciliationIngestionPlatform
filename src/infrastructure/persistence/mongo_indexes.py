"""MongoDB index definitions and startup application adapter."""

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, IndexModel
from pymongo.errors import OperationFailure


INDEXES: dict[str, list[IndexModel]] = {
    "ingestion_checkpoint": [
        IndexModel(
            [("partner", ASCENDING), ("fetchConfigId", ASCENDING), ("sourceType", ASCENDING), ("streamKey", ASCENDING), ("mode", ASCENDING)],
            unique=True,
            name="idx_checkpoint_stream_unique",
        ),
        IndexModel(
            [("status", ASCENDING), ("updatedAt", DESCENDING)],
            name="idx_checkpoint_status_updated",
        ),
        IndexModel(
            [("mode", ASCENDING), ("status", ASCENDING), ("updatedAt", DESCENDING)],
            name="idx_checkpoint_mode_status_updated",
        ),
    ],
    "reconciliation_file": [
        IndexModel(
            [("partner", ASCENDING), ("fileHash", ASCENDING)],
            unique=True,
            name="idx_file_hash_unique",
        ),
        IndexModel(
            "fetchUnitKey",
            unique=True,
            partialFilterExpression={"fetchUnitKey": {"$type": "string"}},
            name="idx_fetch_unit_key_unique",
        ),
        IndexModel(
            [("partner", ASCENDING), ("reconciliationDate", ASCENDING)],
            name="idx_partner_date",
        ),
        IndexModel(
            [("processingStatus", ASCENDING), ("createdAt", DESCENDING)],
            name="idx_file_processing_status_created",
        ),
    ],
    "raw_ingestion_page": [
        IndexModel(
            [("sourceUnitKey", ASCENDING)],
            unique=True,
            name="idx_raw_page_source_unit_unique",
        ),
        IndexModel(
            [("stageKey", ASCENDING), ("page", ASCENDING)],
            name="idx_raw_page_stage_page",
        ),
        IndexModel(
            [("status", ASCENDING), ("expiresAt", ASCENDING)],
            name="idx_raw_page_status_expiry",
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
        IndexModel(
            [("sourceUnitKey", ASCENDING), ("status", ASCENDING), ("createdAt", ASCENDING)],
            name="idx_quarantine_source_unit_status_created",
        ),
        IndexModel(
            [("errors.errorCode", ASCENDING), ("status", ASCENDING), ("createdAt", ASCENDING)],
            name="idx_quarantine_error_status_created",
        ),
        IndexModel(
            [("status", ASCENDING), ("retentionUntil", ASCENDING)],
            name="idx_quarantine_status_retention",
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
    "backfill_run": [
        IndexModel(
            [("partner", ASCENDING), ("fetchConfigId", ASCENDING), ("createdAt", DESCENDING)],
            name="idx_backfill_run_partner_config_created",
        ),
        IndexModel(
            [("status", ASCENDING), ("updatedAt", DESCENDING)],
            name="idx_backfill_run_status_updated",
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


def _index_signature(document: dict) -> dict:
    """Return the key and options that determine MongoDB index identity."""
    return {
        "key": list(document.get("key", {}).items()),
        "unique": document.get("unique", False),
        "sparse": document.get("sparse", False),
        "partialFilterExpression": document.get("partialFilterExpression"),
        "expireAfterSeconds": document.get("expireAfterSeconds"),
        "collation": document.get("collation"),
        "weights": document.get("weights"),
        "default_language": document.get("default_language"),
        "language_override": document.get("language_override"),
        "hidden": document.get("hidden", False),
    }


async def _ensure_collection_indexes(collection, indexes: list[IndexModel]) -> None:
    """Create indexes and replace same-name definitions whose options changed."""
    try:
        existing_indexes = await collection.list_indexes().to_list(length=None)
    except OperationFailure as exc:
        if exc.code == 26:
            await collection.create_indexes(indexes)
            return
        raise
    existing_by_name = {
        index.get("name"): index
        for index in existing_indexes
        if index.get("name")
    }

    for index in indexes:
        name = index.document.get("name")
        existing = existing_by_name.get(name)
        if existing and _index_signature(existing) != _index_signature(index.document):
            await collection.drop_index(name)

    await collection.create_indexes(indexes)


async def apply_indexes(db: AsyncIOMotorDatabase) -> None:
    """Create all MongoDB indexes and normalize legacy mapping documents."""

    for collection_name, indexes in INDEXES.items():
        await _ensure_collection_indexes(db[collection_name], indexes)

    await db["reconciliation_mapping_config"].update_many(
        {"status": {"$exists": False}},
        {"$set": {"status": "APPROVED"}},
    )
