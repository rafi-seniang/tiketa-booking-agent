"""Chat models through LiteLLM. The model name alone switches provider: deepseek/..., gemini/..., and so on.
With LLM_GATEWAY_URL set, every call goes through that gateway instead."""

from typing import Any

import litellm
from langchain_litellm import ChatLiteLLM
from litellm.exceptions import MidStreamFallbackError

from app.settings import Settings

# LiteLLM prints a provider list to stderr whenever its own cost lookup misses a name. Our errors are logged anyway
litellm.suppress_debug_info = True


def api_key_for(model: str, settings: Settings) -> str:
    """The provider's key for a LiteLLM model name. Refuses to start without one rather than fail every turn."""
    provider = litellm.get_llm_provider(model)[1]
    if provider == "gemini":
        if not settings.gemini_api_keys:
            raise RuntimeError(f"{model} needs {provider.upper()}_API_KEY in the secrets file")
        return settings.gemini_api_keys[0]
    keys = {"deepseek": settings.deepseek_api_key}
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
    # LiteLLM turns "none" into DeepSeek's thinking: disabled, and passes reasoning back when it is on
    model_kwargs: dict[str, Any] = {"reasoning_effort": reasoning_effort or settings.llm_reasoning_effort}
    if litellm.get_llm_provider(model)[1] == "gemini" and len(settings.gemini_api_keys) > 1:
        model_kwargs["fallbacks"] = [{"model": model, "api_key": key} for key in settings.gemini_api_keys[1:]]
    return ChatLiteLLM(
        model=model,
        api_key=api_key_for(model, settings),
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_output_tokens,
        request_timeout=settings.llm_timeout_seconds,
        # Counts attempts, the first included: ChatLiteLLM retries timeouts, 429 and 5xx with backoff
        max_retries=settings.llm_max_attempts,
        model_kwargs=model_kwargs,
        stream_options={"include_usage": True},
    )


def build_agent_model(settings: Settings, reasoning_effort: str | None = None) -> ChatLiteLLM:
    """The model the agent talks through: the gateway when one is set, otherwise the provider directly."""
    if settings.llm_gateway_url:
        return build_gateway_model(settings)
    return build_chat_model(settings.llm_model, settings, reasoning_effort)


def build_gateway_model(settings: Settings) -> ChatLiteLLM:
    """The same calls through an OpenAI-compatible gateway, which picks the model and holds the provider's key.

    A gateway that masks text answers in one piece, so streaming is turned off here and each reply arrives whole.
    Thinking is off too: its reasoning would have to pass back through the gateway on every tool call.
    """
    return ChatLiteLLM(
        model=f"openai/{settings.llm_gateway_model}",  # LiteLLM's name for "speak the OpenAI protocol to api_base"
        api_base=settings.llm_gateway_url,
        api_key=settings.llm_gateway_api_key.get_secret_value() or "no-key",  # the client refuses an empty one
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_output_tokens,
        request_timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_attempts,
        disable_streaming=True,
    )
