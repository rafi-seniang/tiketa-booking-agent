"""Chat models through LiteLLM. The model name alone switches provider: deepseek/..., gemini/..., and so on."""

import litellm
from langchain_litellm import ChatLiteLLM
from litellm.exceptions import MidStreamFallbackError

from app.settings import Settings

# LiteLLM prints a provider list to stderr whenever its own cost lookup misses a name. Our errors are logged anyway
litellm.suppress_debug_info = True


def api_key_for(model: str, settings: Settings) -> str:
    """The provider's key for a LiteLLM model name. Refuses to start without one rather than fail every turn."""
    provider = litellm.get_llm_provider(model)[1]
    keys = {"deepseek": settings.deepseek_api_key, "gemini": settings.gemini_api_key}
    if provider not in keys:
        raise RuntimeError(f"No API key setting for provider {provider!r} (model {model}). Add one to Settings")
    key = keys[provider].get_secret_value()
    if not key:
        raise RuntimeError(f"{model} needs {provider.upper()}_API_KEY in the secrets file")
    return key


# ChatLiteLLM retries a call that fails to start. These end a stream the provider dropped half way
STREAM_DROPPED_ERRORS: tuple[type[Exception], ...] = (MidStreamFallbackError,)


def build_chat_model(model: str, settings: Settings, reasoning_effort: str | None = None) -> ChatLiteLLM:
    """`reasoning_effort` overrides the setting, for calls that must not think (forced tool calls refuse it)."""
    return ChatLiteLLM(
        model=model,
        api_key=api_key_for(model, settings),
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_output_tokens,
        request_timeout=settings.llm_timeout_seconds,
        # Counts attempts, the first included: ChatLiteLLM retries timeouts, 429 and 5xx with backoff
        max_retries=settings.llm_max_attempts,
        # LiteLLM turns "none" into DeepSeek's thinking: disabled, and passes reasoning back when it is on
        model_kwargs={"reasoning_effort": reasoning_effort or settings.llm_reasoning_effort},
        stream_options={"include_usage": True},
    )
