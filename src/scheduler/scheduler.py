"""Partner Data Fetch Scheduler.

Integrates APScheduler with MongoDB job store for persistent scheduling
of partner data fetch jobs.
"""

import logging
from datetime import datetime
from typing import Optional

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from apscheduler.jobstores.mongodb import MongoDBJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.scheduler.config import SchedulerConfig

logger = logging.getLogger("reconciliation.scheduler")


class PartnerDataScheduler:
    """Scheduler for partner data fetch jobs.

    Uses APScheduler with AsyncIOScheduler for async compatibility and
    MongoDB job store for persistence across restarts.

    Note: Phase 8 is designed for single-instance deployment. For multi-instance
    clustering, use MongoDB-based job locking or run scheduler as separate service.
    """

    def __init__(
        self,
        config: Optional[SchedulerConfig] = None,
        on_job_executed=None,
        on_job_error=None,
    ):
        """Initialize the scheduler.

        Args:
            config: Scheduler configuration. If None, uses defaults.
            on_job_executed: Callback for successful job execution.
            on_job_error: Callback for job errors.
        """
        self._config = config or SchedulerConfig()
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._on_job_executed = on_job_executed
        self._on_job_error = on_job_error

    def start(self) -> None:
        """Start the scheduler.

        Initializes APScheduler with MongoDB job store and registers
        event listeners for job execution tracking.
        """
        if self._scheduler is not None and self._scheduler.running:
            logger.warning("Scheduler is already running")
            return

        # Configure job stores
        job_stores = {}
        if self._config.job_store_type == "mongodb":
            job_stores["default"] = MongoDBJobStore(
                host=self._config.mongodb_url or "mongodb://localhost:27017",
                database=self._config.db_name,
                collection="apscheduler_jobs",
            )
        else:
            from apscheduler.jobstores.memory import MemoryJobStore
            job_stores["default"] = MemoryJobStore()

        # Create and configure scheduler
        self._scheduler = AsyncIOScheduler(
            jobstores=job_stores,
            job_defaults={
                "max_instances": self._config.max_instances,
                "misfire_grace_time": self._config.misfire_grace_time,
                "coalesce": self._config.coalesce,
            },
        )

        # Register event listeners
        self._scheduler.add_listener(
            self._on_job_executed_event, EVENT_JOB_EXECUTED
        )
        self._scheduler.add_listener(
            self._on_job_error_event, EVENT_JOB_ERROR
        )

        # Start scheduler
        self._scheduler.start()
        logger.info(
            "Scheduler started with job_store=%s",
            self._config.job_store_type,
        )

    def stop(self, wait: bool = True) -> None:
        """Stop the scheduler.

        Args:
            wait: Whether to wait for currently running jobs to complete.
        """
        if self._scheduler is None:
            return

        self._scheduler.shutdown(wait=wait)
        self._scheduler = None
        logger.info("Scheduler stopped")

    def add_daily_job(
        self,
        job_func,
        job_id: str = "daily_partner_fetch",
        cron_schedule: Optional[str] = None,
        **kwargs,
    ) -> None:
        """Add a daily fetch job to the scheduler.

        Args:
            job_func: Async function to execute.
            job_id: Unique job identifier.
            cron_schedule: Cron expression (default: from config).
            **kwargs: Additional arguments to pass to job_func.
        """
        if self._scheduler is None:
            raise RuntimeError("Scheduler not started. Call start() first.")

        schedule = cron_schedule or self._config.default_schedule
        minute, hour, day, month, day_of_week = schedule.split()

        self._scheduler.add_job(
            job_func,
            trigger="cron",
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
            id=job_id,
            name="Daily Partner Data Fetch",
            replace_existing=True,
            kwargs=kwargs,
        )

        logger.info(
            "Added daily job: id=%s, schedule=%s",
            job_id,
            schedule,
        )

    def remove_job(self, job_id: str) -> None:
        """Remove a job from the scheduler.

        Args:
            job_id: Job identifier to remove.
        """
        if self._scheduler is None:
            return

        try:
            self._scheduler.remove_job(job_id)
            logger.info("Removed job: id=%s", job_id)
        except Exception as exc:
            logger.warning("Failed to remove job %s: %s", job_id, exc)

    def run_job_now(self, job_id: str) -> None:
        """Manually trigger a job execution.

        Args:
            job_id: Job identifier to run.
        """
        if self._scheduler is None:
            raise RuntimeError("Scheduler not started. Call start() first.")

        job = self._scheduler.get_job(job_id)
        if job is None:
            raise ValueError(f"Job not found: {job_id}")

        job.modify(next_run_time=datetime.now())
        logger.info("Triggered job execution: id=%s", job_id)

    def list_jobs(self) -> list[dict]:
        """List all scheduled jobs.

        Returns:
            List of job information dicts.
        """
        if self._scheduler is None:
            return []

        jobs = []
        for job in self._scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run_time": str(job.next_run_time),
                "trigger": str(job.trigger),
            })
        return jobs

    @property
    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self._scheduler is not None and self._scheduler.running

    def _on_job_executed_event(self, event) -> None:
        """Handle job execution success event."""
        logger.info(
            "Job executed successfully: id=%s, retval=%s",
            event.job_id,
            event.retval,
        )
        if self._on_job_executed:
            self._on_job_executed(event)

    def _on_job_error_event(self, event) -> None:
        """Handle job execution error event."""
        logger.error(
            "Job execution failed: id=%s, exception=%s, traceback=%s",
            event.job_id,
            event.exception,
            event.traceback,
        )
        if self._on_job_error:
            self._on_job_error(event)
