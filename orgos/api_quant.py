"""Quant desk API — agentic endpoints only.

Live-book monitoring (Desk) and agent-driven discovery (Strategist). Manual
scanner/signals/crypto shortcuts are gone — the strategist agent owns discovery.
Nothing here trades or writes the trading DB (except /halt for emergency stop).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/quant", tags=["quant"])


@router.get("/book")
def book() -> dict:
    """Live Icarus state: account, active pairs (with live z-score), performance.

    Reads the trading DB read-only. 503 if the DB is unreachable (engine off /
    network) so the UI can show a clear 'engine offline' state.
    """
    from .quant_supervisor import live_overview

    try:
        return live_overview()
    except Exception as exc:  # noqa: BLE001 — surface as a clean 503 for the UI
        raise HTTPException(status_code=503, detail=f"Icarus DB unreachable: {exc}")


class StrategistBody(BaseModel):
    objective: str
    asset_class: str = "equity"
    allow_research: bool = False


@router.post("/strategist")
def strategist(body: StrategistBody) -> dict:
    """Agent-driven discovery: an LLM strategist proposes universes, scans them,
    optionally spawns research, and synthesises a handoff. Slow (minutes)."""
    from .quant_strategist import run_strategist

    from .audit import read_trail

    r = run_strategist(body.objective, asset_class=body.asset_class,
                       allow_research=body.allow_research, verbose=False)
    e = r.envelope
    return {"status": e.status, "criteria_met": e.success_criteria_met,
            "summary": e.summary, "notes": e.notes,
            "tokens": (r.token_usage or {}).get("total_tokens"),
            "run_id": r.run_id, "trail": read_trail(r.run_id)}


@router.get("/risk")
def risk() -> dict:
    """Read-only risk assessment of the live book + current kill-switch state."""
    from .kill_switch import assess_active_pairs

    try:
        return assess_active_pairs()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"risk assessment failed: {exc}")


class HaltBody(BaseModel):
    pair_id: int
    reason: str


@router.post("/halt")
def halt(body: HaltBody) -> dict:
    """Publish a HALT to Icarus's Redis kill switch for one pair (set-only).

    This is the one write orgos makes to the live system. It only STOPS a pair
    (the fail-safe direction) — orgos never clears a halt; un-halting is a human
    decision in Icarus/Mimir.
    """
    from .kill_switch import publish_halt

    try:
        return publish_halt(body.pair_id, body.reason)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"halt failed: {exc}")
