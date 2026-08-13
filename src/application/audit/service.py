"""Application service for append-only audit logging."""

from typing import Any, Optional

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
    event = AuditEvent(
        entityType=entity_type,
        entityId=entity_id,
        action=action,
        actor=actor,
        metadata=metadata or {},
    )
    await AuditEventRepository(db).create(event)
    return event
