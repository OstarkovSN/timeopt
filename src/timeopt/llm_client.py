import logging
import os

logger = logging.getLogger(__name__)

try:
    import anthropic
except ImportError:
    anthropic = None  # type: ignore

try:
    import openai
except ImportError:
    openai = None  # type: ignore


class LLMClient:
    """Abstract LLM client interface."""

    def complete(self, system: str, user: str) -> str:
        raise NotImplementedError


class AnthropicClient(LLMClient):
    def __init__(self, api_key: str | None, model: str, max_tokens: int = 4096):
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise ValueError(
                "ANTHROPIC_API_KEY is not set. "
                "Set it via environment variable or timeopt config: "
                "timeopt config set llm_api_key <key>"
            )
        self._client = anthropic.Anthropic(api_key=key)
        self._model = model
        self._max_tokens = max_tokens

    def complete(self, system: str, user: str) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        result = response.content[0].text
        logger.debug("AnthropicClient.complete: %d chars", len(result))
        return result


class OpenAICompatibleClient(LLMClient):
    def __init__(self, base_url: str, api_key: str, model: str):
        self._client = openai.OpenAI(base_url=base_url, api_key=api_key)
        self._model = model

    def complete(self, system: str, user: str) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        result = response.choices[0].message.content
        logger.debug("OpenAICompatibleClient.complete: %d chars", len(result))
        return result


def build_llm_client(config: dict) -> LLMClient:
    """
    Build the appropriate LLM client from config.
    Uses OpenAICompatibleClient if llm_base_url is set, else AnthropicClient.
    """
    try:
        max_tokens = int(config.get("llm_max_tokens") or "4096")
    except ValueError:
        logger.warning("build_llm_client: llm_max_tokens is not a valid integer, using default 4096")
        max_tokens = 4096
    if config.get("llm_base_url"):
        return OpenAICompatibleClient(
            base_url=config["llm_base_url"],
            api_key=config.get("llm_api_key", ""),
            model=config.get("llm_model", "claude-sonnet-4-6"),
        )
    return AnthropicClient(
        api_key=config.get("llm_api_key"),
        model=config.get("llm_model", "claude-sonnet-4-6"),
        max_tokens=max_tokens,
    )
