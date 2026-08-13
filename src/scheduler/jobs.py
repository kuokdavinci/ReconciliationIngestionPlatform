"""Temporary compatibility facade for the migrated application runner."""

from src.application.automation.stream_runner import run_source_stream

run_fetch_config_once = run_source_stream

__all__ = ["run_fetch_config_once"]
