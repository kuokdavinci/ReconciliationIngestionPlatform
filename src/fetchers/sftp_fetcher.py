"""SFTP fetcher for downloading partner files from SFTP servers.

Refactored from run.py SFTP code with async wrapper, credential resolution,
and date interpolation support.
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

import paramiko

from src.fetchers.base import BaseFetcher, FetchResult
from src.domain.fetch_config.models import SFTPConfig
from src.domain.ingestion.source_units import SourceUnitMetadata


class SFTPFetcher(BaseFetcher):
    """Fetches files from SFTP servers.

    Uses paramiko for SFTP connections with async wrapper via thread pool.
    Supports wildcard remote paths and date interpolation.
    """

    async def fetch(
        self,
        config: SFTPConfig,
        reconciliation_date: datetime,
        fetch_metadata: dict[str, Any] | None = None,
    ) -> FetchResult:
        """Download file from SFTP server.

        Args:
            config: SFTP configuration with host, credentials, remote path.
            reconciliation_date: Date for interpolating remote path.

        Returns:
            FetchResult with local file path or error.
        """
        try:
            # Resolve credentials
            username = self.resolve_credential(config.username)
            password = self.resolve_credential(config.password)

            # Interpolate date in remote path
            remote_path = self.interpolate_date(
                config.remote_path, reconciliation_date
            )

            # Create local download directory
            download_dir = config.download_dir or "./downloads"
            local_dir = self.resolve_local_path(download_dir)
            local_dir.mkdir(parents=True, exist_ok=True)
            loop = asyncio.get_running_loop()
            remote_paths = await loop.run_in_executor(
                None,
                self._resolve_remote_paths_via_sftp,
                config.host,
                config.port,
                username,
                password,
                remote_path,
                config.timeout,
            )
            remote_paths = sorted(remote_paths)
            units: list[SourceUnitMetadata] = []
            for resolved_remote_path in remote_paths:
                local_path = local_dir / Path(resolved_remote_path).name
                await loop.run_in_executor(
                    None,
                    self._download_via_sftp,
                    config.host,
                    config.port,
                    username,
                    password,
                    resolved_remote_path,
                    str(local_path),
                    config.timeout,
                )
                if not self.validate_file(str(local_path)):
                    return FetchResult(
                        success=False,
                        local_path=str(units[0]["localPath"]) if units else None,
                        error=f"Downloaded file is empty or missing: {local_path}",
                        units=units,
                    )

                units.append(
                    self.build_file_source_unit(
                        str(local_path),
                        "SFTP",
                        {
                            "host": config.host,
                            "remotePath": resolved_remote_path,
                            "remotePattern": remote_path,
                            # Local mtime changes on every download. Keep the
                            # remote mtime slot explicit until SFTP stat data
                            # is available, so replay identity stays stable.
                            "modifiedAt": None,
                            **(
                                {"configVersion": fetch_metadata["configVersion"]}
                                if fetch_metadata and fetch_metadata.get("configVersion")
                                else {}
                            ),
                        },
                    )
                )

            local_path = Path(units[0]["localPath"])
            file_size = units[0]["fileSize"]

            return FetchResult(
                success=True,
                local_path=str(local_path),
                file_size=file_size,
                metadata={
                    "remote_path": str(remote_paths[0]),
                    "remote_paths": remote_paths,
                    "host": config.host,
                },
                units=units,
            )

        except ValueError as exc:
            # Credential resolution error
            return FetchResult(success=False, error=str(exc))
        except Exception as exc:
            return FetchResult(success=False, error=f"SFTP fetch failed: {exc}")

    @staticmethod
    def _resolve_remote_paths_via_sftp(
        host: str,
        port: int,
        username: str,
        password: str,
        remote_path: str,
        timeout: int,
    ) -> list[str]:
        """Resolve a remote path or wildcard into deterministic remote objects."""
        if "*" not in remote_path and "?" not in remote_path:
            return [remote_path]

        ssh = paramiko.SSHClient()
        ssh.load_system_host_keys()
        ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
        sftp = None
        try:
            ssh.connect(
                host,
                port=port,
                username=username,
                password=password,
                timeout=timeout,
            )
            sftp = ssh.open_sftp()
            remote_dir = str(Path(remote_path).parent)
            pattern = Path(remote_path).name
            try:
                files = sftp.listdir(remote_dir)
            except FileNotFoundError:
                raise FileNotFoundError(f"Remote directory not found: {remote_dir}")

            matching_files = sorted(
                filename for filename in files if _match_pattern(filename, pattern)
            )
            if not matching_files:
                raise FileNotFoundError(
                    f"No files matching pattern '{pattern}' in {remote_dir}"
                )
            return [f"{remote_dir}/{filename}" for filename in matching_files]
        finally:
            if sftp is not None:
                sftp.close()
            ssh.close()

    @staticmethod
    def _download_via_sftp(
        host: str,
        port: int,
        username: str,
        password: str,
        remote_path: str,
        local_path: str,
        timeout: int,
    ) -> None:
        """Download file via SFTP (synchronous, runs in thread pool).

        Args:
            host: SFTP server hostname.
            port: SFTP server port.
            username: SFTP username.
            password: SFTP password.
            remote_path: Remote file path (may contain wildcards).
            local_path: Local file path to save to.
            timeout: Connection timeout in seconds.

        Raises:
            Exception: If SFTP connection or download fails.
        """
        ssh = paramiko.SSHClient()
        ssh.load_system_host_keys()
        ssh.set_missing_host_key_policy(paramiko.RejectPolicy())

        try:
            ssh.connect(host, port=port, username=username, password=password, timeout=timeout)
            sftp = ssh.open_sftp()

            # Handle wildcard paths
            if "*" in remote_path or "?" in remote_path:
                # Find matching files
                remote_dir = str(Path(remote_path).parent)
                pattern = Path(remote_path).name
                try:
                    files = sftp.listdir(remote_dir)
                except FileNotFoundError:
                    raise FileNotFoundError(f"Remote directory not found: {remote_dir}")

                matching_files = [f for f in files if _match_pattern(f, pattern)]
                if not matching_files:
                    raise FileNotFoundError(
                        f"No files matching pattern '{pattern}' in {remote_dir}"
                    )

                # Use the first matching file
                remote_path = f"{remote_dir}/{matching_files[0]}"

            # Download the file
            sftp.get(remote_path, local_path)
            sftp.close()
        finally:
            ssh.close()


def _match_pattern(filename: str, pattern: str) -> bool:
    """Match a filename against a glob pattern.

    Args:
        filename: Filename to check.
        pattern: Glob pattern (e.g., "*.xlsx").

    Returns:
        True if filename matches pattern.
    """
    import fnmatch
    return fnmatch.fnmatch(filename, pattern)
