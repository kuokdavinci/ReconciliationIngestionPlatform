"""Tests for ConfigLoader — repository, cache, and validator integration.

TDD-driven: RED→GREEN cycle for ConfigLoader service that loads, caches,
validates, and version-resolves mapping configurations.
"""

from unittest.mock import AsyncMock

import pytest

from src.core.enums import FileType
from src.core.types import FieldMapping, FieldMappingType
from src.models.mapping_config import MappingConfig


def _make_config(partner: str = "MOMO", version: str | None = "v1.0") -> MappingConfig:
    """Helper to create a minimal valid MappingConfig for testing."""
    return MappingConfig(
        partner=partner,
        workflow_type="UPC",
        file_type=FileType.SETTLEMENT,
        sheet_name="Sheet1",
        field_mappings=[
            FieldMapping(path="amount", column="D", type=FieldMappingType.DECIMAL, required=True),
            FieldMapping(path="currency", constant="VND", type=FieldMappingType.CONSTANT),
            FieldMapping(path="status", column="F", type=FieldMappingType.STRING),
        ],
        config_version=version,
    )


class TestConfigLoadError:
    """Tests for ConfigLoadError exception."""

    def test_error_has_message(self):
        """ConfigLoadError stores a message string."""
        from src.config.loader import ConfigLoadError

        err = ConfigLoadError(message="Config validation failed")

        assert err.message == "Config validation failed"

    def test_error_has_validation_errors(self):
        """ConfigLoadError stores validation_errors list."""
        from src.config.loader import ConfigLoadError
        from src.config.validator import ConfigValidationError

        validation_errors = [
            ConfigValidationError(field="amount", reason="duplicate path"),
        ]
        err = ConfigLoadError(
            message="Config validation failed",
            validation_errors=validation_errors,
        )

        assert len(err.validation_errors) == 1
        assert err.validation_errors[0].field == "amount"

    def test_error_validation_errors_defaults_to_empty(self):
        """ConfigLoadError.validation_errors defaults to empty list."""
        from src.config.loader import ConfigLoadError

        err = ConfigLoadError(message="Config not found")

        assert err.validation_errors == []


class TestConfigLoaderInit:
    """Tests for ConfigLoader initialization."""

    def test_loader_initializes_with_dependencies(self):
        """ConfigLoader.__init__ accepts repository, cache, validator."""
        from src.config.cache import ConfigCache
        from src.config.loader import ConfigLoader
        from src.config.validator import ConfigValidator

        repository = AsyncMock()
        cache = ConfigCache()
        validator = ConfigValidator()

        loader = ConfigLoader(repository, cache, validator)

        assert loader._repository is repository
        assert loader._cache is cache
        assert loader._validator is validator
        assert loader._default_ttl == 300

    def test_loader_accepts_custom_ttl(self):
        """ConfigLoader.__init__ accepts custom default_ttl."""
        from src.config.cache import ConfigCache
        from src.config.loader import ConfigLoader
        from src.config.validator import ConfigValidator

        repository = AsyncMock()
        cache = ConfigCache()
        validator = ConfigValidator()

        loader = ConfigLoader(repository, cache, validator, default_ttl=600)

        assert loader._default_ttl == 600


class TestCacheKeyGeneration:
    """Tests for cache key generation methods."""

    def test_cache_key_partner_type_format(self):
        """_cache_key_partner_type produces '{partner}:{workflow_type}:{file_type.value}:latest'."""
        from src.config.cache import ConfigCache
        from src.config.loader import ConfigLoader
        from src.config.validator import ConfigValidator

        repository = AsyncMock()
        cache = ConfigCache()
        validator = ConfigValidator()
        loader = ConfigLoader(repository, cache, validator)

        key = loader._cache_key_partner_type("MOMO", "UPC", FileType.SETTLEMENT)

        assert key == "MOMO:UPC:SETTLEMENT:latest"

    def test_cache_key_version_format(self):
        """_cache_key_version produces '{partner}:*:*:{version}'."""
        from src.config.cache import ConfigCache
        from src.config.loader import ConfigLoader
        from src.config.validator import ConfigValidator

        repository = AsyncMock()
        cache = ConfigCache()
        validator = ConfigValidator()
        loader = ConfigLoader(repository, cache, validator)

        key = loader._cache_key_version("MOMO", "v2.0")

        assert key == "MOMO:*:*:v2.0"


class TestLoadByPartnerType:
    """Tests for load_by_partner_type method."""

    def setup_method(self):
        from src.config.cache import ConfigCache
        from src.config.loader import ConfigLoader, ConfigLoadError
        from src.config.validator import ConfigValidator

        self.repository = AsyncMock()
        self.cache = ConfigCache()
        self.validator = ConfigValidator()
        self.loader = ConfigLoader(self.repository, self.cache, self.validator)
        self.ConfigLoadError = ConfigLoadError

    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached_config(self):
        """load_by_partner_type returns cached config without DB call on cache hit."""
        config = _make_config()
        key = "MOMO:UPC:SETTLEMENT:latest"
        self.cache.put(key, config)

        result = await self.loader.load_by_partner_type("MOMO", "UPC", FileType.SETTLEMENT)

        assert result is config
        # Repository should NOT have been called
        self.repository.find_by_partner_and_type.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_invalidated_when_different_config_approved(self):
        """load_by_partner_type invalidates cache if a different config is approved in DB."""
        from unittest.mock import MagicMock
        config = _make_config()
        key = "MOMO:UPC:SETTLEMENT:latest"
        self.cache.put(key, config)

        # Create a custom dummy repository class to bypass the Mock checks
        class DummyCollection:
            def __init__(self):
                self.find_one = AsyncMock(return_value={"_id": "different_id"})

        class DummyRepository:
            def __init__(self):
                self.collection = DummyCollection()
                self.find_by_partner_and_type = AsyncMock()

        dummy_repo = DummyRepository()
        dummy_repo.find_by_partner_and_type.return_value = config

        # Set loader's repository to our dummy
        self.loader._repository = dummy_repo

        result = await self.loader.load_by_partner_type("MOMO", "UPC", FileType.SETTLEMENT)

        # It should detect the ID mismatch, invalidate the cache, query find_by_partner_and_type, and return config
        assert result is config
        dummy_repo.find_by_partner_and_type.assert_called_once()
        dummy_repo.collection.find_one.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_miss_queries_db_validates_caches_returns(self):
        """load_by_partner_type queries DB on cache miss, validates, caches, returns."""
        config = _make_config()
        self.repository.find_by_partner_and_type.return_value = config

        result = await self.loader.load_by_partner_type("MOMO", "UPC", FileType.SETTLEMENT)

        assert result is config
        self.repository.find_by_partner_and_type.assert_called_once_with(
            "MOMO", "UPC", FileType.SETTLEMENT
        )
        # Verify it's cached
        cached = self.cache.get("MOMO:UPC:SETTLEMENT:latest")
        assert cached is config

    @pytest.mark.asyncio
    async def test_db_returns_none_raises_config_load_error(self):
        """load_by_partner_type raises ConfigLoadError when DB returns None."""
        self.repository.find_by_partner_and_type.return_value = None

        with pytest.raises(self.ConfigLoadError) as exc_info:
            await self.loader.load_by_partner_type("MOMO", "UPC", FileType.SETTLEMENT)

        assert exc_info.value.validation_errors == []
        self.repository.find_by_partner_and_type.assert_called_once()

    @pytest.mark.asyncio
    async def test_validation_errors_raises_config_load_error_with_details(self):
        """load_by_partner_type raises ConfigLoadError with validation_errors on invalid config."""
        from src.config.validator import ConfigValidationError

        # Config with empty field_mappings (will fail validation)
        bad_config = MappingConfig(
            partner="MOMO",
            workflow_type="UPC",
            file_type=FileType.SETTLEMENT,
            sheet_name="Sheet1",
            field_mappings=[],
            config_version="v1.0",
        )
        self.repository.find_by_partner_and_type.return_value = bad_config

        with pytest.raises(self.ConfigLoadError) as exc_info:
            await self.loader.load_by_partner_type("MOMO", "UPC", FileType.SETTLEMENT)

        assert len(exc_info.value.validation_errors) > 0
        assert exc_info.value.validation_errors[0].field == "_global"

    @pytest.mark.asyncio
    async def test_required_paths_coverage_failure_raises_config_load_error(self):
        """load_by_partner_type raises ConfigLoadError when required_paths not covered."""
        config = _make_config()
        self.repository.find_by_partner_and_type.return_value = config

        # Require a path that doesn't exist in the config
        with pytest.raises(self.ConfigLoadError) as exc_info:
            await self.loader.load_by_partner_type(
                "MOMO", "UPC", FileType.SETTLEMENT,
                required_paths={"amount", "currency", "nonexistent_path"},
            )

        assert len(exc_info.value.validation_errors) > 0
        missing_paths = {e.field for e in exc_info.value.validation_errors}
        assert "nonexistent_path" in missing_paths


class TestLoadByVersion:
    """Tests for load_by_version method."""

    def setup_method(self):
        from src.config.cache import ConfigCache
        from src.config.loader import ConfigLoader, ConfigLoadError
        from src.config.validator import ConfigValidator

        self.repository = AsyncMock()
        self.cache = ConfigCache()
        self.validator = ConfigValidator()
        self.loader = ConfigLoader(self.repository, self.cache, self.validator)
        self.ConfigLoadError = ConfigLoadError

    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached_config(self):
        """load_by_version returns cached config without DB call on cache hit."""
        config = _make_config(version="v2.0")
        key = "MOMO:*:*:v2.0"
        self.cache.put(key, config)

        result = await self.loader.load_by_version("MOMO", "v2.0")

        assert result is config
        self.repository.find_by_version.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_miss_queries_db_by_version_validates_caches(self):
        """load_by_version queries DB by version on cache miss, validates, caches."""
        config = _make_config(version="v2.0")
        self.repository.find_by_version.return_value = config

        result = await self.loader.load_by_version("MOMO", "v2.0")

        assert result is config
        self.repository.find_by_version.assert_called_once_with("MOMO", "v2.0")
        # Verify it's cached
        cached = self.cache.get("MOMO:*:*:v2.0")
        assert cached is config

    @pytest.mark.asyncio
    async def test_db_returns_none_raises_config_load_error(self):
        """load_by_version raises ConfigLoadError when DB returns None."""
        self.repository.find_by_version.return_value = None

        with pytest.raises(self.ConfigLoadError) as exc_info:
            await self.loader.load_by_version("MOMO", "v99.0")

        assert exc_info.value.validation_errors == []
        self.repository.find_by_version.assert_called_once()


class TestInvalidateCache:
    """Tests for invalidate_cache method."""

    def setup_method(self):
        from src.config.cache import ConfigCache
        from src.config.loader import ConfigLoader, ConfigLoadError
        from src.config.validator import ConfigValidator

        self.repository = AsyncMock()
        self.cache = ConfigCache()
        self.validator = ConfigValidator()
        self.loader = ConfigLoader(self.repository, self.cache, self.validator)
        self.ConfigLoadError = ConfigLoadError

    @pytest.mark.asyncio
    async def test_invalidate_removes_entry_next_load_hits_db(self):
        """invalidate_cache removes entry, next load_by_partner_type hits DB."""
        config = _make_config()
        key = "MOMO:UPC:SETTLEMENT:latest"
        self.cache.put(key, config)

        # Verify cache hit first
        cached = self.cache.get(key)
        assert cached is config

        # Invalidate
        self.loader.invalidate_cache(key)

        # Verify cache miss
        assert self.cache.get(key) is None

        # Now load should hit DB
        self.repository.find_by_partner_and_type.return_value = config
        result = await self.loader.load_by_partner_type("MOMO", "UPC", FileType.SETTLEMENT)

        assert result is config
        self.repository.find_by_partner_and_type.assert_called_once()


class TestDefaultTtlApplied:
    """Tests for default_ttl applied to cached entries."""

    def setup_method(self):
        from src.config.cache import ConfigCache
        from src.config.loader import ConfigLoader
        from src.config.validator import ConfigValidator

        self.repository = AsyncMock()
        self.cache = ConfigCache()
        self.validator = ConfigValidator()
        self.loader = ConfigLoader(self.repository, self.cache, self.validator, default_ttl=600)

    @pytest.mark.asyncio
    async def test_default_ttl_applied_to_cached_entries(self):
        """ConfigLoader uses custom default_ttl for cached entries."""
        config = _make_config()
        self.repository.find_by_partner_and_type.return_value = config

        await self.loader.load_by_partner_type("MOMO", "UPC", FileType.SETTLEMENT)

        # Check the cache entry has the correct TTL
        entry = self.cache._store.get("MOMO:UPC:SETTLEMENT:latest")
        assert entry is not None
        # The expiry should be ~600 seconds from now (within 1 second tolerance)
        from datetime import datetime, timezone
        expected_expiry = datetime.now(timezone.utc).timestamp() + 600
        actual_expiry = entry.expires_at.timestamp()
        assert abs(actual_expiry - expected_expiry) < 1
