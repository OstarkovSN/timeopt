from unittest.mock import MagicMock, patch
from timeopt.llm_client import AnthropicClient, OpenAICompatibleClient, LLMClient


def test_anthropic_client_implements_interface():
    assert hasattr(AnthropicClient, "complete")


def test_openai_compatible_client_implements_interface():
    assert hasattr(OpenAICompatibleClient, "complete")


def test_anthropic_client_calls_api():
    with patch("timeopt.llm_client.anthropic") as mock_anthropic:
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="response text")]
        )
        client = AnthropicClient(api_key="test-key", model="claude-sonnet-4-6")
        result = client.complete(system="sys", user="user msg")
        assert result == "response text"
        mock_client.messages.create.assert_called_once()


def test_openai_compatible_client_calls_api():
    with patch("timeopt.llm_client.openai") as mock_openai:
        mock_client = MagicMock()
        mock_openai.OpenAI.return_value = mock_client
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="response text"))]
        )
        client = OpenAICompatibleClient(
            base_url="http://localhost:11434/v1",
            api_key="test",
            model="llama3",
        )
        result = client.complete(system="sys", user="user msg")
        assert result == "response text"


def test_anthropic_client_missing_key_raises():
    import pytest
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            AnthropicClient(api_key=None, model="claude-sonnet-4-6")


def test_build_llm_client_with_base_url_returns_openai_client():
    """When llm_base_url is set in config, build_llm_client should return OpenAICompatibleClient."""
    from timeopt.llm_client import build_llm_client
    with patch("timeopt.llm_client.openai") as mock_openai:
        mock_client = MagicMock()
        mock_openai.OpenAI.return_value = mock_client
        config = {
            "llm_base_url": "http://localhost:11434/v1",
            "llm_api_key": "test-key",
            "llm_model": "llama3",
        }
        client = build_llm_client(config)
        assert isinstance(client, OpenAICompatibleClient)


def test_build_llm_client_without_base_url_returns_anthropic_client():
    """When llm_base_url is not set in config, build_llm_client should return AnthropicClient."""
    from timeopt.llm_client import build_llm_client
    with patch("timeopt.llm_client.anthropic") as mock_anthropic:
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client
        config = {
            "llm_api_key": "test-key",
            "llm_model": "claude-sonnet-4-6",
        }
        client = build_llm_client(config)
        assert isinstance(client, AnthropicClient)


def test_anthropic_client_env_var_fallback():
    """When llm_api_key=None in config but ANTHROPIC_API_KEY is set in environment, AnthropicClient should construct successfully."""
    with patch("timeopt.llm_client.anthropic") as mock_anthropic:
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "env-key"}):
            client = AnthropicClient(api_key=None, model="claude-sonnet-4-6")
            assert isinstance(client, AnthropicClient)
            mock_anthropic.Anthropic.assert_called_once_with(api_key="env-key")


def test_build_llm_client_default_model_fallback():
    """When llm_model is not set in config, build_llm_client should fall back to default 'claude-sonnet-4-6'."""
    from timeopt.llm_client import build_llm_client
    with patch("timeopt.llm_client.anthropic") as mock_anthropic:
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client
        config = {"llm_api_key": "test-key"}
        client = build_llm_client(config)
        assert client._model == "claude-sonnet-4-6"


def test_build_llm_client_openai_default_model_fallback():
    """When llm_model is not set in config and llm_base_url is set, fall back to default 'claude-sonnet-4-6'."""
    from timeopt.llm_client import build_llm_client
    with patch("timeopt.llm_client.openai") as mock_openai:
        mock_client = MagicMock()
        mock_openai.OpenAI.return_value = mock_client
        config = {
            "llm_base_url": "http://localhost:11434/v1",
            "llm_api_key": "test-key",
        }
        client = build_llm_client(config)
        assert client._model == "claude-sonnet-4-6"


def test_anthropic_client_complete_api_error_propagates():
    """When AnthropicClient.complete() calls API and it raises an exception, the exception should propagate."""
    import pytest
    with patch("timeopt.llm_client.anthropic") as mock_anthropic:
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client
        mock_client.messages.create.side_effect = RuntimeError("API error")

        client = AnthropicClient(api_key="test-key", model="claude-sonnet-4-6")
        with pytest.raises(RuntimeError, match="API error"):
            client.complete(system="sys", user="user msg")


def test_openai_compatible_client_complete_api_error_propagates():
    """When OpenAICompatibleClient.complete() calls API and it raises an exception, the exception should propagate."""
    import pytest
    with patch("timeopt.llm_client.openai") as mock_openai:
        mock_client = MagicMock()
        mock_openai.OpenAI.return_value = mock_client
        mock_client.chat.completions.create.side_effect = RuntimeError("API error")

        client = OpenAICompatibleClient(
            base_url="http://localhost:11434/v1",
            api_key="test",
            model="llama3",
        )
        with pytest.raises(RuntimeError, match="API error"):
            client.complete(system="sys", user="user msg")
