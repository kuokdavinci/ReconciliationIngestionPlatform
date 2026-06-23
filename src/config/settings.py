"""Application settings loaded from environment variables."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration with environment variable overrides."""

    mongodb_url: str = "mongodb://localhost:27017"
    db_name: str = "reconciliation"
    log_level: str = "INFO"
    log_format: str = "json"
    app_name: str = "reconciliation-ingestion"
    strict_mapping_approval_enabled: bool = True
    upload_tmp_dir: str = str(Path.cwd() / "scratch" / "temp_uploads")

    # Ingestion Performance Tuning Configurations
    ingest_batch_size: int = 10000
    ingest_write_workers: int = 2
    ingest_ordered_insert: bool = False

    # Reconciliation Performance Tuning Configurations
    recon_partner_batch_size: int = 10000
    recon_result_batch_size: int = 10000
    recon_result_write_workers: int = 2
    recon_result_ordered_insert: bool = False


    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
