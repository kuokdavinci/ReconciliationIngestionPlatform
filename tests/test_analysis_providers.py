"""Tests for OpenAICompatProvider LLM provider implementation."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.analysis.config import AnalysisConfig
from src.analysis.providers.openai_compat import OpenAICompatProvider


@pytest.fixture
def config() -> AnalysisConfig:
    """Create a default AnalysisConfig for testing."""
    return AnalysisConfig(
        provider="openai",
        model="gpt-4o",
        endpoint="https://api.openai.com/v1",
        api_key="test-key",
        timeout=30,
        max_retries=2,
    )


@pytest.fixture
def provider(config: AnalysisConfig) -> OpenAICompatProvider:
    """Create an OpenAICompatProvider instance."""
    return OpenAICompatProvider(config)


class TestOpenAICompatProviderInit:
    """Test provider initialization."""

    def test_init_stores_config(self, provider: OpenAICompatProvider) -> None:
        assert provider._model == "gpt-4o"
        assert provider._endpoint == "https://api.openai.com/v1"
        assert provider._api_key == "test-key"
        assert provider._timeout == 30
        assert provider._max_retries == 2

    def test_init_strips_trailing_slash(self, config: AnalysisConfig) -> None:
        config.endpoint = "https://api.openai.com/v1/"
        p = OpenAICompatProvider(config)
        assert p._endpoint == "https://api.openai.com/v1"


class TestBuildMessages:
    """Test message building."""

    def test_build_messages_with_system_prompt(self, provider: OpenAICompatProvider) -> None:
        messages = provider._build_messages(
            "Analyze this data",
            system_prompt="You are an analyst",
        )
        assert len(messages) == 2
        assert messages[0] == {"role": "system", "content": "You are an analyst"}
        assert messages[1] == {"role": "user", "content": "Analyze this data"}

    def test_build_messages_without_system_prompt(self, provider: OpenAICompatProvider) -> None:
        messages = provider._build_messages("Hello")
        assert len(messages) == 1
        assert messages[0] == {"role": "user", "content": "Hello"}


class TestBuildBody:
    """Test request body building."""

    def test_build_body_includes_model_and_messages(self, provider: OpenAICompatProvider) -> None:
        messages = [{"role": "user", "content": "test"}]
        body = provider._build_body(messages)
        assert body["model"] == "gpt-4o"
        assert body["messages"] == messages
        assert body["temperature"] == 0.1


class TestBuildHeaders:
    """Test header building."""

    def test_build_headers_with_api_key(self, provider: OpenAICompatProvider) -> None:
        headers = provider._build_headers()
        assert headers["Authorization"] == "Bearer test-key"
        assert headers["Content-Type"] == "application/json"

    def test_build_headers_without_api_key(self, config: AnalysisConfig) -> None:
        config.api_key = None
        p = OpenAICompatProvider(config)
        headers = p._build_headers()
        assert "Authorization" not in headers
        assert headers["Content-Type"] == "application/json"


class TestParseResponse:
    """Test response parsing."""

    def test_parse_valid_response(self) -> None:
        data = {
            "choices": [
                {
                    "message": {"content": "This is the analysis result"},
                    "finish_reason": "stop",
                }
            ]
        }
        result = OpenAICompatProvider._parse_response(data)
        assert result == "This is the analysis result"

    def test_parse_empty_choices_raises(self) -> None:
        with pytest.raises(ValueError, match="Empty choices"):
            OpenAICompatProvider._parse_response({"choices": []})

    def test_parse_missing_choices_raises(self) -> None:
        with pytest.raises(ValueError, match="Empty choices"):
            OpenAICompatProvider._parse_response({})

    def test_parse_empty_content_raises(self) -> None:
        data = {
            "choices": [
                {"message": {"content": ""}, "finish_reason": "stop"}
            ]
        }
        with pytest.raises(ValueError, match="Empty content"):
            OpenAICompatProvider._parse_response(data)


class TestGenerate:
    """Test the generate() method with mocked HTTP."""

    @pytest.mark.asyncio
    async def test_generate_returns_content(self, provider: OpenAICompatProvider) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "analysis result"}}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("src.analysis.providers.openai_compat.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await provider.generate("test prompt", system_prompt="be helpful")

            assert result == "analysis result"
            # Verify the request was made correctly
            call_args = mock_client.post.call_args
            assert call_args[1]["json"]["model"] == "gpt-4o"
            assert len(call_args[1]["json"]["messages"]) == 2
            assert call_args[1]["headers"]["Authorization"] == "Bearer test-key"

    @pytest.mark.asyncio
    async def test_generate_retries_on_failure(self, provider: OpenAICompatProvider) -> None:
        """Verify retry logic: fails twice then succeeds."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "success on retry"}}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("src.analysis.providers.openai_compat.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            # First call fails, second succeeds
            mock_client.post.side_effect = [
                httpx.RequestError("Connection error"),
                mock_response,
            ]
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await provider.generate("test prompt")
            assert result == "success on retry"
            assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_generate_raises_after_max_retries(self, provider: OpenAICompatProvider) -> None:
        """Verify that after max_retries, a RuntimeError is raised."""
        with patch("src.analysis.providers.openai_compat.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.RequestError("Persistent failure")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with pytest.raises(RuntimeError, match="failed after 2 retries"):
                await provider.generate("test prompt")
