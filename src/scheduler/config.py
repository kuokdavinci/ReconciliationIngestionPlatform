"""Scheduler configuration models.

Defines configuration for the APScheduler and job settings.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SchedulerConfig:
    """Configuration for the partner data fetch scheduler.

    Attributes:
        job_store_type: Type of job store (mongodb, memory).
        mongodb_url: MongoDB connection string (for mongodb job store).
        db_name: Database name for job store.
        default_schedule: Default cron schedule for jobs.
        max_instances: Maximum concurrent job instances.
        misfire_grace_time: Seconds after scheduled time before job is considered misfired.
        coalesce: Whether to coalesce multiple missed executions into one.
    """

    job_store_type: str = "mongodb"
    mongodb_url: Optional[str] = None
    db_name: str = "reconciliation"
    default_schedule: str = "0 0 * * *"
    max_instances: int = 1
    misfire_grace_time: int = 300  # 5 minutes
    coalesce: bool = True
