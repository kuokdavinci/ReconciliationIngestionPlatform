"""Fetchers package for partner data retrieval.

Exports:
    BaseFetcher: Abstract base class for all fetchers.
    SFTPFetcher: Fetches files from SFTP servers.
    APIFetcher: Fetches data from HTTP APIs.
    FileDropFetcher: Scans local directories for new files.
    create_fetcher: Factory function to create appropriate fetcher.
"""

from src.fetchers.base import BaseFetcher, FetchResult
from src.fetchers.sftp_fetcher import SFTPFetcher
from src.fetchers.api_fetcher import APIFetcher
from src.fetchers.filedrop_fetcher import FileDropFetcher
from src.models.fetch_config import FetchConfig, FetchMethod


def create_fetcher(config: FetchConfig) -> BaseFetcher:
    """Create appropriate fetcher based on fetch method.

    Args:
        config: FetchConfig with fetch_method and method-specific config.

    Returns:
        Appropriate fetcher instance.

    Raises:
        ValueError: If fetch method is not supported.
    """
    if config.fetch_method == FetchMethod.SFTP:
        return SFTPFetcher()
    elif config.fetch_method == FetchMethod.API:
        return APIFetcher()
    elif config.fetch_method == FetchMethod.FILEDROP:
        return FileDropFetcher()
    else:
        raise ValueError(f"Unsupported fetch method: {config.fetch_method}")
