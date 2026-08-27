"""Application settings loaded from environment variables."""

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration with environment variable overrides."""

    mongodb_url: str = "mongodb://localhost:27017"
    db_name: str = "reconciliation"
    postgres_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/reconciliation"
    log_level: str = "INFO"
    log_format: str = "json"
    app_name: str = "reconciliation-ingestion"
    strict_mapping_approval_enabled: bool = True
    upload_tmp_dir: str = str(Path.cwd() / "scratch" / "temp_uploads")
    automation_orchestrator: Literal["airflow"] = "airflow"
    business_timezone: str = "Asia/Ho_Chi_Minh"
    airflow_base_url: str = "http://airflow-api-server:8080"
    airflow_dag_id: str = "reconciliation_ingestion"
    airflow_username: str | None = None
    airflow_password: str | None = None
    airflow_request_timeout_seconds: float = 10.0

    # Ingestion Performance Tuning Configurations
    ingest_batch_size: int = 20000
    ingest_write_workers: int = 2
    ingest_ordered_insert: bool = False
    ingestion_quarantine_retention_days: int = Field(default=30, ge=1, le=3650)
    ingestion_quarantine_review_sla_hours: int = Field(default=24, ge=1, le=8760)

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
