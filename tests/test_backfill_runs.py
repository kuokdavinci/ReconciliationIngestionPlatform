from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.application.automation.workflows import (
    WorkflowProvider,
    WorkflowSubmission,
    WorkflowSubmissionState,
)
from src.domain.fetch_config.models import FetchConfig, FetchMethod, FileDropConfig
from src.domain.ingestion.checkpoints import IngestionMode


class _FakeFetchRepo:
    def __init__(self, config: FetchConfig | None):
        self._config = config

    async def find_by_partner(self, partner: str) -> FetchConfig | None:
        if self._config is None or self._config.partner != partner:
            return None
        return self._config

    async def find_by_id(self, config_id: str) -> FetchConfig | None:
        if self._config is None or str(self._config.id) != config_id:
            return None
        return self._config


class _FakeBackfillRepo:
    def __init__(self) -> None:
        self.created = []
        self.by_id = {}

    async def create(self, run):
        self.created.append(run)
        self.by_id[str(run.id)] = run
        return run

    async def find_by_id(self, backfill_run_id: str):
        return self.by_id.get(backfill_run_id)

    async def update_status(self, backfill_run_id: str, **changes):
        run = self.by_id[backfill_run_id]
        aliases = {
            "approvalRequired": "approval_required",
            "configVersion": "config_version",
            "mappingVersion": "mapping_version",
            "currentDate": "current_date",
            "completedDays": "completed_days",
            "approvalContext": "approval_context",
        }
        for key, value in changes.items():
            setattr(run, aliases.get(key, key), value)
        return True


def _config(*, enabled: bool = True) -> FetchConfig:
    return FetchConfig(
        _id="123e4567-e89b-12d3-a456-426614174111",
        partner="VNPAY",
        fetchMethod=FetchMethod.FILEDROP,
        enabled=enabled,
        schedule="0 0 * * *",
        localDownloadDir="./mock_data",
        filedrop=FileDropConfig(
            directory="./mock_data/vnpay",
            pattern="settlement_VNPAY_{date:%Y%m%d}.xlsx",
        ),
        updatedAt=datetime(2026, 8, 12, 1, 2, 3, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_start_backfill_rejects_invalid_or_empty_business_date_ranges():
    from src.services.backfill_runs import BackfillRunValidationError, BackfillRunService

    service = BackfillRunService(
        fetch_repo=_FakeFetchRepo(_config()),
        backfill_repo=_FakeBackfillRepo(),
        workflow_gateway=SimpleNamespace(trigger=AsyncMock()),
        approved_mapping_version_finder=AsyncMock(return_value="VNPAY_v03"),
    )

    with pytest.raises(BackfillRunValidationError, match="fromDate"):
        await service.start(
            partner="VNPAY",
            actor="ops-user",
            from_date=date(2026, 8, 12),
            to_date=date(2026, 8, 11),
        )

    with pytest.raises(BackfillRunValidationError, match="business day"):
        await service.start(
            partner="VNPAY",
            actor="ops-user",
            from_date=date(2026, 8, 8),
            to_date=date(2026, 8, 9),
        )


@pytest.mark.asyncio
async def test_start_backfill_creates_waiting_config_parent_with_ordered_days():
    from src.domain.backfill.models import BackfillRunStatus
    from src.services.backfill_runs import BackfillRunService

    gateway = SimpleNamespace(trigger=AsyncMock())
    service = BackfillRunService(
        fetch_repo=_FakeFetchRepo(_config()),
        backfill_repo=_FakeBackfillRepo(),
        workflow_gateway=gateway,
        approved_mapping_version_finder=AsyncMock(return_value=None),
    )

    run = await service.start(
        partner="VNPAY",
        actor="ops-user",
        from_date=date(2026, 8, 7),
        to_date=date(2026, 8, 11),
    )

    assert run.status == BackfillRunStatus.WAITING_CONFIG
    assert run.approval_required is True
    assert run.config_version == "2026-08-12 01:02:03+00:00"
    assert run.mapping_version is None
    assert run.current_date == date(2026, 8, 7)
    assert run.completed_days == 0
    assert run.total_days == 3
    assert [day.business_date for day in run.days] == [
        date(2026, 8, 7),
        date(2026, 8, 10),
        date(2026, 8, 11),
    ]
    gateway.trigger.assert_not_awaited()


@pytest.mark.asyncio
async def test_start_backfill_submits_identifier_only_airflow_command_when_mapping_is_approved():
    from src.domain.backfill.models import BackfillRunStatus
    from src.services.backfill_runs import BackfillRunService

    gateway = SimpleNamespace(
        trigger=AsyncMock(
            return_value=WorkflowSubmission(
                provider=WorkflowProvider.AIRFLOW,
                workflowId="reconciliation_ingestion",
                workflowRunId="manual__backfill-1",
                state=WorkflowSubmissionState.SUBMITTED,
            )
        )
    )
    service = BackfillRunService(
        fetch_repo=_FakeFetchRepo(_config()),
        backfill_repo=_FakeBackfillRepo(),
        workflow_gateway=gateway,
        approved_mapping_version_finder=AsyncMock(return_value="VNPAY_v03"),
    )

    run = await service.start(
        partner="VNPAY",
        actor="ops-user",
        from_date=date(2026, 8, 7),
        to_date=date(2026, 8, 11),
    )

    command = gateway.trigger.await_args.args[0]
    assert run.status == BackfillRunStatus.QUEUED
    assert run.config_version == "2026-08-12 01:02:03+00:00"
    assert run.mapping_version == "VNPAY_v03"
    assert command.mode == IngestionMode.BACKFILL
    assert command.partner == "VNPAY"
    assert command.fetch_config_id == "123e4567-e89b-12d3-a456-426614174111"
    assert command.config_version == "2026-08-12 01:02:03+00:00"
    assert command.runtime_run_id == str(run.id)
    assert command.backfill_run_id == str(run.id)
    assert command.mapping_version == "VNPAY_v03"
    assert command.from_date == date(2026, 8, 7)
    assert command.to_date == date(2026, 8, 11)
    assert command.reconciliation_date is None


@pytest.mark.asyncio
async def test_resume_after_mapping_approval_reuses_parent_and_submits_one_backfill_command():
    from src.domain.backfill.models import BackfillRunStatus
    from src.services.backfill_runs import BackfillRunService

    gateway = SimpleNamespace(
        trigger=AsyncMock(
            return_value=WorkflowSubmission(
                provider=WorkflowProvider.AIRFLOW,
                workflowId="reconciliation_ingestion",
                workflowRunId="manual__backfill-resumed",
                state=WorkflowSubmissionState.SUBMITTED,
            )
        )
    )
    repo = _FakeBackfillRepo()
    service = BackfillRunService(
        fetch_repo=_FakeFetchRepo(_config()),
        backfill_repo=repo,
        workflow_gateway=gateway,
        approved_mapping_version_finder=AsyncMock(return_value=None),
    )

    waiting_run = await service.start(
        partner="VNPAY",
        actor="ops-user",
        from_date=date(2026, 8, 7),
        to_date=date(2026, 8, 11),
    )
    assert waiting_run.status == BackfillRunStatus.WAITING_CONFIG

    resumed = await service.resume_after_approval(
        backfill_run_id=str(waiting_run.id),
        mapping_version="VNPAY_BACKFILL_V1",
    )

    assert resumed.status == BackfillRunStatus.QUEUED
    assert resumed.approval_required is False
    assert resumed.mapping_version == "VNPAY_BACKFILL_V1"
    assert resumed.orchestration is not None
    assert resumed.orchestration.dag_run_id == "manual__backfill-resumed"
    assert gateway.trigger.await_count == 1
    command = gateway.trigger.await_args.args[0]
    assert command.backfill_run_id == str(waiting_run.id)
    assert command.mode == IngestionMode.BACKFILL
    assert command.mapping_version == "VNPAY_BACKFILL_V1"


def test_serialize_backfill_run_exposes_status_and_day_progress():
    from src.domain.backfill.models import (
        BackfillApprovalContext,
        BackfillDayRecord,
        BackfillDayStatus,
        BackfillRun,
        BackfillRunStatus,
    )
    from src.domain.runtime.models import RuntimeOrchestrationContext
    from src.services.backfill_runs import serialize_backfill_run

    run = BackfillRun(
        _id="backfill-1",
        partner="VNPAY",
        fetchConfigId="cfg-1",
        mode=IngestionMode.BACKFILL,
        status=BackfillRunStatus.WAITING_CONFIG,
        fromDate=date(2026, 8, 7),
        toDate=date(2026, 8, 11),
        currentDate=date(2026, 8, 7),
        completedDays=0,
        totalDays=3,
        approvalRequired=True,
        approvalContext=BackfillApprovalContext(
            workflowType="UPC",
            fileType="SETTLEMENT",
        ),
        days=[
            BackfillDayRecord(
                businessDate=date(2026, 8, 7),
                status=BackfillDayStatus.PENDING,
            )
        ],
        orchestration=RuntimeOrchestrationContext(
            dagId="reconciliation_ingestion",
            dagRunId="manual__backfill-1",
            taskId="run_stream",
            correlationId="backfill:backfill-1",
        ),
    )

    payload = serialize_backfill_run(run)

    assert payload["_id"] == "backfill-1"
    assert payload["status"] == "WAITING_CONFIG"
    assert payload["currentDate"] == "2026-08-07"
    assert payload["completedDays"] == 0
    assert payload["totalDays"] == 3
    assert payload["approvalRequired"] is True
    assert payload["approvalContext"] == {
        "workflowType": "UPC",
        "fileType": "SETTLEMENT",
        "reviewPacketId": None,
        "reason": None,
    }
    assert payload["days"][0]["businessDate"] == "2026-08-07"
    assert payload["orchestration"]["dagRunId"] == "manual__backfill-1"
