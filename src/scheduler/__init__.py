"""Compatibility package for the application ingestion runner."""

from src.scheduler.jobs import daily_partner_fetch_job

__all__ = ["daily_partner_fetch_job"]
