"""Options paper-trade executor — human-in-the-loop, paper-only, isolated.

The agent proposes a graded, liquidity-validated recommendation; a human reviews it
and clicks "place". This module turns that confirmed order into IBKR paper orders,
reusing the exact `ib.placeOrder(contract, LimitOrder(...))` primitive Icarus uses
(quant-engine/icarus_engine/execution.py) but on a *separate* client id so it can
never disturb the live equity-pairs engine.

Safety, in order of what runs first on every placement:
  1. risk caps (contracts/order, open positions, defined-risk $, daily order count)
  2. a fresh liquidity + spot-sanity recheck on the live chain (run_liquidity_check)
  3. the PAPER_ONLY connection guard (port + 'DU' account id)
  4. the orgos kill-switch halt state

The IB client is injectable so the whole pipeline is unit-testable without a gateway.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from orgos.quant import options_exec_config as cfg
from orgos.quant.options_exec_config import RISK, UnsafeExecutionError, assert_paper_safe
from orgos.quant.options_paper_ledger import OptionsPaperLedger
from orgos.tools.options_tools import run_liquidity_check


# ── Order schema ──────────────────────────────────────────────────────────────

@dataclass
class OrderLeg:
    right: str        # 'P' or 'C'
    action: str       # 'BUY' or 'SELL'
    strike: float
    expiry: str       # ISO 'YYYY-MM-DD'
    qty: int = 1

    def normalized(self) -> "OrderLeg":
        return OrderLeg(self.right.upper()[0], self.action.upper(), float(self.strike),
                        self.expiry, int(self.qty))


@dataclass
class PaperOrderRequest:
    ticker: str
    strategy: str
    legs: list[OrderLeg]
    max_loss_usd: float            # defined risk per the recommendation, for the cap
    run_id: str | None = None
    limit_prices: dict = field(default_factory=dict)  # optional override, keyed "C/180.0"


class OrderRejected(RuntimeError):
    """A pre-trade gate (risk, liquidity, or halt) refused the order."""


# ── Risk + liquidity pre-checks ───────────────────────────────────────────────

def check_risk(req: PaperOrderRequest, ledger: OptionsPaperLedger) -> None:
    """Raise OrderRejected if any configured risk cap would be breached."""
    total_qty = sum(abs(l.qty) for l in req.legs)
    if total_qty > RISK.max_contracts_per_order:
        raise OrderRejected(
            f"order is {total_qty} contracts > cap {RISK.max_contracts_per_order}")
    if req.max_loss_usd > RISK.max_defined_risk_usd:
        raise OrderRejected(
            f"defined risk ${req.max_loss_usd:.0f} > cap ${RISK.max_defined_risk_usd:.0f}")
    if ledger.count_open_positions() >= RISK.max_open_positions:
        raise OrderRejected(
            f"already at max open positions ({RISK.max_open_positions})")
    if ledger.orders_today() >= RISK.max_new_orders_per_day:
        raise OrderRejected(
            f"daily order cap reached ({RISK.max_new_orders_per_day})")


def check_liquidity(req: PaperOrderRequest) -> dict:
    """Fresh liquidity + spot-sanity recheck on the live chain. Raise if not tradeable."""
    expiries = {l.expiry for l in req.legs}
    if len(expiries) != 1:
        raise OrderRejected(f"all legs must share one expiry, got {sorted(expiries)}")
    expiry = expiries.pop()
    puts = [l.strike for l in req.legs if l.right == "P"]
    calls = [l.strike for l in req.legs if l.right == "C"]
    liq = run_liquidity_check(req.ticker, expiry, put_strikes=puts, call_strikes=calls)
    if not liq.get("spot_sanity_ok", False):
        raise OrderRejected(f"spot-sanity failed: {liq.get('reasons')}")
    if not liq.get("liquid", False):
        raise OrderRejected(f"legs not tradeable: {liq.get('reasons')}")
    return liq


def _leg_mid(liq: dict, leg: OrderLeg) -> float | None:
    """Pull the validated mid for a leg from the liquidity result (match type+strike)."""
    want_type = "put" if leg.right == "P" else "call"
    for row in liq.get("legs", []):
        if row.get("type") == want_type and abs(float(row.get("requested_strike", -1)) - leg.strike) < 1e-6:
            return row.get("mid")
    return None


def _ensure_loop() -> None:
    """Guarantee the current thread has an asyncio event loop.

    ib_insync/eventkit call asyncio.get_event_loop() at import time, which raises
    if the thread has no current loop (e.g. a prior test closed it, or we're in a
    fresh worker thread). Set one before any ib_insync import touches it.
    """
    import asyncio
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def _halted() -> bool:
    """Respect the dedicated options-desk halt key only.

    Equity-pair structural-break halts do NOT block options — a broken cointegration
    pair is unrelated to whether you can sell a put. Only an explicit options halt
    (``risk:options_halt``) stands the desk down.

    We fail *open* on a Redis read error: that key governs nothing if Redis is absent,
    a solo options user may not run it at all, and this path is paper-only — so an
    unreachable Redis is not an options halt.
    """
    try:
        from orgos.quant.kill_switch import options_halt_state
        return options_halt_state()
    except Exception:  # noqa: BLE001 — Redis absent/unreachable ≠ an options halt
        return False


# ── IB connection (guarded) ───────────────────────────────────────────────────

def connect(ib: Any = None) -> Any:
    """Connect to the IBKR paper gateway behind the fail-closed guard.

    Port is checked before connecting; the account id is checked once known. An
    injected ``ib`` (a fake) skips the real connect for tests but still runs the guard.
    """
    assert_paper_safe(cfg.IB_GATEWAY_PORT)  # port-only check before we touch the network
    if ib is None:
        _ensure_loop()
        from ib_insync import IB
        ib = IB()
        ib.connect(cfg.IB_GATEWAY_IP, cfg.IB_GATEWAY_PORT, clientId=cfg.OPTIONS_IB_CLIENT_ID)
    accounts = list(ib.managedAccounts() or [])
    assert_paper_safe(cfg.IB_GATEWAY_PORT, accounts[0] if accounts else None)
    return ib


def _build_contracts(ib: Any, ticker: str, legs: list[OrderLeg]) -> list[Any]:
    _ensure_loop()
    from ib_insync import Option
    contracts = []
    for leg in legs:
        c = Option(ticker, leg.expiry.replace("-", ""), leg.strike, leg.right,
                   exchange="SMART", multiplier="100")
        contracts.append(c)
    ib.qualifyContracts(*contracts)
    return contracts


def _is_num(x: Any) -> bool:
    import math
    return isinstance(x, (int, float)) and not math.isnan(float(x)) and x > 0


def _ibkr_mid(ib: Any, contract: Any) -> float | None:
    """Live mid for one contract from IBKR — the venue we actually trade on.

    Prices the limit order against the same book the order is sent to (yfinance
    quotes are stale/inconsistent). Falls back through bid/ask mid → marketPrice →
    last. Returns None if IBKR has no usable quote (e.g. no market-data permission).
    """
    try:
        ib.reqMarketDataType(cfg.IB_MARKET_DATA_TYPE)
    except Exception:  # noqa: BLE001 — type request is best-effort
        pass
    tickers = ib.reqTickers(contract)
    if not tickers:
        return None
    t = tickers[0]
    bid, ask = getattr(t, "bid", None), getattr(t, "ask", None)
    if _is_num(bid) and _is_num(ask):
        return round((bid + ask) / 2, 2)
    for attr in ("marketPrice", "midpoint"):
        fn = getattr(t, attr, None)
        if callable(fn):
            try:
                v = fn()
            except Exception:  # noqa: BLE001
                v = None
            if _is_num(v):
                return round(float(v), 2)
    last = getattr(t, "last", None) or getattr(t, "close", None)
    return round(float(last), 2) if _is_num(last) else None


# ── Place / close ─────────────────────────────────────────────────────────────

def place_paper_order(req: PaperOrderRequest, *, ib: Any = None,
                      ledger: OptionsPaperLedger | None = None) -> dict:
    """Run all pre-trade gates, then place each leg as a paper limit order.

    Returns a summary with the ledger order id, position id, and per-leg order ids.
    Raises OrderRejected if any gate fails (nothing is sent), or UnsafeExecutionError
    if the connection isn't a paper session.
    """
    req = PaperOrderRequest(req.ticker, req.strategy, [l.normalized() for l in req.legs],
                            req.max_loss_usd, req.run_id, req.limit_prices)
    ledger = ledger or OptionsPaperLedger()

    if _halted():
        raise OrderRejected("kill-switch halt active — standing down")
    check_risk(req, ledger)
    liq = check_liquidity(req)  # raises if illiquid/stale

    own_connection = ib is None
    ib = connect(ib)
    try:
        _ensure_loop()
        from ib_insync import LimitOrder
        contracts = _build_contracts(ib, req.ticker, req.legs)
        order_ids: list[Any] = []
        legs_json: list[dict] = []
        net = 0.0  # signed net debit (+ = you pay, − = you collect)
        for leg, contract in zip(req.legs, contracts):
            # Price against IBKR (the venue we send to); fall back to the yfinance
            # liquidity mid, then an explicit override.
            price = (req.limit_prices.get(f"{leg.right}/{leg.strike}")
                     or _ibkr_mid(ib, contract) or _leg_mid(liq, leg))
            if price is None or price <= 0:
                raise OrderRejected(f"no usable limit price for leg {leg.right} {leg.strike}")
            price = round(float(price), 2)
            order = LimitOrder(leg.action, leg.qty, price, tif="DAY")
            trade = ib.placeOrder(contract, order)
            order_ids.append(getattr(getattr(trade, "order", None), "orderId", None))
            d = vars(leg).copy()
            d["limit"] = price
            legs_json.append(d)
            net += price * leg.qty * (1 if leg.action == "BUY" else -1)
    finally:
        if own_connection:
            try:
                ib.disconnect()
            except Exception:  # noqa: BLE001
                pass

    net = round(net, 2)
    order_id = ledger.record_order(
        ticker=req.ticker, strategy=req.strategy, legs=legs_json,
        limit_price=net, run_id=req.run_id, ib_order_ids=order_ids, status="submitted")
    position_id = ledger.open_position(
        order_id=order_id, ticker=req.ticker, strategy=req.strategy,
        legs=legs_json, open_price=net, run_id=req.run_id)

    return {
        "ok": True,
        "order_id": order_id,
        "position_id": position_id,
        "ib_order_ids": order_ids,
        "ticker": req.ticker,
        "strategy": req.strategy,
        "legs": legs_json,
        "net_price": net,  # − = net credit collected, + = net debit paid
        "liquidity": {"liquid": liq.get("liquid"), "spot": liq.get("spot")},
    }


def ibkr_option_positions(ib: Any) -> list[dict]:
    """Live option positions from IBKR — the source of truth for what actually filled.

    Matching by transient order id is unreliable on an account shared with Icarus
    (IBKR reports orderId 0 for cross-session/cross-client orders). Positions are the
    durable record: one row per net option position with signed qty and avg cost.
    """
    out: list[dict] = []
    for p in (ib.positions() or []):
        c = p.contract
        if getattr(c, "secType", None) != "OPT":
            continue
        out.append({
            "symbol": c.symbol,
            "right": getattr(c, "right", None),
            "strike": float(getattr(c, "strike", 0) or 0),
            "expiry": getattr(c, "lastTradeDateOrContractMonth", None),
            "qty": float(p.position),
            "avg_cost": round(float(p.avgCost), 4),  # premium × multiplier
            "_contract": c,
        })
    return out


def reconcile(*, ib: Any = None, ledger: OptionsPaperLedger | None = None) -> dict:
    """Sync the ledger to IBKR's actual option positions and report unrealized P&L.

    Reads live positions (the truth), marks any matching 'submitted' ledger order as
    'filled' (by contract, not order id), and prices each position against the live
    book to compute unrealized P&L. Per-contract premium = avg_cost / 100.
    """
    ledger = ledger or OptionsPaperLedger()
    own_connection = ib is None
    ib = connect(ib)
    try:
        try:
            ib.reqAllOpenOrders()
            ib.sleep(1.0)
        except Exception:  # noqa: BLE001 — best-effort refresh
            pass
        positions = ibkr_option_positions(ib)

        marked = 0
        rows = ledger.conn.execute(
            "SELECT id, legs FROM options_paper_orders WHERE status='submitted'"
        ).fetchall()
        for r in rows:
            if _order_matches_a_position(r["legs"], positions):
                ledger.update_order(r["id"], status="filled")
                marked += 1

        view: list[dict] = []
        for p in positions:
            premium = round(p["avg_cost"] / 100.0, 4)
            mid = _ibkr_mid(ib, p["_contract"])
            # Mark-to-market for a signed position: gain when the contract moves in the
            # direction of your sign. Long (qty>0) profits as price rises; short (qty<0)
            # profits as it falls. Both: (current − entry) × 100 × qty.
            unreal = round((mid - premium) * 100 * p["qty"], 2) if mid is not None else None
            view.append({k: v for k, v in p.items() if k != "_contract"}
                        | {"premium": premium, "current_mid": mid, "unrealized_pnl": unreal})
    finally:
        if own_connection:
            try:
                ib.disconnect()
            except Exception:  # noqa: BLE001
                pass
    return {"ibkr_option_positions": view, "orders_marked_filled": marked}


def _order_matches_a_position(legs_json: str | None, positions: list[dict]) -> bool:
    """True if every leg of a ledger order maps to a live IBKR option position."""
    import json
    try:
        legs = json.loads(legs_json or "[]")
    except (TypeError, ValueError):
        return False
    if not legs:
        return False
    for leg in legs:
        if not any(
            p["right"] == leg.get("right")
            and abs(p["strike"] - float(leg.get("strike", -1))) < 1e-6
            and p["expiry"] == leg.get("expiry", "").replace("-", "")
            for p in positions
        ):
            return False
    return True


def flatten_options(*, ib: Any = None, ledger: OptionsPaperLedger | None = None) -> dict:
    """Close every live IBKR option position with a market order, flat the ledger.

    Closing action is the opposite of the position sign: BUY to cover a short, SELL
    to close a long. Marks all open ledger positions closed. Use to clean up test
    fills or flatten the desk.
    """
    _ensure_loop()
    ledger = ledger or OptionsPaperLedger()
    own_connection = ib is None
    ib = connect(ib)
    closed: list[dict] = []
    try:
        from ib_insync import MarketOrder
        for p in ibkr_option_positions(ib):
            qty = p["qty"]
            if qty == 0:
                continue
            action = "BUY" if qty < 0 else "SELL"
            trade = ib.placeOrder(p["_contract"], MarketOrder(action, abs(qty), tif="DAY"))
            closed.append({"symbol": p["symbol"], "right": p["right"], "strike": p["strike"],
                           "action": action, "qty": abs(qty),
                           "order_id": getattr(getattr(trade, "order", None), "orderId", None)})
        ib.sleep(2)
        for pos in ledger.open_positions():
            ledger.close_position(pos["id"], close_price=None, realized_pnl=None)
    finally:
        if own_connection:
            try:
                ib.disconnect()
            except Exception:  # noqa: BLE001
                pass
    return {"closed": closed}
