"""Configuration for the AI Analysis Layer.

Provides AnalysisConfig with env-prefix AI_ for all LLM-related settings:
- Provider selection (openai/ollama)
- Model name, endpoint, API key
- Timeout, retry, alert thresholds
"""

from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AnalysisConfig(BaseSettings):
    """Configuration for AI Analysis Layer.

    All environment variables are prefixed with AI_.
    """

    model_config = SettingsConfigDict(
        env_prefix="AI_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Primary provider
    provider: str = Field(default="openai", description="LLM provider type: openai | ollama")
    model: str = Field(default="gpt-4o", description="Model name for the selected provider")
    endpoint: str = Field(
        default="https://api.openai.com/v1",
        description="API endpoint URL (OpenAI-compatible format)",
    )
    api_key: Optional[str] = Field(default=None, description="API key for the LLM provider")

    # Fallback provider
    fallback_provider: str = Field(
        default="openai",
        description="Fallback LLM provider type when primary fails",
    )
    fallback_model: str = Field(
        default="gpt-4o-mini",
        description="Fallback model name",
    )
    fallback_endpoint: Optional[str] = Field(
        default=None,
        description="Fallback API endpoint (defaults to primary endpoint if not set)",
    )
    fallback_api_key: Optional[str] = Field(
        default=None,
        description="Fallback API key (defaults to primary key if not set)",
    )

    # Connection settings
    timeout: int = Field(default=30, description="HTTP timeout in seconds for LLM calls")
    max_retries: int = Field(default=2, description="Maximum retry attempts on failure")

    # JSON-mode response format
    json_mode: bool = Field(
        default=True,
        description="Enable JSON-mode response format for structured LLM output",
    )

    # Cache settings
    cache_ttl_seconds: int = Field(
        default=300,
        description="TTL in seconds for AI insight cache",
    )
    cache_enabled: bool = Field(
        default=True,
        description="Enable in-memory caching of AI insight results",
    )

    # Alert thresholds
    alert_mismatch_rate_threshold: float = Field(
        default=5.0,
        description="Mismatch rate percentage threshold for alerts",
    )
    alert_missing_count_threshold: int = Field(
        default=10,
        description="Missing transaction count threshold for alerts",
    )

    @property
    def provider_type(self) -> str:
        """Normalized provider type (lowercase)."""
        return self.provider.lower()

    @property
    def fallback_provider_type(self) -> str:
        """Normalized fallback provider type (lowercase)."""
        return self.fallback_provider.lower()
