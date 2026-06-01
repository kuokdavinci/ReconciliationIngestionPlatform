"""Configuration for the AI Analysis Layer.

Provides AnalysisConfig with env-prefix AI_ for all LLM-related settings:
- Provider selection (openai/ollama)
- Model name, endpoint, API key
- Timeout, retry, alert thresholds
"""

from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings


class AnalysisConfig(BaseSettings):
    """Configuration for AI Analysis Layer.

    All environment variables are prefixed with AI_.
    """

    model_config = {"env_prefix": "AI_", "extra": "ignore"}

    # Provider selection
    ai_provider: str = Field(default="openai", description="LLM provider type: openai | ollama")
    ai_model: str = Field(default="gpt-4o", description="Model name for the selected provider")
    ai_endpoint: str = Field(
        default="https://api.openai.com/v1",
        description="API endpoint URL (OpenAI-compatible format)",
    )
    ai_api_key: Optional[str] = Field(default=None, description="API key for the LLM provider")

    # Connection settings
    ai_timeout: int = Field(default=30, description="HTTP timeout in seconds for LLM calls")
    ai_max_retries: int = Field(default=2, description="Maximum retry attempts on failure")

    # Alert thresholds
    ai_alert_mismatch_rate_threshold: float = Field(
        default=5.0,
        description="Mismatch rate percentage threshold for alerts",
    )
    ai_alert_missing_count_threshold: int = Field(
        default=10,
        description="Missing transaction count threshold for alerts",
    )

    @property
    def provider_type(self) -> str:
        """Normalized provider type (lowercase)."""
        return self.ai_provider.lower()
