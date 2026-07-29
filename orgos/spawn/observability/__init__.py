"""orgos.spawn.observability — OpenTelemetry spans for spawn runs.

Wire this at consumer startup:

    from orgos.spawn.observability import setup_tracing, tracer
    setup_tracing(service_name="my-app")

then wrap each spawn call:

    with tracer.spawn_span(role_name="reviewer", run_id="abc"):
        result = spawn(...)

Each tool call inside the spawn produces a child span if the caller uses
:func:`orgos.spawn.observability.tool_span` around its execution. Import of
this module is safe even if opentelemetry is not installed — the calls
become no-ops. Install the extra: ``pip install 'opentelemetry-sdk'``.
"""

from .tracing import setup_tracing, tracer, tool_span

__all__ = ["setup_tracing", "tracer", "tool_span"]
