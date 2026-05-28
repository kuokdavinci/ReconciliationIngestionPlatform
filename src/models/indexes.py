"""MongoDB index definitions for all collections.

Per requirement.md section 11 (index recommendations) and section 10
(duplicate prevention via fileHash unique index).
"""

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, IndexModel

INDEXES: dict[str, list[IndexModel]] = {
    "reconciliation_file": [
        IndexModel(
            "fileHash",
            unique=True,
            name="idx_file_hash_unique",
        ),
        IndexModel(
            [("partner", ASCENDING), ("reconciliationDate", ASCENDING)],
            name="idx_partner_date",
        ),
    ],
    "reconciliation_mapping_config": [
        IndexModel(
            [
                ("partner", ASCENDING),
                ("workflowType", ASCENDING),
                ("fileType", ASCENDING),
            ],
            name="idx_partner_workflow_type",
        ),
    ],
    "data_container": [
        IndexModel(
            "partnerData.trace",
            name="idx_trace",
        ),
        IndexModel(
            [("identify", ASCENDING), ("reconciliationDate", ASCENDING)],
            name="idx_identify_date",
        ),
        IndexModel(
            "operationStatus",
            name="idx_operation_status",
        ),
        IndexModel(
            "partnerData.status",
            name="idx_partner_status",
        ),
        IndexModel(
            "sourceFileId",
            name="idx_source_file",
        ),
    ],
}


async def apply_indexes(db: AsyncIOMotorDatabase) -> None:
    """Create indexes on all collections if they don't exist.

    MongoDB's create_indexes is idempotent — it only creates indexes
    that don't already exist, making this safe to call on every startup.
    """
    for collection_name, indexes in INDEXES.items():
        await db[collection_name].create_indexes(indexes)
