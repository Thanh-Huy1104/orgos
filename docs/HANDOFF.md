# orgos — handoff snapshot

> **Read this first if you're picking up this project in a new session, with a
> new model, or with a different harness.** It's the "start here" pointer.
> Everything else is either derived from the code or lives in the deeper docs.
>
> **Note (this branch):** the `orgos/spawn/` governance substrate is
> vendored in this repo (imports `orgos.spawn.governance`) — no external
> install needed.

---

## 1. What this project is (30 seconds)

orgos is a platform that deploys an autonomous team of AI agents against a
coding goal. Point it at a local git repo, give it a paragraph describing
what you want built, and the team decomposes, refines, codes, tests, and
merges changes to a persistent integration branch.

Ships with two topologies for benchmarking:
- **Scrum (v2 async, `orgos start`)** — 5 asyncio agents self-organizing via
  a shared filesystem board. Real Scrum machinery: paired test subtasks
  (DoD), time-boxed sprints, PO acceptance gate.
- **Waterfall (`orgos run --waterfall`)** — sequential PO → Architect → Test
  → DevSecOps pipeline. The topology an LLM defaults to when asked for
  "an agentic dev team." Included as the baseline to beat.

Both call into `orgos.spawn.spawn(role, brief)` — the governance substrate
that enforces permission tiers, wraps tools with human-approval gates,
validates envelopes, and writes an audit trail. `orgos/spawn/` is
**off-limits** to modifications made by the agents themselves.

---

## 2. Where the project is right now

- **Version:** 2.1.0 (async runtime + component ownership + spec-in workflow)
- **Branch:** `main`
- **Tests:** 265 passing, ~50 s locally (`pytest -q`)
- **Comparison results (measured, DeepSeek v4-flash, ~$3-5/run):**
  - Run 5 (N=1 scrum): 37 done in 4h — beats waterfall's 12 done in 18 min
  - Run 5c (N=3 no components): 15 done — **regression** (agents fought over `app.py`)
  - Run 5d (N=3 + components): 48 done — **+30% over N=1**, same goal + LLM
  - See [RESULTS.md](RESULTS.md) for the full three-way arc + 17-fix audit.
- **Drop-in-with-specs workflow (2.1.0):**
  - `orgos plan --spec-file spec.md` — dry-run decomposition, no team spawned
  - `orgos doctor` — pre-flight health check
  - `orgos status --watch` — top-like live view during 4h runs
  - `orgos logs --follow` — tail live.jsonl with pretty formatting
  - `.orgos.toml` config — end the 7-flag CLI incantation
  - `## Story: <title>` blocks in spec-file are honored directly (no LLM decomposition)
  - `## AC:` bullets flow into `story.acceptance_criteria` → PO acceptance gate
- **Recipient-ready:** README §quickstart is 3 commands via `--executor mock`
  and produces a report in 60 s.

**Latest architectural additions (in order landed on `main`):**
1. Async runtime (14-task rewrite from dispatcher) — commits `c1b0ac5..352d20a`
2. Merge queue + workspace fixes discovered by smoke runs — `0d338ee..1cd6300`
3. SpawnCodingExecutor + Claude Code + Copilot CLI executors, auto-detect — `d6a6155..04f11b8`
4. HTML comparison + `campaign_result.json` parity for scrum — `0bd8bc7`
5. Real Scrum: DoD subtasks + sprints + PO acceptance gate — `45c6ac3`
6. Docs (architecture.html, RESULTS.md, this file) — `11cc66e..`
7. Pre-merge audit fixes (dead-code pr_feedback, PID file for `orgos stop`,
   version bump, routing coverage test) — `4a0097f`

---

## 3. What to read (in order)

| Doc | Contents | Read if... |
|---|---|---|
| [README.md](../README.md) | Install + executor pick + comparison run | first time, or standing up on a new machine |
| [architecture.html](architecture.html) | Full v2 stack with diagrams | you're changing runtime code |
| [RESULTS.md](RESULTS.md) | Measured comparison + direction | deciding what to build next |
| [spawn-rubric.md](spawn-rubric.md) | Governance layer deep dive | anything touching `orgos/spawn/` (which is off-limits) |
| [superpowers/specs/2026-07-16-orgos-v2-async-scrum-team.md](superpowers/specs/2026-07-16-orgos-v2-async-scrum-team.md) | v2 design spec (as approved) | you want the "why" behind current shape |
| [superpowers/plans/2026-07-16-orgos-v2-async-scrum-team.md](superpowers/plans/2026-07-16-orgos-v2-async-scrum-team.md) | 14-task implementation plan (executed) | you're wondering why a specific file has the shape it does |

---

## 4. Environment

**Required:**
- Python ≥ 3.11
- git ≥ 2.5 (worktree support)
- One of: `claude` CLI, `copilot` CLI, or an LLM API key in `.env`
  (DeepSeek recommended for cost; anything LiteLLM speaks works)

**Persona files** live in `agents/<role>/` — five files per role
(SOUL/BRAIN/HABITS/MEMORY/HEARTBEAT). Only `MEMORY.md` is written by the
agents themselves; the others are human-edited. `HEARTBEAT.md` is a
natural-language schedule (`## Every N seconds`) parsed by
`heartbeat_scheduler.py`.

---

## 5. Windows compatibility (honest read)

**Works on Windows out of the box:**
- Python runtime, asyncio, subprocess-based executors (`claude`, `copilot`
  have Windows installers; `spawn` is HTTP-based)
- git worktrees (git 2.5+)
- All 198 unit tests
- `orgos start` (uses `signal.SIGINT` — Python translates to
  `CTRL_C_EVENT` for console processes)
- `orgos start --timeout-seconds N` (Python-based auto-shutdown, no
  external signal needed — recommended path for LLM-driven Windows use)
- `orgos stop` (uses `os.kill(pid, SIGINT)` — cross-platform)
- `orgos status`, `orgos run`, `orgos serve`, `orgos list-teams`, `orgos reset`

**Doesn't work natively on Windows:**
- `scripts/run_comparison.sh` — bash-only. Windows options:
  a) Run under WSL (recommended, same behavior)
  b) Manually invoke the two commands (`orgos run --waterfall …` then
     `orgos start … --timeout-seconds 480`) plus
     `python3 scripts/build_comparison_html.py …` at the end
  c) Port to PowerShell (~30 lines, not yet done)
- The pgrep fallback in `orgos stop` is skipped on Windows (`sys.platform ==
  "win32"` guard) — this only matters for workspaces that predate the
  pid.txt convention (Windows won't see any of those).

**Recommended Windows workflow:** WSL2 if you have it, otherwise use each
CLI subcommand directly and rebuild the comparison HTML manually.

---

## 6. How to actually run it

### 6a. First time on a fresh machine

```bash
git clone https://github.com/Thanh-Huy1104/orgos
cd orgos
pip install -e ".[dev]"
pytest -q   # ~200 tests, ~30s. If this fails, stop and debug.
```

### 6b. Set up a target (any git repo works; minimal Flask below)

```bash
mkdir /tmp/flask-target && cd /tmp/flask-target
git init -q && \
  echo "from flask import Flask" > app.py && \
  echo "Flask>=3" > requirements.txt && \
  pip install flask pytest && \
  git add -A && git commit -qm "initial" && cd -
```

### 6c. Run the async scrum team

```bash
orgos start \
  --repo /tmp/flask-target --team-id demo \
  --goal "Add /health endpoint returning {status: ok}" \
  --executor auto \
  --timeout-seconds 360
```

`--executor auto` picks `claude` if the CLI is on PATH, else `copilot`,
else `spawn` (needs `DEEPSEEK_API_KEY` or similar in `.env` at the
target repo root).

### 6d. Verify the run

```bash
orgos status --repo /tmp/flask-target --team-id demo
cat /tmp/flask-target/.orgos_teams/demo/campaign_result.json | jq .
git -C /tmp/flask-target log team/demo/integration --oneline | head -10
```

### 6e. Run the head-to-head comparison

```bash
bash scripts/run_comparison.sh \
  --repo /tmp/flask-target \
  --goal "Add /health endpoint returning {status: ok}" \
  --model deepseek/deepseek-chat --executor spawn \
  --scrum-seconds 480
open /tmp/orgos-comparison.html    # macOS; xdg-open on Linux
```

---

## 7. Known limitations (documented, not blocking)

These are honest gaps from [RESULTS.md §Direction](RESULTS.md). Nothing
here would break on first use — they're all "the system does less than a
real Scrum team would."

| # | Gap | Effort |
|---|---|---|
| 1 | Sprint boundary is hardcoded 4h in SM's HEARTBEAT.md — no `--sprint-duration-seconds` knob | ~30 lines |
| 2 | PO acceptance is v1 auto-accept (anything with `commit_sha` passes) — no per-story `acceptance_criteria` parsing | ~30 lines + Story field |
| 3 | `files_to_touch` overlap blocks paired feature+test claim when both touch `tests/*.py` — PO decomposer needs stricter file-path discipline | prompt tune |
| 4 | Blocked stories don't auto-retry — only PO's manual replan rescues them | design decision |
| 5 | Wiki compounding unverified — no test proves agents actually read `wiki/DECISIONS.md` across stories | write integration test |
| 6 | `retro_failed` event fired in an earlier smoke run and was never diagnosed | grep live.jsonl of last real-scrum run |
| 7 | ClaudeCodeExecutor and CopilotCliExecutor are only mock-tested — no end-to-end test against a real CLI | manual smoke |
| 8 | No velocity-informed replan — sprints record `points_completed` but PO doesn't use that to right-size the next sprint | ~40 lines |
| 9 | No CHANGELOG — v1→v2 breaking-change list only exists in git history | template |

---

## 8. What's off-limits

**`orgos/spawn/`** — the governance substrate. `GatedToolBase`,
`HandoffEnvelope`, `TierPolicy`, `PermissionTier`, `spawn()`,
`spawn_chain()`, and the `TIER_POLICY` table must not be modified without
explicit permission. This is the trust boundary that lets us hand a coding
agent significant power without letting it change its own governance.

If a change seems to require touching `orgos/spawn/`, escalate — the
answer is almost always to change what you pass INTO spawn, not spawn
itself.

---

## 9. Ranked next steps (from RESULTS.md)

**Immediate wins (< 1 day each):**
1. Multi-run statistics — wrap `run_comparison.sh` to loop N times per
   topology, emit mean/stddev in the HTML. Gets defensible n≥5.
2. `--sprint-duration-seconds` on `orgos start` so demo runs can see
   multiple sprints in a short window.
3. Velocity-informed replan — PO reads previous sprint's `points_completed`
   and right-sizes the next sprint's commitment.

**Meaningful features (1-3 days each):**
4. Enforce `files_to_touch` non-overlap in decomposer — post-process PO
   output: if feature and test share files, split test file path.
5. Stricter PO acceptance — read commit diff and check against per-story
   `acceptance_criteria: list[str]`.
6. Longer horizon comparison — 4h run on a real project to make scrum's
   compounding advantage visible.

**Bigger direction:**
7. **Dogfood** — point orgos at itself for a real feature (highest signal).
8. Kanban as third topology — tell us whether "sprint" or "board" is the
   dominant factor.
9. Non-code goals (docs, analysis) — see if the topology gap holds.

**Explicit non-goals:**
- Reimplementing Claude Code / Copilot tool suites inside `spawn`. If a
  user wants the vendor's full agentic tool loop, use the vendor's
  executor.
- Multi-process board sharing. Single-process by design.

---

## 10. Where to look for X

| I want to... | Edit / read... |
|---|---|
| Change what PO decomposes into | `orgos/agile/goal_decomposer.py` (see `_DECOMPOSE_BRIEF_TEMPLATE`) |
| Change how stories transition | `orgos/agile/board_store.py` (see `TRANSITIONS` dict) |
| Change how agents pull work | `orgos/agile/agent_loop.py` (see `_pull_and_work_once` + ceremony methods) |
| Change how HEARTBEAT.md schedules parse | `orgos/agile/heartbeat_scheduler.py` |
| Add a new coding executor | Create a class in `orgos/agile/coding_executor.py` (or a new module) implementing the `CodingExecutor` Protocol; wire it in `orgos/cli.py::_cmd_start` |
| Add a new ceremony | Add a `_run_<name>` method to `AsyncAgent`; add keyword routing in `AsyncAgent.loop`; add event type in `orgos/agile/live_events.py::_EVENT_META`; write ceremony trigger in a persona `HEARTBEAT.md` |
| Change merge behavior | `orgos/agile/merge_queue.py` |
| Change sprint semantics | `orgos/agile/sprints.py` |
| Change how personas load | `orgos/spawn/persona_loader.py` (governance-adjacent — ask first) |
| Add a new event type | `orgos/agile/live_events.py::_EVENT_META` |
| Change the HTML comparison layout | `scripts/build_comparison_html.py` |
| Change what the report shows | `orgos/agile/team_report.py` |

---

## 11. How to test your changes

Every source change should end with `pytest -q` green. Preferred order:

1. Focused test: `pytest tests/agile/test_<module>.py -q`
2. Full suite: `pytest -q` (~30 s, ~200 tests)
3. Runtime smoke: `orgos start --repo /tmp/flask-target --team-id T \
   --goal "..." --timeout-seconds 240 --executor spawn` and check
   `campaign_result.json` + `live.jsonl`.
4. Comparison smoke (if you touched topology-affecting code):
   `scripts/run_comparison.sh …` and diff the HTML metrics vs the
   version in `docs/comparison.html`.

**Don't** skip step 1 (write the test first, TDD-style — the plan that
built v2 was strictly TDD and the codebase reflects it).

---

## 12. Persona architecture (for a model touching `agents/`)

Each role has five files. This is the OpenClaw-inspired convention we
adopted:

| File | Layer | Purpose | Who writes |
|---|---|---|---|
| `SOUL.md` | universal | identity, purpose, values | human |
| `BRAIN.md` | specific | domain knowledge, reasoning patterns | human |
| `HABITS.md` | specific | routine behaviors, tool preferences | human |
| `MEMORY.md` | specific | past decisions, learnings | **agent** (only agent-writable) |
| `HEARTBEAT.md` | specific | natural-language schedule | human |

`persona_loader.py` (in `orgos/spawn/`) reads and validates each file's
sections. Missing sections warn but don't fail.

**To add a new role:**
1. Add a directory `agents/<role>/` with the five files
2. Add a role factory in `orgos/subagents/scrum_team.py`
3. If it's a delivery role, add it to `delivery_roles` in
   `orgos/cli.py::_cmd_start`
4. If it needs new type filters, update `board_store.py` `list_ready_for_type`
5. Update `HEARTBEAT.md` schedule + routing test's whitelist if the
   new schedule has intentional-noop actions

---

## 13. Cost/budget notes

- **Waterfall** run cost (DeepSeek Chat, small goal): ~$0.10
- **Waterfall** run cost (full CRUD): ~$0.50–0.80
- **Scrum** run cost (full CRUD, real-Scrum machinery, 12-min window): ~$0.22
- **Claude Code / Copilot** executors: no per-run cost (uses user's subscription)
- Full `run_comparison.sh` (both topologies): ~$0.30–$1 depending on goal

Comparison harness is designed to be re-runnable — each `run_comparison.sh`
call cleans previous team workspaces first. Safe to re-run.

---

## 14. Common questions the next model will ask (pre-emptive answers)

**"Why do we have `spawn.py` AND `spawn_executor.py`?"**
Different layers. `orgos/spawn/spawn.py` is the governance-tier executor
that invokes ONE agent for ONE task with tier enforcement + audit. It's
off-limits. `orgos/agile/spawn_executor.py` is a `CodingExecutor` Protocol
implementation that USES `orgos.spawn.spawn(...)` under the hood — it's
the bridge between the async agile runtime and the governance substrate.

**"Why is there `sprint.py` AND `sprints.py`?"**
`sprint.py` (singular) is a legacy v1 module used by `waterfall_runner`
— one Sprint = one story + one worktree, don't touch unless changing
waterfall. `sprints.py` (plural) is the v2 real-Scrum model — multi-story
time-boxed iterations with committed backlog + velocity.

**"How do I add a new topology (Kanban, etc)?"**
Create `orgos/agile/<topology>_runner.py` mirroring `waterfall_runner.py`
or `agent_loop.py + supervisor.py + cli.py::_cmd_start`. Reuse the board,
merge queue, executor Protocol as-is. Add a CLI subcommand or a flag on
`orgos start`.

**"Can two teams run against the same repo at once?"**
Yes, they use different team-id workspaces (`.orgos_teams/<id>/`) and
different agent branches (`team/<id>/agent/*`). They can't share stories.
Same-process concurrency (multiple `orgos start` in one shell) not tested.

**"Why does the SM's poker fire on non-refined stories?"**
`_run_poker` iterates over both `draft` and `refinement` states. The
`draft → refinement` transition is what the ceremony *does* — it's not a
precondition. If your test breaks this, look at `agent_loop.py::_refine_one_story`.

**"Why doesn't PO accept work automatically after merge?"**
It does, in the v1 acceptance policy — any story with `commit_sha` gets
accepted. See `AsyncAgent._run_acceptance`. To make it stricter, add
`acceptance_criteria: list[str]` to Story and parse commit diff against
it.

**"How do I debug 'nothing is happening'?"**
Read `<workspace>/live.jsonl` line by line. Every state transition and
every ceremony call emits an event. If you see `scheduled_noop`s, a
ceremony's action_text isn't routing — check
`AsyncAgent.loop`'s keyword routing. If no `story_pulled` events, delivery
agents can't find matching-type stories in the current sprint's ready set.
If `story_no_commit` fires often, the executor is failing — check
`raw_stdout`/`raw_stderr` fields in the executor's return value.

**"Where does `agents/<role>/MEMORY.md` get updated?"**
Currently the async agents don't actually update MEMORY.md — that's a
gap. The design intent is that after each story a delivery agent appends
learnings to its MEMORY.md; the code hooks aren't wired. If you're
implementing this, `agent_loop.py::_pull_and_work_once` after
`commit_landed` is the natural place.

---

## 15. What did NOT ship (design choices we backed away from)

- **OpenCode executor** — considered as the primary coding backend, then
  dropped in favor of Claude Code / Copilot / spawn (see git history:
  `1b7dfa1 feat(executor): replace OpenCodeExecutor with ClaudeCodeExecutor`).
  Reasoning: OpenCode CLI turned out unreliable in the smoke tests; the
  vendor CLIs are more mature.
- **Aider executor** — was in the design spec but removed before
  implementation (`17403e7 docs(spec): drop Aider + ClaudeCode executors`
  and then Claude Code was later re-added when we needed a non-API-key
  path).
- **v1 dispatcher scrum path** — the synchronous v1 dispatcher was
  deleted in Task 1 of the v2 rewrite. `orgos run --scrum` now returns
  exit code 3 with a pointer to `orgos start`. `--waterfall` mode still
  works (uses inlined `WorkResult`/`DispatchResult` dataclasses).
- **Reimplementing Claude Code's tool suite inside `spawn`** — the
  temptation was to give `SpawnCodingExecutor` all of opencode's tools
  (Read/Write/Edit/Grep/Glob/etc). Explicitly declined — reimplementing
  the vendor's stack in our codebase is exactly the reliance we were
  trying to escape.
- **Multi-process board.** Threading.Lock in `BoardStore` protects one
  process. Design assumes single asyncio loop. Not tested with multiple
  processes.

---

## 16. If you get stuck

1. Read `docs/RESULTS.md` §"Known limitations" — 15+ things I know are
   imperfect are catalogued there. Odds are your problem is one of them.
2. Read `orgos/agile/agent_loop.py::AsyncAgent.loop` — the routing logic
   for ceremonies. Most "nothing is happening" bugs land here.
3. Run `pytest tests/agile/test_agent_loop.py::TestPersonaHeartbeatRouting -q`
   — proves every persona action_text routes to a ceremony. If this fails,
   someone re-worded a `HEARTBEAT.md`.
4. Check the ledger in `.superpowers/sdd/progress.md` if it exists — it's
   the running log of what the v2 rewrite touched. (Git-ignored, so may
   not be present in your clone. Recover from `git log` if not.)
