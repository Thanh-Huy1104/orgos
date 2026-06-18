"""Quant supervisor — the recommend-only view tying research to the live engine.

Closes the loop: reads Icarus's live state (equity, what's traded, each pair's
own z-score, realized P&L) and the research desk's output (scan → research gate),
then produces ONE recommendation a human acts on. orgos proposes; the user runs
any spawn/swap/retire. It never writes the trading DB or starts a process.

A candidate is only "ready to propose" if it cleared the durability scan AND the
research gate said PROMOTE (no pending corporate action). Everything else is
surfaced with its reason, not acted on.
"""

from __future__ import annotations

from typing import Any

from orgos.quant import icarus_db
from orgos.tools.quant_tool import run_scan
from orgos.quant.research_gate import screen_candidates


def live_overview() -> dict:
    """Read-only snapshot of the Icarus engine: account, active pairs, signals, P&L."""
    state = {p["pair"]: p for p in icarus_db.live_pair_state()}
    active = icarus_db.active_pairs()
    for a in active:
        s = state.get(a["pair"])
        a["z_score"] = s["z_score"] if s else None
        a["as_of"] = s["as_of"] if s else None
    return {
        "account": icarus_db.account_snapshot(),
        "active_pairs": active,
        "performance": icarus_db.performance_summary(),
    }


def recommend(
    universes: list[str], *, gate_days: int = 90, lookback_days: int = 504,
    scanner: Any = run_scan, screener: Any = screen_candidates,
    overview: Any = live_overview,
) -> dict:
    """Scan the given universes, research-gate the candidates, and weigh them
    against the live book — returning a recommend-only report.

    scanner/screener/overview are injectable for testing. Output separates what's
    safe to propose (PROMOTE) from what needs review or should be held.
    """
    book = overview()
    held = {p["pair"] for p in book.get("active_pairs", [])}

    promote: list[dict] = []
    review: list[dict] = []
    hold: list[dict] = []
    scanned_universes: list[str] = []
    for uni in universes:
        scan = scanner(uni, lookback_days=lookback_days)
        if scan.get("error") or not scan.get("candidates"):
            continue
        scanned_universes.append(uni)
        gated = screener(scan["candidates"], days=gate_days)
        promote.extend(gated["promote"])
        review.extend(gated["review"])
        hold.extend(gated["hold"])

    # A PROMOTE candidate already in the book isn't a new idea — flag separately.
    new_promote = [d for d in promote if d["pair"] not in held]
    already_held = [d for d in promote if d["pair"] in held]

    lines = [
        f"Book: {len(held)} active pair(s); "
        f"equity ${book['account']['total_equity']:,.0f}" if book.get("account") else "Book: (no account data)",
        f"Scanned {len(scanned_universes)} universe(s) → "
        f"{len(new_promote)} new pair(s) to PROPOSE, {len(review)} to review, "
        f"{len(hold)} on hold.",
    ]
    if new_promote:
        lines.append("Propose spawning: " + ", ".join(d["pair"] for d in new_promote))

    return {
        "live": book,
        "propose_spawn": new_promote,
        "promote_already_held": already_held,
        "review": review,
        "hold": hold,
        "summary": " ".join(lines),
    }
