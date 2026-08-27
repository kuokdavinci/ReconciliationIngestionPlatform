"""Application use cases for manual reconciliation runs."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from src.application.reconciliation.queries import (
    ReconciliationContextQuery,
    ReconciliationRunContext,
)
from src.core.utils import summarize_runtime_error
from src.domain.runtime.models import (
    PartnerRuntimeRun,
    PartnerRuntimeRunStatus,
    PartnerRuntimeTriggerType,
)


@dataclass(frozen=True)
class QueueManualReconciliationCommand:
    partner: str
    date: str
    triggered_by: str


class ManualReconciliationService:
    """Own runtime transitions and execution for one manual reconciliation."""

    def __init__(
        self,
        *,
        runtime_service,
        reconciliation_service,
        audit_service,
        context_query: ReconciliationContextQuery,
    ) -> None:
        self.runtime_service = runtime_service
        self.reconciliation_service = reconciliation_service
        self.audit_service = audit_service
        self.context_query = context_query

    async def queue(
        self,
        command: QueueManualReconciliationCommand,
        *,
        context: ReconciliationRunContext | None = None,
    ) -> PartnerRuntimeRun:
        context = context or await self.context_query.resolve(command.partner, command.date)
        return await self.runtime_service.create(
            partner=command.partner,
            date=command.date,
            trigger_type=PartnerRuntimeTriggerType.MANUAL_RECONCILIATION,
            triggered_by=command.triggered_by,
            status=PartnerRuntimeRunStatus.QUEUED,
            message="Reconciliation is queued.",
            validation_state="NOT_RUN",
            source_file_id=context.source_file_id,
            mapping_version=context.mapping_version,
        )

    async def execute(self, run_id: str, context: ReconciliationRunContext) -> None:
        started_at = datetime.now(UTC)
        await self.runtime_service.update(
            run_id,
            status=PartnerRuntimeRunStatus.RECONCILING,
            message="Reconciling records for the selected partner/date.",
            started_at=started_at,
            source_file_id=context.source_file_id,
            mapping_version=context.mapping_version,
        )
        try:
            reconciliation_date = datetime.strptime(
                context.date, "%Y-%m-%d"
            ).replace(tzinfo=UTC)
            results = await self.reconciliation_service.reconcile(
                context.partner,
                reconciliation_date,
                source_file_id=context.source_file_id,
                reconciliation_run_id=run_id,
                mapping_version=context.mapping_version,
            )
            finished_at = datetime.now(UTC)
            await self.runtime_service.update(
                run_id,
                status=PartnerRuntimeRunStatus.COMPLETED,
                message="Reconciliation completed successfully.",
                validation_state="NOT_RUN",
                stats={"resultCount": len(results)},
                reconciliation_count=len(results),
                finished_at=finished_at,
            )
            await self.audit_service.record(
                entity_type="RECONCILIATION_RUN",
                entity_id=run_id,
                action="COMPLETED",
                metadata=self._audit_metadata(context, PartnerRuntimeRunStatus.COMPLETED.value, run_id),
            )
        except Exception as exc:
            finished_at = datetime.now(UTC)
            error = summarize_runtime_error(exc)
            await self.runtime_service.update(
                run_id,
                status=PartnerRuntimeRunStatus.FAILED,
                message=f"Reconciliation failed: {error}",
                finished_at=finished_at,
            )
            await self.audit_service.record(
                entity_type="RECONCILIATION_RUN",
                entity_id=run_id,
                action="FAILED",
                metadata={
                    **self._audit_metadata(context, PartnerRuntimeRunStatus.FAILED.value, run_id),
                    "error": error,
                },
            )

    @staticmethod
    def _audit_metadata(
        context: ReconciliationRunContext,
        status: str,
        run_id: str,
    ) -> dict[str, Any]:
        return {
            "partner": context.partner,
            "date": context.date,
            "status": status,
            "reference": run_id,
            "sourceFileId": context.source_file_id,
            "mappingVersion": context.mapping_version,
        }
