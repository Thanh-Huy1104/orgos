"""Quant desk API — agentic endpoints only.

Live-book monitoring (Desk) and agent-driven discovery (Strategist). Manual
scanner/signals/crypto shortcuts are gone — the strategist agent owns discovery.
Nothing here trades or writes the trading DB (except /halt for emergency stop).
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/quant", tags=["quant"])


@router.get("/book")
def book() -> dict:
    """Live Icarus state: account, active pairs (with live z-score), performance.

    Reads the trading DB read-only. 503 if the DB is unreachable (engine off /
    network) so the UI can show a clear 'engine offline' state.
    """
    from orgos.subagents.quant_supervisor import live_overview

    try:
        return live_overview()
    except Exception as exc:  # noqa: BLE001 — surface as a clean 503 for the UI
        raise HTTPException(status_code=503, detail=f"Icarus DB unreachable: {exc}")


class StrategistBody(BaseModel):
    objective: str
    asset_class: str = "equity"
    allow_research: bool = False
    max_attempts: int = 2


# A strategist hunt takes minutes — far longer than any HTTP/proxy idle timeout
# will hold a connection open. So the run is dispatched to a background thread and
# the UI polls for the result. The job store is in-process (the API is a single
# worker); a lost job is harmless because run_strategist also records to the
# journal, so the result is never actually lost.
_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()
_JOB_TTL_S = 3600  # forget finished jobs after an hour


def _result_dict(r: Any) -> dict:
    from orgos.spawn import read_trail

    e = r.envelope
    g = getattr(r, "grade", None)
    rubric = None
    if g is not None:
        rubric = {"passed": g.passed, "score": round(g.score, 4),
                  "grader": g.grader, "notes": g.notes}
    return {"status": e.status, "criteria_met": e.success_criteria_met,
            "summary": e.summary, "notes": e.notes,
            "tokens": (r.token_usage or {}).get("total_tokens"),
            "run_id": r.run_id, "trail": read_trail(r.run_id),
            "attempts": getattr(r, "attempts", 1), "rubric": rubric,
            "attempt_run_ids": getattr(r, "attempt_run_ids", [])}


def _prune_jobs() -> None:
    now = time.time()
    for jid, job in list(_JOBS.items()):
        if job.get("status") != "running" and now - job.get("ended_at", now) > _JOB_TTL_S:
            _JOBS.pop(jid, None)


@router.post("/strategist")
def strategist(body: StrategistBody) -> dict:
    """Dispatch an agent-driven discovery hunt. Returns a job id immediately; the
    run continues in the background (minutes). Poll GET /strategist/{job_id}."""
    from orgos.subagents.quant_strategist import run_strategist

    job_id = uuid.uuid4().hex[:12]
    with _JOBS_LOCK:
        _prune_jobs()
        _JOBS[job_id] = {"status": "running", "started_at": time.time()}

    def _run() -> None:
        try:
            r = run_strategist(body.objective, asset_class=body.asset_class,
                               allow_research=body.allow_research,
                               max_attempts=body.max_attempts, verbose=False)
            out = {"status": "done", "result": _result_dict(r)}
        except Exception as exc:  # noqa: BLE001 — surface the error to the UI
            out = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
        out["ended_at"] = time.time()
        with _JOBS_LOCK:
            out["started_at"] = _JOBS.get(job_id, {}).get("started_at", out["ended_at"])
            _JOBS[job_id] = out

    threading.Thread(target=_run, daemon=True).start()
    return {"job_id": job_id, "status": "running"}


@router.get("/strategist/{job_id}")
def strategist_job(job_id: str) -> dict:
    """Poll a dispatched hunt: status running | done | error, with the result when done."""
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "unknown or expired job")
    elapsed = round(time.time() - job.get("started_at", time.time()))
    return {"job_id": job_id, "elapsed_s": elapsed, **job}


@router.get("/journal")
def journal(limit: int = 25) -> dict:
    """The research journal: past hunts with their result, rubric strength, and a
    link (run_id) to the research trail. This is what the desk has found."""
    from orgos.quant import journal as quant_journal

    return {"entries": quant_journal.recent(limit)}


@router.get("/trails")
def trails(limit: int = 25) -> dict:
    """Recent runs that left a research trail, newest first (for the Logs view)."""
    from orgos.spawn import recent_trails

    return {"runs": recent_trails(limit)}


@router.get("/trail/{run_id}")
def trail(run_id: str) -> dict:
    """The full tool-by-tool research trail for one run."""
    from orgos.spawn import read_trail

    return {"run_id": run_id, "trail": read_trail(run_id)}


class IvScanBody(BaseModel):
    tickers: list[str]


@router.get("/volatility/{ticker}")
def volatility(ticker: str) -> dict:
    """Realized vol snapshot + VIX context for one ticker.

    Returns current vol, 1m/3m averages, vol regime, spike flag, suggested
    position size (15% target vol), and live VIX level + regime.
    503 if market data is unavailable.
    """
    from .marketdata import get_prices, MarketDataError
    from .volatility import fetch_vix, vol_summary

    try:
        prices = get_prices(ticker.upper(), lookback_days=252)
    except MarketDataError as exc:
        raise HTTPException(status_code=503, detail=f"no price data: {exc}")

    try:
        vix = fetch_vix(lookback_days=252)
    except Exception:  # noqa: BLE001 — VIX is optional, don't block the response
        vix = None

    result = vol_summary(prices, vol_window=20, vix=vix)
    return {"ticker": ticker.upper(), **result}


@router.post("/volatility/iv-scan")
def iv_scan(body: IvScanBody) -> dict:
    """IV rank scan across a list of equity tickers.

    High IV rank (> 50) → options expensive vs trailing year → sell premium.
    Low IV rank (< 20)  → options cheap → buy options for direction or protection.
    Requires a liquid options market on each ticker; returns an error entry for
    tickers with no options data.
    """
    from .volatility import scan_iv_rank

    results = scan_iv_rank(body.tickers)
    return {"results": results, "count": len(results)}


class OptionsStrategistBody(BaseModel):
    objective: str
    view: str = "neutral"   # bullish | bearish | neutral | volatile
    max_attempts: int = 2


class OptionsSurfaceBody(BaseModel):
    ticker: str
    target_dte: int = 30
    max_expiries: int = 8


class StrategyBody(BaseModel):
    ticker: str
    view: str = "neutral"   # bullish | bearish | neutral | volatile
    target_dte: int = 30


class GreeksBody(BaseModel):
    S: float          # current spot price
    K: float          # strike
    T: float          # time to expiry in years (e.g. 30/365)
    r: float = 0.05   # risk-free rate
    sigma: float      # implied volatility (annualised, e.g. 0.20)
    option_type: str = "call"


@router.post("/options/strategist")
def options_strategist(body: OptionsStrategistBody) -> dict:
    """Dispatch a full options research hunt. Returns a job id immediately; poll
    GET /options/strategist/{job_id} for the result (takes 1-3 minutes).

    The pipeline: researcher identifies liquid tickers from news → analyst runs
    vol + surface scans → synth produces the final strategy recommendation.
    Grades against the options_edge rubric (IV rank, vol signal, defined-risk structure).
    Result is recorded to the quant journal.
    """
    from orgos.subagents.options_strategist import run_options_strategist

    job_id = uuid.uuid4().hex[:12]
    with _JOBS_LOCK:
        _prune_jobs()
        _JOBS[job_id] = {"status": "running", "started_at": time.time(), "type": "options"}

    def _run() -> None:
        try:
            r = run_options_strategist(
                body.objective, view=body.view, max_attempts=body.max_attempts, verbose=False
            )
            out = {"status": "done", "result": _result_dict(r)}
        except Exception as exc:  # noqa: BLE001
            out = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
        out["ended_at"] = time.time()
        with _JOBS_LOCK:
            out["started_at"] = _JOBS.get(job_id, {}).get("started_at", out["ended_at"])
            out["type"] = "options"
            _JOBS[job_id] = out

    threading.Thread(target=_run, daemon=True).start()
    return {"job_id": job_id, "status": "running", "type": "options"}


@router.get("/options/strategist/{job_id}")
def options_strategist_job(job_id: str) -> dict:
    """Poll an options research hunt: status running | done | error."""
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "unknown or expired job")
    elapsed = round(time.time() - job.get("started_at", time.time()))
    return {"job_id": job_id, "elapsed_s": elapsed, **job}


@router.post("/options/surface")
def options_surface(body: OptionsSurfaceBody) -> dict:
    """Full IV surface snapshot for one ticker: ATM IV, skew, term structure, edge signal.

    Fetches the option chain via yfinance, computes realized vol for the IV vs RV
    comparison, and returns a structured surface ready for display or agent injection.
    503 if no options data is available.
    """
    from orgos.options.chain import get_chain, OptionDataError
    from orgos.options.surface import surface_snapshot
    from .marketdata import get_prices, MarketDataError
    from .volatility import realized_vol as compute_rv

    try:
        chain = get_chain(body.ticker, max_expiries=body.max_expiries)
    except OptionDataError as exc:
        raise HTTPException(status_code=503, detail=f"no options data: {exc}")

    rv: float | None = None
    try:
        prices = get_prices(body.ticker.upper(), lookback_days=63)
        rv_series = compute_rv(prices, window=20)
        rv = float(rv_series.dropna().iloc[-1]) if len(rv_series.dropna()) else None
    except (MarketDataError, Exception):  # noqa: BLE001 — RV is optional
        pass

    return surface_snapshot(chain, rv, target_dte=body.target_dte)


@router.post("/options/suggest")
def options_suggest(body: StrategyBody) -> dict:
    """Suggest an options strategy based on the current IV rank and directional view.

    Fetches IV rank (from the option chain) and realized vol, then runs the
    heuristic strategy selector. Returns ranked strategy candidates with rationale.
    503 if no options data is available.
    """
    from orgos.options.chain import get_chain, OptionDataError
    from orgos.options.surface import atm_iv as compute_atm_iv
    from orgos.options.strategies import suggest_strategy
    from orgos.quant.volatility import iv_rank as compute_iv_rank
    from .marketdata import get_prices, MarketDataError
    from .volatility import realized_vol as compute_rv

    ticker = body.ticker.upper()

    iv_rank_result = compute_iv_rank(ticker)
    rank = iv_rank_result.get("iv_rank")
    current_iv = (iv_rank_result.get("current_iv_pct") or 0) / 100

    rv: float = 0.20  # fallback
    try:
        prices = get_prices(ticker, lookback_days=63)
        rv_series = compute_rv(prices, window=20)
        if len(rv_series.dropna()):
            rv = float(rv_series.dropna().iloc[-1])
    except (MarketDataError, Exception):  # noqa: BLE001
        pass

    if rank is None:
        raise HTTPException(status_code=503, detail=iv_rank_result.get("error", "IV rank unavailable"))

    suggestion = suggest_strategy(
        iv_rank=rank,
        rv=rv,
        atm_iv=current_iv,
        view=body.view,  # type: ignore[arg-type]
    )
    return {"ticker": ticker, **suggestion}


@router.post("/options/greeks")
def options_greeks(body: GreeksBody) -> dict:
    """Compute Black-Scholes price and all Greeks for one options contract.

    Inputs: spot (S), strike (K), time to expiry in years (T), risk-free rate (r),
    implied vol (sigma), and option type (call/put). Returns price + delta/gamma/
    theta/vega/rho with plain-English units.
    """
    from orgos.options.pricer import bs_greeks

    try:
        result = bs_greeks(
            body.S, body.K, body.T, body.r, body.sigma,
            "call" if body.option_type.lower() == "call" else "put",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return result


# ── Options paper trading (human-in-the-loop, paper-only) ─────────────────────

class PaperLegBody(BaseModel):
    right: str        # 'P' or 'C'
    action: str       # 'BUY' or 'SELL'
    strike: float
    expiry: str       # ISO 'YYYY-MM-DD'
    qty: int = 1


class PaperOrderBody(BaseModel):
    ticker: str
    strategy: str = ""
    legs: list[PaperLegBody]
    max_loss_usd: float
    run_id: str | None = None


def _to_request(body: PaperOrderBody):
    from orgos.quant.options_exec import OrderLeg, PaperOrderRequest

    return PaperOrderRequest(
        ticker=body.ticker.upper(),
        strategy=body.strategy,
        legs=[OrderLeg(l.right, l.action, l.strike, l.expiry, l.qty) for l in body.legs],
        max_loss_usd=body.max_loss_usd,
        run_id=body.run_id,
    )


@router.post("/options/paper/preview")
def options_paper_preview(body: PaperOrderBody) -> dict:
    """Dry-run: re-check liquidity + spot-sanity on the live chain for these legs.

    Returns exactly what the place call would validate against — the per-leg live
    bid/ask/mid/OI and whether the structure is currently tradeable — WITHOUT sending
    anything. The dashboard uses this to enable/disable the Place button.
    """
    from orgos.quant.options_exec import check_liquidity, OrderRejected

    try:
        liq = check_liquidity(_to_request(body))
        return {"tradeable": True, "liquidity": liq}
    except OrderRejected as exc:
        return {"tradeable": False, "reason": str(exc)}


@router.post("/options/paper/place")
def options_paper_place(body: PaperOrderBody) -> dict:
    """Place the confirmed paper order on IBKR (paper-only, guarded).

    Runs every pre-trade gate (risk caps → fresh liquidity recheck → PAPER_ONLY
    connection guard → kill-switch). 409 if a gate rejects the order; 503 if the
    paper gateway is unreachable or the safety guard refuses the session.
    """
    from orgos.quant.options_exec import place_paper_order, OrderRejected
    from orgos.quant.options_exec_config import UnsafeExecutionError

    try:
        return place_paper_order(_to_request(body))
    except OrderRejected as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except UnsafeExecutionError as exc:
        raise HTTPException(status_code=503, detail=f"safety guard: {exc}")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"paper order failed: {exc}")


@router.get("/options/paper/positions")
def options_paper_positions() -> dict:
    """All paper options positions (open first) with realized P&L where closed."""
    from orgos.quant.options_paper_ledger import OptionsPaperLedger

    led = OptionsPaperLedger()
    return {"positions": led.all_positions(), "open_count": led.count_open_positions()}


class PaperCloseBody(BaseModel):
    close_price: float | None = None
    realized_pnl: float | None = None


@router.post("/options/paper/close/{position_id}")
def options_paper_close(position_id: str, body: PaperCloseBody) -> dict:
    """Mark a paper position closed and record realized P&L (manual close for now)."""
    from orgos.quant.options_paper_ledger import OptionsPaperLedger

    led = OptionsPaperLedger()
    led.close_position(position_id, close_price=body.close_price,
                       realized_pnl=body.realized_pnl)
    return {"ok": True, "position_id": position_id}


@router.post("/options/paper/reconcile")
def options_paper_reconcile() -> dict:
    """Sync the ledger to IBKR's actual filled option positions + unrealized P&L."""
    from orgos.quant.options_exec import reconcile

    try:
        return reconcile()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"reconcile failed: {exc}")


@router.post("/options/paper/flatten")
def options_paper_flatten() -> dict:
    """Close every live IBKR option position with a market order (clean-up/flatten)."""
    from orgos.quant.options_exec import flatten_options

    try:
        return flatten_options()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"flatten failed: {exc}")


class OptionsBacktestBody(BaseModel):
    ticker: str
    structure: str = "put_spread"   # put_spread | cash_secured_put
    dte: int = 30
    target_delta: float = 0.30
    width: float = 5.0
    iv_scale: float = 1.0           # bump VIX for single names richer than the index
    min_vix_rank: float = 0.0       # only sell when VIX IV-rank ≥ this (0 = always)
    lookback_days: int = 1200


@router.post("/options/backtest")
def options_backtest(body: OptionsBacktestBody) -> dict:
    """Backtest systematically selling the structure (VRP), priced at VIX as the
    implied vol and settled against the realized underlying path. The money metric:
    win rate, total/avg P&L after costs, return-on-risk, Sharpe, max drawdown.

    VIX is SPX/SPY's implied vol, so SPY/QQQ/IWM are faithful; single names use VIX
    as a proxy (set iv_scale > 1 since their IV usually runs richer than the index).
    """
    from orgos.quant.options_backtest import run_backtest

    return run_backtest(
        body.ticker, lookback_days=body.lookback_days, structure=body.structure,
        dte=body.dte, target_delta=body.target_delta, width=body.width,
        iv_scale=body.iv_scale, min_vix_rank=body.min_vix_rank,
    )


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
