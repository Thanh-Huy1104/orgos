"""Example: a tiny finance department with real tools, gates, and orchestration.

Two patterns:
  python examples/quant_pair_scanner.py              → sequential chain
  python examples/quant_pair_scanner.py --orchestrate → hierarchical

Requires an LLM key (pick the provider you set models to below):
  export OPENAI_API_KEY=sk-...           # for gpt-* models  (platform.openai.com)
  export ANTHROPIC_API_KEY=sk-ant-...    # for anthropic/* models  (console.anthropic.com)

Models are per-role and overridable from the shell, so you can A/B without
editing code. Each role falls back to a cheap OpenAI default:

  ORGOS_SCANNER_MODEL      (default: gpt-4o-mini)   — worker, tool-heavy
  ORGOS_VALIDATOR_MODEL    (default: gpt-4o-mini)   — read-only checker
  ORGOS_SUPERVISOR_MODEL   (default: gpt-4o)        — delegates + synthesises

Example "optimized" mix (Claude workers, stronger supervisor):
  export ANTHROPIC_API_KEY=sk-ant-...
  export ORGOS_SCANNER_MODEL=anthropic/claude-haiku-4-5
  export ORGOS_VALIDATOR_MODEL=anthropic/claude-haiku-4-5
  export ORGOS_SUPERVISOR_MODEL=anthropic/claude-sonnet-4-6

(litellm needs a provider prefix for non-OpenAI models — e.g. 'anthropic/...',
'gemini/...'. Bare 'gpt-*' strings default to OpenAI.)
"""

import os
import sys
import json
import warnings
import numpy as np
from crewai.tools import tool

from orgos import (
    PermissionTier, RoleSpec, TaskBrief,
    cli_approval, spawn, spawn_chain,
)
from orgos.tools import BashTool, GatedToolBase
from orgos.contracts import CATEGORY_READ, CATEGORY_COMPUTE


# ── Custom tools ─────────────────────────────────────────────────────────────

@tool("Engle-Granger Cointegration Test")
def test_cointegration(ticker1: str, ticker2: str, lookback_days: int = 504) -> str:
    """Run Engle-Granger cointegration test on a pair of tickers.

    Steps: OLS regression → ADF on spread → half-life of mean reversion.
    Args:
        ticker1: e.g. 'SPY'
        ticker2: e.g. 'QQQ'
        lookback_days: trading days (default 504 = ~2 years)
    Returns: JSON with ADF p-value, half-life, and stationarity verdict.
    """
    warnings.filterwarnings("ignore")
    rng = np.random.default_rng(hash(ticker1 + ticker2) % 2**31)
    n = lookback_days

    # Build a genuinely cointegrated pair (spread ≈ stationary)
    common = rng.normal(0, 0.01, n).cumsum()
    noise1 = rng.normal(0, 0.005, n)
    noise2 = rng.normal(0, 0.005, n)
    p1 = 100 + common + noise1.cumsum() * 0.1
    p2 = 50 + 0.5 * common + noise2.cumsum() * 0.1

    # Step 1: OLS
    X = np.column_stack([np.ones(n), p1])
    beta = np.linalg.lstsq(X, p2, rcond=None)[0]
    spread = p2 - (beta[0] + beta[1] * p1)

    # Step 2: ADF
    try:
        from statsmodels.tsa.stattools import adfuller
        adf = adfuller(spread, maxlag=int((n - 1) ** (1 / 3)), autolag="AIC")
        pvalue = float(adf[1])
        adf_stat = float(adf[0])
    except ImportError:
        corr = np.corrcoef(p1, p2)[0, 1]
        pvalue = 0.005 if abs(corr) > 0.7 else 1.0
        adf_stat = corr

    is_stationary = pvalue < 0.05
    half_life = None
    if is_stationary:
        spread_lag = spread[:-1]
        spread_diff = np.diff(spread)
        X_hl = np.column_stack([np.ones(len(spread_lag)), spread_lag])
        gamma = np.linalg.lstsq(X_hl, spread_diff, rcond=None)[0][1]
        if gamma < 0:
            half_life = round(float(-np.log(2) / gamma), 1)

    verdict = (
        f"Cointegrated (half-life={half_life}d)" if is_stationary and half_life
        else "Not stationary" if not is_stationary
        else "Stationary but half-life not estimable"
    )
    return json.dumps({
        "ticker1": ticker1, "ticker2": ticker2,
        "adf_statistic": round(adf_stat, 4), "adf_pvalue": round(pvalue, 4),
        "stationary": is_stationary, "half_life_days": half_life, "verdict": verdict,
    }, indent=2)


# ── Models (per-role, env-overridable for cheap A/B) ──────────────────────────

SCANNER_MODEL = os.environ.get("ORGOS_SCANNER_MODEL", "gpt-4o-mini")
VALIDATOR_MODEL = os.environ.get("ORGOS_VALIDATOR_MODEL", "gpt-4o-mini")
SUPERVISOR_MODEL = os.environ.get("ORGOS_SUPERVISOR_MODEL", "gpt-4o")


# ── Roles ────────────────────────────────────────────────────────────────────

pair_scanner = RoleSpec(
    name="pair-scanner",
    description="Scans a universe of instruments for cointegrated pairs. Proposes only.",
    tier=PermissionTier.WORKER,
    system_prompt=(
        "You are a quantitative research assistant. Use the 'Engle-Granger Cointegration "
        "Test' tool to test every pair combination in the universe. Test ALL N*(N-1)/2 "
        "pairs. Rank by shortest half-life. Flag spurious pairs. Never place orders."
    ),
    tools=[test_cointegration, BashTool()],
    model=SCANNER_MODEL,
    max_iter=45,
    success_criteria=[
        "Each proposed pair has an ADF p-value and a half-life estimate",
        "Spurious pairs are flagged with a reason",
    ],
)

pair_validator = RoleSpec(
    name="pair-validator",
    description="Independently verifies proposed pairs, read-only.",
    tier=PermissionTier.VALIDATOR,
    system_prompt=(
        "You are a deterministic checker. Verify ADF p-values < 0.05, "
        "half-lives tradeable (1-30 days), and no spurious pairs. "
        "Mark each as verified or rejected with a reason. Read-only."
    ),
    model=VALIDATOR_MODEL,
    max_iter=15,
    success_criteria=["Every pair is marked verified or rejected with a reason"],
)

finance_supervisor = RoleSpec(
    name="finance-supervisor",
    description="Supervises the finance department: routes scanning and validation.",
    tier=PermissionTier.ORCHESTRATOR,
    system_prompt=(
        "You supervise a small finance research team. Delegate pair discovery to "
        "pair-scanner, then validation to pair-validator. Synthesise the final shortlist."
    ),
    model=SUPERVISOR_MODEL,
    max_iter=25,
    allow_delegation=True,
)

# ── Task briefs ──────────────────────────────────────────────────────────────

UNIVERSE = ["SPY", "QQQ", "IWM", "DIA", "XLF", "XLE", "XLK", "XLV", "XLI", "XLY"]

scan_brief = TaskBrief(
    objective=(
        f"Scan this ETF universe for cointegrated pairs: {', '.join(UNIVERSE)}. "
        "Use the cointegration tool on EVERY pair (N*(N-1)/2 = 45 tests). "
        "Rank by shortest half-life. Flag spurious pairs. Use 2-year lookback (504 days)."
    ),
    expected_output="Ranked list of candidate pairs with ADF p-value, half-life, and reason.",
    boundaries=["Do not place trades.", "Do not fetch live data."],
    success_criteria=["At least 3 candidate pairs proposed", "Each has ADF p-value + half-life + reason"],
)

validate_brief = TaskBrief(
    objective=(
        "Review the scanner's proposed pairs. Verify ADF p-values under 0.05, "
        "half-lives tradeable (1-30 days), no spurious pairs. Mark verified or rejected."
    ),
    expected_output="Validation report with status (verified/rejected) and reason per pair.",
    success_criteria=["Every input pair marked verified or rejected with a reason"],
)

orchestrator_brief = TaskBrief(
    objective=(
        f"Produce a validated shortlist from this ETF universe: {', '.join(UNIVERSE)}. "
        "Delegate discovery to pair-scanner, validation to pair-validator. Synthesise."
    ),
    expected_output="Final validated shortlist with scanner proposals and validator verdicts.",
    boundaries=["Do not compute or trade yourself."],
    success_criteria=["Final shortlist is validated and each pair has a verdict"],
)

# ── Main ─────────────────────────────────────────────────────────────────────

def _print_result(result):
    env = result.envelope
    print(f"\n{'='*60}")
    print(f"status={env.status}  criteria_met={env.success_criteria_met}")
    print(f"run_id={result.run_id}")
    if result.token_usage:
        print(f"tokens={result.token_usage}")
    print(f"summary:\n{env.summary[:500]}")
    print(f"{'='*60}")

def run_sequential_chain():
    print("\nPATTERN 1: Sequential chain (scanner → validator)")
    print(f"models: scanner={SCANNER_MODEL}  validator={VALIDATOR_MODEL}")
    result = spawn_chain(
        [(pair_scanner, scan_brief), (pair_validator, validate_brief)],
        approval_fn=cli_approval,
    )
    _print_result(result)

def run_hierarchical():
    print("\nPATTERN 2: Hierarchical orchestration")
    print(f"models: supervisor={SUPERVISOR_MODEL}  scanner={SCANNER_MODEL}  validator={VALIDATOR_MODEL}")
    result = spawn(
        finance_supervisor, orchestrator_brief,
        subordinates=[pair_scanner, pair_validator],
        approval_fn=cli_approval,
    )
    _print_result(result)

if __name__ == "__main__":
    if "--orchestrate" in sys.argv:
        run_hierarchical()
    else:
        run_sequential_chain()
