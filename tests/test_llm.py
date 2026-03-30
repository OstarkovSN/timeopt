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
