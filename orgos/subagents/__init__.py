"""orgos.subagents — pre-built agent definitions.

Modules here assemble RoleSpecs + briefs into ready-to-run agents and pipelines
on top of the spawn engine: the *who* of the org, distinct from the engine
(orgos.spawn), the tools they wield (orgos.tools), and the MCP servers they
connect to (orgos.mcps).

  quant_strategist  — the research → scan → synth discovery pipeline
  quant_supervisor  — the live-book overview + recommendation view
"""

from . import quant_strategist, quant_supervisor

__all__ = ["quant_strategist", "quant_supervisor"]
