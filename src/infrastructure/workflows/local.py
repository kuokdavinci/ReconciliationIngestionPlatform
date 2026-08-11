"""Compatibility workflow adapter for in-process execution."""

import asyncio
from collections.abc import Callable
from typing import Any, Coroutine

from src.application.automation.contracts import ExecuteStreamCommand
from src.application.automation.workflows import (
    WorkflowProvider,
    WorkflowSubmission,
    WorkflowSubmissionState,
)

LocalRunner = Callable[[ExecuteStreamCommand], Coroutine[Any, Any, None]]
TaskTracker = Callable[[asyncio.Task[None]], None]


class LocalWorkflowGateway:
    def __init__(self, *, runner: LocalRunner, track_task: TaskTracker) -> None:
        self._runner = runner
        self._track_task = track_task

    async def trigger(self, command: ExecuteStreamCommand) -> WorkflowSubmission:
        if command.runtime_run_id is None:
            raise ValueError("runtime_run_id is required for local execution")
        task: asyncio.Task[None] = asyncio.create_task(self._runner(command))
        self._track_task(task)
        return WorkflowSubmission(
            provider=WorkflowProvider.LOCAL,
            workflowId="local_ingestion",
            workflowRunId=f"local__{command.runtime_run_id}",
            state=WorkflowSubmissionState.SUBMITTED,
        )
