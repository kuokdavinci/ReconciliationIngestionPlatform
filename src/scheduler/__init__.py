"""Scheduler package for partner data fetch scheduling.

Exports:
    PartnerDataScheduler: Main scheduler class with APScheduler integration.
    SchedulerConfig: Configuration for scheduler settings.
    daily_partner_fetch_job: Daily job function for fetching and ingesting partner data.
"""

from typing import TYPE_CHECKING, Any

from src.scheduler.config import SchedulerConfig
from src.scheduler.jobs import daily_partner_fetch_job

if TYPE_CHECKING:
    from src.scheduler.scheduler import PartnerDataScheduler


def __getattr__(name: str) -> Any:
    if name == "PartnerDataScheduler":
        from src.scheduler.scheduler import PartnerDataScheduler

        return PartnerDataScheduler
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "PartnerDataScheduler",
    "SchedulerConfig",
    "daily_partner_fetch_job",
]
