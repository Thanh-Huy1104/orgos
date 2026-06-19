"""Deterministic rubric grader for the quant strategist.

A scan candidate that the scanner returns has *already* cleared every gate —
ADF cointegration, half-life bounds, Hurst, sub-period durability, and factor
independence — inside ``scan()``. So the strategist's rubric reduces to a single
honest question: did the run surface at least one durable pair?

We answer it from the deterministic scan output in the run's *tool trail*
(``read_trail``), not from the synth agent's prose — the grade reflects ground
truth (what the scanner actually returned), not what the LLM claimed. Zero
tokens.

Importing this module registers the ``cointegration_gates`` grader.
"""

from __future__ import annotations

import re
from typing import Any

from orgos.spawn.audit import read_trail
from orgos.spawn.rubric import GradeResult, register_grader

_SCAN_TOOLS = {"scan_cointegrated_pairs", "scan_crypto_pairs"}
# `candidates_found` is emitted before the (large) candidates array, so it lands
# within the trail's output preview even when the full scan JSON is truncated.
_FOUND = re.compile(r'"candidates_found":\s*(\d+)')
# Per-candidate cointegration p-values, used to *rank* one attempt against
# another: the most significant pair found this attempt sets the score. The scan
# serialises this as "adf_p"; the lower-level pair test uses "adf_pvalue" — match
# either so the score never silently falls back.
_PVAL = re.compile(r'"adf_p(?:value)?":\s*([0-9.eE+-]+)')


@register_grader("cointegration_gates")
def grade_cointegration(result: Any, org: Any = None) -> GradeResult:
    """Pass iff the run's scan trail surfaced ≥1 durable cointegrated pair.

    The ``score`` (higher = better) is ``1 - min(adf_pvalue)`` across every pair
    found this attempt — i.e. the most statistically significant cointegration
    surfaced — so an optimise loop keeps the strongest pair across attempts, not
    just the first that clears the bar.
    """
    trail = read_trail(result.run_id)
    scans = [r for r in trail if r.get("tool") in _SCAN_TOOLS and r.get("ok")]
    if not scans:
        return GradeResult(
            passed=False, grader="cointegration_gates", score=0.0,
            failures=["no cointegration scan ran — propose at least one concrete, "
                      "scannable ticker universe built from live index data"],
        )
    total = sum(int(m.group(1)) for s in scans
                if (m := _FOUND.search(s.get("output_preview", "") or "")))
    pvals = [float(p) for s in scans
             for p in _PVAL.findall(s.get("output_preview", "") or "")]
    if total >= 1:
        best_p = min(pvals) if pvals else None
        score = (1.0 - best_p) if best_p is not None else 0.5
        note = f"{total} durable pair(s) across {len(scans)} scan(s)"
        if best_p is not None:
            note += f"; best adf_p={best_p:.4f}"
        return GradeResult(passed=True, grader="cointegration_gates", score=score, notes=note)
    return GradeResult(
        passed=False, grader="cointegration_gates", score=0.0,
        failures=[f"all {len(scans)} scanned universe(s) returned 0 durable pairs — "
                  "try different or wider universes/sectors, or a different catalyst"],
    )


# ── Money grader: rank/select on out-of-sample, after-cost P&L, not p-values ───

# Candidates are serialised best-OOS-Sharpe-first, so the FIRST oos_sharpe /
# n_trades / folds_profitable in a scan's preview belong to that universe's best
# pair — read them together rather than maxing fields independently.
_SHARPE = re.compile(r'"oos_sharpe":\s*(-?[0-9.eE+]+)')
_NTRADES = re.compile(r'"n_trades":\s*(\d+)')
_FOLDS = re.compile(r'"folds_profitable":\s*(\d+)')
_MIN_SHARPE = 0.5   # a pair must have actually traded profitably OOS
_MIN_TRADES = 5     # …over enough trades that the Sharpe isn't a small-sample fluke
_MIN_FOLDS = 2      # …and profitably in at least 2 walk-forward regimes


@register_grader("tradeable_pnl")
def grade_tradeable_pnl(result: Any, org: Any = None) -> GradeResult:
    """Pass iff a surviving pair *traded profitably out-of-sample* — high OOS
    Sharpe after costs, over enough trades, across multiple walk-forward folds.
    Cointegration alone, or a great Sharpe on 3 lucky trades, does not pass.

    ``score`` is the best OOS Sharpe (normalised), so the optimise loop keeps the
    most *profitable* attempt, not the most statistically significant one.
    """
    trail = read_trail(result.run_id)
    scans = [r for r in trail if r.get("tool") in _SCAN_TOOLS and r.get("ok")]
    if not scans:
        return GradeResult(
            passed=False, grader="tradeable_pnl", score=0.0,
            failures=["no scan ran — propose at least one scannable ticker universe"],
        )

    best_sharpe = best_trades = best_folds = None
    for s in scans:
        prev = s.get("output_preview", "") or ""
        m = _SHARPE.search(prev)  # first match = that universe's best pair
        if m is None:
            continue
        sv = float(m.group(1))
        if best_sharpe is None or sv > best_sharpe:
            best_sharpe = sv
            best_trades = int(_NTRADES.search(prev).group(1)) if _NTRADES.search(prev) else None
            best_folds = int(_FOLDS.search(prev).group(1)) if _FOLDS.search(prev) else None

    if best_sharpe is None:
        return GradeResult(
            passed=False, grader="tradeable_pnl", score=0.0,
            failures=["scans returned pairs but none reported an out-of-sample P&L — "
                      "could not confirm any pair would have traded profitably"],
        )

    score = max(0.0, min(1.0, best_sharpe / 3.0))  # Sharpe 3 ≈ top of the scale
    if best_sharpe < _MIN_SHARPE:
        return GradeResult(
            passed=False, grader="tradeable_pnl", score=score,
            failures=[f"best OOS Sharpe {best_sharpe:.2f} < {_MIN_SHARPE} — pairs co-move "
                      "but didn't trade profitably OOS; try faster-reverting spreads"])
    if best_trades is not None and best_trades < _MIN_TRADES:
        return GradeResult(
            passed=False, grader="tradeable_pnl", score=score,
            failures=[f"best pair traded only {best_trades}× out-of-sample — too few to "
                      f"trust (Sharpe {best_sharpe:.2f} is small-sample); widen the universe "
                      "or pick faster-reverting spreads with more entries"])
    if best_folds is not None and best_folds < _MIN_FOLDS:
        return GradeResult(
            passed=False, grader="tradeable_pnl", score=score,
            failures=[f"profitable in only {best_folds} walk-forward fold(s) — not robust "
                      "across regimes; the edge likely won't persist live"])

    note = f"best OOS Sharpe {best_sharpe:.2f}"
    if best_trades is not None:
        note += f" over {best_trades} trades"
    if best_folds is not None:
        note += f", profitable in {best_folds} folds"
    return GradeResult(passed=True, grader="tradeable_pnl", score=score, notes=note)
