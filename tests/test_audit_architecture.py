"""Architecture checks for the audit bounded context."""

from src.domain.audit.models import AuditEvent
from src.infrastructure.audit.repository import AuditEventRepository
from src.models.audit_event import (
    AuditEvent as LegacyAuditEvent,
    AuditEventRepository as LegacyAuditEventRepository,
)


def test_legacy_audit_module_is_a_compatibility_facade() -> None:
    """Legacy imports must resolve to domain and infrastructure implementations."""

    assert LegacyAuditEvent is AuditEvent
    assert LegacyAuditEventRepository is AuditEventRepository
