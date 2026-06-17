"""Quant strategist — the AI-organization layer driving cointegration discovery.

This is the agent that was missing. Instead of scanning hardcoded sector lists,
an LLM strategist *reasons* about where non-obvious cointegration might live
(supply-chain links, shared-commodity exposure, cross-sector single-factor,
corporate-structure pairs), PROPOSES concrete ticker universes, and tests each
with the deterministic scanner tools. It can SPAWN the research department to
verify the economic rationale for a promising pair.

The division of labour that keeps it both autonomous and rigorous:
  - the agent is creative about WHAT to look at (hypothesis generation — the
    alpha-bearing, genuinely agentic part);
  - the tools are strict about WHAT'S REAL (cointegration + FDR + durability).
A bad hypothesis just yields a universe that fails the screen — contained.

Agent-driven (the strategist decides the universes and the tool calls), uses the
scanner/crypto tools as skills, and spawns real orgos research. Recommend-only.
"""

from __future__ import annotations

import json
import os
from typing import Any

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from .contracts import PermissionTier, RoleSpec, TaskBrief
from .crypto_tool import CryptoScannerTool
from .quant_tool import CointegrationScannerTool
from .spawn import spawn_chain

STRATEGIST_MODEL = os.environ.get("ORGOS_STRATEGIST_MODEL", "deepseek/deepseek-v4-pro")

_ORG = None


def _org():
    global _ORG
    if _ORG is None:
        from .departments import load_org

        _ORG = load_org(os.environ.get("ORGOS_ORG_YAML", "./examples/org.yaml"))
    return _ORG


class _ResearchInput(BaseModel):
    thesis: str = Field(description="The economic-linkage thesis to investigate, "
                                    "e.g. 'DUK and SO are both regulated SE-US utilities "
                                    "with similar rate-base and rate exposure'.")


class ResearchLinkageTool(BaseTool):
    name: str = "research_linkage"
    description: str = (
        "Spawn the research department to investigate WHY a candidate pair should "
        "be cointegrated — economic linkage, shared drivers, recent news/filings. "
        "Use sparingly (it's slow/expensive) and only for a pair that already "
        "passed the deterministic scan. Returns a short verified verdict."
    )
    args_schema: type[BaseModel] = _ResearchInput
    tool_category: str = "read"

    def _run(self, thesis: str) -> str:
        from .departments import run_department

        brief = TaskBrief(
            objective=(
                "Assess whether the following pairs-trading linkage thesis is "
                "economically sound. State supported/weak/refuted with one or two "
                "sources.\n\nThesis: " + thesis
            ),
            source_guidance="Prefer primary sources and reputable financial press. One source per claim is enough.",
            tool_call_budget=4,
            success_criteria=["A supported/weak/refuted verdict", "At least one source URL"],
        )
        try:
            r = run_department(_org(), "research", brief, verbose=False, record=False,
                               run_budget_tokens=200_000)
            return json.dumps({"verdict_status": r.envelope.status,
                               "summary": (r.envelope.summary or "")[:800],
                               "notes": r.envelope.notes})
        except Exception as exc:  # noqa: BLE001 — never crash the strategist
            return json.dumps({"error": f"{type(exc).__name__}: {exc}"})


_STRATEGIST_PROMPT = (
    "You are a quantitative strategist hunting cointegration alpha that others "
    "miss. You do NOT scan obvious same-sector lists — that's crowded. Instead "
    "you reason about NON-OBVIOUS reasons two assets should move together:\n"
    "  - supply-chain / customer-supplier links (chip designer & foundry, "
    "automaker & parts supplier)\n"
    "  - shared commodity/input exposure (airlines & a refiner; two names both "
    "driven by copper)\n"
    "  - corporate-structure pairs (spinoff & parent, dual share classes)\n"
    "  - cross-sector single-factor (rate-sensitive names across REITs, utilities, "
    "regional banks)\n\n"
    "Workflow:\n"
    "1. From the objective, PROPOSE 2-4 concrete candidate universes (explicit "
    "ticker lists), each with a one-line economic thesis for why cointegration is "
    "plausible there.\n"
    "2. Test each universe by calling the scan tool (scan_cointegrated_pairs for "
    "equities, scan_crypto_pairs for crypto) with your ticker list.\n"
    "3. For a pair that SURVIVES the scan, you may call research_linkage once to "
    "verify the economic rationale (optional, slow).\n"
    "4. Report the durable surviving pairs, each with: the stats from the scan AND "
    "the economic thesis that led you to look there. If nothing survives, say so "
    "honestly — a clean 'no durable pairs in these hypotheses' is a valid result.\n"
    "You propose and validate; you never trade."
)


def run_strategist(
    objective: str, *, asset_class: str = "equity", allow_research: bool = True,
    model: str | None = None, tool_call_budget: int = 8, verbose: bool = False,
) -> Any:
    """Hypothesize → scan → (optionally) research → synthesise a clean handoff.

    Two-step chain: a tool-using strategist does the discovery (proposes
    universes, calls the scan/research tools), then a terminal synthesis worker
    (no tools → json_object on DeepSeek) wraps the findings into a valid
    HandoffEnvelope. A single tool-using agent can't reliably emit the envelope
    shape (it returns domain JSON), so the synthesis step is what guarantees a
    clean handoff — the same pattern the departments use.
    """
    mdl = model or STRATEGIST_MODEL
    tools: list[Any] = [CointegrationScannerTool(), CryptoScannerTool()]
    if allow_research:
        tools.append(ResearchLinkageTool())

    strategist = RoleSpec(
        name="quant-strategist",
        description="Proposes non-obvious cointegration universes and validates them with the scan tools.",
        tier=PermissionTier.WORKER,
        system_prompt=_STRATEGIST_PROMPT,
        tools=tools,
        model=mdl,
        max_iter=20,
    )
    synth = RoleSpec(
        name="quant-synth",
        description="Synthesises the strategist's findings into the final handoff.",
        tier=PermissionTier.WORKER,
        system_prompt=(
            "You are a synthesis lead. The strategist's findings (proposed "
            "universes, scan results, rationale) are in your context. Combine them "
            "into one final handoff: list each durable surviving pair with its "
            "stats and the economic thesis that led there; if none survived, say so "
            "plainly. Do not redo the work or call tools — just synthesise."
        ),
        model=mdl,
        max_iter=5,
    )
    strat_brief = TaskBrief(
        objective=(
            f"Objective: {objective}\n\nAsset class focus: {asset_class}. "
            "Propose candidate universes, test each with the scan tool, optionally "
            "verify a survivor's linkage, and lay out the durable pairs with rationale."
        ),
        tool_call_budget=tool_call_budget,
        success_criteria=[
            "At least 2 candidate universes proposed, each with an economic thesis",
            "Each proposed universe tested with the scan tool",
        ],
    )
    synth_brief = TaskBrief(
        objective=(
            "Synthesise the strategist's findings (in context) into the final "
            "handoff: durable surviving cointegrated pairs with stats + the economic "
            "rationale for each, or an honest 'no durable pairs in these hypotheses'."
        ),
        success_criteria=[
            "Surviving pairs reported with stats and rationale, or an honest 'none'",
        ],
    )
    return spawn_chain(
        [(strategist, strat_brief), (synth, synth_brief)],
        verbose=verbose, run_budget_tokens=400_000,
    )
