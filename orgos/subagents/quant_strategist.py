"""Quant strategist — the AI-organization layer driving cointegration discovery.

The strategist is a deterministic 3-agent chain (no manager, no delegation —
just a hard pipeline like the departments use with sequential=True):

  quant-researcher → quant-scanner → quant-synth
    (ground truth)     (validation)     (handoff)

Each agent sees the prior agent's output as context. The pipeline is enforced
in code, not left to a manager-LLM to *decide* — the same battle-tested pattern
that fixed department runs (managers narrate "I should delegate" and block).

Division of labour:
  - Researcher: creative hypothesis generation (the alpha-bearing part), grounded
    in news catalysts, arXiv literature, and live S&P 500 index constituents.
  - Scanner: deterministic validation — FDR, durability, factor independence.
    The math judge. Optionally research_linkage on a top survivor.
  - Synth: terminal synthesis into the HandoffEnvelope. No tools, just writes.

Agent-driven, recommend-only. Never trades or writes Icarus.
"""

from __future__ import annotations

import json
import os
from typing import Any

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from pathlib import Path

from orgos.quant import journal as quant_journal
from orgos.quant import grading as _grading  # noqa: F401 — registers cointegration_gates grader
from orgos.reflect import Reflector
from orgos.spawn import PermissionTier, RoleSpec, TaskBrief
from orgos.tools.crypto_tool import CryptoScannerTool
from orgos.tools.quant_tool import CointegrationScannerTool
from orgos.tools.research_sources import ArxivSearchTool, IndexConstituentsTool, NewsCatalystTool
from orgos.spawn import Rubric, chain_until, spawn_chain

STRATEGIST_MODEL = os.environ.get("ORGOS_STRATEGIST_MODEL", "deepseek/deepseek-v4-pro")
_FAST_MODEL = os.environ.get("ORGOS_STRATEGIST_FAST_MODEL", "deepseek/deepseek-v4-pro")
_SKILL_DIR = Path(__file__).resolve().parent.parent.parent / "skills" / "quant" / "strategy-research"

_ORG = None


def _org():
    global _ORG
    if _ORG is None:
        from orgos.departments import load_org

        _ORG = load_org(os.environ.get("ORGOS_ORG_YAML", "./config/org.yaml"))
    return _ORG


# ── ResearchLinkageTool (on scanner — vet a survivor with the org research dept)

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
        from orgos.departments import run_department

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


# ── Phase 1: Research — ground truth from live sources ────────────────────────

_RESEARCHER_PROMPT = (
    "You are a quantitative research analyst. Your job is to ground the "
    "objective in REAL, current evidence — never from memory.\n\n"
    "Pipeline (follow in order):\n"
    "1. If the brief mentions 'Prior research notes', read them first — don't "
    "re-test known dead ends; build on previously found live pairs.\n"
    "2. Use news_catalysts to find what's moving now (M&A announcements, regime "
    "shifts, supply-chain events, sector rotation). A catalyst is a REASON to "
    "look at a universe.\n"
    "3. Use search_arxiv to find documented cointegration relationships in the "
    "q-fin literature. Let findings shape your hypotheses, not your recall.\n"
    "4. Use index_constituents to get the ACTUAL, complete S&P 500 membership "
    "for any sector you're investigating — pass the full real list forward, "
    "never a remembered subset.\n"
    "5. For each candidate universe, state the economic thesis clearly and "
    "which specific evidence (catalyst / paper / constituent membership) "
    "supports it.\n"
    "6. Output: concrete ticker lists (space-separated for the scanner), the "
    "economic thesis for each universe, and the evidence trail.\n\n"
    "You propose ideas; the scanner judges them. A rejected hypothesis is not "
    "a failure — it's a contained dead end."
)

# ── Phase 2: Scan — deterministic validation ──────────────────────────────────

_SCANNER_PROMPT = (
    "You are a quantitative validation analyst. The researcher's grounded "
    "universes and economic theses are in your context. Your job: run "
    "deterministic cointegration scans on each proposed universe.\n\n"
    "Pipeline:\n"
    "1. For each universe (ticker list) from the researcher, call "
    "scan_cointegrated_pairs (equities) or scan_crypto_pairs (crypto) with "
    "the full ticker list as a space-separated string.\n"
    "2. The scanner implements Benjamini-Hochberg FDR + sub-period durability "
    "+ factor independence + half-life bounds. TRUST its output — it is the "
    "ground truth. You cannot override a negative scan result.\n"
    "3. For each SURVIVING pair, report: tickers, adf_p, half-life, hurst, "
    "beta, factor_r2, sub-period p-values, and the researcher's economic "
    "thesis.\n"
    "4. If a top survivor needs deeper economic vetting, optionally call "
    "research_linkage (slow — spawns the full research department). Use for "
    "at most 1-2 candidates.\n"
    "5. If a universe returns zero survivors, note it — the hypothesis was "
    "wrong, which is a valid result.\n\n"
    "You validate; you never fabricate. The scanner is the judge."
)

# ── Phase 3: Synthesis — terminal handoff ─────────────────────────────────────

_SYNTH_PROMPT = (
    "You are a synthesis lead. The researcher's grounded evidence and the "
    "scanner's validated results are in your context. Combine everything into "
    "a single, honest handoff.\n\n"
    "For each durable surviving pair, report:\n"
    "- Pair tickers\n"
    "- Cointegration stats (adf_p, half-life, hurst, beta, factor_r2, "
    "sub-period p-values)\n"
    "- OUT-OF-SAMPLE P&L (the bottom line): oos_sharpe, oos_return, n_trades, "
    "win_rate, max_dd. A pair is only worth trading if it made money out-of-sample; "
    "lead with the highest-Sharpe pair and say plainly if the best one still lost money.\n"
    "- The economic thesis that led there (from the researcher)\n"
    "- Whether research_linkage verified it\n"
    "- Whether it's a known-live pair from prior research or newly discovered\n\n"
    "If no durable pairs survived any universe, say so plainly. An honest "
    "'no durable pairs found' is better than fabrication.\n\n"
    "End with a one-line LESSON for the journal — what worked, what didn't, "
    "what to try next time."
)


# ── Main entry point ──────────────────────────────────────────────────────────

def run_strategist(
    objective: str, *, asset_class: str = "equity", allow_research: bool = True,
    model: str | None = None, tool_call_budget: int = 12, verbose: bool = False,
    max_attempts: int = 2,
) -> Any:
    """Research → scan → synthesise — a hard 3-agent pipeline, under a rubric loop.

    Deterministic chain (like department runs with sequential=True): each agent
    owns one phase and sees prior outputs as context. No manager, no delegation
    failures — the order is enforced in code.

    The chain runs under a deterministic rubric: a hunt "succeeds" only if the
    scan surfaced at least one durable cointegrated pair. If a pass finds none,
    the failure is fed back to the researcher to re-aim (different/wider
    universes) and the chain re-runs, up to ``max_attempts`` (set 1 to disable
    the loop). The grade is read from the scan trail, not the synth's prose — and
    it costs no extra tokens to compute.
    """
    mdl = model or STRATEGIST_MODEL
    skills = [str(_SKILL_DIR)] if _SKILL_DIR.is_dir() else []

    # ── Agent specs ──────────────────────────────────────────────────────────

    scanner_tools: list[Any] = [CointegrationScannerTool(), CryptoScannerTool()]
    if allow_research:
        scanner_tools.append(ResearchLinkageTool())

    researcher = RoleSpec(
        name="quant-researcher",
        description="Grounds the objective in news catalysts, arXiv literature, and live S&P 500 constituents.",
        tier=PermissionTier.WORKER,
        system_prompt=_RESEARCHER_PROMPT,
        tools=[NewsCatalystTool(), ArxivSearchTool(), IndexConstituentsTool()],
        model=_FAST_MODEL,
        max_iter=12,
        skills=skills,
    )
    scanner = RoleSpec(
        name="quant-scanner",
        description="Runs deterministic cointegration scans on proposed universes; optionally vets a survivor.",
        tier=PermissionTier.WORKER,
        system_prompt=_SCANNER_PROMPT,
        tools=scanner_tools,
        model=_FAST_MODEL,
        max_iter=12,
        skills=skills,
    )
    synth = RoleSpec(
        name="quant-synth",
        description="Synthesises research and scan results into the final handoff.",
        tier=PermissionTier.WORKER,
        system_prompt=_SYNTH_PROMPT,
        model=mdl,
        max_iter=4,
        skills=skills,
    )

    # ── Briefs (each phase gets a focused objective + prior research injected) ─

    prior = quant_journal.prior_research_block(n=5)

    _reflector = Reflector(domain="quant_pairs")
    playbook_heuristics = _reflector.retrieve(objective, n=4)
    playbook_block = _reflector.inject_block(playbook_heuristics)

    research_brief = TaskBrief(
        objective=(
            f"Objective: {objective}\n\nAsset class focus: {asset_class}. "
            "Research current catalysts, relevant literature, and live index "
            "constituents for candidate sectors. Propose concrete ticker "
            "universes with economic theses grounded in evidence — never from "
            "memory."
            + (f"\n\n{prior}" if prior else "")
            + (f"\n\n{playbook_block}" if playbook_block else "")
        ),
        tool_call_budget=max(tool_call_budget // 2, 4),
        success_criteria=[
            "At least 2 candidate universes proposed with concrete ticker lists from live index data",
            "Each universe has an economic thesis citing specific evidence",
        ],
    )
    scan_brief = TaskBrief(
        objective=(
            "Scan each universe proposed by the researcher (see context). Run "
            "scan_cointegrated_pairs for equities, scan_crypto_pairs for crypto. "
            "Report every surviving pair with full stats. Optionally "
            "research_linkage on the top survivor. If a universe returns zero "
            "survivors, report that honestly."
        ),
        tool_call_budget=8,
        success_criteria=[
            "Each proposed universe scanned",
            "Surviving pairs reported with stats (adf_p, half-life, hurst, beta, factor_r2)",
        ],
    )
    synth_brief = TaskBrief(
        objective=(
            "Synthesise the researcher's evidence and the scanner's validated "
            "results (both in context) into the final handoff. Report each "
            "durable surviving pair with stats and its economic thesis. If none "
            "survived, say so plainly. End with a one-line LESSON for the "
            "journal."
        ),
        success_criteria=[
            "Durable pairs reported with stats and rationale, or an honest 'none'",
            "One-line LESSON for the journal",
        ],
    )

    # ── Run the deterministic chain ──────────────────────────────────────────

    rubric = Rubric(
        criteria=["At least one surviving pair trades PROFITABLY out-of-sample "
                  "(positive OOS Sharpe after costs) — cointegration alone is not "
                  "enough; the spread must actually have made money on held-out data"],
        grader="tradeable_pnl",
        max_attempts=max_attempts,
        # Optimise for money: run the full attempt budget and keep the most
        # *profitable* pair found (highest OOS Sharpe), not just the most significant.
        optimize=max_attempts > 1,
    )
    result = chain_until(
        [(researcher, research_brief), (scanner, scan_brief), (synth, synth_brief)],
        rubric,
        runner=spawn_chain,   # module global — patchable in tests
        feedback_into=0,      # push "no pair survived" back to the researcher to re-aim
        verbose=verbose,
        run_budget_tokens=400_000,
    )

    # ── Record to journal ────────────────────────────────────────────────────

    try:
        g = getattr(result, "grade", None)
        quant_journal.record(
            objective, result.envelope.summary or "",
            status=result.envelope.status,
            tokens=(result.token_usage or {}).get("total_tokens"),
            run_id=getattr(result, "run_id", None),
            score=(g.score if g is not None else None),
            attempts=getattr(result, "attempts", None),
            attempt_run_ids=getattr(result, "attempt_run_ids", None),
        )
    except Exception:
        pass

    # ── Reflect: extract heuristics from rubric diffs for future runs ────────
    try:
        _reflector.reflect(result)
    except Exception:
        pass

    return result
