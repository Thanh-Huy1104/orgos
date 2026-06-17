"""Quant desk API — endpoints behind the dashboard's Desk + Scanner pages.

All read/recommend-only: surfaces the live Icarus book, runs cointegration scans,
and produces the research-gated recommendation. Nothing here trades or writes the
trading DB.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/quant", tags=["quant"])


class ScanBody(BaseModel):
    universe: str
    lookback_days: int = 504


class RecommendBody(BaseModel):
    universes: list[str]
    gate_days: int = 90
    lookback_days: int = 504


@router.get("/universes")
def universes() -> dict:
    """The curated sector presets the scanner knows."""
    from .quant_tool import UNIVERSES

    return {"universes": {name: tickers for name, tickers in UNIVERSES.items()}}


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


@router.post("/scan")
def scan(body: ScanBody) -> dict:
    """Run a cointegration scan over one universe (cached bars)."""
    from .quant_tool import run_scan

    return run_scan(body.universe, lookback_days=body.lookback_days)


@router.post("/recommend")
def recommend(body: RecommendBody) -> dict:
    """Scan the universes, research-gate them, weigh against the live book."""
    from .quant_supervisor import recommend as _recommend

    return _recommend(body.universes, gate_days=body.gate_days,
                      lookback_days=body.lookback_days)


class EventScanBody(BaseModel):
    event_days: int = 7
    gate_days: int = 90
    universes: list[str] | None = None


@router.post("/events")
def events(body: EventScanBody) -> dict:
    """Event-driven discovery: material SEC filings → implicated sectors → scan → gate."""
    from .event_discovery import discover_from_events

    return discover_from_events(
        event_days=body.event_days, gate_days=body.gate_days,
        universes=body.universes,
    )


class CryptoScanBody(BaseModel):
    coins: list[str] | None = None
    lookback_days: int = 365
    fdr: float = 0.10


@router.post("/crypto")
def crypto(body: CryptoScanBody) -> dict:
    """Crypto cointegration scan — recent-window durability, hub exclusion, OOS flag."""
    from .crypto_tool import run_crypto_scan

    return run_crypto_scan(body.coins, lookback_days=body.lookback_days, fdr=body.fdr)


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
