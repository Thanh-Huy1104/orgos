# Strategy findings — what we learned hunting for an edge

A research log of the strategies this desk tested, the **real results**, and the
honest conclusions. Everything below is from deterministic backtests on real market
data (equities via yfinance, crypto via ccxt), out-of-sample and after costs where
noted. The headline: **easy market edges are arbitraged away; the value is rigorous,
honest research — and the few things that "work" are modest risk premia, not jackpots.**

---

## 1. Cointegration / statistical-arbitrage pairs trading

**Idea:** find two assets whose spread is mean-reverting (cointegrated), trade the
spread back to its mean. The desk's original premise.

**What we ran:** dozens of universes through the Engle-Granger + durability pipeline
(ADF, half-life, Hurst, sub-period stability, factor independence, BH-FDR) — banks,
utilities, cross-sector "supply-chain" theses, REIT subsectors, midstream, gold
miners, timber, dual-class shares, ETFs — each then **back-tested out-of-sample after
costs**.

**Results:**
- **Durable cointegration is rare.** Most "obvious peer" universes (self-storage,
  cell-tower, data-center, midstream, gold miners, timber, banks) returned **0
  survivors**. Across a full analyst slate, **~1 tradeable pair total**.
- The one robust survivor — **AEE/NI** (Ameren / NiSource utilities): ADF p≈0.0002,
  half-life ~8d, factor R²≈0.04, stable across sub-periods. Real, but well-known and
  low-capacity. It surfaced from a **brute-force full-sector sweep, not a clever
  thesis** — every cross-sector / supply-chain hypothesis failed.
- **The decisive lesson — significance ≠ profitability.** The *tightest* cointegration
  in the whole study, **IWM/VTWO** (two Russell-2000 ETFs, ADF p = 0.0000, stable),
  **LOST money out-of-sample: OOS Sharpe −4.08, 0/4 folds profitable, −7.5%.** Its
  spread vol (~0.06%) is *smaller than trading costs*. Tight tracking pairs (ETFs,
  dual-class) either revert faster than a daily bar (IVV/VOO half-life 0.8d) or have
  spreads too small to beat costs — untradeable despite perfect statistics.

**Verdict:** thin-to-no edge for a small participant; the space is efficient. This is
why we changed selection to hinge on **out-of-sample after-cost P&L, not p-values.**

---

## 2. Crypto funding-rate carry (basis / cash-and-carry)

**Idea:** perps pay a funding rate; hold **long spot + short perp** (delta-neutral)
and collect it. A structural, mechanical edge — not a statistical hope.

**What we ran:** live funding scan across ~20 perps + a 1-year delta-neutral carry
backtest (after costs, always-on vs regime-filtered).

**Results:**
- **Real and positive, but modest:** ~**3–5% APR** delta-neutral on consistent payers
  (BTC 3.4%, LINK 5.0%, SUI 3.9%); SOL *lost* (−0.9%, negative funding).
- **Currently thin:** live BTC funding ≈ **0.2% APR**; about half the basket had
  *negative* funding (market not euphoric). The fat 2021-era yields are gone.
- **The high Sharpe is a trap:** the carry stream shows Sharpe ~20–29, but that's
  *carry only* — it ignores the real risks (exchange/custody blowup, liquidation,
  crash funding spikes). Real-trade risk is a fat left tail the funding data can't see.
- Regime-timing **hurt** consistent payers (you lose more sitting out dips than you save).

**Verdict:** real but modest and regime-gated — a "wait for the fat pitch" carry.
Needs a crypto execution + custody layer (not Interactive Brokers), and you eat
exchange risk.

---

## 3. Trend-following / time-series momentum

**Idea:** a paid risk premium — ride what's moving, cut losers. Long if above the
~100-day trend, else flat. The most empirically robust documented strategy.

**What we ran:** MA-100 / TSMOM backtests on crypto (full cycle 2020–2026) and a
diversified IB-tradeable ETF basket (2007–2026), vs buy-and-hold.

**Results:**

| Market | Strategy | CAGR | Sharpe | Max DD |
|---|---|---|---|---|
| **BTC** (full cycle) | buy & hold | 33.1% | 0.78 | −76.6% |
| **BTC** | **MA-100 trend** | **37.7%** | **1.00** | **−38.5%** |
| ETFs (10, '07–'26) | SPY buy & hold | 11.0% | 0.63 | −55% |
| ETFs | **diversified buy & hold** | 8.6% | **0.67** | −39% |
| ETFs | diversified trend (MA-100) | 4.2% | 0.58 | **−14.5%** |

- **Crypto trend WORKED** — beat buy-and-hold on return *and* Sharpe with half the
  drawdown. The one clear *active* edge found, because crypto actually trends.
- **ETF trend did NOT beat buy-and-hold** — it was a *drawdown reducer* (−14.5% vs
  −55%), not a return enhancer. Trend had a weak decade in mature, choppy markets.
- **The quiet winner: diversified buy-and-hold** (Sharpe 0.67) beat both SPY-alone and
  the clever trend version. *Boring beat clever.*

**Verdict:** trend is a genuine risk premium, but **regime/market-dependent** — it
shines where things trend (crypto) and merely de-risks where they don't (ETFs). And
its "works" still means a −38% drawdown and ~90% of the time underwater.

---

## Meta-lessons

1. **Arbitrage is gone.** Every "free money" idea (cointegration, funding spread) came
   up thin — exactly as efficient-market logic predicts. If it were easy, it'd already
   be arbed away.
2. **What works is harvesting a risk premium with discipline through drawdowns**, not
   cleverness. The premium is the *pay for the discomfort* most people won't bear.
3. **Significance ≠ money.** Select on out-of-sample, after-cost P&L — never a p-value.
   (IWM/VTWO: perfect cointegration, lost money.)
4. **Backtest honestly:** out-of-sample, after costs, **multiple walk-forward folds**,
   and always show **drawdowns and trade counts** — a 100% win rate over 4 trades is
   noise, not skill.
5. **Breadth + rigor beat clever theses.** The one real pair came from a brute-force
   sweep; every elegant economic story failed.
6. **The realistic personal path:** a diversified **buy-and-hold core** + a small
   **crypto-trend sleeve** (the only active edge that held up), sized to survive its
   drawdowns. Not a product — personal capital.
7. **The real asset is the system, not the alpha.** The durable value built here is a
   *governed, auditable, honestly-graded* research-and-automation framework — worth
   far more (consulting / vertical automation) than the thin market edges it proved
   don't exist. The desk's job, done well, is telling you the truth — including
   "this doesn't work."
