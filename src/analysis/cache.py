"""In-memory TTL cache for AI insight results.

Reduces repeated LLM calls for identical partner+date+focus+model combos.
Cache is invalidated on re-reconciliation via bypass trigger.

Thread-safe for concurrent async access.
"""

import threading
import time
from typing import Any, Optional


class TTLCache:
    """Simple in-memory TTL cache with optional bypass.

    Cache key format: {partner}:{date}:{focus}:{reconciliation_run_id}:{model}
    """

    def __init__(self, default_ttl_seconds: int = 300) -> None:
        self._default_ttl = default_ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache if it exists and hasn't expired.

        Args:
            key: Cache key string.

        Returns:
            Cached value or None if miss/expired.
        """
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if time.monotonic() > expires_at:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        """Set value in cache with TTL.

        Args:
            key: Cache key string.
            value: Value to cache.
            ttl_seconds: Time-to-live in seconds (defaults to instance default).
        """
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        expires_at = time.monotonic() + ttl
        with self._lock:
            self._store[key] = (expires_at, value)

    def invalidate(self, key: str) -> None:
        """Remove a specific key from cache.

        Args:
            key: Cache key to invalidate.
        """
        with self._lock:
            self._store.pop(key, None)

    def invalidate_by_partner(self, partner: str) -> int:
        """Invalidate all cache entries for a given partner.

        Args:
            partner: Partner identifier.

        Returns:
            Number of invalidated entries.
        """
        count = 0
        with self._lock:
            keys_to_delete = [k for k in self._store if k.startswith(f"{partner}:")]
            for k in keys_to_delete:
                del self._store[k]
                count += 1
        return count

    def clear(self) -> None:
        """Clear all cached entries."""
        with self._lock:
            self._store.clear()

    @property
    def size(self) -> int:
        """Current number of entries in cache."""
        with self._lock:
            return len(self._store)


# Module-level singleton
_insight_cache: Optional[TTLCache] = None
_cache_lock = threading.Lock()


def get_insight_cache() -> TTLCache:
    """Get or create the module-level insight cache singleton.

    Returns:
        TTLCache instance with 5-minute default TTL.
    """
    global _insight_cache
    if _insight_cache is None:
        with _cache_lock:
            if _insight_cache is None:
                _insight_cache = TTLCache(default_ttl_seconds=300)
    return _insight_cache


def build_cache_key(
    partner: str,
    date: str,
    focus: str,
    model: str,
    reconciliation_run_id: Optional[str] = None,
) -> str:
    """Build a cache key for AI insight results.

    Args:
        partner: Partner identifier.
        date: Date string (YYYY-MM-DD).
        focus: Analysis focus type.
        model: Model name used.
        reconciliation_run_id: Optional reconciliation run ID for bypass.

    Returns:
        Cache key string.
    """
    run_id = reconciliation_run_id or ""
    return f"{partner}:{date}:{focus}:{run_id}:{model}"
