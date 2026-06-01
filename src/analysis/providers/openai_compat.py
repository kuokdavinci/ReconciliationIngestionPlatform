"""OpenAI-compatible LLM provider (GPT-4o default).

Uses httpx.AsyncClient to call any OpenAI-compatible endpoint
(e.g. OpenAI API, Azure OpenAI, local vLLM) with the standard
/v1/chat/completions API shape.
"""

import asyncio
from typing import Optional

import httpx

from src.analysis.config import AnalysisConfig
from src.logging import get_structured_logger

logger = get_structured_logger()


class OpenAICompatProvider:
    """OpenAI-compatible LLM provider using HTTP POST to /v1/chat/completions.

    Supports any endpoint that follows the OpenAI chat completions API format:
    POST {endpoint}/chat/completions with {model, messages, ...} body.
    """

    def __init__(self, config: AnalysisConfig) -> None:
        self._config = config
        self._endpoint = config.ai_endpoint.rstrip("/")
        self._model = config.ai_model
        self._timeout = config.ai_timeout
        self._max_retries = config.ai_max_retries
        self._api_key = config.ai_api_key

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
                    await asyncio.sleep(1 * attempt)  # exponential-ish backoff

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
        return {
            "model": self._model,
            "messages": messages,
            "temperature": 0.1,  # Low temperature for deterministic output
        }

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
