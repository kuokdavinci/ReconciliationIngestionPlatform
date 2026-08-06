"""Persistence adapters for append-only audit events."""

from .repository import AuditEventRepository

__all__ = ["AuditEventRepository"]
