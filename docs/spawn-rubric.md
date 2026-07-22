# Spawn + Rubric: architecture & runtime

> **Note (2026-07-22):** the spawn/governance layer described here was
> extracted into the standalone [agentkit](https://github.com/Thanh-Huy1104/agentkit)
> library (private) and orgos now imports it (`agentkit.governance`).
> The architecture below still describes how it works; file paths that
> read `orgos/spawn/...` now live in `agentkit/src/agentkit/governance/...`.

## The approach

```
                    ┌──────────────────────────────┐
                    │          RUBRIC               │
                    │  "good enough" = declarative  │
                    │   criteria + named grader     │
                    └──────────────┬───────────────┘
                                   │
                          ┌────────▼────────┐
                          │   GRADE OUTPUT   │
                          │  (deterministic  │
                          │   or separate    │
                          │   agent — never  │
                          │    self-graded)  │
                          └───┬─────────┬────┘
                              │         │
                           PASS       FAIL
                              │         │
                              │    ┌────▼────────────┐
                              │    │ FEED FAILURES    │
                              │    │ BACK INTO BRIEF  │
                              │    │ (re-aim, re-run) │
                              │    └────────┬─────────┘
                              │             │
                              │    ┌────────▼─────────┐
                              │    │ MAX ATTEMPTS?     │
                              │    │  YES → fail closed│
                              │    │  NO  → retry      │
                              │    └───────────────────┘
                              │
                    ┌─────────▼──────────┐
                    │   DONE: return      │
                    │   HandoffEnvelope   │
                    │   (or best attempt  │
                    │    if optimize=True)│
                    └────────────────────┘


             ┌─────────────── SPAWN LAYER ───────────────┐
             │                                            │
             │  RoleSpec ──► tier enforcement ──► tools   │
             │  TaskBrief ──► boundaries + budget ──► task│
             │                                            │
             │  ┌─────────────────────────────────────┐  │
             │  │  PERMISSION TIERS (enforced in code) │  │
             │  │  ─────────────────────────────────── │  │
             │  │  worker     compute only, no publish │  │
             │  │  validator  review + gate            │  │
             │  │  publisher  external actions (gated) │  │
             │  │  orchestrator manage subordinates    │  │
             │  └─────────────────────────────────────┘  │
             │                                            │
             │  ┌─────────────────────────────────────┐  │
             │  │  AUDIT TRAIL (every run)             │  │
             │  │  ─────────────────────────────────── │  │
             │  │  _audit_logs/<run_id>.jsonl          │  │
             │  │  records every tool call with I/O    │  │
             │  └─────────────────────────────────────┘  │
             └───────────────────────────────────────────┘
```

---

## Runtime: the quant strategist pipeline

```
   ┌───────────────────┐
   │  User objective   │  e.g. "Find cointegrated pairs in financials"
   └────────┬──────────┘
            │
            ▼
   ┌────────────────────────────────────────────────────────────┐
   │  STEP 1 — RESEARCHER  (Worker tier, max_iter=12)           │
   │                                                            │
   │  Tools: news_catalysts · search_arxiv · index_constituents │
   │                                                            │
   │  ┌─ news_catalysts("M&A financial sector")                 │
   │  ├─ search_arxiv("cointegration banking stocks")           │
   │  ├─ index_constituents("financials") → real tickers        │
   │  └─ Output: "Tickers: BAC WFC JPM ... Thesis: post-merger  │
   │            convergence in regional banks"                  │
   │                                                            │
   │  Audit: logged ← _audit_logs/chain-3f8a1b.jsonl           │
   └──────────────────────┬─────────────────────────────────────┘
                          │ context chaining
                          ▼
   ┌────────────────────────────────────────────────────────────┐
   │  STEP 2 — SCANNER  (Worker tier, max_iter=12)              │
   │                                                            │
   │  Tools: scan_cointegrated_pairs · scan_crypto_pairs        │
   │                                                            │
   │  ┌─ scan_cointegrated_pairs("BAC WFC JPM ...")             │
   │  │   → 56 pairs tested (all combos)                        │
   │  │   → Benjamini-Hochberg FDR correction                   │
   │  │   → half-life check (5 < HL < 126 days)                 │
   │  │   → sub-period durability                              │
   │  │   → factor independence (r² < 0.30)                    │
   │  │   → SURVIVORS: WFC/USB (adf=0.008, HL=22d, hurst=0.31) │
   │  ├─ scan_cointegrated_pairs("JPM GS MS ...")               │
   │  │   → SURVIVORS: 0                                        │
   │  └─ Output: "1 pair survived: WFC/USB with full stats"     │
   │                                                            │
   │  Audit: logged                                             │
   └──────────────────────┬─────────────────────────────────────┘
                          │ context chaining
                          ▼
   ┌────────────────────────────────────────────────────────────┐
   │  STEP 3 — SYNTH  (Worker tier, no tools, just writes)      │
   │                                                            │
   │  Compiles researcher evidence + scanner results             │
   │  into a validated HandoffEnvelope:                          │
   │                                                            │
   │  {                                                         │
   │    "status": "completed",                                  │
   │    "role": "quant-synth",                                  │
   │    "success_criteria_met": true,                           │
   │    "summary": "WFC/USB: OOS Sharpe=1.21, return=+8.4%,     │
   │                n_trades=17, max_dd=-2.1%. Thesis: ...",   │
   │    "notes": "LESSON: large-cap regionals narrow bands..."  │
   │  }                                                         │
   │                                                            │
   │  Validation: envelope is parsed, status checked,           │
   │  success_criteria_met verified. Malformed? → needs_revision│
   └──────────────────────┬─────────────────────────────────────┘
                          │
                          ▼
   ┌────────────────────────────────────────────────────────────┐
   │  RUBRIC GRADER: "tradeable_pnl"  (deterministic, $0 cost)  │
   │                                                            │
   │  Reads scan trail (not synth prose — actual numbers):      │
   │                                                            │
   │    → Any pair with positive OOS Sharpe after costs?        │
   │                                                            │
   │  ┌─ YES (OOS Sharpe=1.21 > 0)                              │
   │  │   optimize=True → keep running to beat own best?        │
   │  │     max_attempts=2 exhausted → DONE                     │
   │  │                                                         │
   │  ┌─ NO (all OOS Sharpe ≤ 0)                                │
   │  │   Push failure back to researcher:                      │
   │  │   "Attempt 1 found zero tradeable pairs. Try DIFFERENT  │
   │  │    sectors/universes — do not re-scan the same names."  │
   │  │   → re-run entire chain (researcher re-aims)            │
   │  │                                                         │
   │  ┌─ max_attempts exhausted, still no pass                  │
   │  │   → FAIL CLOSED: envelope.status = "needs_revision"     │
   │  │   → "rubric 'tradeable_pnl' not met after 2 attempts"   │
   └──────────────────────┬─────────────────────────────────────┘
                          │
                          ▼
   ┌────────────────────────────────────────────────────────────┐
   │  RESULT  →  SpawnResult{}                                   │
   │                                                            │
   │  result.envelope.status        = "completed"               │
   │  result.attempts               = 2                         │
   │  result.grade.score            = 0.92                      │
   │  result.attempt_run_ids        = [chain-a1b2, chain-c3d4]  │
   │                                                            │
   │  Journal: recorded for cross-run memory                    │
   └────────────────────────────────────────────────────────────┘
```

---

## Permission tier enforcement (at load time, not runtime)

```
   RoleSpec(tier=WORKER, tools=[email_tool, scanner])
                        │
                        ▼
              ┌─────────────────────┐
              │  _enforce_tier()    │
              │                     │
              │  email_tool         │
              │   category=publish  │
              │   tier=WORKER       │
              │   can_publish=False │
              │   → RAISE           │
              │   _TierViolation    │
              │                     │
              │  scanner            │
              │   category=read     │
              │   → APPROVED        │
              └─────────────────────┘
```

A worker literally cannot be given a publish-class tool — the code raises before any tokens are spent. Same for validators: they can review but can't publish. A publisher's tools must be wrapped in `GatedToolBase` and require a human `approval_fn` or the system refuses to spawn.

---

## Key guarantees

| Guarantee | How |
|---|---|
| Worker can't publish | `_enforce_tier` rejects publish-category tools |
| Publisher needs human gate | `_wire_gates` — no `approval_fn` → `_TierViolation` |
| Bad output ≠ accepted | `_read_envelope`: non-JSON / empty / missing criteria → `needs_revision` or `failed` |
| Worker never grades itself | Rubric grader is a separate function or agent |
| Max attempts = fail closed | `_exhausted` overrides envelope to `needs_revision` |
| Everything is logged | `_audit_logs/<run_id>.jsonl` + `make_audit_callback` |
| Optimize keeps best score | `optimize=True` runs full budget, returns max score |
