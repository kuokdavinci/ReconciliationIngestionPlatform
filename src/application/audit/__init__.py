"""Application services for append-only audit logging."""

from src.application.audit.service import record_audit_event

__all__ = ["record_audit_event"]
