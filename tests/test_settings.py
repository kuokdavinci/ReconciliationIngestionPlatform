"""Tests for project structure, configuration, and settings."""



class TestSettingsDefaults:
    """Test that settings load with correct defaults."""

    def test_settings_import(self):
        """Settings module is importable."""
        from src.config.settings import settings
        assert settings is not None

    def test_mongodb_url_default(self):
        """mongodb_url contains localhost:27017."""
        from src.config.settings import settings
        assert "localhost:27017" in settings.mongodb_url

    def test_db_name_default(self):
        """db_name defaults to 'reconciliation'."""
        from src.config.settings import settings
        assert settings.db_name == "reconciliation"

    def test_log_level_default(self):
        """log_level defaults to 'INFO'."""
        from src.config.settings import settings
        assert settings.log_level == "INFO"

    def test_log_format_default(self):
        """log_format defaults to 'json'."""
        from src.config.settings import settings
        assert settings.log_format == "json"

    def test_app_name_default(self):
        """app_name defaults to 'reconciliation-ingestion'."""
        from src.config.settings import settings
        assert settings.app_name == "reconciliation-ingestion"


class TestSettingsEnvOverride:
    """Test that environment variables override defaults."""

    def test_mongodb_url_env_override(self, monkeypatch):
        """APP_MONGODB_URL overrides default."""
        # Need to reload module to pick up new env var
        import importlib
        monkeypatch.setenv("APP_MONGODB_URL", "mongodb://custom:27017/testdb")
        monkeypatch.setenv("APP_DB_NAME", "testdb")
        monkeypatch.setenv("APP_LOG_LEVEL", "DEBUG")
        monkeypatch.setenv("APP_LOG_FORMAT", "text")
        monkeypatch.setenv("APP_APP_NAME", "test-app")

        from src.config import settings as settings_module
        importlib.reload(settings_module)
        assert settings_module.settings.mongodb_url == "mongodb://custom:27017/testdb"
        assert settings_module.settings.db_name == "testdb"
