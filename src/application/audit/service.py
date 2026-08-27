"""Application service for append-only audit logging."""

from typing import Any, Optional

from pymongo.errors import DuplicateKeyError

from src.domain.audit.models import AuditEvent
from src.infrastructure.audit.repository import AuditEventRepository


async def record_audit_event(
    db,
    *,
    entity_type: str,
    entity_id: str,
    action: str,
    actor: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> AuditEvent:
    repository = AuditEventRepository(db)
    audit_metadata = metadata or {}
    action_id = audit_metadata.get("actionId")
    if isinstance(action_id, str) and action_id:
        existing = await repository.find_by_action_id(entity_type, entity_id, action_id)
        if existing is not None:
            return existing
    event = AuditEvent(
        entityType=entity_type,
        entityId=entity_id,
        action=action,
        actor=actor,
        metadata=metadata or {},
    )
    try:
        await repository.create(event)
    except DuplicateKeyError:
        if isinstance(action_id, str) and action_id:
            existing = await repository.find_by_action_id(entity_type, entity_id, action_id)
            if existing is not None:
                return existing
        raise
    return event
