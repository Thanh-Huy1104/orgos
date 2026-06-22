"""Options strategy builder — structure legs, compute risk profile, P&L at expiry.

Six core strategies covering the most common retail and quant use cases.
Every strategy returns a structured dict with:
  legs          — each contract (type, strike, expiry, position, premium)
  max_profit    — best case P&L per share (None if theoretically unlimited)
  max_loss      — worst case P&L per share (always defined — we only build defined-risk)
  breakevens    — price(s) where P&L crosses zero at expiry
  greeks        — net delta, gamma, theta, vega for the whole structure
  payoff        — [{spot, pnl}] list across a price range for charting
  rationale     — plain-text reasoning about when to use this structure

All builders take a spot price, strikes, premiums, and optional Greeks — they do
not fetch data themselves. The chain fetcher + pricer produce the inputs; this
module only assembles and analyses the structure.

Strategies (in complexity order):
  covered_call       — own stock, sell OTM call. Income, capped upside.
  cash_secured_put   — sell OTM put with cash to cover. Get paid to buy a dip.
  bull_call_spread   — buy ATM call, sell OTM call. Bullish, defined risk.
  bear_put_spread    — buy ATM put, sell OTM put. Bearish, defined risk.
  iron_condor        — sell OTM call spread + OTM put spread. Rangebound, collect premium.
  long_straddle      — buy ATM call + ATM put. Big move in either direction.
"""

from __future__ import annotations

import math
from typing import Literal

from .pricer import bs_greeks, payoff_at_expiry, OptionType

Position = Literal["long", "short"]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _net_greeks(*legs: dict) -> dict:
    """Sum greeks across legs, accounting for long (+1) / short (-1) position."""
    keys = ("delta", "gamma", "theta", "vega")
    totals = {k: 0.0 for k in keys}
    for leg in legs:
        sign = 1.0 if leg["position"] == "long" else -1.0
        g = leg.get("greeks", {})
        for k in keys:
            totals[k] = round(totals[k] + sign * g.get(k, 0.0), 4)
    return totals


def _combine_payoffs(*leg_payoffs: list[dict]) -> list[dict]:
    """Sum per-leg payoff lists (same spot grid) into one net P&L list."""
    if not leg_payoffs:
        return []
    combined = [{"spot": p["spot"], "pnl": p["pnl"]} for p in leg_payoffs[0]]
    for extra in leg_payoffs[1:]:
        for i, p in enumerate(extra):
            combined[i]["pnl"] = round(combined[i]["pnl"] + p["pnl"], 4)
    return combined


def _breakevens(payoff: list[dict]) -> list[float]:
    """Find spots where P&L crosses zero (sign changes in adjacent points)."""
    bps = []
    for i in range(len(payoff) - 1):
        a, b = payoff[i]["pnl"], payoff[i + 1]["pnl"]
        if a == 0:
            bps.append(payoff[i]["spot"])
        elif a * b < 0:  # sign change — linear interpolate
            x0, x1 = payoff[i]["spot"], payoff[i + 1]["spot"]
            bp = x0 + (x1 - x0) * abs(a) / (abs(a) + abs(b))
            bps.append(round(bp, 2))
    return bps


def _spot_range(spot: float, width: float = 0.30, n: int = 80) -> tuple[float, float]:
    return spot * (1 - width), spot * (1 + width)


# ── Strategy builders ──────────────────────────────────────────────────────────

def covered_call(
    spot: float,
    call_strike: float,
    call_premium: float,
    *,
    T: float,
    r: float = 0.05,
    sigma: float,
    shares: int = 100,
) -> dict:
    """Covered call: long 100 shares + short 1 OTM call.

    Income strategy. You already own the stock (or buy it now) and sell a call
    against it to collect premium. You keep the premium no matter what; you cap
    your upside at the call strike.

    Best for: high-IV-rank environment (premium is rich), mildly bullish / neutral view.
    Risk:     stock falling below purchase price (standard equity risk, reduced by premium).
    """
    call_g = bs_greeks(spot, call_strike, T, r, sigma, "call")

    # Stock payoff at expiry (long shares): spot_final - spot (the entry price)
    sr = _spot_range(spot)
    n_pts = 80
    step = (sr[1] - sr[0]) / (n_pts - 1)
    stock_payoff = [{"spot": sr[0] + i * step,
                     "pnl": round((sr[0] + i * step - spot), 4)} for i in range(n_pts)]

    call_payoff_long = payoff_at_expiry(call_strike, call_premium, "call",
                                        spot_range=sr, n_points=n_pts)
    # Short call: flip the sign (we sold it, so profit when buyer loses)
    call_payoff_short = [{"spot": p["spot"], "pnl": -p["pnl"]} for p in call_payoff_long]

    payoff = _combine_payoffs(stock_payoff, call_payoff_short)

    max_profit = round(call_strike - spot + call_premium, 2)
    breakeven = round(spot - call_premium, 2)

    net_delta = round(1.0 - call_g["delta"], 4)  # long stock delta=1, short call=-delta

    return {
        "strategy": "covered_call",
        "spot": spot,
        "legs": [
            {"type": "stock", "position": "long", "strike": None,
             "premium": spot, "quantity": shares},
            {"type": "call", "position": "short", "strike": call_strike,
             "premium": call_premium, "expiry_years": T},
        ],
        "net_premium_collected": round(call_premium, 2),
        "max_profit": max_profit,
        "max_loss": f"stock → 0 minus {call_premium:.2f} premium collected",
        "breakeven": breakeven,
        "greeks": {"delta": net_delta, "gamma": round(-call_g["gamma"], 6),
                   "theta": round(-call_g["theta"], 4), "vega": round(-call_g["vega"], 4)},
        "payoff": payoff,
        "rationale": (
            f"Collect ${call_premium:.2f} premium by selling the {call_strike} call. "
            f"Max profit ${max_profit:.2f} if stock finishes above {call_strike}. "
            f"Breakeven at ${breakeven:.2f} (you lose money only below there). "
            "Use when IV is high (premium is rich) and you are neutral-to-mildly bullish."
        ),
    }


def cash_secured_put(
    spot: float,
    put_strike: float,
    put_premium: float,
    *,
    T: float,
    r: float = 0.05,
    sigma: float,
) -> dict:
    """Cash-secured put: short OTM put, cash set aside to buy shares if assigned.

    You get paid to commit to buying a stock at a lower price. If the stock stays
    above the strike, you keep the premium. If it falls below, you buy the shares
    at strike (net cost = strike - premium).

    Best for: high-IV-rank stock you would genuinely want to own at the strike price.
    Risk:     stock crashing far below strike (you still buy at the strike).
    """
    put_g = bs_greeks(spot, put_strike, T, r, sigma, "put")

    sr = _spot_range(spot)
    put_payoff_long = payoff_at_expiry(put_strike, put_premium, "put",
                                       spot_range=sr, n_points=80)
    put_payoff_short = [{"spot": p["spot"], "pnl": -p["pnl"]} for p in put_payoff_long]

    max_profit = round(put_premium, 2)
    max_loss = round(put_strike - put_premium, 2)  # stock goes to 0
    breakeven = round(put_strike - put_premium, 2)

    return {
        "strategy": "cash_secured_put",
        "spot": spot,
        "legs": [
            {"type": "put", "position": "short", "strike": put_strike,
             "premium": put_premium, "expiry_years": T},
        ],
        "cash_required": round(put_strike * 100, 2),
        "net_premium_collected": max_profit,
        "max_profit": max_profit,
        "max_loss": max_loss,
        "breakeven": breakeven,
        "effective_buy_price": breakeven,
        "greeks": {"delta": round(-put_g["delta"], 4), "gamma": round(-put_g["gamma"], 6),
                   "theta": round(-put_g["theta"], 4), "vega": round(-put_g["vega"], 4)},
        "payoff": put_payoff_short,
        "rationale": (
            f"Collect ${put_premium:.2f} premium. If stock stays above ${put_strike}, "
            f"you keep it all. If assigned, you buy at ${put_strike} — effective cost "
            f"${breakeven:.2f} (below today's ${spot:.2f}). "
            "Use when IV is high and you want to own the stock at a discount."
        ),
    }


def bull_call_spread(
    spot: float,
    long_strike: float,
    short_strike: float,
    long_premium: float,
    short_premium: float,
    *,
    T: float,
    r: float = 0.05,
    sigma_long: float,
    sigma_short: float,
) -> dict:
    """Bull call spread: buy lower call, sell higher call. Bullish, defined risk.

    You buy a call for directional exposure and sell a higher-strike call to
    finance part of the cost. This caps both your profit (at the short strike)
    and your loss (at the premium paid).

    Best for: moderately bullish view, lower IV (calls cheaper than usual).
    Risk:     lose the net premium paid if stock stays below long strike.
    """
    long_g = bs_greeks(spot, long_strike, T, r, sigma_long, "call")
    short_g = bs_greeks(spot, short_strike, T, r, sigma_short, "call")

    net_debit = round(long_premium - short_premium, 2)
    max_profit = round(short_strike - long_strike - net_debit, 2)
    max_loss = net_debit
    breakeven = round(long_strike + net_debit, 2)

    sr = _spot_range(spot)
    long_po = payoff_at_expiry(long_strike, long_premium, "call", spot_range=sr, n_points=80)
    short_po = payoff_at_expiry(short_strike, short_premium, "call", spot_range=sr, n_points=80)
    short_po_flipped = [{"spot": p["spot"], "pnl": -p["pnl"]} for p in short_po]
    payoff = _combine_payoffs(long_po, short_po_flipped)

    legs = [
        {"type": "call", "position": "long", "strike": long_strike,
         "premium": long_premium, "expiry_years": T},
        {"type": "call", "position": "short", "strike": short_strike,
         "premium": short_premium, "expiry_years": T},
    ]

    return {
        "strategy": "bull_call_spread",
        "spot": spot,
        "legs": legs,
        "net_debit": net_debit,
        "max_profit": max_profit,
        "max_loss": max_loss,
        "breakeven": breakeven,
        "greeks": _net_greeks(
            {"position": "long", "greeks": long_g},
            {"position": "short", "greeks": short_g},
        ),
        "payoff": payoff,
        "rationale": (
            f"Pay ${net_debit:.2f} for exposure to a move from ${long_strike} to "
            f"${short_strike}. Max profit ${max_profit:.2f} if stock finishes above "
            f"${short_strike}. Breakeven at ${breakeven:.2f}. "
            "Lower cost than buying a naked call; gives up unlimited upside above the spread."
        ),
    }


def bear_put_spread(
    spot: float,
    long_strike: float,
    short_strike: float,
    long_premium: float,
    short_premium: float,
    *,
    T: float,
    r: float = 0.05,
    sigma_long: float,
    sigma_short: float,
) -> dict:
    """Bear put spread: buy higher put, sell lower put. Bearish, defined risk.

    Mirror of bull call spread, for a bearish view. You pay less than a naked put
    but cap your downside profit at the short (lower) strike.

    Best for: moderately bearish view.
    Risk:     lose net premium if stock stays above long (higher) strike.
    """
    long_g = bs_greeks(spot, long_strike, T, r, sigma_long, "put")
    short_g = bs_greeks(spot, short_strike, T, r, sigma_short, "put")

    net_debit = round(long_premium - short_premium, 2)
    max_profit = round(long_strike - short_strike - net_debit, 2)
    max_loss = net_debit
    breakeven = round(long_strike - net_debit, 2)

    sr = _spot_range(spot)
    long_po = payoff_at_expiry(long_strike, long_premium, "put", spot_range=sr, n_points=80)
    short_po = payoff_at_expiry(short_strike, short_premium, "put", spot_range=sr, n_points=80)
    short_po_flipped = [{"spot": p["spot"], "pnl": -p["pnl"]} for p in short_po]
    payoff = _combine_payoffs(long_po, short_po_flipped)

    return {
        "strategy": "bear_put_spread",
        "spot": spot,
        "legs": [
            {"type": "put", "position": "long", "strike": long_strike,
             "premium": long_premium, "expiry_years": T},
            {"type": "put", "position": "short", "strike": short_strike,
             "premium": short_premium, "expiry_years": T},
        ],
        "net_debit": net_debit,
        "max_profit": max_profit,
        "max_loss": max_loss,
        "breakeven": breakeven,
        "greeks": _net_greeks(
            {"position": "long", "greeks": long_g},
            {"position": "short", "greeks": short_g},
        ),
        "payoff": payoff,
        "rationale": (
            f"Pay ${net_debit:.2f} to profit from a drop from ${long_strike} toward "
            f"${short_strike}. Max profit ${max_profit:.2f} below ${short_strike}. "
            f"Breakeven at ${breakeven:.2f}. Cheaper than a naked put; caps downside profit."
        ),
    }


def iron_condor(
    spot: float,
    put_short_strike: float,
    put_long_strike: float,
    call_short_strike: float,
    call_long_strike: float,
    put_short_premium: float,
    put_long_premium: float,
    call_short_premium: float,
    call_long_premium: float,
    *,
    T: float,
    r: float = 0.05,
    sigma: float,
) -> dict:
    """Iron condor: sell OTM put spread + sell OTM call spread. Rangebound.

    You collect premium from both sides and profit if the stock stays between
    the two short strikes. The long wings limit your loss.

    Best for: high-IV-rank environment where you expect the stock to chop sideways.
    Risk:     stock breaking out above call_short or below put_short.

    Strike layout (low → high):
      put_long < put_short < [spot] < call_short < call_long
    """
    sr = (_spot_range(spot)[0], _spot_range(spot)[1])

    # Short put spread: sell put_short, buy put_long (protection below)
    ps_po = payoff_at_expiry(put_short_strike, put_short_premium, "put", spot_range=sr, n_points=80)
    pl_po = payoff_at_expiry(put_long_strike, put_long_premium, "put", spot_range=sr, n_points=80)
    short_put_spread = [{"spot": p["spot"], "pnl": round(-p["pnl"] + pl_po[i]["pnl"], 4)}
                        for i, p in enumerate(ps_po)]
    # Short call spread: sell call_short, buy call_long (protection above)
    cs_po = payoff_at_expiry(call_short_strike, call_short_premium, "call", spot_range=sr, n_points=80)
    cl_po = payoff_at_expiry(call_long_strike, call_long_premium, "call", spot_range=sr, n_points=80)
    short_call_spread = [{"spot": p["spot"], "pnl": round(-p["pnl"] + cl_po[i]["pnl"], 4)}
                         for i, p in enumerate(cs_po)]

    payoff = _combine_payoffs(short_put_spread, short_call_spread)

    net_credit = round(
        (put_short_premium - put_long_premium) + (call_short_premium - call_long_premium), 2
    )
    put_wing_width = round(put_short_strike - put_long_strike, 2)
    call_wing_width = round(call_long_strike - call_short_strike, 2)
    max_loss = round(max(put_wing_width, call_wing_width) - net_credit, 2)
    max_profit = net_credit
    lower_be = round(put_short_strike - net_credit, 2)
    upper_be = round(call_short_strike + net_credit, 2)

    return {
        "strategy": "iron_condor",
        "spot": spot,
        "legs": [
            {"type": "put", "position": "long", "strike": put_long_strike,
             "premium": put_long_premium, "expiry_years": T},
            {"type": "put", "position": "short", "strike": put_short_strike,
             "premium": put_short_premium, "expiry_years": T},
            {"type": "call", "position": "short", "strike": call_short_strike,
             "premium": call_short_premium, "expiry_years": T},
            {"type": "call", "position": "long", "strike": call_long_strike,
             "premium": call_long_premium, "expiry_years": T},
        ],
        "net_credit": net_credit,
        "max_profit": max_profit,
        "max_loss": max_loss,
        "breakevens": [lower_be, upper_be],
        "profit_zone": [put_short_strike, call_short_strike],
        "payoff": payoff,
        "rationale": (
            f"Collect ${net_credit:.2f} credit. Profit as long as stock stays between "
            f"${put_short_strike} and ${call_short_strike} at expiry. "
            f"Max loss ${max_loss:.2f} if stock breaks out. "
            f"Breakevens at ${lower_be:.2f} / ${upper_be:.2f}. "
            "Best when IV is elevated and you expect the stock to go nowhere."
        ),
    }


def long_straddle(
    spot: float,
    strike: float,
    call_premium: float,
    put_premium: float,
    *,
    T: float,
    r: float = 0.05,
    sigma: float,
) -> dict:
    """Long straddle: buy ATM call + ATM put. Bet on a big move, any direction.

    You profit if the stock moves more than the total premium paid — in either
    direction. This is a pure volatility bet: you want realized vol to exceed
    implied vol (the price you paid for the options).

    Best for: low-IV-rank (options cheap), pre-earnings or pre-event situations.
    Risk:     stock stays flat — you lose the full premium to theta decay.
    """
    call_g = bs_greeks(spot, strike, T, r, sigma, "call")
    put_g = bs_greeks(spot, strike, T, r, sigma, "put")

    total_premium = round(call_premium + put_premium, 2)
    upper_be = round(strike + total_premium, 2)
    lower_be = round(strike - total_premium, 2)

    sr = _spot_range(spot, width=0.40)
    call_po = payoff_at_expiry(strike, call_premium, "call", spot_range=sr, n_points=80)
    put_po = payoff_at_expiry(strike, put_premium, "put", spot_range=sr, n_points=80)
    payoff = _combine_payoffs(call_po, put_po)

    # Breakeven: stock must move more than total premium from strike
    implied_move_pct = round(total_premium / spot * 100, 1)

    return {
        "strategy": "long_straddle",
        "spot": spot,
        "legs": [
            {"type": "call", "position": "long", "strike": strike,
             "premium": call_premium, "expiry_years": T},
            {"type": "put", "position": "long", "strike": strike,
             "premium": put_premium, "expiry_years": T},
        ],
        "total_premium_paid": total_premium,
        "max_profit": None,  # unlimited (on the call side)
        "max_loss": total_premium,
        "breakevens": [lower_be, upper_be],
        "implied_move_pct": implied_move_pct,
        "greeks": _net_greeks(
            {"position": "long", "greeks": call_g},
            {"position": "long", "greeks": put_g},
        ),
        "payoff": payoff,
        "rationale": (
            f"Pay ${total_premium:.2f} total. Profit if stock moves more than "
            f"${total_premium:.2f} ({implied_move_pct:.1f}%) from ${strike} "
            f"in either direction. Breakevens: ${lower_be:.2f} / ${upper_be:.2f}. "
            "Positive vega: you want IV to spike (options become more valuable). "
            "Use before known events (earnings, FOMC) when options are cheap."
        ),
    }


# ── Strategy selector ──────────────────────────────────────────────────────────

def suggest_strategy(
    iv_rank: float,
    rv: float,
    atm_iv: float,
    *,
    view: Literal["bullish", "bearish", "neutral", "volatile"] = "neutral",
) -> dict:
    """Given market conditions, suggest the most appropriate strategy structure.

    This is a heuristic rule-set — a starting point for the agent or analyst to
    refine, not a trade signal. The agent reads this recommendation and evaluates
    it against the full chain data.

    Args:
        iv_rank: 0–100. Current IV vs trailing 52-week range.
        rv:      Annualised realized vol (e.g. 0.20 for 20%).
        atm_iv:  Current ATM implied vol (annualised).
        view:    Your directional thesis.
    """
    vol_premium = atm_iv - rv  # positive = options expensive

    candidates: list[dict] = []

    if iv_rank >= 50 and view == "neutral":
        candidates.append({
            "strategy": "iron_condor",
            "reason": (
                f"IV rank {iv_rank:.0f} is elevated — options expensive. "
                "Selling an iron condor collects that premium; "
                "neutrality means no directional bet needed."
            ),
            "priority": 1,
        })

    if iv_rank >= 50 and view in ("bullish", "neutral"):
        candidates.append({
            "strategy": "covered_call",
            "reason": (
                f"IV rank {iv_rank:.0f} → rich premium. "
                "Covered call collects income while you hold the stock."
            ),
            "priority": 2,
        })

    if iv_rank >= 50 and view == "bullish":
        candidates.append({
            "strategy": "cash_secured_put",
            "reason": (
                f"IV rank {iv_rank:.0f} → sell an OTM put at inflated premium. "
                "If assigned, you buy the stock at a discount."
            ),
            "priority": 2,
        })

    if iv_rank <= 30 and view == "volatile":
        candidates.append({
            "strategy": "long_straddle",
            "reason": (
                f"IV rank {iv_rank:.0f} → options cheap. "
                "A straddle buys vol at a discount — profitable if the "
                "move exceeds the low premium paid."
            ),
            "priority": 1,
        })

    if view == "bullish" and iv_rank <= 50:
        candidates.append({
            "strategy": "bull_call_spread",
            "reason": (
                "Bullish view, moderate IV — bull call spread gives directional "
                "exposure at lower cost than a naked call."
            ),
            "priority": 3,
        })

    if view == "bearish" and iv_rank <= 50:
        candidates.append({
            "strategy": "bear_put_spread",
            "reason": (
                "Bearish view, moderate IV — bear put spread gives defined-risk "
                "downside exposure."
            ),
            "priority": 3,
        })

    if not candidates:
        candidates.append({
            "strategy": "none",
            "reason": (
                f"IV rank {iv_rank:.0f}, vol premium {vol_premium:.1%}, view '{view}' — "
                "no strong structural edge. Wait for a clearer setup."
            ),
            "priority": 99,
        })

    candidates.sort(key=lambda c: c["priority"])
    return {
        "iv_rank": iv_rank,
        "atm_iv_pct": round(atm_iv * 100, 1),
        "realized_vol_pct": round(rv * 100, 1),
        "vol_premium_pts": round(vol_premium * 100, 1),
        "view": view,
        "top_suggestion": candidates[0]["strategy"],
        "candidates": candidates,
    }
