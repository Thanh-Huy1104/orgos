"""Options strategist — AI-organisation layer driving options research.

Hard 3-agent pipeline (same pattern as quant_strategist.py — no manager LLM,
no delegation failures):

  options-researcher → options-analyst → options-synth

  Researcher:  identifies candidate tickers from news/catalysts and the user's
               directional thesis. Grounds the idea in real evidence.
  Analyst:     runs vol scan + surface scan for each candidate, interprets the
               IV surface, and suggests the appropriate strategy structure.
  Synth:       assembles the final handoff: recommended strategy, strike/expiry
               targets, Greeks, rationale, and an honest 'no edge found' if none.

Rubric: passes only when a real structural edge was found — IV rank in a
tradeable zone, a non-neutral vol signal, and a defined-risk structure
recommended. Grader reads tool outputs (not prose), so the model cannot
hallucinate a pass.

Journal: every run is recorded so the desk compounds — next run reads
what tickers/setups were already researched.
"""

from __future__ import annotations

import json
import os
from typing import Any

from orgos.options import grading as _grading  # noqa: F401 — registers options_edge grader
from orgos.quant import journal as quant_journal
from orgos.reflect import Reflector
from orgos.spawn import PermissionTier, RoleSpec, TaskBrief
from orgos.spawn import Rubric, chain_until, spawn_chain
from orgos.tools.options_tools import (
    OptionsGreeksTool,
    OptionsSurfaceTool,
    StrategySuggestTool,
    VolatilityScanTool,
)
from orgos.tools.research_sources import NewsCatalystTool

OPTIONS_MODEL = os.environ.get("ORGOS_OPTIONS_MODEL", "deepseek/deepseek-v4-pro")
_FAST_MODEL = os.environ.get("ORGOS_OPTIONS_FAST_MODEL", "deepseek/deepseek-v4-pro")


# ── Agent prompts ─────────────────────────────────────────────────────────────

_RESEARCHER_PROMPT = """You are an options research analyst. Your job is to identify
1-3 specific, liquid equity tickers that are strong candidates for an options strategy
given the objective and current market conditions.

Pipeline (follow in order):
1. Use news_catalysts to scan for what's moving right now — earnings upcoming,
   macro events, sector rotation, unusual volume. These create vol events worth trading.
2. For each catalyst, identify the 1-2 most liquid tickers involved. Liquid options
   require: price > $10, average daily volume > 500k shares, established options market
   (SPY, QQQ, AAPL, MSFT, NVDA, AMZN, TSLA, META, GOOGL are always valid; sector ETFs
   like XLF, XLE, XLK are also good).
3. State your directional view on each ticker: bullish, bearish, neutral, or volatile
   (expecting a big move but unsure of direction). Ground it in the news catalyst.
4. Output: a list of tickers with the catalyst, your view, and why this ticker is
   worth scanning for options edge.

You propose ideas. The analyst validates them with real IV data. A thesis that turns
out to have no edge is a valid result — report it honestly."""

_ANALYST_PROMPT = """You are a quantitative options analyst. The researcher's ticker
candidates and directional views are in your context. Your job: run the vol and
surface scans and determine whether a structural options edge exists.

Pipeline (for each candidate ticker):
1. Call scan_volatility to get realized vol, vol regime, and IV rank.
2. Call scan_options_surface to get the IV surface: ATM IV, skew, term structure.
3. If IV rank and surface confirm an edge (sell_premium or buy_options signal),
   call suggest_options_strategy with the ticker and the researcher's directional view.
4. Optionally call compute_options_greeks for the specific strike/expiry of interest
   to confirm the daily theta decay and delta exposure are acceptable.

What to report for each ticker:
- IV rank (0-100) and what it means: ≥50 = expensive, ≤25 = cheap
- ATM IV vs realized vol: positive difference = options overpriced → sell premium
- Skew interpretation: steep put skew = market nervous about downside
- Vol regime: low/medium/high and whether there's a spike today
- Top strategy recommendation with rationale
- Target expiry (DTE) and approximate strike zone

If a ticker has no structural edge (neutral IV zone, no clear signal), say so
explicitly. An honest 'no edge on AAPL today' is better than a forced recommendation.
The grader reads your tool outputs directly — you cannot pass the rubric without
real tool evidence."""

_SYNTH_PROMPT = """You are a synthesis lead. The researcher's candidates and the
analyst's validated surface data are in your context. Produce the final handoff.

For each ticker where a structural edge was found, report:
- Ticker and spot price
- Edge type: sell_premium (IV expensive) or buy_options (IV cheap)
- IV rank and ATM IV vs realized vol (the numbers)
- Recommended strategy structure (e.g. iron_condor, covered_call, long_straddle)
- Target expiry (DTE range) and approximate strikes to target
- Max profit / max loss profile
- Key Greeks to watch: delta exposure per $1 move, daily theta decay
- Specific risk to monitor: what breaks this trade?

If no ticker had a structural edge, say so plainly — 'no tradeable options edge
found today on the scanned tickers' — and suggest what setup would create one
(e.g. 'wait for IV rank > 50 on AAPL, currently at 38').

End with a one-line LESSON for the journal: what the IV environment was like,
which setups worked or didn't, what to watch next session."""


# ── Main entry point ──────────────────────────────────────────────────────────

def run_options_strategist(
    objective: str,
    *,
    view: str = "neutral",
    model: str | None = None,
    tool_call_budget: int = 10,
    verbose: bool = False,
    max_attempts: int = 2,
) -> Any:
    """Research → analyse → synthesise — 3-agent options research pipeline.

    Args:
        objective:        What you want to find, e.g. 'Find an options strategy
                         on a tech stock with upcoming earnings'.
        view:            Default directional view if not specified in the objective
                         ('bullish', 'bearish', 'neutral', 'volatile').
        model:           LLM override (defaults to ORGOS_OPTIONS_MODEL env var).
        tool_call_budget: Max tool calls per agent phase.
        verbose:         Stream agent thoughts to terminal.
        max_attempts:    Rubric retry limit. Set 1 to disable retry loop.

    Returns:
        SpawnResult with envelope (status, summary, notes), token_usage, run_id,
        grade (passed, score, notes from the options_edge grader).
    """
    mdl = model or OPTIONS_MODEL

    # ── Agent specs ──────────────────────────────────────────────────────────

    researcher = RoleSpec(
        name="options-researcher",
        description="Identifies 1-3 liquid ticker candidates from news catalysts and the objective.",
        tier=PermissionTier.WORKER,
        system_prompt=_RESEARCHER_PROMPT,
        tools=[NewsCatalystTool()],
        model=_FAST_MODEL,
        max_iter=8,
    )
    analyst = RoleSpec(
        name="options-analyst",
        description="Runs vol + surface scans, interprets IV, recommends strategy structures.",
        tier=PermissionTier.WORKER,
        system_prompt=_ANALYST_PROMPT,
        tools=[
            VolatilityScanTool(),
            OptionsSurfaceTool(),
            StrategySuggestTool(),
            OptionsGreeksTool(),
        ],
        model=_FAST_MODEL,
        max_iter=12,
    )
    synth = RoleSpec(
        name="options-synth",
        description="Synthesises research and analysis into the final strategy handoff.",
        tier=PermissionTier.WORKER,
        system_prompt=_SYNTH_PROMPT,
        model=mdl,
        max_iter=4,
    )

    # ── Briefs ────────────────────────────────────────────────────────────────

    prior = quant_journal.prior_research_block(n=3)

    _reflector = Reflector(domain="options")
    playbook_heuristics = _reflector.retrieve(objective, n=3)
    playbook_block = _reflector.inject_block(playbook_heuristics)

    research_brief = TaskBrief(
        objective=(
            f"Objective: {objective}\n"
            f"Default view: {view}\n\n"
            "Scan recent news catalysts. Identify 1-3 liquid equity tickers where "
            "an options strategy might have structural edge given the objective and "
            "current market conditions. Ground each candidate in a specific catalyst."
            + (f"\n\n{prior}" if prior else "")
            + (f"\n\n{playbook_block}" if playbook_block else "")
        ),
        tool_call_budget=max(tool_call_budget // 2, 3),
        success_criteria=[
            "1-3 specific ticker candidates with directional view and catalyst rationale",
        ],
    )
    analysis_brief = TaskBrief(
        objective=(
            "For each ticker from the researcher (see context), run scan_volatility "
            "then scan_options_surface. If an edge exists (sell_premium or buy_options "
            "signal), also call suggest_options_strategy with the researcher's view. "
            "Report the IV rank, surface shape, and top strategy recommendation for "
            "each ticker. If no edge, say so plainly."
        ),
        tool_call_budget=tool_call_budget,
        success_criteria=[
            "Vol scan and surface scan run for each proposed ticker",
            "IV rank and edge signal reported for each ticker",
            "Strategy recommendation provided where edge exists",
        ],
    )
    synth_brief = TaskBrief(
        objective=(
            "Synthesise the researcher's candidates and the analyst's surface data "
            "(both in context) into the final options strategy handoff. "
            "For tickers with edge: report the structure, target strikes/expiry, "
            "risk profile, and Greeks. For tickers without: explain what's missing. "
            "End with a one-line LESSON for the journal."
        ),
        success_criteria=[
            "Each ticker's edge (or lack of edge) addressed with supporting data",
            "Concrete strategy recommendation or honest 'no edge found'",
            "One-line LESSON for the journal",
        ],
    )

    # ── Rubric + chain ────────────────────────────────────────────────────────

    rubric = Rubric(
        criteria=[
            "IV rank is in a tradeable zone (≥40 for premium selling, ≤35 for buying) "
            "AND the vol surface confirms a non-neutral edge signal AND the recommended "
            "strategy is defined-risk",
        ],
        grader="options_edge",
        max_attempts=max_attempts,
        optimize=max_attempts > 1,  # keep the attempt with the strongest edge score
    )

    result = chain_until(
        [(researcher, research_brief), (analyst, analysis_brief), (synth, synth_brief)],
        rubric,
        runner=spawn_chain,
        feedback_into=0,   # on failure push back to researcher to try different tickers
        verbose=verbose,
        run_budget_tokens=300_000,
    )

    # ── Record to journal (same table as quant_strategist) ────────────────────

    try:
        g = getattr(result, "grade", None)
        quant_journal.record(
            f"[options] {objective}",
            result.envelope.summary or "",
            status=result.envelope.status,
            tokens=(result.token_usage or {}).get("total_tokens"),
            run_id=getattr(result, "run_id", None),
            score=(g.score if g is not None else None),
            attempts=getattr(result, "attempts", None),
            attempt_run_ids=getattr(result, "attempt_run_ids", None),
        )
    except Exception:  # noqa: BLE001 — journal failure must never kill the result
        pass

    # ── Reflect: extract heuristics from rubric diffs for future runs ────────
    try:
        _reflector.reflect(result)
    except Exception:  # noqa: BLE001
        pass

    return result
