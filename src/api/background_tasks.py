"""Shared lifecycle tracking for API-created background tasks."""

import asyncio
from typing import Any


def track_background_task(app: Any, task: asyncio.Task) -> None:
    """Keep a task referenced until completion so failures remain observable."""

    tasks = getattr(app.state, "background_tasks", None)
    if tasks is None:
        tasks = set()
        app.state.background_tasks = tasks
    tasks.add(task)
    task.add_done_callback(tasks.discard)
