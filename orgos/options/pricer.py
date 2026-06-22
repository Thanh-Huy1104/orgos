"""Black-Scholes option pricer — price, Greeks, and IV solver.

Pure math: no network, no LLM. All functions take plain floats and return
plain floats or dicts. Fully unit-testable offline.

Black-Scholes assumptions (honest scope):
  - European-style exercise only (no early exercise)
  - Constant volatility and risk-free rate over the option's life
  - No dividends (use forward price S*exp(-q*T) if needed)
  - Liquid, frictionless market

For American-style single-stock options (where early exercise matters on deep
ITM puts or dividend-paying stocks), use a binomial tree instead — this module
flags that clearly and provides the binomial pricer as well.
"""

from __future__ import annotations

import math
from typing import Literal

OptionType = Literal["call", "put"]

# ── Helpers ────────────────────────────────────────────────────────────────────

_SQRT_2PI = math.sqrt(2 * math.pi)


def _norm_cdf(x: float) -> float:
    """Standard normal CDF — pure Python, no scipy needed."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2)))


def _norm_pdf(x: float) -> float:
    """Standard normal PDF."""
    return math.exp(-0.5 * x * x) / _SQRT_2PI


def _d1_d2(S: float, K: float, T: float, r: float, sigma: float) -> tuple[float, float]:
    """Black-Scholes d1 and d2."""
    if T <= 0:
        raise ValueError(f"T must be > 0 (got {T})")
    if sigma <= 0:
        raise ValueError(f"sigma must be > 0 (got {sigma})")
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    return d1, d2


# ── Black-Scholes price ────────────────────────────────────────────────────────

def bs_price(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: OptionType = "call",
) -> float:
    """Black-Scholes European option price.

    Args:
        S:           Current underlying price.
        K:           Strike price.
        T:           Time to expiration in years (e.g. 30 days = 30/365).
        r:           Annualized risk-free rate (e.g. 0.05 for 5%).
        sigma:       Annualized implied volatility (e.g. 0.20 for 20%).
        option_type: 'call' or 'put'.

    Returns:
        Theoretical option price (same currency as S and K).
    """
    d1, d2 = _d1_d2(S, K, T, r, sigma)
    disc = math.exp(-r * T)
    if option_type == "call":
        return S * _norm_cdf(d1) - K * disc * _norm_cdf(d2)
    return K * disc * _norm_cdf(-d2) - S * _norm_cdf(-d1)


# ── Greeks ─────────────────────────────────────────────────────────────────────

def bs_greeks(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: OptionType = "call",
) -> dict:
    """Black-Scholes Greeks.

    Returns a dict with:
        price   — theoretical option value
        delta   — $ change per $1 move in S  (call: 0→1, put: -1→0)
        gamma   — rate of change of delta per $1 move in S (always positive)
        theta   — daily time decay in $ (negative for long options — the clock ticking)
        vega    — $ change per 1-point move in IV (e.g. IV from 20% to 21%)
        rho     — $ change per 1-point move in r  (e.g. rate from 5% to 6%)
    """
    d1, d2 = _d1_d2(S, K, T, r, sigma)
    disc = math.exp(-r * T)
    sqrt_T = math.sqrt(T)
    nd1 = _norm_pdf(d1)

    price = bs_price(S, K, T, r, sigma, option_type)

    # Delta: directional exposure
    if option_type == "call":
        delta = _norm_cdf(d1)
        # Theta: daily decay (divide annual by 365)
        theta = (
            -(S * nd1 * sigma) / (2 * sqrt_T)
            - r * K * disc * _norm_cdf(d2)
        ) / 365
        rho = K * T * disc * _norm_cdf(d2) / 100  # per 1-point (1%) rate move
    else:
        delta = _norm_cdf(d1) - 1
        theta = (
            -(S * nd1 * sigma) / (2 * sqrt_T)
            + r * K * disc * _norm_cdf(-d2)
        ) / 365
        rho = -K * T * disc * _norm_cdf(-d2) / 100

    # Gamma and vega are the same for calls and puts (put-call parity)
    gamma = nd1 / (S * sigma * sqrt_T)
    vega = S * nd1 * sqrt_T / 100  # per 1-point (1%) vol move

    return {
        "price": round(price, 4),
        "delta": round(delta, 4),
        "gamma": round(gamma, 6),
        "theta": round(theta, 4),   # $ per day (negative = option losing value)
        "vega": round(vega, 4),     # $ per 1% vol move
        "rho": round(rho, 4),       # $ per 1% rate move
    }


# ── Intrinsic value and time value breakdown ───────────────────────────────────

def intrinsic_value(S: float, K: float, option_type: OptionType = "call") -> float:
    """The floor of an option's value — how much it's worth if exercised now."""
    if option_type == "call":
        return max(0.0, S - K)
    return max(0.0, K - S)


def time_value(
    market_price: float, S: float, K: float, option_type: OptionType = "call"
) -> float:
    """The premium above intrinsic — what you're paying for time and uncertainty."""
    return max(0.0, market_price - intrinsic_value(S, K, option_type))


# ── Implied volatility solver ──────────────────────────────────────────────────

def implied_vol(
    market_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    option_type: OptionType = "call",
    *,
    tol: float = 1e-6,
    max_iter: int = 100,
) -> float | None:
    """Solve for the implied volatility that makes BS price == market_price.

    Uses Newton-Raphson iteration (fast convergence for options).
    Returns None if the market price implies no valid IV (e.g. below intrinsic,
    or the solver diverges — this happens for deep ITM options near expiry).

    The result is the market's forecast of forward realized volatility, expressed
    as an annualized %. Comparing it to actual realized vol is how you find edge.
    """
    intrinsic = intrinsic_value(S, K, option_type)
    if market_price <= intrinsic:
        return None  # price below intrinsic — no time value, IV undefined

    sigma = 0.2  # starting guess: 20% is typical
    for _ in range(max_iter):
        try:
            price = bs_price(S, K, T, r, sigma, option_type)
            # vega = sensitivity of price to sigma (our Newton step denominator)
            d1, _ = _d1_d2(S, K, T, r, sigma)
            vega_raw = S * _norm_pdf(d1) * math.sqrt(T)
            if vega_raw < 1e-10:
                return None  # vega collapsed — solver cannot converge
            sigma = sigma - (price - market_price) / vega_raw
            if sigma <= 0:
                sigma = 1e-6  # keep positive
            if abs(price - market_price) < tol:
                return round(sigma, 6)
        except (ValueError, ZeroDivisionError):
            return None
    return None  # did not converge


# ── Binomial tree (American options) ──────────────────────────────────────────

def binomial_price(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: OptionType = "call",
    *,
    steps: int = 200,
    american: bool = True,
) -> float:
    """Cox-Ross-Rubinstein binomial tree.

    More accurate than Black-Scholes for American-style options (e.g. single-stock
    equity options where early exercise of deep-ITM puts matters). For European
    options they converge to the same value given enough steps.

    Args:
        steps:    Tree depth (200 is fast and accurate enough for most purposes).
        american: If True, check early exercise at every node.
    """
    dt = T / steps
    u = math.exp(sigma * math.sqrt(dt))     # up factor
    d = 1.0 / u                              # down factor (recombining tree)
    disc = math.exp(-r * dt)
    p = (math.exp(r * dt) - d) / (u - d)    # risk-neutral probability of up move

    # Terminal asset prices
    prices_at_T = [S * (u ** (steps - 2 * j)) for j in range(steps + 1)]

    # Terminal option values
    if option_type == "call":
        values = [max(0.0, px - K) for px in prices_at_T]
    else:
        values = [max(0.0, K - px) for px in prices_at_T]

    # Backward induction
    for step in range(steps - 1, -1, -1):
        for j in range(step + 1):
            hold = disc * (p * values[j] + (1 - p) * values[j + 1])
            if american:
                node_price = S * (u ** (step - 2 * j))
                exercise = (node_price - K) if option_type == "call" else (K - node_price)
                values[j] = max(hold, exercise)
            else:
                values[j] = hold

    return round(values[0], 4)


# ── Payoff diagram helper ──────────────────────────────────────────────────────

def payoff_at_expiry(
    K: float,
    premium: float,
    option_type: OptionType = "call",
    *,
    spot_range: tuple[float, float] | None = None,
    n_points: int = 50,
) -> list[dict]:
    """P&L at expiry across a range of underlying prices.

    Returns a list of {spot, pnl} dicts suitable for charting. Buyers flip the
    sign of premium (they paid it); this function returns the *buyer's* P&L by
    default (long one contract per unit). Multiply by -1 for the seller's view.
    """
    lo, hi = spot_range or (K * 0.7, K * 1.3)
    step = (hi - lo) / (n_points - 1)
    result = []
    for i in range(n_points):
        spot = lo + i * step
        if option_type == "call":
            pnl = max(0.0, spot - K) - premium
        else:
            pnl = max(0.0, K - spot) - premium
        result.append({"spot": round(spot, 2), "pnl": round(pnl, 4)})
    return result
