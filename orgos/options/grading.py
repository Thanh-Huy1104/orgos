"""Deterministic rubric grader for the options strategist.

Grades a run by reading what the tools actually returned — not the LLM's prose.
The grader reads the research trail for scan_volatility and scan_options_surface
calls, checks that a real edge was found (IV rank in a tradeable range, IV vs RV
signal is not neutral), and that the recommendation is a defined-risk structure.

Importing this module registers the 'options_edge' grader.
"""

from __future__ import annotations

import re
from typing import Any

from orgos.spawn.audit import read_trail
from orgos.spawn.rubric import GradeResult, register_grader

_OPTIONS_TOOLS = {
    "scan_volatility",
    "scan_options_surface",
    "suggest_options_strategy",
    "compute_options_greeks",
    "check_options_liquidity",
}

_LIQUID = re.compile(r'"liquid":\s*(true|false)')
_SPOT_SANITY = re.compile(r'"spot_sanity_ok":\s*(true|false)')

_IV_RANK = re.compile(r'"iv_rank":\s*([0-9.]+)')
_SIGNAL = re.compile(r'"signal":\s*"([^"]+)"')
_EDGE_SIGNAL = re.compile(r'"signal":\s*"(sell_premium|buy_options)"')
_TOP_SUGGESTION = re.compile(r'"top_suggestion":\s*"([^"]+)"')
_ATM_IV = re.compile(r'"atm_iv_pct":\s*([0-9.]+)')
_ERROR = re.compile(r'"error":\s*"([^"]+)"')

_DEFINED_RISK_STRATEGIES = {
    "covered_call", "cash_secured_put", "bull_call_spread",
    "bear_put_spread", "iron_condor", "long_straddle",
}

# IV rank thresholds — outside these we skip (edge not clear enough)
_MIN_IV_RANK_SELL = 40.0   # sell premium when IV is at least in the top 60th percentile
_MAX_IV_RANK_BUY  = 35.0   # buy options when IV is at most in the bottom 35th percentile


@register_grader("options_edge")
def grade_options_edge(result: Any, org: Any = None) -> GradeResult:
    """Pass iff the run surfaced a real, structural options edge.

    Gates (all must pass):
      1. At least one options tool ran successfully (not all errored)
      2. A surface or vol scan returned a non-neutral edge signal
         (sell_premium when IV rank ≥ 40, OR buy_options when IV rank ≤ 35)
      3. The top suggested strategy is defined-risk (no naked shorts)

    Score (higher = stronger edge):
      - Base 0.5 for passing all gates
      - +0.3 if IV rank is in a strong zone (≥60 or ≤20)
      - +0.2 if the surface confirmed the vol signal (ATM IV > 0)
    """
    trail = read_trail(result.run_id)
    options_calls = [r for r in trail if r.get("tool") in _OPTIONS_TOOLS]

    if not options_calls:
        return GradeResult(
            passed=False, grader="options_edge", score=0.0,
            failures=["no options tools ran — call scan_volatility and "
                      "scan_options_surface before recommending a strategy"],
        )

    # Gate 1: at least one successful tool call
    successful = [r for r in options_calls if r.get("ok") and not _ERROR.search(
        r.get("output_preview", "") or "")]
    if not successful:
        errors = [_ERROR.search(r.get("output_preview", "") or "") for r in options_calls]
        err_msgs = [m.group(1) for m in errors if m]
        return GradeResult(
            passed=False, grader="options_edge", score=0.0,
            failures=[f"all options tool calls errored: {err_msgs[:3]}"],
        )

    # Gate 2: non-neutral edge signal found
    all_output = " ".join(r.get("output_preview", "") or "" for r in successful)

    iv_rank_matches = _IV_RANK.findall(all_output)
    iv_rank_values = [float(v) for v in iv_rank_matches if v.replace(".", "").isdigit()]

    edge_signals = _EDGE_SIGNAL.findall(all_output)

    if not edge_signals:
        iv_info = f"IV ranks found: {iv_rank_values}" if iv_rank_values else "no IV rank data"
        return GradeResult(
            passed=False, grader="options_edge", score=0.1,
            failures=[
                f"no clear edge signal (sell_premium or buy_options) found in tool outputs. "
                f"{iv_info}. Either IV rank is in the neutral zone (35-40) or options "
                "data was unavailable — try a different ticker or wait for a better setup.",
            ],
        )

    # Check IV rank is in a tradeable zone
    sell_signals = [s for s in edge_signals if s == "sell_premium"]
    buy_signals  = [s for s in edge_signals if s == "buy_options"]

    tradeable = False
    iv_zone = "unknown"
    best_rank: float | None = None

    if iv_rank_values:
        best_rank = max(iv_rank_values) if sell_signals else min(iv_rank_values)
        if sell_signals and best_rank >= _MIN_IV_RANK_SELL:
            tradeable = True
            iv_zone = f"elevated (rank={best_rank:.0f} ≥ {_MIN_IV_RANK_SELL})"
        elif buy_signals and best_rank <= _MAX_IV_RANK_BUY:
            tradeable = True
            iv_zone = f"depressed (rank={best_rank:.0f} ≤ {_MAX_IV_RANK_BUY})"
        else:
            tradeable = False
            iv_zone = f"borderline (rank={best_rank:.0f})"
    else:
        # No IV rank data but edge signal present — accept with lower score
        tradeable = True
        iv_zone = "unknown (no rank data)"

    if not tradeable:
        return GradeResult(
            passed=False, grader="options_edge", score=0.2,
            failures=[
                f"edge signal found ({edge_signals[0]}) but IV rank is borderline "
                f"({iv_zone}) — not enough structural edge. Wait for IV rank ≥ "
                f"{_MIN_IV_RANK_SELL} to sell premium or ≤ {_MAX_IV_RANK_BUY} "
                "to buy options. Try a different ticker.",
            ],
        )

    # Gate 3: defined-risk strategy recommended
    # "none"/"n/a" are the engine's no-recommendation sentinels — not a naked strategy.
    _NO_STRATEGY = {"none", "n/a", "na", "no_edge", "no_strategy", ""}
    suggestions = _TOP_SUGGESTION.findall(all_output)
    real_suggestions = [s for s in suggestions if s.strip().lower() not in _NO_STRATEGY]

    if suggestions and not real_suggestions:
        # the engine explicitly declined to recommend a structure → no tradeable edge
        return GradeResult(
            passed=False, grader="options_edge", score=0.2,
            failures=[
                "the strategy engine returned no recommendation (top_suggestion='none') — "
                "IV/surface did not support a concrete defined-risk structure. No tradeable "
                "edge; try a different ticker or wait for a better vol setup.",
            ],
        )

    undefined_risk = [s for s in real_suggestions if s not in _DEFINED_RISK_STRATEGIES]
    if undefined_risk:
        return GradeResult(
            passed=False, grader="options_edge", score=0.3,
            failures=[
                f"strategy {undefined_risk[0]!r} is not defined-risk — "
                "only use covered_call, cash_secured_put, bull_call_spread, "
                "bear_put_spread, iron_condor, or long_straddle.",
            ],
        )

    # Gate 4: recommended structure is actually executable (live liquidity + sane spot)
    liquidity_calls = [r for r in trail if r.get("tool") == "check_options_liquidity"]
    liquidity_ran = bool(liquidity_calls)
    liquidity_ok = False
    if liquidity_ran:
        liq_output = " ".join(r.get("output_preview", "") or "" for r in liquidity_calls)
        liquid_flags = _LIQUID.findall(liq_output)
        sanity_flags = _SPOT_SANITY.findall(liq_output)

        if "false" in sanity_flags:
            return GradeResult(
                passed=False, grader="options_edge", score=0.35,
                failures=[
                    "spot-sanity check FAILED — the chain's underlying price diverges from "
                    "the recent close (stale or bad data). Every strike built on that spot is "
                    "untrustworthy. Re-fetch a clean quote or pick a different ticker.",
                ],
            )
        if liquid_flags and "true" not in liquid_flags:
            return GradeResult(
                passed=False, grader="options_edge", score=0.4,
                failures=[
                    "liquidity check FAILED — one or more legs of the recommended structure "
                    "have no two-sided market, too little open interest, or a bid/ask spread "
                    "too wide to trade. Re-strike to liquid contracts or drop the ticker.",
                ],
            )
        liquidity_ok = "true" in liquid_flags

    # ── Passed: compute score ─────────────────────────────────────────────────
    score = 0.5
    if best_rank is not None:
        if best_rank >= 60 or best_rank <= 20:
            score += 0.3  # strong IV zone
        elif best_rank >= 50 or best_rank <= 25:
            score += 0.15

    atm_ivs = _ATM_IV.findall(all_output)
    if atm_ivs:
        score += 0.2  # surface data confirmed

    if liquidity_ok:
        score += 0.15  # recommendation is verified executable (liquid legs + sane spot)

    score = round(min(score, 1.0), 3)

    note = f"edge={edge_signals[0]}, IV {iv_zone}"
    if real_suggestions:
        note += f", strategy={real_suggestions[0]}"
    if atm_ivs:
        note += f", ATM IV={atm_ivs[0]}%"
    if liquidity_ok:
        note += ", liquidity=verified"
    elif not liquidity_ran:
        note += ", liquidity=UNCHECKED (call check_options_liquidity on final strikes)"

    return GradeResult(passed=True, grader="options_edge", score=score, notes=note)
