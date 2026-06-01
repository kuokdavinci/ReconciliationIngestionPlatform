"""LLM Provider abstraction for the AI Analysis Layer.

Defines the LLMProvider Protocol contract and a factory function
to route to the correct provider implementation based on config.
"""

from typing import Optional, Protocol

from src.analysis.config import AnalysisConfig


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


def create_provider(config: AnalysisConfig) -> LLMProvider:
    """Factory function that returns the appropriate LLM provider.

    Routes based on config.provider_type:
    - "openai" → OpenAICompatProvider
    - "ollama" → OllamaProvider (deferred, raises NotImplementedError)

    Args:
        config: AnalysisConfig instance with provider settings.

    Returns:
        An LLMProvider implementation.

    Raises:
        ValueError: If provider_type is not recognized.
    """
    provider_type = config.provider_type

    if provider_type == "openai":
        from src.analysis.providers.openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(config)

    if provider_type == "ollama":
        raise NotImplementedError(
            "OllamaProvider is deferred. Set AI_PROVIDER=openai to use GPT-4o."
        )

    raise ValueError(f"Unknown LLM provider type: {provider_type!r}. Supported: openai, ollama")
