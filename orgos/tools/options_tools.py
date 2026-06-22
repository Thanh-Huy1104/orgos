"""Options desk tools — agent-invokable wrappers around the options math layer.

Three tools, matching the same pattern as quant_tool.py:
  VolatilityScanTool   — realized vol + IV rank for a ticker (pure read)
  OptionsSurfaceTool   — full IV surface snapshot: ATM IV, skew, term structure,
                         IV vs RV edge signal
  OptionsGreeksTool    — Black-Scholes price + Greeks for a specific contract

All tools are read-only (tier = worker). They discover and propose; they never
place orders or touch any execution layer.
"""

from __future__ import annotations

import json

from crewai.tools import BaseTool
from pydantic import BaseModel, Field


# ── VolatilityScanTool ────────────────────────────────────────────────────────

class _VolScanInput(BaseModel):
    ticker: str = Field(description="Equity ticker, e.g. 'AAPL'.")
    vol_window: int = Field(default=20, description="Rolling window for realized vol (trading days).")
    include_vix: bool = Field(default=True, description="Include live VIX level and regime.")


def run_vol_scan(ticker: str, vol_window: int = 20, include_vix: bool = True) -> dict:
    """Realized vol snapshot + IV rank for one ticker.

    Returns:
      realized vol (current, 1m avg, 3m avg), vol regime, spike flag,
      suggested position size at 15% target vol, optional VIX level,
      and IV rank (0-100) with sell/buy/neutral signal.
    """
    from orgos.quant.marketdata import get_prices, MarketDataError
    from orgos.quant.volatility import fetch_vix, vol_summary, iv_rank

    ticker = ticker.upper()
    result: dict = {"ticker": ticker}

    try:
        prices = get_prices(ticker, lookback_days=252)
    except MarketDataError as exc:
        return {"ticker": ticker, "error": f"no price data: {exc}"}

    vix = None
    if include_vix:
        try:
            vix = fetch_vix(lookback_days=252)
        except Exception:  # noqa: BLE001 — VIX is optional
            pass

    result.update(vol_summary(prices, vol_window=vol_window, vix=vix))

    # IV rank — needs live options data, may fail for illiquid tickers
    iv_result = iv_rank(ticker)
    result["iv_rank"] = iv_result

    return result


class VolatilityScanTool(BaseTool):
    name: str = "scan_volatility"
    description: str = (
        "Scan realized volatility and implied volatility rank for one equity ticker. "
        "Returns current realized vol, vol regime (low/medium/high), vol spike flag, "
        "suggested position size for a 15% target-vol strategy, VIX level, and "
        "IV rank (0-100) with a sell_premium/buy_options/neutral signal. "
        "Use this before building any options strategy — you need to know whether "
        "IV is cheap or expensive relative to the past year."
    )
    args_schema: type[BaseModel] = _VolScanInput
    tool_category: str = "compute"

    def _run(self, ticker: str, vol_window: int = 20, include_vix: bool = True) -> str:
        try:
            result = run_vol_scan(ticker, vol_window=vol_window, include_vix=include_vix)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": f"{type(exc).__name__}: {exc}"})
        return json.dumps(result, indent=2, default=str)


# ── OptionsSurfaceTool ────────────────────────────────────────────────────────

class _SurfaceInput(BaseModel):
    ticker: str = Field(description="Equity ticker with liquid options, e.g. 'SPY', 'AAPL'.")
    target_dte: int = Field(default=30, description="Target days-to-expiry for the main IV read (default 30).")
    max_expiries: int = Field(default=8, description="Max expiry dates to load (default 8 ≈ 8 months out).")


def run_surface(ticker: str, target_dte: int = 30, max_expiries: int = 8) -> dict:
    """Full IV surface for one ticker.

    Fetches the live option chain, computes ATM IV, skew, term structure
    (contango vs backwardation), and the core edge signal: IV vs realized vol.
    """
    from orgos.options.chain import get_chain, OptionDataError
    from orgos.options.surface import surface_snapshot
    from orgos.quant.marketdata import get_prices, MarketDataError
    from orgos.quant.volatility import realized_vol as compute_rv

    ticker = ticker.upper()

    try:
        chain = get_chain(ticker, max_expiries=max_expiries)
    except OptionDataError as exc:
        return {"ticker": ticker, "error": f"no options data: {exc}"}

    rv: float | None = None
    try:
        prices = get_prices(ticker, lookback_days=63)
        rv_series = compute_rv(prices, window=20)
        if len(rv_series.dropna()):
            rv = float(rv_series.dropna().iloc[-1])
    except (MarketDataError, Exception):  # noqa: BLE001
        pass

    return surface_snapshot(chain, rv, target_dte=target_dte)


class OptionsSurfaceTool(BaseTool):
    name: str = "scan_options_surface"
    description: str = (
        "Fetch the live IV surface for one equity ticker: ATM implied volatility, "
        "put skew (25-delta), term structure shape (contango/backwardation), and "
        "the edge signal comparing IV to recent realized vol. "
        "High IV vs RV → sell premium (iron condor, covered call, cash-secured put). "
        "Low IV vs RV → buy options (straddle, vertical spread). "
        "Use this after scan_volatility to get the full picture before recommending "
        "a strategy structure."
    )
    args_schema: type[BaseModel] = _SurfaceInput
    tool_category: str = "compute"

    def _run(self, ticker: str, target_dte: int = 30, max_expiries: int = 8) -> str:
        try:
            result = run_surface(ticker, target_dte=target_dte, max_expiries=max_expiries)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": f"{type(exc).__name__}: {exc}"})
        return json.dumps(result, indent=2, default=str)


# ── OptionsGreeksTool ─────────────────────────────────────────────────────────

class _GreeksInput(BaseModel):
    ticker: str = Field(description="Equity ticker, e.g. 'AAPL'.")
    strike: float = Field(description="Strike price.")
    expiry: str = Field(description="Expiry date as ISO string, e.g. '2025-09-19'.")
    option_type: str = Field(default="call", description="'call' or 'put'.")
    r: float = Field(default=0.05, description="Risk-free rate, e.g. 0.05 for 5%.")


def run_greeks(ticker: str, strike: float, expiry: str, option_type: str = "call",
               r: float = 0.05) -> dict:
    """Compute Black-Scholes price and Greeks for a specific contract.

    Fetches the live spot price and IV from the option chain, then runs the
    BS pricer for the exact strike/expiry. Returns price, delta, gamma, theta,
    vega, rho, intrinsic value, and time value.
    """
    import datetime as dt
    from orgos.options.chain import get_chain, OptionDataError
    from orgos.options.pricer import bs_greeks, intrinsic_value, time_value
    from orgos.options.surface import atm_iv

    ticker = ticker.upper()
    otype = "call" if option_type.lower() == "call" else "put"

    try:
        chain = get_chain(ticker, max_expiries=12)
    except OptionDataError as exc:
        return {"ticker": ticker, "error": f"no options data: {exc}"}

    if chain.spot is None:
        return {"ticker": ticker, "error": "spot price unavailable"}

    today = dt.date.today()
    try:
        exp_date = dt.date.fromisoformat(expiry)
    except ValueError:
        return {"error": f"invalid expiry format: {expiry!r} (use YYYY-MM-DD)"}

    T = max((exp_date - today).days / 365, 1 / 365)

    # Find the market IV for this specific strike from the chain
    calls_exp, puts_exp = chain.for_expiry(expiry) if expiry in chain.expiries else (
        __import__("pandas").DataFrame(), __import__("pandas").DataFrame()
    )
    df = calls_exp if otype == "call" else puts_exp

    sigma: float | None = None
    if not df.empty and "implied_vol" in df.columns and "strike" in df.columns:
        valid = df[df["implied_vol"].notna() & (df["implied_vol"] > 0)]
        if not valid.empty:
            nearest = valid.iloc[(valid["strike"] - strike).abs().argsort()[:1]]
            sigma = float(nearest["implied_vol"].iloc[0])

    if sigma is None:
        # Fall back to ATM IV as a proxy
        calls_near, puts_near = chain.for_expiry(chain.nearest_expiry() or expiry) \
            if chain.nearest_expiry() else (df, df)
        sigma = atm_iv(calls_near, puts_near, chain.spot) or 0.25

    greeks = bs_greeks(chain.spot, strike, T, r, sigma, otype)
    mkt_price = greeks["price"]

    return {
        "ticker": ticker,
        "spot": chain.spot,
        "strike": strike,
        "expiry": expiry,
        "dte": (exp_date - today).days,
        "option_type": otype,
        "sigma_used": round(sigma, 4),
        **greeks,
        "intrinsic": round(intrinsic_value(chain.spot, strike, otype), 4),
        "time_value": round(time_value(mkt_price, chain.spot, strike, otype), 4),
    }


class OptionsGreeksTool(BaseTool):
    name: str = "compute_options_greeks"
    description: str = (
        "Compute Black-Scholes price and Greeks (delta, gamma, theta, vega, rho) "
        "for a specific options contract given ticker, strike, and expiry date. "
        "Fetches the live spot price and implied vol from the option chain. "
        "Use this to precisely size a position, understand the daily theta decay "
        "(how much the option loses per day), or check delta exposure (how much "
        "you make/lose per $1 move in the stock)."
    )
    args_schema: type[BaseModel] = _GreeksInput
    tool_category: str = "compute"

    def _run(self, ticker: str, strike: float, expiry: str,
             option_type: str = "call", r: float = 0.05) -> str:
        try:
            result = run_greeks(ticker, strike, expiry, option_type, r)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": f"{type(exc).__name__}: {exc}"})
        return json.dumps(result, indent=2, default=str)


# ── StrategySuggestTool ───────────────────────────────────────────────────────

class _SuggestInput(BaseModel):
    ticker: str = Field(description="Equity ticker, e.g. 'AAPL'.")
    view: str = Field(
        default="neutral",
        description="Directional view: 'bullish', 'bearish', 'neutral', or 'volatile' "
                    "(expecting a big move but unsure of direction)."
    )
    target_dte: int = Field(default=30, description="Target days-to-expiry for the structure.")


def run_strategy_suggest(ticker: str, view: str = "neutral", target_dte: int = 30) -> dict:
    """Surface + strategy suggestion in one call.

    Fetches the IV surface, runs the heuristic strategy selector, and returns
    the top recommended structure with rationale.
    """
    from orgos.options.strategies import suggest_strategy
    from orgos.quant.volatility import iv_rank as compute_iv_rank
    from orgos.quant.marketdata import get_prices, MarketDataError
    from orgos.quant.volatility import realized_vol as compute_rv

    ticker = ticker.upper()
    iv_result = compute_iv_rank(ticker)
    rank = iv_result.get("iv_rank")
    current_iv = (iv_result.get("current_iv_pct") or 20) / 100

    rv: float = 0.20
    try:
        prices = get_prices(ticker, lookback_days=63)
        rv_series = compute_rv(prices, window=20)
        if len(rv_series.dropna()):
            rv = float(rv_series.dropna().iloc[-1])
    except (MarketDataError, Exception):  # noqa: BLE001
        pass

    if rank is None:
        return {
            "ticker": ticker,
            "error": iv_result.get("error", "IV rank unavailable"),
            "iv_rank_raw": iv_result,
        }

    suggestion = suggest_strategy(
        iv_rank=rank,
        rv=rv,
        atm_iv=current_iv,
        view=view,  # type: ignore[arg-type]
    )
    return {"ticker": ticker, "target_dte": target_dte, **suggestion}


class StrategySuggestTool(BaseTool):
    name: str = "suggest_options_strategy"
    description: str = (
        "Given a ticker and directional view, suggest the most appropriate options "
        "strategy based on current IV rank and realized vol. Returns ranked strategy "
        "candidates (iron_condor, covered_call, bull_call_spread, bear_put_spread, "
        "long_straddle, etc.) with rationale. "
        "Use this after scan_volatility and scan_options_surface to translate market "
        "conditions into a concrete structure recommendation."
    )
    args_schema: type[BaseModel] = _SuggestInput
    tool_category: str = "compute"

    def _run(self, ticker: str, view: str = "neutral", target_dte: int = 30) -> str:
        try:
            result = run_strategy_suggest(ticker, view=view, target_dte=target_dte)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": f"{type(exc).__name__}: {exc}"})
        return json.dumps(result, indent=2, default=str)


# ── Factory ───────────────────────────────────────────────────────────────────

def create_options_tools() -> list[BaseTool]:
    """All four options tools as a list, ready to attach to an agent."""
    return [
        VolatilityScanTool(),
        OptionsSurfaceTool(),
        OptionsGreeksTool(),
        StrategySuggestTool(),
    ]
