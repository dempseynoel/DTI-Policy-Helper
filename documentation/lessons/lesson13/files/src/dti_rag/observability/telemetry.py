"""OpenTelemetry -> this environment's Application Insights.

Every span carries `deployment.environment.name` (APP_ENV) and `service.version` (the git
SHA), so "which environment, which code?" is on every trace. Sampling is 100% in dev and test
and lower in prod (TRACE_SAMPLING_RATIO in deploy/<env>.env): a cost setting, not behaviour.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace

from dti_rag.config import get_settings

tracer = trace.get_tracer("dti_rag")
_configured = False


def configure_telemetry() -> None:
    """Call once at app startup. Instruments FastAPI, httpx and azure-core as well."""
    global _configured
    if _configured:
        return
    from azure.monitor.opentelemetry import configure_azure_monitor
    from opentelemetry.sdk.resources import Resource

    settings = get_settings()
    (connection_string,) = settings.require("applicationinsights_connection_string")
    configure_azure_monitor(
        connection_string=connection_string,
        credential=None,  # set a credential if App Insights local auth is disabled
        sampling_ratio=settings.trace_sampling_ratio,
        resource=Resource.create(
            {
                "service.name": "dti-rag",
                "service.version": settings.git_sha or "local",
                "deployment.environment.name": settings.app_env,
            }
        ),
    )
    _configured = True


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[trace.Span]:
    """A pipeline-stage span. Per-stage latency says WHICH part is slow."""
    with tracer.start_as_current_span(name) as s:
        for key, value in attributes.items():
            if value is not None:
                s.set_attribute(key, value)
        yield s


def current_trace_id() -> str | None:
    context = trace.get_current_span().get_span_context()
    return format(context.trace_id, "032x") if context.is_valid else None


def record_usage(usage: Any) -> None:
    """Add a model call's token counts to the current span. Cost surprises come from prompt
    growth. Accumulates: one stage can make several calls (one per edition)."""
    if usage is None:
        return
    current = trace.get_current_span()
    so_far = getattr(current, "attributes", None) or {}
    for key, value in (
        ("gen_ai.usage.input_tokens", getattr(usage, "prompt_tokens", 0) or 0),
        ("gen_ai.usage.output_tokens", getattr(usage, "completion_tokens", 0) or 0),
    ):
        current.set_attribute(key, int(so_far.get(key, 0)) + value)
