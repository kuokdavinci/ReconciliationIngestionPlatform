"""MongoDB adapter for append-only audit events."""

from motor.motor_asyncio import AsyncIOMotorDatabase

from src.domain.audit.models import AuditEvent
from src.infrastructure.persistence.mongo_repository import BaseRepository


class AuditEventRepository(BaseRepository[AuditEvent]):
    """Repository for audit event documents."""

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(collection_name="audit_event", db=db)
        self._set_model_class(AuditEvent)

    async def find_by_action_id(
        self,
        entity_type: str,
        entity_id: str,
        action_id: str,
    ) -> AuditEvent | None:
        """Find the one action projection for an entity, if already recorded."""
        return await self.find_one(
            {
                "entityType": entity_type,
                "entityId": entity_id,
                "metadata.actionId": action_id,
            }
        )
