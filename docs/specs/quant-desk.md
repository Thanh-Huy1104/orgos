# quant-desk — algo backtest + paper-trading platform

Version: 1.0.0
Author: orgos
Status: ready-to-build

## Overview

A single-user quantitative research platform. Users define trading
strategies in Python against a market-data feed, backtest them against
historical bars, and run them live against a paper broker with realistic
order-book simulation. Ships as one `quant` Python package with a CLI and
a FastAPI HTTP surface.

Stack: Python 3.11, FastAPI, Uvicorn, SQLite (stdlib only), pandas,
numpy, websockets, pydantic v2, pytest. Zero third-party market-data
provider at MVP — a deterministic mock feed lets us test everything
end-to-end without hitting any external API.

## Architecture

Ten disjoint top-level packages, each owning one responsibility. Every
inter-package call goes through a stable interface (dataclass or ABC), so
teams can work each package in parallel without stepping on each other.

```
quant/
    market_data/     — OHLCV Bar storage, deterministic mock feed, feed ABC
    strategies/      — Strategy base + registry + built-ins (momentum, mean-rev, ma-cross)
    portfolio/       — Position tracking + PnL calc
    risk/            — Position sizing, stop-loss, max-exposure enforcement
    paper_broker/    — Sim order book with realistic fills + slippage model
    backtest/        — Vectorized replay engine + BacktestResult dataclass
    metrics/         — Sharpe, Sortino, max-drawdown, alpha/beta vs benchmark
    storage/         — SQLite persistence for strategies + backtest results
    api/             — FastAPI: /strategies, /backtest, /portfolio, /orders
    cli/             — `quant backtest`, `quant paper`, `quant report`
```

Data flow at backtest time:

```
mock_feed → backtest.engine → strategy.on_bar → risk.check → paper_broker
                                      ↓                            ↓
                                  portfolio ←──── fills ──────────┘
                                      ↓
                                  metrics → BacktestResult → storage → api/cli
```

## Definition of done for the project as a whole

- `pip install -e .` in the target repo installs the `quant` package.
- `pytest -q` passes with ≥150 tests and ≥70% coverage on non-CLI modules.
- `quant backtest --strategy momentum --symbols BTC --days 30` prints
  Sharpe ratio + final equity.
- `uvicorn quant.api:app` serves the four endpoint families; `curl
  localhost:8000/strategies` returns a JSON array of registered strategy
  names.
- Zero external network calls in any test (the mock feed is deterministic).

---

## Story: Set up project scaffolding + baseline test harness
Files: pyproject.toml, quant/__init__.py, tests/__init__.py, conftest.py, README.md
Type: architecture
Priority: 100
AC:
  - `pip install -e .` succeeds on Python 3.11+
  - `pytest -q` runs cleanly (may report 0 tests initially)
  - `quant` package is importable; `from quant import __version__` returns "0.1.0"
  - conftest.py exposes a `tmp_db` pytest fixture returning a fresh in-memory sqlite3 connection
  - README.md has a one-paragraph description + install + test commands

## Story: OHLCV storage — Bar dataclass + append-only SQLite table
Files: quant/market_data/__init__.py, quant/market_data/bars.py, quant/market_data/schema.sql
Type: architecture
Priority: 95
Component: market_data
AC:
  - `Bar(symbol: str, ts: datetime, o: float, h: float, l: float, c: float, v: float)` with type validation via pydantic
  - `BarStore(conn)` provides `.append(bar)`, `.append_many(bars)`, `.range(symbol, start, end)`
  - Append is idempotent: appending the same (symbol, ts) twice does NOT duplicate rows
  - `.range()` returns bars in ascending ts order; handles gaps in the sequence without error
  - schema.sql is applied on `BarStore(conn).ensure_schema()` — idempotent

## Story: Add tests for OHLCV storage
Files: tests/market_data/__init__.py, tests/market_data/test_bars.py
Type: test
Priority: 94
Depends: 2
AC:
  - 10+ tests cover: append, append_many, upsert idempotency, range query, out-of-range window, gap handling, timezone-aware timestamps
  - Tests use the `tmp_db` fixture from conftest.py (no on-disk file)
  - All tests run in isolation AND together

## Story: Deterministic mock market-data feed
Files: quant/market_data/mock_feed.py
Type: feature
Priority: 92
Component: market_data
Depends: 2
AC:
  - `MockFeed(symbols=['BTC','ETH'], seed=42, start_price=100.0, volatility=0.02)` produces reproducible Bar streams
  - `.stream_bars(n)` yields exactly `n` bars per symbol, ts spaced 1 minute apart starting from a fixed epoch
  - Same seed → identical sequence bit-for-bit
  - Different seeds → different sequences (verified by hashing bar prices)
  - No network calls, no filesystem reads

## Story: Add tests for mock feed
Files: tests/market_data/test_mock_feed.py
Type: test
Priority: 91
Depends: 4
AC:
  - Determinism test: same seed produces same 1000-bar sequence
  - Symbol independence test: 'BTC' and 'ETH' produce different sequences under the same seed
  - Time monotonicity test: bar timestamps strictly increasing per symbol
  - Volatility parameter smoke test: higher volatility → larger stddev of returns

## Story: Feed adapter ABC for pluggable data sources
Files: quant/market_data/feed_abc.py
Type: architecture
Priority: 88
Component: market_data
AC:
  - `class MarketDataFeed(ABC)` with abstract `stream_bars(n_or_forever)` and `subscribe(symbol)`
  - `MockFeed` in mock_feed.py inherits from `MarketDataFeed`
  - Docstring documents the contract: bars must be yielded in ts order, must never repeat a (symbol, ts) pair
  - Type-checks with mypy (no `# type: ignore` required)

## Story: Strategy base class + name-keyed registry
Files: quant/strategies/__init__.py, quant/strategies/base.py, quant/strategies/registry.py
Type: architecture
Priority: 87
Component: strategies
AC:
  - `class Strategy(ABC)` with `on_bar(bar: Bar) -> Optional[Signal]`
  - `Signal(side: Literal['buy','sell','hold'], size: float, reason: str)` dataclass
  - `@register_strategy("name")` decorator adds a class to a global name→class dict
  - `list_strategies()` returns sorted list of registered names
  - Registering two strategies with the same name raises `DuplicateStrategyError` with a clear message

## Story: Momentum strategy — SMA cross
Files: quant/strategies/momentum.py
Type: feature
Priority: 84
Component: strategies
Depends: 7
AC:
  - `MomentumStrategy(window=20)` emits `Signal(side='buy', size=1.0)` when latest price > SMA(window), `Signal(side='sell', size=1.0)` when latest price < SMA(window)
  - Returns `None` for the first `window - 1` bars (not enough history)
  - Registered under the name "momentum"
  - Stateful across calls: maintains a rolling window internally

## Story: Mean-reversion strategy — z-score around mean
Files: quant/strategies/mean_reversion.py
Type: feature
Priority: 83
Component: strategies
Depends: 7
AC:
  - `MeanReversionStrategy(window=20, entry_z=2.0)` emits `Signal('sell')` when z-score > entry_z (price stretched high), `Signal('buy')` when z < -entry_z
  - Returns `Signal('hold')` when abs(z) ≤ entry_z
  - Returns `None` for first `window - 1` bars
  - Registered under the name "mean_reversion"

## Story: MA-crossover strategy — fast/slow SMA
Files: quant/strategies/ma_cross.py
Type: feature
Priority: 82
Component: strategies
Depends: 7
AC:
  - `MACrossStrategy(fast=10, slow=30)` emits `Signal('buy')` when fast SMA crosses above slow SMA, `Signal('sell')` on the reverse cross
  - Only emits on the bar where the cross happens (edge-triggered, not level-triggered)
  - Returns `None` for first `slow - 1` bars
  - Registered under the name "ma_cross"

## Story: Add tests for all three strategies
Files: tests/strategies/__init__.py, tests/strategies/test_strategies.py
Type: test
Priority: 81
Depends: 8, 9, 10
AC:
  - Test each strategy against a hand-crafted 100-bar synthetic sequence with known signals
  - Momentum: verify buy fires when trend flips up, sell on flip down
  - Mean-reversion: verify buy fires at bottom of a synthetic spike-and-revert sequence
  - MA-cross: verify exactly one buy and one sell over a golden-cross / death-cross synthetic
  - All three registrations survive a fresh `list_strategies()` call

## Story: Position tracking — Position + Portfolio dataclasses
Files: quant/portfolio/__init__.py, quant/portfolio/position.py
Type: architecture
Priority: 80
Component: portfolio
AC:
  - `Position(symbol, qty, avg_price)` dataclass with type validation
  - `Portfolio(cash: float)` holds a `dict[str, Position]` of open positions
  - `.apply_fill(fill: Fill)` updates the position (average price weighted, qty accumulated on same-side, closed on opposite-side)
  - Selling more than held raises `InsufficientPositionError`
  - `.market_value(prices: dict[str, float])` returns total portfolio market value

## Story: PnL calculation — realized + unrealized
Files: quant/portfolio/pnl.py
Type: feature
Priority: 79
Component: portfolio
Depends: 12
AC:
  - `realized_pnl(portfolio, trades)` sums all closed-position P&L across trades
  - `unrealized_pnl(portfolio, current_prices)` sums `(current - avg_price) * qty` for open positions
  - `total_pnl` is realized + unrealized
  - Returns 0.0 when portfolio is empty (not NaN)

## Story: Add tests for portfolio + PnL
Files: tests/portfolio/__init__.py, tests/portfolio/test_portfolio.py
Type: test
Priority: 78
Depends: 13
AC:
  - Test buy-then-sell round-trip produces expected realized PnL
  - Test partial-close correctly reduces qty and leaves avg_price unchanged
  - Test unrealized PnL responds correctly to price changes
  - Test InsufficientPositionError fires on oversell
  - Test empty portfolio metrics are all zero, not NaN

## Story: Position sizing — max-exposure enforcement
Files: quant/risk/__init__.py, quant/risk/sizing.py
Type: security
Priority: 76
Component: risk
AC:
  - `RiskChecker(max_position_pct=0.20, max_total_exposure_pct=0.80)` gates orders before they hit the broker
  - `.check_order(order, portfolio, prices)` returns `(True, "")` or `(False, reason)`
  - Reject condition 1: single position would exceed max_position_pct of portfolio value
  - Reject condition 2: total exposure across all positions would exceed max_total_exposure_pct
  - Rejection returns non-empty reason string, never silent

## Story: Stop-loss enforcement
Files: quant/risk/stop_loss.py
Type: security
Priority: 75
Component: risk
Depends: 15
AC:
  - `StopLossPolicy(max_loss_pct=0.05)` returns a forced-sell Signal when open position PnL drops below threshold
  - `.check_positions(portfolio, current_prices)` returns list of forced-sell signals (may be empty)
  - Fires exactly once per breach (not repeatedly for the same position)
  - Configurable per-symbol overrides via constructor

## Story: Add tests for risk module
Files: tests/risk/__init__.py, tests/risk/test_risk.py
Type: test
Priority: 74
Depends: 16
AC:
  - 8+ tests covering sizing + stop-loss
  - Test max-position rejection fires at exactly the boundary (max_position_pct + epsilon)
  - Test max-total-exposure fires when adding a new position would breach
  - Test stop-loss fires when unrealized loss crosses threshold
  - Test per-symbol override respects config

## Story: Order + Fill dataclasses + order book
Files: quant/paper_broker/__init__.py, quant/paper_broker/orders.py
Type: architecture
Priority: 72
Component: paper_broker
AC:
  - `Order(id: str, symbol, side, qty, order_type: Literal['market','limit'], limit_price: Optional[float])` with pydantic validation
  - `Fill(order_id, symbol, side, qty, price, ts, fee)` dataclass
  - `OrderBook` maintains a list of open orders and a list of completed fills
  - New order gets a UUID4 id if not provided

## Story: Paper broker — fill simulator with slippage + fees
Files: quant/paper_broker/broker.py
Type: feature
Priority: 71
Component: paper_broker
Depends: 18
AC:
  - `PaperBroker(slippage_bps=5, fee_bps=10)` fills market orders at (bar.close * (1 ± slippage))
  - Limit orders fill only if the bar's price range crossed the limit price
  - Fee = notional * fee_bps / 10000, deducted from cash
  - `.submit(order, bar)` returns the resulting `Fill` (or `None` if limit not crossed)
  - Every fill has a monotonically increasing ts

## Story: Add tests for paper broker
Files: tests/paper_broker/__init__.py, tests/paper_broker/test_broker.py
Type: test
Priority: 70
Depends: 19
AC:
  - Test market buy fills at close + slippage
  - Test market sell fills at close - slippage
  - Test limit buy fills when bar low ≤ limit price
  - Test limit buy does NOT fill when bar low > limit price
  - Test fees are deducted correctly (5 bps on 10k notional = $5.00)

## Story: Backtest engine — vectorized replay
Files: quant/backtest/__init__.py, quant/backtest/engine.py
Type: architecture
Priority: 68
Component: backtest
Depends: 4, 7, 12, 15, 19
AC:
  - `run_backtest(strategy, feed, initial_cash=10000, risk=None, broker=None) -> BacktestResult`
  - Iterates every bar from feed, calls `strategy.on_bar`, applies risk check, sends to broker, updates portfolio
  - Same seed + same strategy + same initial_cash → identical BacktestResult (deterministic)
  - Completes 10,000 bars in < 500ms on a modern laptop
  - No exceptions propagate — bad strategies get logged and the run continues with `Signal('hold')`

## Story: BacktestResult dataclass + JSON serialization
Files: quant/backtest/result.py
Type: architecture
Priority: 67
Component: backtest
Depends: 21
AC:
  - `BacktestResult` fields: strategy_name, initial_cash, final_cash, trades (list of Fill), equity_curve (list of (ts, equity) pairs), n_bars_processed, started_at, ended_at
  - `.to_json()` returns a JSON-serializable dict (datetimes as ISO strings)
  - `.from_json(dict)` round-trips losslessly
  - `.summary()` returns a one-line human-readable string ("momentum: 1024 bars, final $10,842 (+8.4%), 12 trades")

## Story: Add tests for backtest engine + result
Files: tests/backtest/__init__.py, tests/backtest/test_backtest.py
Type: test
Priority: 66
Depends: 22
AC:
  - Test determinism: same seed twice produces identical BacktestResult
  - Test that a `Strategy` that always returns `hold` produces zero trades and final_cash == initial_cash
  - Test that a `Strategy` that always buys drains cash and accumulates position
  - Test JSON round-trip (to_json → from_json → to_json is stable)
  - Test 10k-bar performance target on a mock feed

## Story: Performance metrics — Sharpe, Sortino, max-drawdown
Files: quant/metrics/__init__.py, quant/metrics/performance.py
Type: feature
Priority: 64
Component: metrics
Depends: 22
AC:
  - `sharpe(returns: list[float], risk_free_rate=0.0, periods_per_year=252)` matches the standard formula to 6 decimals
  - `sortino(returns, risk_free_rate=0.0)` matches its standard formula
  - `max_drawdown(equity_curve: list[float])` returns the worst peak-to-trough drop as a negative float ≤ 0
  - All handle empty or single-element inputs by returning NaN (never crash)
  - Include a `from_backtest_result(result: BacktestResult)` convenience returning a dict of all three

## Story: Risk-adjusted metrics — alpha, beta vs benchmark
Files: quant/metrics/regression.py
Type: feature
Priority: 63
Component: metrics
Depends: 22
AC:
  - `alpha_beta(strategy_returns, benchmark_returns)` returns `(alpha: float, beta: float)`
  - Beta matches numpy.cov / numpy.var to 4 decimals
  - Alpha is intercept from OLS regression of strategy on benchmark
  - Handles different lengths by taking the shorter tail
  - Returns `(NaN, NaN)` for < 5 shared data points

## Story: Add tests for metrics
Files: tests/metrics/__init__.py, tests/metrics/test_metrics.py
Type: test
Priority: 62
Depends: 24, 25
AC:
  - 12+ tests covering all four metric functions
  - Sharpe of constant returns (all zeros) is NaN
  - Sharpe of known synthetic sequence matches hand-calculated value to 4 decimals
  - MDD of monotonic upward sequence is 0
  - Alpha=0, Beta=1 for a strategy that IS the benchmark
  - Beta = 2.0 for a strategy with exactly 2x the benchmark returns

## Story: SQLite persistence — strategies + backtest results
Files: quant/storage/__init__.py, quant/storage/db.py, quant/storage/schema.sql
Type: architecture
Priority: 60
Component: storage
AC:
  - `Storage(path: Path)` opens or creates a SQLite file, applies schema idempotently
  - `.save_backtest_result(result: BacktestResult) -> int` inserts and returns the row id
  - `.get_backtest_result(id: int) -> BacktestResult` round-trips
  - `.list_backtest_results(limit=50, strategy: Optional[str]=None)` returns most-recent-first
  - `.save_strategy_config(name, config: dict) -> int` persists user-defined strategy parameter sets

## Story: Add tests for storage
Files: tests/storage/__init__.py, tests/storage/test_storage.py
Type: test
Priority: 59
Depends: 27
AC:
  - 8+ tests covering save/get/list of backtest results and strategy configs
  - Test that saving a result then retrieving it produces an equal BacktestResult
  - Test list_backtest_results ordering (most recent first)
  - Test strategy filter on list
  - Test that opening an existing DB file works without re-applying schema

## Story: FastAPI app skeleton + /health + CORS
Files: quant/api/__init__.py, quant/api/app.py
Type: architecture
Priority: 55
Component: api
AC:
  - `from quant.api import app` returns a FastAPI instance
  - GET /health returns `{"status": "ok", "version": "0.1.0"}` with 200
  - CORS middleware allows all origins in DEBUG mode, none in production
  - App startup event opens a shared Storage instance from `QUANT_DB_PATH` env var (default `./quant.db`)
  - `uvicorn quant.api:app` starts the server without error

## Story: /strategies API — list + configure + validate
Files: quant/api/strategies_routes.py
Type: feature
Priority: 54
Component: api
Depends: 7, 27, 29
AC:
  - GET /strategies returns list of {name, params_schema} for every registered strategy
  - POST /strategies/configs {name, params} validates params against the strategy's constructor, persists via Storage
  - GET /strategies/configs returns saved configs, most recent first
  - 400 with a descriptive error on invalid params (e.g. window=0)
  - 404 on unknown strategy name

## Story: /backtest API — submit + status + list
Files: quant/api/backtest_routes.py
Type: feature
Priority: 53
Component: api
Depends: 21, 27, 29
AC:
  - POST /backtest {strategy, params, symbols, days} returns 202 + {job_id}
  - Backtest runs in a background task; result persisted on completion
  - GET /backtest/{job_id} returns {status: 'running'|'done'|'failed', result?, error?}
  - GET /backtest?limit=10 lists most recent completed backtests with summary
  - 400 on unknown strategy name
  - Job ID is a UUID4 hex string

## Story: /portfolio API — position + PnL
Files: quant/api/portfolio_routes.py
Type: feature
Priority: 52
Component: api
Depends: 12, 29
AC:
  - GET /portfolio returns current positions (list of {symbol, qty, avg_price, unrealized_pnl})
  - GET /portfolio/pnl returns {realized, unrealized, total} for the current paper session
  - Uses a module-level `current_paper_session` reference initialized on `quant paper` startup
  - Returns empty list + zero PnL when no session active (not 404)

## Story: Add tests for the API surface
Files: tests/api/__init__.py, tests/api/test_api.py
Type: test
Priority: 51
Depends: 30, 31, 32
AC:
  - 10+ tests using FastAPI TestClient (no live uvicorn)
  - Test /health returns expected shape
  - Test /strategies returns all three built-in strategies
  - Test full backtest lifecycle: POST → poll GET until done → verify result shape
  - Test invalid strategy name returns 400 with error field
  - Test /portfolio returns empty when no session

## Story: CLI — `quant backtest` command
Files: quant/cli/__init__.py, quant/cli/main.py, quant/cli/backtest_cmd.py
Type: feature
Priority: 45
Component: cli
Depends: 21
AC:
  - `quant backtest --strategy momentum --symbols BTC --days 30` runs and prints Sharpe + final equity
  - `--output json` writes the full BacktestResult as JSON to stdout
  - `--output pretty` (default) prints a compact human-readable summary
  - `--seed N` controls the mock feed determinism
  - Exit code 0 on success; non-zero + error message on unknown strategy

## Story: CLI — `quant paper` live paper-trading command
Files: quant/cli/paper_cmd.py
Type: feature
Priority: 44
Component: cli
Depends: 19
AC:
  - `quant paper --strategy momentum --symbols BTC` starts a live paper session against the mock feed
  - Ticks once per second (mock feed cadence), prints each fill on its own line
  - SIGINT (Ctrl-C) stops cleanly and prints a session-summary line (n_trades, final PnL)
  - `--duration-seconds N` for automated stops
  - Never writes to disk during a session (paper only)

## Story: CLI — `quant report` command
Files: quant/cli/report_cmd.py
Type: feature
Priority: 43
Component: cli
Depends: 27, 24
AC:
  - `quant report --backtest-id N` loads a saved backtest and prints Sharpe/Sortino/MDD in a table
  - `quant report --list` shows the 20 most-recent saved backtests with strategy name + summary
  - `quant report --strategy momentum` filters the list by strategy
  - Uses only stdlib formatting (no rich/tabulate dependency)

## Story: End-to-end integration test — full stack smoke
Files: tests/e2e/__init__.py, tests/e2e/test_end_to_end.py
Type: test
Priority: 35
Depends: 34, 35, 36
AC:
  - Test that the CLI (`quant backtest`) produces the same numeric result as calling `run_backtest()` directly
  - Test that a backtest submitted through the API produces the same numeric result as the CLI
  - Test that CLI report of a saved API-submitted backtest shows the correct summary
  - All e2e tests complete in < 15 seconds total
  - No network I/O, no external processes (uses `subprocess.run([sys.executable, "-m", "quant.cli", ...])` for CLI tests)
