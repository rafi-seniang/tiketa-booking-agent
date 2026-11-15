"""Traces of every agent run (prompts, tool calls, tokens) sent to a self-hosted Phoenix over OpenTelemetry."""

from collections.abc import Callable

from phoenix.otel import register

from app.settings import Settings


def start_tracing(settings: Settings) -> Callable[[], None] | None:
    """Returns the shutdown that flushes the last spans, or None when tracing is off."""
    if not settings.phoenix_collector_endpoint:
        return None
    provider = register(
        endpoint=settings.phoenix_collector_endpoint,
        project_name=settings.phoenix_project_name,
        batch=True,
        auto_instrument=True,  # the installed OpenInference instrumentor for LangChain
        verbose=False,
    )
    return provider.shutdown
