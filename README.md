# orgos

**A framework for AI agents you can actually deploy — governed, auditable, and
self-correcting** — built on CrewAI, model-agnostic via litellm.

Most agent stacks make it easy to *run* an agent. orgos makes agents **safe to put
in front of stakeholders**: capability is separated from authority, every action is
logged, outputs are **graded against a rubric rather than trusted**, and anything
consequential passes a human gate. Its worked example is a **quant research desk**
that discovers and rigorously back-tests trading strategies — and honestly reports
when something *doesn't* work.

> Architecture decisions live in [`DESIGN.md`](./DESIGN.md). A demo walkthrough lives
> in [`DEMO.md`](./DEMO.md).

---

## What's in the box

**Governance core (`orgos/spawn/`)**
- **Four permission tiers** — `worker` / `validator` / `publisher` / `orchestrator`.
  A worker can compute but can't publish or act externally; that needs a validator
  and a human approval, enforced in code (`GatedToolBase`), never in the model's
  judgement.
- **Typed handoffs** — every result is a validated `HandoffEnvelope`; bad output
  becomes a `failed` envelope, never silent garbage.
- **Append-only audit + research trail** — `_audit_logs/<run_id>.jsonl` records every
  tool call (inputs *and* outputs); `read_trail()` reconstructs what an agent did.
- **Budgets & caps** — per-role token/iteration/time limits and a whole-run ceiling.

**Rubric loop (`orgos/spawn/rubric.py`)**
- State "good enough" as a `Rubric`; `spawn_until` / `chain_until` run → grade →
  re-aim → **fail closed**. `optimize` mode keeps the best-scoring attempt. Graders
  are registered by name so a rubric stays declarative.

**Self-improvement (`orgos/evolve.py`)** — the org analyses its own run history and
**proposes** changes to its own structure (add a role, request a tool, adjust a
budget). It changes nothing autonomously — **you approve every change**, and applies
are comment-preserving with backups.

**Quant research desk (`orgos/quant/`, `orgos/subagents/`)** — the proof it works on
real, gradeable work:
- Deterministic **cointegration** engine + scanner (Engle-Granger, half-life, Hurst,
  sub-period durability, factor independence, Benjamini-Hochberg FDR).
- **Out-of-sample, after-cost P&L backtest** with walk-forward folds (`backtest.py`) —
  selection hinges on *did this trade profitably out-of-sample*, not on a p-value.
- **Funding-rate carry** research (`funding.py`) and **trend-following** backtests
  (`trend.py`).
- A **journal** (`journal.py`) — cross-run memory so the desk compounds.
- The **strategist** — a research → scan → synthesise agent chain run under the
  rubric loop, recommend-only.

**Dashboard (`dashboard/`, Next.js)** — Desk · Strategist · **Journal** (results +
rubric strength + every attempt) · **Logs** (the research trail) · Org · Proposals ·
Calendar · Policies.

---

## Install & run

```bash
pip install -r requirements.txt        # Python 3.10+ (CrewAI, pydantic, ruamel.yaml, …)

# Set any provider key (litellm under the hood):
export OPENAI_API_KEY=sk-...            # or ANTHROPIC_API_KEY / GEMINI_API_KEY / DEEPSEEK_API_KEY

# Full test suite (offline, no API keys needed):
python -m pytest -q                     # 337 passing

# REST API (reads config/org.yaml):
python -m uvicorn orgos.api:app --host 0.0.0.0 --port 8420

# Dashboard:
cd dashboard && npm install && npm run dev   # http://localhost:3000
```

Config lives in `config/org.yaml` (the org "constitution") and
`config/policy-bank.yaml` (compliance rules).

---

## The primitive

```python
from orgos import RoleSpec, TaskBrief, PermissionTier, spawn

role = RoleSpec(
    name="researcher",
    description="Research a topic and write a brief.",
    tier=PermissionTier.WORKER,
    system_prompt="You are a careful research assistant.",
    max_iter=15,
)
result = spawn(role, TaskBrief(objective="Summarise X into a one-page brief"))
print(result.envelope.status, result.envelope.summary)
```

Run it under a rubric so it grades itself and retries until it passes (or fails closed):

```python
from orgos import Rubric, spawn_until

result = spawn_until(role, brief, Rubric(grader="completed", max_attempts=3))
```

`spawn()` gives you, on every run: a structured brief (no free-form delegation),
tier-enforced guardrails, the audit trail, the human gate on publish-class actions,
hard caps, and a validated `HandoffEnvelope`.

---

## Layout

| Concern | Where |
|---|---|
| Contracts (RoleSpec, TaskBrief, HandoffEnvelope, tiers) | `orgos/spawn/contracts.py` |
| Spawn engine (`spawn`, `spawn_chain`, `SpawnResult`) | `orgos/spawn/engine.py` |
| Rubric loop (`Rubric`, `spawn_until`, `chain_until`, graders) | `orgos/spawn/rubric.py` |
| Tool framework + audit/research trail | `orgos/spawn/toolbase.py`, `orgos/spawn/audit.py` |
| Concrete tools (scanners, research sources, bash) | `orgos/tools/` |
| MCP servers | `orgos/mcps/` |
| Pre-built agents (the strategist) | `orgos/subagents/` |
| Quant desk (cointegration, backtest, funding, trend, journal) | `orgos/quant/` |
| Org model, self-improvement, REST API | `orgos/departments.py`, `orgos/evolve.py`, `orgos/api.py` |
| Dashboard | `dashboard/` |
| Constitution + policy bank | `config/` |

---

## Honest scope

The desk **researches and recommends** — it does not place trades. The strategy
search in this repo found that easy market edges are largely arbitraged away; the
desk's value is producing *rigorous, out-of-sample, honestly-graded* analysis (and
saying "this doesn't work" when it doesn't) — exactly the reliability the governance
layer is built to guarantee.
