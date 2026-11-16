"""Typed settings. Every environment value the service reads is declared here, nowhere else."""

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../../secrets/secrets.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )

    environment: Literal["local", "test", "staging", "production"] = "local"
    log_level: str = "INFO"

    # Browser origins allowed to call the agent (Tiketa's web app in development and preview)
    cors_origins: list[str] = ["http://localhost:5174", "http://localhost:4174"]

    # The booking service (tiketa-app): films, showtimes, seats, bookings, and who a caller is.
    # The agent does not start without it
    booking_api_url: str = "http://127.0.0.1:8070"
    # For the agent's own two reads at startup (the cinema and its films). Empty when that service runs without keys
    booking_api_key: SecretStr = SecretStr("")
    booking_api_timeout_seconds: float = Field(default=10, gt=0)

    # SQLAlchemy URL of the agent's own database: who owns each conversation, and the conversation checkpoints.
    # postgresql+psycopg://... for real use, sqlite+aiosqlite:///./agent.db for a quick local run
    database_url: SecretStr

    # The chat model as a LiteLLM name. The provider prefix picks the key: deepseek/ or gemini/
    llm_model: str = "deepseek/deepseek-flash"
    deepseek_api_key: SecretStr = Field(default=SecretStr(""), validation_alias=AliasChoices("DEEPSEEK_API_KEY"))
    gemini_api_key: SecretStr = Field(default=SecretStr(""), validation_alias=AliasChoices("GEMINI_API_KEY"))
    gemini_api_key_2: SecretStr = Field(default=SecretStr(""), validation_alias=AliasChoices("GEMINI_API_KEY_2"))
    gemini_api_key_3: SecretStr = Field(default=SecretStr(""), validation_alias=AliasChoices("GEMINI_API_KEY_3"))

    @property
    def gemini_api_keys(self) -> list[str]:
        """All configured Gemini API keys in priority order for automatic quota failover."""
        return [
            k
            for raw in (self.gemini_api_key, self.gemini_api_key_2, self.gemini_api_key_3)
            if (k := raw.get_secret_value().strip())
        ]

    # low turns DeepSeek's thinking mode on, none turns it off. With it, seats described in words ("at the back by the
    # aisle") came out right 3 of 3 times against 1 of 3, for 0.6 s more per turn (evals/README.md)
    llm_reasoning_effort: Literal["none", "low", "medium", "high"] = "low"
    llm_temperature: float = Field(default=0.3, ge=0, le=2)
    # Thinking counts as output, so this leaves room for it on top of a short reply
    llm_max_output_tokens: int = Field(default=4000, gt=0)
    llm_timeout_seconds: float = Field(default=60, gt=0)
    # Attempts at one model call, counting the first, on timeouts, 429 and 5xx before the turn fails
    llm_max_attempts: int = Field(default=3, gt=0)
    # An OpenAI-compatible gateway in front of the model (Gatekeeper: masking and injection checks). Empty calls
    # the provider directly. With a gateway, replies arrive whole instead of token by token and thinking is off,
    # because the gateway answers in one piece
    llm_gateway_url: str = ""
    llm_gateway_api_key: SecretStr = SecretStr("")
    # The model name the gateway is asked for. Gatekeeper answers with its own model whatever is named
    llm_gateway_model: str = "small"
    # Gatekeeper checks each visitor message before the agent reads it: a prompt injection or a request outside the
    # cinema (code, recipes, poems) is refused at once, and no model is called. Empty skips the check (local runs)
    gatekeeper_url: str = ""
    gatekeeper_api_key: SecretStr = SecretStr("")
    # The scope kept in Gatekeeper under this name, so its console shows the text this agent is checked against
    gatekeeper_scope_name: str = "tiketa"
    gatekeeper_timeout_seconds: float = Field(default=5, gt=0)
    # Model calls one turn may make. Past it the turn stops with an error instead of looping
    max_model_calls_per_turn: int = Field(default=10, gt=0)
    # Older messages are summarised once a conversation passes this many tokens
    summarize_from_tokens: int = Field(default=8000, gt=0)
    messages_kept_after_summary: int = Field(default=20, gt=0)
    # Grades the scenario runs. A different, stronger model than the agent, so it does not grade itself
    judge_model: str = "deepseek/deepseek-v4-pro"

    # Redis for the shared rate limit and the one-turn-at-a-time lock. Empty keeps both per process: local only
    redis_url: SecretStr = SecretStr("")
    redis_timeout_seconds: float = Field(default=2, gt=0)
    # Requests per caller per minute on /v1
    rate_limit_per_minute: int = Field(default=60, gt=0)
    # Model tokens (input and output) per caller per UTC day on chat turns. A turn starts only below it
    daily_tokens_per_caller: int = Field(default=400_000, gt=0)
    # Model tokens for all callers together per UTC day: the most the chat can spend in a day, whoever calls
    daily_tokens_total: int = Field(default=3_000_000, gt=0)
    # How long a turn may hold its conversation before the lock expires on its own (a crashed worker)
    turn_lock_seconds: int = Field(default=180, gt=0)

    # Phoenix's OTLP endpoint, for example http://localhost:6006/v1/traces. Empty turns tracing off
    phoenix_collector_endpoint: str = ""
    phoenix_project_name: str = "tiketa"

    @model_validator(mode="after")
    def production_needs_a_key_for_the_booking_api(self) -> "Settings":
        if self.environment == "production" and not self.booking_api_key.get_secret_value():
            raise ValueError("production needs BOOKING_API_KEY: the booking service refuses callers without one there")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # database_url comes from the environment
