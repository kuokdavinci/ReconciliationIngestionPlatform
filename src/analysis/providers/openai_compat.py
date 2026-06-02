"""OpenAI-compatible LLM provider (GPT-4o default).

Uses httpx.AsyncClient to call any OpenAI-compatible endpoint
(e.g. OpenAI API, Azure OpenAI, local vLLM) with the standard
/v1/chat/completions API shape.

Supports JSON-mode response format and token usage tracking.
"""

import asyncio
from typing import Optional

import httpx

from src.analysis.config import AnalysisConfig
from src.logging import get_structured_logger

logger = get_structured_logger()

# Estimated cost per 1K tokens (USD) — used for observability
_MODEL_COST_PER_1K: dict[str, dict[str, float]] = {
    "gpt-4o": {"input": 0.0025, "output": 0.01},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-4": {"input": 0.03, "output": 0.06},
    "gpt-4-turbo": {"input": 0.01, "output": 0.03},
    "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
    "gpt-3.5-turbo-16k": {"input": 0.001, "output": 0.002},
}

_DEFAULT_COST = {"input": 0.002, "output": 0.008}


def _estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate cost in USD for a given model and token usage.

    Args:
        model: Model name.
        prompt_tokens: Input token count.
        completion_tokens: Output token count.

    Returns:
        Estimated cost in USD.
    """
    rates = _MODEL_COST_PER_1K.get(model, _DEFAULT_COST)
    input_cost = (prompt_tokens / 1000) * rates["input"]
    output_cost = (completion_tokens / 1000) * rates["output"]
    return round(input_cost + output_cost, 6)


class OpenAICompatProvider:
    """OpenAI-compatible LLM provider using HTTP POST to /v1/chat/completions.

    Supports any endpoint that follows the OpenAI chat completions API format:
    POST {endpoint}/chat/completions with {model, messages, ...} body.
    """

    def __init__(
        self,
        config: AnalysisConfig,
        model_override: Optional[str] = None,
        endpoint_override: Optional[str] = None,
        api_key_override: Optional[str] = None,
    ) -> None:
        """Initialize provider.

        Args:
            config: AnalysisConfig instance.
            model_override: Override model name (used by provider router).
            endpoint_override: Override endpoint URL.
            api_key_override: Override API key.
        """
        self._config = config
        self._endpoint = (endpoint_override or config.endpoint).rstrip("/")
        self._model = model_override or config.model
        self._timeout = config.timeout
        self._max_retries = config.max_retries
        self._api_key = api_key_override or config.api_key
        self._json_mode = config.json_mode
        self._last_usage: Optional[dict[str, int]] = None

    @property
    def model(self) -> str:
        """Model name used by this provider."""
        return self._model

    @property
    def provider_name(self) -> str:
        """Human-readable provider name."""
        return f"OpenAI/{self._model}"

    @property
    def last_token_usage(self) -> Optional[dict[str, int]]:
        """Token usage from the last generate call, if available.

        Returns:
            Dict with prompt_tokens, completion_tokens, total_tokens, or None.
        """
        return self._last_usage

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
    ) -> str:
        """Generate a response from the LLM with retry logic.

        Args:
            prompt: The user prompt / main content.
            system_prompt: Optional system-level instructions.

        Returns:
            The LLM response text (content of first choice).

        Raises:
            httpx.HTTPStatusError: If the API returns an error after retries.
            httpx.RequestError: If the request fails after retries.
        """
        messages = self._build_messages(prompt, system_prompt)
        body = self._build_body(messages)

        last_exception: Optional[Exception] = None

        for attempt in range(1, self._max_retries + 1):
            try:
                return await self._call_api(body)
            except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                last_exception = exc
                logger.get_logger().warning(
                    f"LLM call failed (attempt {attempt}/{self._max_retries}): {exc}"
                )
                if attempt < self._max_retries:
                    await asyncio.sleep(1 * attempt)

        raise RuntimeError(
            f"LLM call failed after {self._max_retries} retries: {last_exception}"
        ) from last_exception

    async def _call_api(self, body: dict) -> str:
        """Make a single API call and parse the response.

        Args:
            body: The JSON body for the chat completions request.

        Returns:
            The response content string.

        Raises:
            httpx.HTTPStatusError: If the response status is not 2xx.
            httpx.RequestError: If the request fails.
            ValueError: If the response cannot be parsed.
        """
        headers = self._build_headers()

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._endpoint}/chat/completions",
                headers=headers,
                json=body,
            )
            response.raise_for_status()
            data = response.json()

        # Track token usage from API response
        self._last_usage = data.get("usage")

        content = self._parse_response(data)
        return content

    def _build_messages(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
    ) -> list[dict[str, str]]:
        """Build the messages array for the chat completions API.

        Args:
            prompt: User prompt content.
            system_prompt: Optional system instructions.

        Returns:
            List of message dicts with role and content.
        """
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _build_body(self, messages: list[dict[str, str]]) -> dict:
        """Build the request body for the chat completions API.

        Args:
            messages: List of message dicts.

        Returns:
            Request body dict.
        """
        body: dict = {
            "model": self._model,
            "messages": messages,
            "temperature": 0.1,
        }

        if self._json_mode:
            body["response_format"] = {"type": "json_object"}

        return body

    def _build_headers(self) -> dict[str, str]:
        """Build HTTP headers for the request.

        Returns:
            Headers dict with Authorization and Content-Type.
        """
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    @staticmethod
    def _parse_response(data: dict) -> str:
        """Parse the API response and extract the content.

        Args:
            data: Parsed JSON response from the API.

        Returns:
            The content string from the first choice.

        Raises:
            ValueError: If the response structure is unexpected.
        """
        try:
            choices = data.get("choices", [])
            if not choices:
                raise ValueError("Empty choices in LLM response")
            message = choices[0].get("message", {})
            content = message.get("content", "")
            if not content:
                raise ValueError("Empty content in LLM response")
            return content
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError(f"Unexpected LLM response structure: {data!r}") from exc

    @staticmethod
    def estimate_cost_for_usage(
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> float:
        """Estimate cost for a given model and token usage.

        Args:
            model: Model name.
            prompt_tokens: Input token count.
            completion_tokens: Output token count.

        Returns:
            Estimated cost in USD.
        """
        return _estimate_cost(model, prompt_tokens, completion_tokens)
