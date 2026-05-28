"""FileDrop fetcher for scanning local directories for new partner files.

Uses scheduled scan (glob/os.listdir) instead of watchdog daemon to avoid
resource overhead. Scans directory at scheduled time and picks up matching files.
"""

import glob
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.fetchers.base import BaseFetcher, FetchResult
from src.models.fetch_config import FileDropConfig


class FileDropFetcher(BaseFetcher):
    """Scans local directories for new partner files.

    Uses scheduled scan at job execution time instead of real-time watching.
    Supports file pattern matching and file lock checking.
    """

    FILE_LOCK_TIMEOUT = 5  # seconds to wait for file to stop growing

    async def fetch(
        self, config: FileDropConfig, reconciliation_date: datetime
    ) -> FetchResult:
        """Scan directory for matching files.

        Args:
            config: FileDrop configuration with directory and pattern.
            reconciliation_date: Date for context (not used in scanning).

        Returns:
            FetchResult with local file path or error.
        """
        try:
            directory = config.directory
            pattern = config.pattern

            # Check if directory exists
            if not os.path.isdir(directory):
                return FetchResult(
                    success=False,
                    error=f"FileDrop directory does not exist: {directory}",
                )

            # Scan for matching files
            search_pattern = os.path.join(directory, pattern)
            matching_files = glob.glob(search_pattern)

            if not matching_files:
                return FetchResult(
                    success=False,
                    error=f"No files matching '{pattern}' in {directory}",
                    metadata={"scanned_files": 0},
                )

            # Filter out files that are still being written (file lock check)
            ready_files = []
            for file_path in matching_files:
                if self._is_file_ready(file_path):
                    ready_files.append(file_path)

            if not ready_files:
                return FetchResult(
                    success=False,
                    error="Found matching files but all are still being written",
                    metadata={"scanned_files": len(matching_files)},
                )

            # Use the first ready file (can be enhanced to pick by date/name)
            selected_file = ready_files[0]
            file_size = os.path.getsize(selected_file)

            return FetchResult(
                success=True,
                local_path=selected_file,
                file_size=file_size,
                metadata={
                    "scanned_files": len(matching_files),
                    "ready_files": len(ready_files),
                    "selected_file": selected_file,
                },
            )

        except Exception as exc:
            return FetchResult(
                success=False,
                error=f"FileDrop scan failed: {exc}",
            )

    def _is_file_ready(self, file_path: str) -> bool:
        """Check if a file is ready (not being written to).

        Uses file size stability check: if file size doesn't change within
        FILE_LOCK_TIMEOUT seconds, consider it ready.

        Args:
            file_path: Path to the file.

        Returns:
            True if file is ready for processing.
        """
        try:
            # First size check
            size1 = os.path.getsize(file_path)
            time.sleep(self.FILE_LOCK_TIMEOUT)
            # Second size check
            size2 = os.path.getsize(file_path)

            # If sizes match, file is stable
            return size1 == size2
        except (OSError, FileNotFoundError):
            return False
