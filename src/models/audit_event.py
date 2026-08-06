"""Compatibility facade for audit domain and persistence types."""

from src.domain.audit.models import AuditEvent
from src.infrastructure.audit.repository import AuditEventRepository

__all__ = ["AuditEvent", "AuditEventRepository"]
