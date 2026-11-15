"""Which model the agent talks through: the provider directly, or a gateway when one is set."""

from pydantic import SecretStr

from app.engines.llm import build_agent_model
from app.settings import Settings


def test_without_a_gateway_the_provider_is_called_directly_and_replies_stream(settings: Settings) -> None:
    direct = settings.model_copy(update={"deepseek_api_key": SecretStr("test-provider-key")})
    model = build_agent_model(direct)
    assert model.model == "deepseek/deepseek-flash" and model.api_base is None
    assert model.model_kwargs == {"reasoning_effort": "low"}
    assert not model.disable_streaming
    assert build_agent_model(direct, reasoning_effort="none").model_kwargs == {"reasoning_effort": "none"}


def test_with_a_gateway_every_call_goes_through_it_and_streaming_turns_off_by_itself(settings: Settings) -> None:
    behind_gateway = settings.model_copy(
        update={"llm_gateway_url": "http://127.0.0.1:8020/v1", "llm_gateway_api_key": SecretStr("gate-key")}
    )
    model = build_agent_model(behind_gateway)  # no provider key is needed: the gateway holds it
    assert model.model == "openai/small" and model.api_base == "http://127.0.0.1:8020/v1"
    assert model.disable_streaming is True
    assert model.model_kwargs == {}  # thinking is off behind a gateway
