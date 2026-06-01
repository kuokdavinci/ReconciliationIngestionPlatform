"""Base fetcher abstract class for partner data fetching.

Defines the interface that all fetchers must implement and provides
common utilities for file validation, cleanup, and credential resolution.
"""

import os
import re
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


@dataclass
class FetchResult:
    """Result of a fetch operation."""

    success: bool
    local_path: Optional[str] = None
    error: Optional[str] = None
    file_size: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseFetcher(ABC):
    """Abstract base class for partner data fetchers.

    All fetchers must implement the fetch() method which downloads/retrieves
    data from the partner and returns a local file path.
    """

    @abstractmethod
    async def fetch(self, config: Any, reconciliation_date: datetime) -> FetchResult:
        """Fetch data from partner.

        Args:
            config: Method-specific configuration (SFTPConfig, APIConfig, or FileDropConfig).
            reconciliation_date: The date for which to fetch data.

        Returns:
            FetchResult with local file path or error information.
        """
        pass

    @staticmethod
    def resolve_credential(value: str) -> str:
        """Resolve a credential value.

        Supports:
        - env:VAR_NAME → resolves from environment variable
        - encrypted:VALUE → decrypts using Fernet (if ENCRYPTION_KEY is set)
        - plain text → returns as-is (not recommended for production)

        Args:
            value: Credential value to resolve.

        Returns:
            Resolved credential value.
        """
        if value.startswith("env:"):
            var_name = value[4:]
            resolved = os.getenv(var_name, "")
            if not resolved:
                raise ValueError(f"Environment variable {var_name} not set")
            return resolved

        if value.startswith("encrypted:"):
            encrypted_value = value[10:]
            return BaseFetcher._decrypt_value(encrypted_value)

        return value

    @staticmethod
    def _decrypt_value(encrypted_value: str) -> str:
        """Decrypt a Fernet-encrypted value.

        Requires ENCRYPTION_KEY environment variable to be set.

        Args:
            encrypted_value: Base64-encoded encrypted value.

        Returns:
            Decrypted plaintext value.

        Raises:
            ValueError: If ENCRYPTION_KEY is not set.
        """
        encryption_key = os.getenv("ENCRYPTION_KEY")
        if not encryption_key:
            raise ValueError(
                "ENCRYPTION_KEY environment variable not set for decryption"
            )

        from cryptography.fernet import Fernet

        fernet = Fernet(encryption_key.encode())
        return fernet.decrypt(encrypted_value.encode()).decode()

    @staticmethod
    def interpolate_date(template: str, date: datetime) -> str:
        """Replace {date:<format>} placeholders with formatted date.

        Args:
            template: String with {date:<strftime_format>} placeholders.
            date: Date to interpolate.

        Returns:
            String with placeholders replaced.

        Example:
            >>> interpolate_date("file_{date:%Y%m%d}.xlsx", datetime(2024, 7, 7))
            'file_20240707.xlsx'
        """

        def replace(match: re.Match) -> str:
            fmt = match.group(1) or "%Y%m%d"
            return date.strftime(fmt)

        return re.sub(r"\{date:(.*?)\}", replace, template)

    @staticmethod
    def validate_file(file_path: str) -> bool:
        """Validate that a file exists and is non-empty.

        Args:
            file_path: Path to the file.

        Returns:
            True if file exists and has size > 0.
        """
        path = Path(file_path)
        return path.exists() and path.stat().st_size > 0

    @staticmethod
    def cleanup_file(file_path: str) -> bool:
        """Delete a file after successful ingestion.

        Args:
            file_path: Path to the file to delete.

        Returns:
            True if file was deleted, False otherwise.
        """
        try:
            Path(file_path).unlink()
            return True
        except (OSError, FileNotFoundError):
            return False

    @staticmethod
    def archive_file(
        file_path: str, archive_dir: str, retention_days: int = 30
    ) -> Optional[str]:
        """Move a file to archive directory.

        Args:
            file_path: Path to the file to archive.
            archive_dir: Directory to move the file to.
            retention_days: Number of days to retain (for future cleanup).

        Returns:
            New archived file path, or None if archiving failed.
        """
        try:
            archive_path = Path(archive_dir)
            archive_path.mkdir(parents=True, exist_ok=True)
            dest = archive_path / Path(file_path).name
            shutil.move(file_path, dest)
            return str(dest)
        except (OSError, FileNotFoundError):
            return None
