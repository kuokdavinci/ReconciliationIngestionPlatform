"""MongoDB adapters for review and post-approval workflows."""

from datetime import datetime
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from src.domain.review.models import (
    CopilotAction,
    CopilotActionStatus,
    PostApprovalRun,
    ReconciliationReviewRecord,
    ReviewPacket,
    ReviewPacketSourceType,
    ReviewPacketStatus,
)
from src.infrastructure.persistence.mongo_repository import BaseRepository


class PostApprovalRunRepository(BaseRepository[PostApprovalRun]):
    """Repository for long-running post-approval processing state."""

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(collection_name="post_approval_run", db=db)
        self._set_model_class(PostApprovalRun)

    async def find_latest_by_packet_id(self, packet_id: str) -> Optional[PostApprovalRun]:
        raw = await self.collection.find_one(
            {"packetId": packet_id},
            sort=[("createdAt", -1)],
        )
        if raw is None:
            return None
        return self._from_mongo(raw)


class ReconciliationReviewRecordRepository(BaseRepository[ReconciliationReviewRecord]):
    """Repository for reconciliation review notes and resolution state."""

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(collection_name="reconciliation_review_record", db=db)
        self._set_model_class(ReconciliationReviewRecord)

    async def find_by_partner_and_date(
        self, partner: str, date: str
    ) -> list[ReconciliationReviewRecord]:
        return await self.find_many({"partner": partner, "date": date})


class ReviewPacketRepository(BaseRepository[ReviewPacket]):
    """Repository for approval-desk review packets."""

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(collection_name="review_packet", db=db)
        self._set_model_class(ReviewPacket)

    async def find_latest_by_proposal(self, proposal_config_id: str) -> Optional[ReviewPacket]:
        raw = await self.collection.find_one(
            {"$or": [{"draftMappingId": proposal_config_id}, {"proposalConfigId": proposal_config_id}]},
            sort=[("createdAt", -1)],
        )
        if raw is None:
            return None
        return self._from_mongo(raw)

    async def find_latest_pending_by_stage(
        self,
        *,
        partner: str,
        raw_stage_key: str,
        file_type: str,
    ) -> Optional[ReviewPacket]:
        """Find the one pending scheduler packet for a staged source stream.

        ``rawStageKey`` is stable across Airflow retries, so it is the
        idempotency boundary for a full paginated fetch.  Looking up by this
        key also repairs older runs where the proposal id was not persisted
        consistently under the ``draftMappingId``/``proposalConfigId`` alias.
        """

        raw = await self.collection.find_one(
            {
                "partner": partner,
                "sourceType": ReviewPacketSourceType.SCHEDULER_JOB.value,
                "fileTypeDetected": file_type,
                "rawStageKey": raw_stage_key,
                "status": ReviewPacketStatus.PENDING.value,
            },
            sort=[("createdAt", -1)],
        )
        if raw is None:
            return None
        return self._from_mongo(raw)

    async def sync_mapping_status(
        self,
        config_id: str,
        status: ReviewPacketStatus,
        reviewed_at: datetime,
    ) -> int:
        result = await self.collection.update_many(
            {
                "$or": [
                    {"draftMappingId": str(config_id)},
                    {"proposalConfigId": str(config_id)},
                ],
                "status": ReviewPacketStatus.PENDING.value,
            },
            {
                "$set": {
                    "status": status.value,
                    "reviewedAt": reviewed_at,
                }
            },
        )
        return result.modified_count


class CopilotActionRepository(BaseRepository[CopilotAction]):
    """Repository for copilot approval items."""

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(collection_name="copilot_action", db=db)
        self._set_model_class(CopilotAction)

    async def sync_mapping_status(
        self,
        config_id: str,
        status: CopilotActionStatus,
        reviewed_by: str | None,
        reviewed_at: datetime,
    ) -> int:
        result = await self.collection.update_many(
            {
                "$or": [
                    {"draftMappingId": str(config_id)},
                    {"targetConfigId": str(config_id)},
                ],
                "status": CopilotActionStatus.PENDING_APPROVAL.value,
            },
            {
                "$set": {
                    "status": status.value,
                    "reviewedAt": reviewed_at,
                    "reviewedBy": reviewed_by,
                }
            },
        )
        return result.modified_count
