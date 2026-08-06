"""TTL-based in-memory cache for MappingConfig objects.

Provides thread-safe caching to avoid repeated MongoDB queries.
Entries expire after a configurable TTL and are lazily cleaned on access.
"""

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.domain.mapping.models import MappingConfig


@dataclass
class CacheEntry:
    """A cache entry storing a MappingConfig with an expiry timestamp."""

    config: MappingConfig
    expires_at: datetime


class ConfigCache:
    """Thread-safe TTL in-memory cache for MappingConfig objects.

    Cache key format: "{partner}:{workflow_type}:{file_type}:{version_or_latest}"

    Entries are lazily cleaned on get() — no background threads.
    """

    DEFAULT_TTL = 300  # 5 minutes

    def __init__(self) -> None:
        self._store: dict[str, CacheEntry] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[MappingConfig]:
        """Retrieve a MappingConfig by key.

        Returns None if key not found or entry has expired.
        Expired entries are lazily removed from the store.
        """
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None

            if datetime.now(timezone.utc) >= entry.expires_at:
                # Lazy cleanup: remove expired entry
                del self._store[key]
                return None

            return entry.config

    def put(self, key: str, config: MappingConfig, ttl_seconds: int = DEFAULT_TTL) -> None:
        """Store a MappingConfig with TTL-based expiration.

        Args:
            key: Cache key in format "{partner}:{workflow_type}:{file_type}:{version_or_latest}"
            config: The MappingConfig to cache
            ttl_seconds: Time-to-live in seconds (default: 300)
        """
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        with self._lock:
            self._store[key] = CacheEntry(config=config, expires_at=expires_at)

    def invalidate(self, key: str) -> None:
        """Remove a specific cache entry.

        No-op if key does not exist.
        """
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        """Remove all cache entries."""
        with self._lock:
            self._store.clear()
