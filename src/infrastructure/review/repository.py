"""MongoDB adapters for review and post-approval workflows."""

from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from src.domain.review.models import (
    CopilotAction,
    PostApprovalRun,
    ReconciliationReviewRecord,
    ReviewPacket,
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


class CopilotActionRepository(BaseRepository[CopilotAction]):
    """Repository for copilot approval items."""

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(collection_name="copilot_action", db=db)
        self._set_model_class(CopilotAction)
