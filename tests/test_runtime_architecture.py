"""Architecture checks for the runtime visibility bounded context."""

from src.domain.runtime.models import (
    PartnerRuntimeRun,
    PartnerRuntimeRunStatus,
    PartnerRuntimeTriggerType,
)
from src.infrastructure.runtime.repository import PartnerRuntimeRunRepository
from src.models.partner_runtime_run import (
    PartnerRuntimeRun as LegacyPartnerRuntimeRun,
    PartnerRuntimeRunRepository as LegacyPartnerRuntimeRunRepository,
    PartnerRuntimeRunStatus as LegacyPartnerRuntimeRunStatus,
    PartnerRuntimeTriggerType as LegacyPartnerRuntimeTriggerType,
)


def test_legacy_runtime_module_is_a_compatibility_facade() -> None:
    """Legacy imports must resolve to domain and infrastructure implementations."""

    assert LegacyPartnerRuntimeRun is PartnerRuntimeRun
    assert LegacyPartnerRuntimeRunRepository is PartnerRuntimeRunRepository
    assert LegacyPartnerRuntimeRunStatus is PartnerRuntimeRunStatus
    assert LegacyPartnerRuntimeTriggerType is PartnerRuntimeTriggerType
