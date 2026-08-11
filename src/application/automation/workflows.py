"""Workflow submission boundary shared by local and Airflow adapters."""

from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from src.application.automation.contracts import ExecuteStreamCommand


class WorkflowProvider(StrEnum):
    LOCAL = "LOCAL"
    AIRFLOW = "AIRFLOW"


class WorkflowSubmissionState(StrEnum):
    SUBMITTED = "SUBMITTED"
    ALREADY_EXISTS = "ALREADY_EXISTS"
    RETRIED = "RETRIED"


class WorkflowSubmission(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    provider: WorkflowProvider
    workflow_id: str = Field(alias="workflowId")
    workflow_run_id: str = Field(alias="workflowRunId")
    state: WorkflowSubmissionState


class WorkflowSubmissionError(RuntimeError):
    """A workflow could not be submitted safely."""


class WorkflowSubmissionConflict(WorkflowSubmissionError):
    """A deterministic workflow ID belongs to another command."""


class WorkflowUnavailable(WorkflowSubmissionError):
    """The workflow control plane is unavailable."""


class WorkflowGateway(Protocol):
    async def trigger(self, command: ExecuteStreamCommand) -> WorkflowSubmission: ...
