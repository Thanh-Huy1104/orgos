# orgos — handoff to next session

> **Read this first if you're picking up in a new chat.** Everything else is
> derived from code or deeper docs. This doc captures state as of 2026-07-20
> ~15:50 EDT, after ~24h of intensive iteration.
>
> **Update 2026-07-22:** `orgos/spawn/` has since been extracted into the
> standalone `agentkit` library and orgos migrated to consume it
> (`pip install -e ../agentkit`; imports are `agentkit.governance`). Suite
> is now ~475 tests. References to `orgos.spawn` below are historical.

---

## 30-second orientation

**orgos** is an async multi-agent framework that turns a spec file into
working code via a team of LLM agents playing Scrum roles (PO, SM,
architects, testers, devsecops, + new Customer). It ships two modes:
`orgos start` (async scrum runtime, primary) and `orgos run --waterfall`
(baseline for comparison).

Under the hood: `orgos/spawn/` is the governance substrate (permission
tiers, gated tools, audit log, envelope validation, budget enforcement).
`orgos/agile/` is the async runtime layered on top.

**Current version: 2.3.2** on `main`. 387 pytest tests passing.

Two big things happened this session:
1. Shipped runtime hardening (§H1-H13) + true-Scrum features (§D1 team
   adaptation + §D2 customer agent). Fully validated in production runs.
2. Decided to extract the reusable substrate into a new library called
   **`agentkit`** (see extraction plan below).

---

## What is truly settled

### The runtime works — empirically validated

Latest production experiment (v8, 2026-07-20 ~11:44-13:08 EDT):
- **11-agent team** including the new Customer agent
- **18/37 stories delivered** on the quant-desk spec
- **158 tests passing** in the built code
- **5 `customer_review` events + 7 `customer_reject` events** — §D2 catches
  REAL spec violations the AC gate missed (wrong class names, dataclass
  vs pydantic, missing config)
- Clean exit via budget cap at $8.09 (§A5 works)
- **Real DeepSeek spend: $1.09** (orgos estimator said $7.86 — cache-hit
  rate is 95-98% on agentic prompts)

Parallel run earlier: `minisearch` spec (text search engine, completely
different domain) → 23/28 delivered (82%), 201 tests passing, clean §H7
timeout exit at 2h. **Same runtime, different domain = orgos generalizes.**

### Fixes shipped today (each with a §H tag for git-grep)

| Ver | Fix | What it does |
|---|---|---|
| 2.2.4 | §H7 | threading.Timer watchdog — guarantees process exit at --timeout-seconds (was unreliable via asyncio) |
| 2.2.5 | §H8 | Verifier skips LLM-produced unparseable files (was reporting 0 passed) |
| 2.2.6 | §H9 | Post-merge collection check — reopens stories that break integration `pytest --collect-only` |
| 2.2.7 | §H10 | Cache-aware pricing (`cost_usd_cached`, `estimate_with_cache_rate`) — real DeepSeek billing |
| 2.3.0 | §D1 + §D2 | Team adaptation loop + Customer agent (turn Scrum-mechanics into closer-to-real Scrum) |
| 2.3.1 | §H12 | Customer routing collision fix (customer's HEARTBEAT mentioned "spec" → hijacked to replan) |
| 2.3.2 | §H13 | Two bugs blocking §D1: (a) close_sprint never wrote sprints.jsonl, (b) signals_from_history type mismatch |

Full commit log: `git log --oneline main | head -20`

### §D1 team adaptation status

Code path proven correct via post-hoc backfill of v8's data:
```
signals: 4
  sprint 1: 4/16 done (25%)
  sprint 2: 8/16 done (50%)
  sprint 3: 8/16 done (50%)
  sprint 4: 0/7  done ( 0%)

Would propose:
  velocity_target:  16 → 13  (team under-delivering, avg 33%)
  max_ac_retries:   3 → 2   (AC retries mostly exhaust)
```

**Not yet validated in a live run** — v8 was pre-fix. Would need a v9 (~2h,
~$1 real spend) to see `team_adapted` events fire in production. This
is the ONLY orgos claim not yet empirically validated.

---

## Current state (things running or not)

- **No active experiment processes** — everything exited (mostly at budget
  caps, all cleanly).
- **DeepSeek balance: $10.85** (started morning at $11.94; total real spend
  today across all experiments: $1.09).
- **Latest commit on origin/main: `1853a75`** (2.3.2 §H13 fix).
- **Preserved workspaces**: `~/orgos-runs/{quant-desk-v3,v6,v7,v8,minisearch,
  quant-desk-v5,smoke}` (older ones like v1/v2 were wiped when `/tmp` was cleared).
- **Test count**: 387 passing (was 265 at start of yesterday).

---

## The two open threads

### Thread A — orgos v9 (optional final validation)

Purpose: prove §D1 fires in production. Fast, cheap, definitive.

```bash
mkdir -p ~/orgos-runs/quant-desk-v9 && cd ~/orgos-runs/quant-desk-v9 && \
  git init -q && git config user.email quant@orgos.local && \
  git config user.name orgos && cp /Users/th/Documents/Github/orgos/.env .env && \
  echo "v9 — §H13 fix validation" > README.md && git add -A && git commit -qm init && \
  cd - > /dev/null

python3 -m orgos.cli start --repo /Users/th/orgos-runs/quant-desk-v9 \
  --team-id quant-desk-v9 \
  --spec-file /Users/th/Documents/Github/orgos/docs/specs/quant-desk.md \
  --executor spawn --model deepseek/deepseek-chat \
  --architects 3 --testers 3 --devsecops 2 --customer \
  --sprint-duration-seconds 900 --timeout-seconds 7200 --max-usd 4.0 --fresh
```

Success = at end of run, `cat .../adaptation.json` shows `version > 1` AND
`jq 'select(.action=="team_adapted")' .../live.jsonl` shows > 0 events.

Cost: ~$0.50-1 real, ~2h wall.

### Thread B — `agentkit` extraction (the productization move)

**The core insight**: `orgos/spawn/` is a reusable governance substrate for
ANY agentic app. Extracting it as `agentkit` gives every future project
(yours or client's) a "IAM + audit + envelope" layer for free. Sales moat:
compliance-by-default for enterprise buyers.

**Naming decided: `agentkit`** — user acknowledged the name is taken by
Coinbase, Cloudflare, LangChain but wants to keep it as the project name.
For PyPI publishing, will need a suffix like `agentkit-py` or `agentkit-core`.

**What to extract (from orgos):**
```
orgos/spawn/                → agentkit/governance/
  contracts.py                (RoleSpec, PermissionTier, HandoffEnvelope, TierPolicy)
  engine.py                   (spawn, spawn_chain)
  toolbase.py                 (GatedToolBase)
  tier_policy.py

orgos/agile/pricing.py     → agentkit/cost/
                              (cost_usd, cost_usd_cached, estimate_with_cache_rate)

new: agentkit/backends/
  base.py                     (SpawnBackend abstract interface)
  litellm_backend.py          (current CrewAI+LiteLLM path)
  claude_backend.py           (direct Anthropic SDK — native caching, streaming, MCP)
```

**What NOT to extract** — orgos-specific and stays in orgos:
- `orgos/agile/agent_loop.py` (AsyncAgent is orgos-specific)
- `orgos/agile/board_store.py` (Scrum-specific)
- `orgos/agile/sprints.py`, `retrospective.py`, `replan.py` (Scrum ceremonies)
- `orgos/agile/customer_review.py`, `team_adaptation.py` (Scrum-specific)

**The pluggable-backend design** (decided this session):
```python
# agentkit/backends/base.py
class SpawnBackend(ABC):
    async def execute(self, *, role, brief, tools, max_tokens,
                      on_tool_call, on_token_usage) -> BackendResult: ...
```

Governance stays in `spawn()` itself; the backend just executes.

**Missing pieces (that need adding before 0.1.0 ships):**

Critical (dealbreakers for enterprise):
1. **OTel tracing** (~200 lines) — every spawn = span, tool calls = child spans
2. **Secret redaction** (~150 lines) — regex + tag-based scrubbers pre-audit
3. **Structured output validation per role** (~100 lines) — pydantic model per role

Nice-to-have (0.2.0):
- Retry policy on tool failures (~80 lines)
- Cost forecasting `spawn.estimate()` (~100 lines)
- **`agentkit-test` companion** (~300 lines) — this is the DIFFERENTIATOR:
  fixture agents, mock tools, replay-from-audit, diff-across-persona-versions.
  No competing framework has good agent-testing story.

**Shipping plan:**
- Week 1: extract governance + pricing, add LiteLLM backend, publish as 0.1.0
- Week 2: add Claude SDK backend (native caching + streaming) → 0.2.0
- Week 3: ship `agentkit-test` companion → 0.3.0
- Reference apps to build alongside: "SOC2 evidence collector" (best demo
  for enterprise pitches), "fix my failing test" GitHub bot, "deploy pilot"
  Slack bot.

---

## Critical files to know

### orgos itself
- `orgos/spawn/contracts.py` — RoleSpec, PermissionTier, HandoffEnvelope,
  budget_llm(). **This is what agentkit extracts.**
- `orgos/spawn/engine.py` — `spawn()` and `spawn_chain()`. Same.
- `orgos/spawn/toolbase.py` — GatedToolBase. Same.
- `orgos/agile/agent_loop.py` — AsyncAgent. The async runtime. 1000+ lines.
- `orgos/agile/team_adaptation.py` — §D1 implementation
- `orgos/agile/customer_review.py` — §D2 implementation
- `orgos/agile/pricing.py` — §H10 cache-aware pricing
- `orgos/agile/verifier.py` — §C10 overall DoD + §H8 skip broken files
- `orgos/agile/collection_gate.py` — §H9 post-merge collection check
- `orgos/cli.py` — CLI entry points. Contains §H7 threading.Timer watchdog.
- `orgos/agile/sprints.py` — sprint state. Contains §H13 fix (append_record).
- `orgos/agile/sprint_history.py` — sprints.jsonl reader.

### Persona files (`agents/`)
- Each role has 5 files: SOUL, BRAIN, HABITS, HEARTBEAT, MEMORY (all `.md`)
- `agents/customer/` — new role added this session (§D2)
- Loaded via `RoleSpec.from_agent_dir(agents_root, role_name)`

### Specs
- `docs/specs/quant-desk.md` — 37-story trading platform spec (main test target)
- `docs/specs/minisearch.md` — 28-story text search engine spec (domain-diversity test)

### Docs
- `docs/HANDOFF.md` — the pre-2.3.x general handoff (still mostly accurate)
- `docs/RESULTS.md` — measured runs history (Run 5a-d, may need Run 6 = v8 append)
- `docs/TROUBLESHOOTING.md` — 10 concrete failure-mode runbooks
- `README.md` — includes 5-min quickstart at top

---

## Confidential / off-limits (persistent)

- **Governance layer OFF-LIMITS**: do not modify `orgos/spawn/GatedToolBase`,
  `HandoffEnvelope`, `TierPolicy`, `PermissionTier`, `spawn()`, `spawn_chain()`,
  or the `TIER_POLICY` table without explicit permission. Reading is fine.
- **External collaborator name / methodology name is CONFIDENTIAL** — must not
  appear in any committed file, commit message, PR description, memory, or
  public artifact. Refer to reference model as "the autonomous scrum team
  model", "the reference spec", or "external methodology".

---

## Decisions made this session

- **`agentkit` is the extraction name** (user knows it's taken, will suffix for PyPI)
- **Backend interface is pluggable** (LiteLLM first, Claude SDK adapter second)
- **Compliance is the moat** — audit + tiers + redaction, not "another framework"
- **Chat model wins over reasoner** for this workload class (v6 reasoner: 9 done vs v5 chat: 22)
- **`orgos ship` gated on ≥80% delivered AND ≥90% pass rate** (§C11 defaults)
- **§D1 adaptation uses bounded ±20% steps + hard bounds** to prevent thrashing
- **§D2 customer max 3 rejects per story** (customer is a second signal, not the final judge)

---

## Environment quirks

- **anyio dep**: openai/crewai auto-updated to require anyio ≥ 3.0. Fixed
  today with `pip install -U anyio` (now 4.14.2). If a new session sees
  `ModuleNotFoundError: anyio.to_thread`, run that.
- **DeepSeek model naming**: both `deepseek-chat` and `deepseek-reasoner`
  return `deepseek-v4-flash` as the underlying model name. That's their
  marketing. Reasoner still generates `reasoning_content` correctly.
- **macOS `/tmp` gets wiped on reboot**: use `~/orgos-runs/` for persistent
  target repos. All current experiments live there.
- **Test env**: `pytest` needs to be installed in each team's
  `.orgos_venv` for `orgos verify` to work; this is a known gap (potential
  §H14 for future).

---

## How to run anything

```bash
# Full test suite (~65 sec)
pytest -q

# Launch a run
python3 -m orgos.cli start --repo <path> --team-id <name> \
  --spec-file <spec.md> --executor spawn --model deepseek/deepseek-chat \
  --architects 3 --testers 3 --devsecops 2 --customer \
  --sprint-duration-seconds 1200 --timeout-seconds 14400 \
  --max-usd 8.0 --fresh

# Monitor
python3 -m orgos.cli status --watch --team-id <name> --repo <path>
python3 -m orgos.cli logs --follow --team-id <name> --repo <path>

# After run
python3 -m orgos.cli deliver --team-id <name> --repo <path> --spec-file <spec.md>
python3 -m orgos.cli verify --team-id <name> --repo <path>

# Real DeepSeek balance
curl -s -H "Authorization: Bearer $DEEPSEEK_API_KEY" \
  https://api.deepseek.com/user/balance | jq '.balance_infos[0].total_balance'
```

---

## What "next session" should do first

1. **Read this doc + `docs/HANDOFF.md`** (5 min)
2. **Check state**:
   - `git log --oneline main -5` — should show `1853a75` at top
   - `pytest -q` — should show 387 passing in ~65s
   - `ps aux | grep orgos.cli | grep -v grep` — should be empty
3. **Ask the user which thread to pick**: A (launch v9 for final §D1 validation)
   or B (start `agentkit` extraction) or both in parallel

If user has already decided (they may say "start extraction"), go straight
to that. The plan for each thread is above.

If user wants agentkit extraction: create a NEW repo (or a subpackage,
depends on user preference), lift `orgos/spawn/` verbatim, write the
`SpawnBackend` ABC + LiteLLM adapter, add the 3 critical gaps (OTel,
redaction, structured outputs). Aim for a shippable 0.1.0.

If user wants v9: use the exact command in Thread A above; schedule
check-ins at T+30, T+1h, T+2h END; report on `team_adapted` events.

**Do not re-derive today's decisions.** They're documented above. Read the
doc, ask which thread, execute.
