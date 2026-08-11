"""Scheduler daemon CLI handler."""

import asyncio

from src.config.settings import settings
from src.scheduler import PartnerDataScheduler, SchedulerConfig, daily_partner_fetch_job


def apscheduler_is_owner() -> bool:
    """Return whether APScheduler is allowed to own production schedules."""

    return settings.automation_orchestrator == "apscheduler"


async def handle_scheduler_mode(
    start_scheduler: bool = False,
    run_job_now: bool = False,
    list_jobs: bool = False,
) -> None:
    """Handle scheduler-related CLI commands.

    Args:
        start_scheduler: Whether to start the scheduler daemon.
        run_job_now: Whether to manually trigger the job now.
        list_jobs: Whether to list scheduled jobs.
    """

    if not apscheduler_is_owner():
        if list_jobs or run_job_now:
            raise RuntimeError(
                "APScheduler is disabled because Airflow owns automation orchestration."
            )
        if start_scheduler:
            print("APScheduler disabled: Airflow owns automation orchestration.")
            while True:
                await asyncio.sleep(3600)
        return

    scheduler_config = SchedulerConfig(
        job_store_type="mongodb",
        mongodb_url=settings.mongodb_url,
        db_name=settings.db_name,
    )

    def on_job_executed(event):
        print(f"[SCHEDULER] Job executed: {event.job_id}")

    def on_job_error(event):
        print(f"[SCHEDULER] Job failed: {event.job_id} - {event.exception}")

    scheduler = PartnerDataScheduler(
        config=scheduler_config,
        on_job_executed=on_job_executed,
        on_job_error=on_job_error,
    )

    # Start the scheduler first so jobs can be added to it
    scheduler.start()

    # Add daily job (connections are resolved dynamically inside the job to allow pickling)
    scheduler.add_daily_job(
        job_func=daily_partner_fetch_job,
        job_id="daily_partner_fetch",
    )

    if list_jobs:
        jobs = scheduler.list_jobs()
        if not jobs:
            print("No scheduled jobs.")
        else:
            print("\n=== Scheduled Jobs ===")
            for job in jobs:
                print(f"  ID: {job['id']}")
                print(f"  Name: {job['name']}")
                print(f"  Next Run: {job['next_run_time']}")
                print(f"  Trigger: {job['trigger']}")
                print()
        scheduler.stop()
        return

    if run_job_now:
        print("Triggering daily fetch job now...")
        scheduler.run_job_now("daily_partner_fetch")
        # Wait a bit for job to complete
        await asyncio.sleep(5)
        print("Job triggered. Check logs for results.")
        scheduler.stop()
        return

    if start_scheduler:
        print("Starting scheduler daemon...")
        print(f"  Job Store: {scheduler_config.job_store_type}")
        print(f"  Default Schedule: {scheduler_config.default_schedule}")
        print("\nPress Ctrl+C to stop.\n")

        try:
            # Keep the event loop running
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping scheduler...")
            scheduler.stop()
            print("Scheduler stopped.")
