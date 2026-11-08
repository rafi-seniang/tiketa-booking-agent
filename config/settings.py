"""Typed settings. Every environment value the service reads is declared here, nowhere else."""

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
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

    # Comma-separated keys accepted in the X-API-Key header. Empty disables auth (local only).
    api_keys: SecretStr = SecretStr("")
    # Browser origins allowed to call the API (the lab frontend in development and preview)
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:4173"]

    # SQLAlchemy URL of the cinema database, which also holds the conversation checkpoints.
    # postgresql+psycopg://... for real use, sqlite+aiosqlite:///./tiketa.db for a quick local run
    database_url: SecretStr

    # The chat model as a LiteLLM name. The provider prefix picks the key: deepseek/ or gemini/
    llm_model: str = "deepseek/deepseek-flash"
    deepseek_api_key: SecretStr = Field(default=SecretStr(""), validation_alias=AliasChoices("DEEPSEEK_API_KEY"))
    gemini_api_key: SecretStr = Field(default=SecretStr(""), validation_alias=AliasChoices("GEMINI_API_KEY"))
    # low turns DeepSeek's thinking mode on, none turns it off. With it, seats described in words ("at the back by the
    # aisle") came out right 3 of 3 times against 1 of 3, for 0.6 s more per turn (evals/README.md)
    llm_reasoning_effort: Literal["none", "low", "medium", "high"] = "low"
    llm_temperature: float = Field(default=0.3, ge=0, le=2)
    # Thinking counts as output, so this leaves room for it on top of a short reply
    llm_max_output_tokens: int = Field(default=4000, gt=0)
    llm_timeout_seconds: float = Field(default=60, gt=0)
    # Attempts at one model call, counting the first, on timeouts, 429 and 5xx before the turn fails
    llm_max_attempts: int = Field(default=3, gt=0)
    # Model calls one turn may make. Past it the turn stops with an error instead of looping
    max_model_calls_per_turn: int = Field(default=10, gt=0)
    # Older messages are summarised once a conversation passes this many tokens
    summarize_from_tokens: int = Field(default=8000, gt=0)
    messages_kept_after_summary: int = Field(default=20, gt=0)
    # Grades the scenario runs. A different, stronger model than the agent, so it does not grade itself
    judge_model: str = "deepseek/deepseek-v4-pro"

    cinema_name: str = "Tiketa Cinema"
    # Showtimes are stored in UTC and shown, and understood, in this timezone
    cinema_timezone: str = "Asia/Jakarta"
    max_seats_per_booking: int = Field(default=8, gt=0)

    # Redis for the shared rate limit and the one-turn-at-a-time lock. Empty keeps both per process: local only
    redis_url: SecretStr = SecretStr("")
    redis_timeout_seconds: float = Field(default=2, gt=0)
    # Requests per caller (API key, or client address without one) per minute on /v1
    rate_limit_per_minute: int = Field(default=60, gt=0)
    # How long a turn may hold its conversation before the lock expires on its own (a crashed worker)
    turn_lock_seconds: int = Field(default=180, gt=0)

    # Phoenix's OTLP endpoint, for example http://localhost:6006/v1/traces. Empty turns tracing off
    phoenix_collector_endpoint: str = ""
    phoenix_project_name: str = "tiketa"

    @property
    def api_key_list(self) -> list[str]:
        return [key.strip() for key in self.api_keys.get_secret_value().split(",") if key.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # database_url comes from the environment
