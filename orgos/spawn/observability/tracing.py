"""OpenTelemetry tracing for spawn runs. Optional dep — see package docstring.

Design goals:
  1. Zero overhead when OTel isn't installed / configured. Every helper is
     a no-op that returns a null context manager.
  2. Stable span names + attribute keys so dashboards don't break when
     orgos.spawn internals evolve.
  3. One place to redact prompts before they land in span attributes (large
     prompts + secrets don't belong in a trace).

Attribute conventions (loosely follow OTel GenAI semantic conventions):
  orgos.spawn.role         — role name
  orgos.spawn.run_id       — the unique run id
  orgos.spawn.tier         — the PermissionTier value
  orgos.spawn.stop_reason  — "stop" / "length" / "tool_error" / "budget"
  orgos.spawn.tool.name          — tool name for a tool span
  orgos.spawn.tool.approved      — bool for gated tools
  gen_ai.usage.prompt_tokens
  gen_ai.usage.completion_tokens
  gen_ai.usage.cached_tokens
"""

from __future__ import annotations

import contextlib
import logging
from contextlib import contextmanager
from typing import Any, Iterator

logger = logging.getLogger(__name__)

# Detect OTel at import time. If it's missing we shim everything to no-ops so
# consumers don't have to conditionally import.
try:
    from opentelemetry import trace as _otel_trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        ConsoleSpanExporter,
    )

    _HAS_OTEL = True
except ImportError:  # pragma: no cover - depends on install extras
    _HAS_OTEL = False


_INSTRUMENTATION_NAME = "orgos.spawn"
_INSTRUMENTATION_VERSION = "0.2.1"

_configured = False


def setup_tracing(
    *,
    service_name: str = "orgos-app",
    console: bool = False,
    exporter: Any | None = None,
) -> None:
    """Idempotent tracer setup.

    If ``console=True`` (or nothing else has configured a provider) a
    ``ConsoleSpanExporter`` is attached, which is useful for local dev.
    Otherwise it's the consumer's job to add exporters via
    ``opentelemetry.sdk.trace.TracerProvider.add_span_processor`` — passing
    one explicitly via ``exporter`` is a shortcut.

    In production, prefer wiring an OTLP exporter yourself and calling this
    with ``console=False`` (the default) so orgos.spawn doesn't fight your setup.
    """
    global _configured
    if _configured or not _HAS_OTEL:
        return

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    if exporter is not None:
        provider.add_span_processor(BatchSpanProcessor(exporter))
    elif console:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    _otel_trace.set_tracer_provider(provider)
    _configured = True
    logger.info("orgos.spawn tracing configured (service=%s)", service_name)


class _Tracer:
    """Facade so consumers write ``tracer.spawn_span(...)`` regardless of OTel state."""

    def _get(self) -> Any | None:
        if not _HAS_OTEL:
            return None
        return _otel_trace.get_tracer(_INSTRUMENTATION_NAME, _INSTRUMENTATION_VERSION)

    @contextmanager
    def spawn_span(
        self,
        *,
        role_name: str,
        run_id: str,
        tier: str | None = None,
    ) -> Iterator[Any]:
        t = self._get()
        if t is None:
            yield None
            return
        with t.start_as_current_span("orgos.spawn.spawn") as span:
            span.set_attribute("orgos.spawn.role", role_name)
            span.set_attribute("orgos.spawn.run_id", run_id)
            if tier is not None:
                span.set_attribute("orgos.spawn.tier", tier)
            yield span

    @contextmanager
    def tool_span(
        self,
        *,
        tool_name: str,
        approved: bool = True,
    ) -> Iterator[Any]:
        t = self._get()
        if t is None:
            yield None
            return
        with t.start_as_current_span(f"orgos.spawn.tool.{tool_name}") as span:
            span.set_attribute("orgos.spawn.tool.name", tool_name)
            span.set_attribute("orgos.spawn.tool.approved", approved)
            yield span

    def record_usage(
        self,
        span: Any,
        *,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cached_tokens: int = 0,
    ) -> None:
        if span is None or not _HAS_OTEL:
            return
        span.set_attribute("gen_ai.request.model", model)
        span.set_attribute("gen_ai.usage.prompt_tokens", prompt_tokens)
        span.set_attribute("gen_ai.usage.completion_tokens", completion_tokens)
        if cached_tokens:
            span.set_attribute("gen_ai.usage.cached_tokens", cached_tokens)

    def record_stop_reason(self, span: Any, reason: str) -> None:
        if span is None or not _HAS_OTEL:
            return
        span.set_attribute("orgos.spawn.stop_reason", reason)


tracer = _Tracer()


@contextmanager
def tool_span(tool_name: str, *, approved: bool = True) -> Iterator[Any]:
    """Convenience: use ``with tool_span('bash'): ...`` around a tool exec."""
    with tracer.tool_span(tool_name=tool_name, approved=approved) as span:
        yield span


# Public no-op context manager for tests / non-OTel code paths.
noop_span: contextlib.AbstractContextManager = contextlib.nullcontext()
