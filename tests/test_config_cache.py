"""Tests for ConfigCache — TTL-based in-memory cache for MappingConfig."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch


from src.core.enums import FileType
from src.core.types import FieldMapping, FieldMappingType
from src.models.mapping_config import MappingConfig


def _make_config(partner: str = "MOMO", version: str | None = None) -> MappingConfig:
    """Helper to create a minimal MappingConfig for testing."""
    return MappingConfig(
        partner=partner,
        workflow_type="UPC",
        file_type=FileType.SETTLEMENT,
        sheet_name="Sheet1",
        field_mappings=[
            FieldMapping(path="amount", column="D", type=FieldMappingType.DECIMAL),
        ],
        config_version=version,
    )


def _cache_key(partner: str, workflow_type: str, file_type: FileType, version: str | None = None) -> str:
    """Build cache key in the expected format."""
    v = version or "latest"
    return f"{partner}:{workflow_type}:{file_type.value}:{v}"


class TestCacheEntry:
    """Tests for CacheEntry dataclass."""

    def test_cache_entry_stores_config_and_expiry(self):
        """CacheEntry stores a MappingConfig with an expires_at datetime."""
        from src.config.cache import CacheEntry

        config = _make_config()
        now = datetime.now(timezone.utc)
        entry = CacheEntry(config=config, expires_at=now + timedelta(seconds=300))

        assert entry.config is config
        assert entry.expires_at == now + timedelta(seconds=300)


class TestConfigCachePutAndGet:
    """Tests for ConfigCache.put() and get() roundtrip."""

    def setup_method(self):
        from src.config.cache import ConfigCache

        self.cache = ConfigCache()

    def test_put_get_roundtrip(self):
        """ConfigCache.get(key) returns MappingConfig after put()."""
        config = _make_config()
        key = _cache_key(config.partner, config.workflow_type, config.file_type)

        self.cache.put(key, config)
        result = self.cache.get(key)

        assert result is not None
        assert result.partner == "MOMO"
        assert result.workflow_type == "UPC"

    def test_get_returns_none_for_missing_key(self):
        """ConfigCache.get(key) returns None for non-existent key."""
        result = self.cache.get("nonexistent:key:SETTLEMENT:latest")
        assert result is None

    def test_put_with_custom_ttl(self):
        """ConfigCache.put() accepts custom ttl_seconds overriding default."""
        config = _make_config()
        key = _cache_key(config.partner, config.workflow_type, config.file_type)

        with patch("src.config.cache.datetime") as mock_dt:
            now = datetime(2026, 1, 1, tzinfo=timezone.utc)
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

            self.cache.put(key, config, ttl_seconds=60)

        entry = self.cache._store[key]
        assert entry.expires_at == now + timedelta(seconds=60)

    def test_default_ttl_is_300_seconds(self):
        """ConfigCache.put() uses 300 seconds as default TTL."""
        config = _make_config()
        key = _cache_key(config.partner, config.workflow_type, config.file_type)

        with patch("src.config.cache.datetime") as mock_dt:
            now = datetime(2026, 1, 1, tzinfo=timezone.utc)
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

            self.cache.put(key, config)

        entry = self.cache._store[key]
        assert entry.expires_at == now + timedelta(seconds=300)


class TestConfigCacheExpiration:
    """Tests for TTL expiration behavior."""

    def setup_method(self):
        from src.config.cache import ConfigCache

        self.cache = ConfigCache()

    def test_expired_entry_returns_none(self):
        """ConfigCache.get(key) returns None for expired entries."""
        config = _make_config()
        key = _cache_key(config.partner, config.workflow_type, config.file_type)

        # Insert with an already-expired time
        past = datetime.now(timezone.utc) - timedelta(seconds=1)
        from src.config.cache import CacheEntry
        self.cache._store[key] = CacheEntry(config=config, expires_at=past)

        result = self.cache.get(key)
        assert result is None

    def test_expired_entry_cleaned_on_get(self):
        """Expired entries are lazily removed from the store on get()."""
        config = _make_config()
        key = _cache_key(config.partner, config.workflow_type, config.file_type)

        past = datetime.now(timezone.utc) - timedelta(seconds=1)
        from src.config.cache import CacheEntry
        self.cache._store[key] = CacheEntry(config=config, expires_at=past)

        # get should return None and remove the entry
        self.cache.get(key)
        assert key not in self.cache._store

    def test_non_expired_entry_returns_config(self):
        """ConfigCache.get(key) returns config for non-expired entries."""
        config = _make_config()
        key = _cache_key(config.partner, config.workflow_type, config.file_type)

        future = datetime.now(timezone.utc) + timedelta(seconds=300)
        from src.config.cache import CacheEntry
        self.cache._store[key] = CacheEntry(config=config, expires_at=future)

        result = self.cache.get(key)
        assert result is not None
        assert result.partner == "MOMO"


class TestConfigCacheInvalidation:
    """Tests for ConfigCache.invalidate() and clear()."""

    def setup_method(self):
        from src.config.cache import ConfigCache

        self.cache = ConfigCache()

    def test_invalidate_removes_entry(self):
        """ConfigCache.invalidate(key) removes a specific entry."""
        config = _make_config()
        key = _cache_key(config.partner, config.workflow_type, config.file_type)

        self.cache.put(key, config)
        assert self.cache.get(key) is not None

        self.cache.invalidate(key)
        assert self.cache.get(key) is None

    def test_invalidate_nonexistent_key_no_error(self):
        """ConfigCache.invalidate(key) on non-existent key does not raise."""
        self.cache.invalidate("nonexistent:key:SETTLEMENT:latest")
        # No exception raised

    def test_clear_removes_all_entries(self):
        """ConfigCache.clear() removes all entries."""
        config1 = _make_config(partner="MOMO")
        config2 = _make_config(partner="VNPAY")
        key1 = _cache_key(config1.partner, config1.workflow_type, config1.file_type)
        key2 = _cache_key(config2.partner, config2.workflow_type, config2.file_type)

        self.cache.put(key1, config1)
        self.cache.put(key2, config2)

        self.cache.clear()

        assert self.cache.get(key1) is None
        assert self.cache.get(key2) is None
        assert len(self.cache._store) == 0


class TestConfigCacheThreadSafety:
    """Tests for thread-safe cache access."""

    def test_cache_has_lock(self):
        """ConfigCache uses threading.Lock for thread safety."""
        from src.config.cache import ConfigCache
        import threading

        cache = ConfigCache()
        assert isinstance(cache._lock, type(threading.Lock()))

    def test_concurrent_put_get(self):
        """ConfigCache handles concurrent put/get without corruption."""
        import threading
        from src.config.cache import ConfigCache

        cache = ConfigCache()
        errors = []

        def writer(n: int):
            try:
                config = _make_config(partner=f"PARTNER_{n}")
                key = _cache_key(config.partner, config.workflow_type, config.file_type)
                cache.put(key, config)
            except Exception as e:
                errors.append(e)

        def reader(n: int):
            try:
                config = _make_config(partner=f"PARTNER_{n}")
                key = _cache_key(config.partner, config.workflow_type, config.file_type)
                cache.get(key)  # May be None, that's OK
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(10):
            t1 = threading.Thread(target=writer, args=(i,))
            t2 = threading.Thread(target=reader, args=(i,))
            threads.extend([t1, t2])

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
