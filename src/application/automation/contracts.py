"""Typed contract for running one configured ingestion stream."""

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.domain.ingestion.checkpoints import IngestionMode


class ExecuteStreamOutcome(StrEnum):
    COMPLETED = "COMPLETED"
    NO_DATA = "NO_DATA"
    ALREADY_PROCESSED = "ALREADY_PROCESSED"
    SAFE_DUPLICATE = "SAFE_DUPLICATE"
    PARTIAL = "PARTIAL"
    WAITING_REVIEW = "WAITING_REVIEW"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class OrchestrationContext(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    provider: Literal["AIRFLOW"] = "AIRFLOW"
    dag_id: str = Field(alias="dagId")
    dag_run_id: str = Field(alias="dagRunId")
    task_id: str = Field(alias="taskId")
    map_index: int | None = Field(default=None, alias="mapIndex")
    try_number: int = Field(default=1, alias="tryNumber", ge=1)
    logical_date: datetime | None = Field(default=None, alias="logicalDate")


class ExecuteStreamCommand(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_version: Literal[1] = Field(default=1, alias="schemaVersion")
    fetch_config_id: str = Field(alias="fetchConfigId", min_length=1)
    partner: str = Field(min_length=1)
    config_version: str = Field(alias="configVersion", min_length=1)
    mapping_version: str | None = Field(default=None, alias="mappingVersion")
    reconciliation_date: date | None = Field(default=None, alias="reconciliationDate")
    backfill_run_id: str | None = Field(default=None, alias="backfillRunId")
    from_date: date | None = Field(default=None, alias="fromDate")
    to_date: date | None = Field(default=None, alias="toDate")
    mode: IngestionMode = IngestionMode.SCHEDULED
    runtime_run_id: str | None = Field(default=None, alias="runtimeRunId")
    correlation_id: str | None = Field(default=None, alias="correlationId")
    orchestration: OrchestrationContext | None = None

    @model_validator(mode="after")
    def validate_mode_payload(self):
        if self.mode == IngestionMode.BACKFILL:
            if not self.backfill_run_id:
                raise ValueError("backfillRunId is required for BACKFILL mode")
            if self.from_date is None or self.to_date is None:
                raise ValueError("fromDate and toDate are required for BACKFILL mode")
            if self.from_date > self.to_date:
                raise ValueError("fromDate must be on or before toDate")
            return self
        if self.reconciliation_date is None:
            raise ValueError("reconciliationDate is required for SCHEDULED mode")
        return self


class ExecuteStreamResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    runtime_run_id: str = Field(alias="runtimeRunId")
    outcome: ExecuteStreamOutcome
    retryable: bool = False
    error_code: str | None = Field(default=None, alias="errorCode")
    next_retry_at: datetime | None = Field(default=None, alias="nextRetryAt")
    message: str | None = None
    checkpoint: dict[str, Any] | None = None
    counters: dict[str, int] = Field(default_factory=dict)
    stage_summary: dict[str, Any] = Field(default_factory=dict, alias="stageSummary")
