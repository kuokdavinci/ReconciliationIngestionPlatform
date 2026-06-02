"""LLM Provider abstraction for the AI Analysis Layer.

Defines the LLMProvider Protocol contract, the AIProviderRouter for
fallback chaining, and a factory function to wire providers from config.
"""

import logging
from typing import Optional, Protocol

from src.analysis.config import AnalysisConfig

logger = logging.getLogger(__name__)


class LLMProvider(Protocol):
    """Protocol defining the contract for LLM providers.

    All providers must implement an async generate() method that
    accepts a user prompt and optional system prompt, returning
    the LLM response as a string.
    """

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
    ) -> str:
        """Generate a response from the LLM.

        Args:
            prompt: The user prompt / main content.
            system_prompt: Optional system-level instructions.

        Returns:
            The LLM response text.
        """
        ...

    @property
    def model(self) -> str:
        """Model name used by this provider."""
        return ""

    @property
    def provider_name(self) -> str:
        """Human-readable provider name."""
        return ""

    @property
    def last_token_usage(self) -> Optional[dict[str, int]]:
        """Token usage from the last generate call, if available.

        Returns:
            Dict with prompt_tokens, completion_tokens, total_tokens, or None.
        """
        return None


class AIProviderRouter:
    """Routes LLM calls through primary → fallback chain.

    Tries the primary provider first. On failure (timeout, rate-limit,
    provider error, invalid schema), falls back to the secondary provider.
    If both fail, returns None so the caller can use rule-based fallback.

    Usage:
        router = AIProviderRouter(primary, fallback)
        result = await router.generate(prompt, system_prompt)
    """

    def __init__(
        self,
        primary_provider: LLMProvider,
        fallback_provider: Optional[LLMProvider] = None,
    ) -> None:
        """Initialize provider router with primary and optional fallback.

        Args:
            primary_provider: Primary LLM provider.
            fallback_provider: Optional fallback provider.
        """
        self._primary = primary_provider
        self._fallback = fallback_provider
        self._last_provider: Optional[LLMProvider] = None
        self._resolution: str = "rule_based"

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
    ) -> Optional[str]:
        """Generate response via primary → fallback chain.

        Args:
            prompt: The user prompt / main content.
            system_prompt: Optional system-level instructions.

        Returns:
            LLM response text, or None if both providers fail.
        """
        # Try primary provider
        try:
            result = await self._primary.generate(prompt, system_prompt)
            self._last_provider = self._primary
            self._resolution = "llm"
            return result
        except Exception as exc:
            logger.warning(
                f"Primary LLM provider failed: {exc}",
                extra={"event": "ai_provider_primary_fail", "error": str(exc)},
            )

        # Try fallback provider
        if self._fallback is not None:
            try:
                result = await self._fallback.generate(prompt, system_prompt)
                self._last_provider = self._fallback
                self._resolution = "llm_fallback"
                return result
            except Exception as exc:
                logger.warning(
                    f"Fallback LLM provider failed: {exc}",
                    extra={"event": "ai_provider_fallback_fail", "error": str(exc)},
                )

        # Both failed
        self._last_provider = None
        self._resolution = "rule_based"
        return None

    @property
    def last_provider(self) -> Optional[LLMProvider]:
        """Provider used for the last successful call."""
        return self._last_provider

    @property
    def resolution(self) -> str:
        """Resolution path: llm | llm_fallback | rule_based."""
        return self._resolution


def _create_single_provider(
    config: AnalysisConfig,
    provider_type: str,
    model: str,
    endpoint: str,
    api_key: Optional[str],
) -> LLMProvider:
    """Create a single LLM provider instance.

    Args:
        config: AnalysisConfig instance.
        provider_type: Provider type string.
        model: Model name.
        endpoint: API endpoint URL.
        api_key: Optional API key.

    Returns:
        LLMProvider implementation.

    Raises:
        ValueError: If provider_type is not recognized.
    """
    from src.analysis.providers.openai_compat import OpenAICompatProvider

    if provider_type == "openai":
        return OpenAICompatProvider(
            config=config,
            model_override=model,
            endpoint_override=endpoint,
            api_key_override=api_key,
        )

    if provider_type == "ollama":
        raise NotImplementedError(
            f"OllamaProvider is not yet implemented. Use AI_PROVIDER=openai."
        )

    raise ValueError(
        f"Unknown LLM provider type: {provider_type!r}. Supported: openai, ollama"
    )


def create_provider(config: AnalysisConfig) -> AIProviderRouter:
    """Factory function that returns a provider router with fallback chain.

    Routes based on config values:
    - Primary: config.provider / config.model
    - Fallback: config.fallback_provider / config.fallback_model
    - If primary is "ollama", raises NotImplementedError

    Args:
        config: AnalysisConfig instance with provider settings.

    Returns:
        AIProviderRouter with primary and optional fallback provider.
    """
    primary = _create_single_provider(
        config,
        provider_type=config.provider_type,
        model=config.model,
        endpoint=config.endpoint,
        api_key=config.api_key,
    )

    fallback_endpoint = config.fallback_endpoint or config.endpoint
    fallback_api_key = config.fallback_api_key or config.api_key

    try:
        fallback = _create_single_provider(
            config,
            provider_type=config.fallback_provider_type,
            model=config.fallback_model,
            endpoint=fallback_endpoint,
            api_key=fallback_api_key,
        )
    except (NotImplementedError, ValueError):
        fallback = None

    return AIProviderRouter(primary_provider=primary, fallback_provider=fallback)
