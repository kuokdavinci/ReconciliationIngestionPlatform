"""Architecture checks for the audit bounded context."""

from src.domain.audit.models import AuditEvent
from src.infrastructure.audit.repository import AuditEventRepository
def test_audit_domain_and_adapter_have_separate_ownership() -> None:
    assert AuditEvent.__module__ == "src.domain.audit.models"
    assert AuditEventRepository.__module__ == "src.infrastructure.audit.repository"
