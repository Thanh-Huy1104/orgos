# orgos v2 — Async Scrum Team on OpenCode

**Status:** approved for planning, 2026-07-16
**Author:** brainstorming session with user
**Supersedes:** the synchronous dispatcher architecture (`orgos/agile/dispatcher.py`, `orgos/agile/multi_sprint.py`) — those get deleted.

## 1. Motivation

The current orgos platform has a synchronous dispatcher that pulls work *for* the agents. That is philosophically waterfall — it's what
[the reference chapter](../../../Chapter%204_%20Why%20AIs%20Are%20Waterfall%20Developers%20—%20Scrum%20at%20Machine%20Speed.txt)
warns against. Real Scrum (Sutherland's model, OpenClaw's deployment pattern) is asynchronous:
each agent runs independently, wakes on its own heartbeat, and pulls work from a shared board
only if there's something matching its type. No central coordinator.

Additionally, our current architect writes code via BashTool + heredoc. On real (non-toy) codebases
this fails: editing an existing 500-line file requires heredoc'ing the whole file, which the architect
uses opportunistically to scope-creep unrelated changes. The industry pattern for 2026 is a
**pluggable coding executor**: use a dedicated coding agent (OpenCode, Aider, Claude Code) as a
subprocess, invoked per story with proper Read/Edit/Grep tools.

v2 fixes both:

- **True Scrum runtime**: each role becomes an independent asyncio task with an internal heartbeat.
  The board is the *only* coordination mechanism.
- **Pluggable coding executor**: default OpenCode + DeepSeek. Fallbacks: Aider, Claude Code.

## 2. Goals and non-goals

### Goals

1. Remove the synchronous dispatcher; each of the 5 roles runs as an independent async agent.
2. Board becomes the only coordination surface. Agents self-organize by pulling.
3. Coding is delegated to a pluggable `CodingExecutor` (OpenCode default).
4. Multi-sprint behavior falls out naturally from continuous operation — no explicit sprint loop.
5. Ceremonies (poker, retro, replan) become scheduled tasks on the responsible agents' HEARTBEAT.md.
6. Preserve the demoable claim: **drop-in spec → end-to-end working app + draft PR**.
7. Merge-conflict handling via industry-standard patterns (FIFO merge queue, git rerere,
   rebase-before-merge, non-overlapping file-domain assignment).
8. Runtime supervisor that restarts crashed agents with backoff and durable state.
9. All 138 existing regression tests continue to pass. Add new tests for AsyncAgent and CodingExecutor.

### Non-goals

- Not adopting OpenClaw runtime as a dependency (its own agent framework). We steal patterns, not code.
- Not adopting the OpenClaw 6-file convention. We keep our 5-file persona structure (user preference).
- No automatic LLM-based conflict resolution (CHATMERGE-style) — too immature for production.
- No fully-autonomous "goal met, stop" declaration. Sprints are timeboxed; incomplete work rolls to next sprint.
- Not supporting concurrent workers on the *same* role in v2 (N=1 per role type). Multi-worker
  per role is future work.

## 3. Architecture

### 3.1 Component overview

```
teams/<team_id>/
├── manifest.json               team metadata (goal, model, executor, budgets)
├── integration/                integration git worktree (merged commits land here)
│                                  branch: team/<id>/integration
├── agents/
│   ├── architect/
│   │   ├── SOUL.md             human-edited: personality, tone
│   │   ├── BRAIN.md            human-edited: decision framework, codebase map
│   │   ├── HABITS.md           human-edited: operating rules
│   │   ├── MEMORY.md           agent-updated: accumulated learnings (append-only)
│   │   ├── HEARTBEAT.md        human-edited: natural-language schedule
│   │   ├── worktree/           this agent's isolated checkout
│   │   │                          branch: team/<id>/agent/architect
│   │   ├── session.jsonl       persistent CodingExecutor session state
│   │   └── task_state.json     supervisor-owned; last-known-good agent state
│   ├── test/         (same shape)
│   ├── devsecops/    (same shape)
│   ├── po/           (same shape; PO's worktree is essentially unused)
│   └── scrum_master/ (same shape)
├── board/                      atomic-write JSON per story; audit trail
├── wiki/                       shared knowledge (SPEC.md, DECISIONS.md, RETRO.md)
├── merge_queue.jsonl           FIFO queue of pending merges
├── locks/
│   └── git.lock                serializes cross-worktree git operations
├── live.jsonl                  event feed (unchanged from v1)
└── report.html                 live view (updated for async event types)
```

### 3.2 Keep from v1 (with minor changes)

| Module | Change |
|---|---|
| `agile/board_store.py` | Add `try_claim_next_for(role)` (atomic under board lock). Add `files_to_touch` conflict check on claim. |
| `agile/goal_decomposer.py` | Extend prompt: require `files_to_touch: [...]` on every story. |
| `agile/pricing.py` | No change |
| `agile/pr_publisher.py` | No change |
| `agile/live_events.py` | Add event types: `agent_started`, `agent_crashed`, `agent_restarted`, `merge_queued`, `merge_completed`, `merge_conflict`, `subagent_spawned` |
| `agile/team_report.py` | Add sections: per-agent status (5 rows), merge queue tail. |
| `serve.py` | No structural change |
| `mcps/wiki_mcp.py` | No change |
| `agile/retrospective.py` | Callable from `scrum_master` agent's scheduled task, not from dispatcher |
| `agile/replan.py` | Callable from `po` agent's scheduled task |
| `agile/pr_feedback.py` | Callable from `po` agent's scheduled task |
| `agile/team_workspace.py` | **Rework** for per-agent worktrees |

### 3.3 New modules

| Module | Purpose |
|---|---|
| `agile/agent_loop.py` | The `AsyncAgent` class. One instance per role. Owns: heartbeat timer, pull-and-work loop, MEMORY.md update, session persistence. |
| `agile/coding_executor.py` | `CodingExecutor` Protocol + `OpenCodeExecutor` (default), `AiderExecutor`, `ClaudeCodeExecutor`. Every executor exposes `run_story()` and `spawn_subagent()`. |
| `agile/heartbeat_scheduler.py` | Parses HEARTBEAT.md's natural-language schedule into asyncio timers. |
| `agile/merge_queue.py` | FIFO merge queue. Agents enqueue "merge-me" requests. A merge worker serializes under `git_op_lock`, tries rebase-before-merge, escalates blocked stories on failure. |
| `agile/supervisor.py` | Team supervisor. Watches 5 async agent tasks; restarts on crash with exponential backoff; persists task state (`agents/<role>/task_state.json`) so restart resumes cleanly. |

### 3.4 Delete from v1

- `agile/dispatcher.py` — the synchronous orchestrator (~750 lines)
- `agile/multi_sprint.py` — outer loop replaced by continuous async operation
- `agile/dispatcher_briefs.py` — brief construction moves into `agent_loop.py`

### 3.5 Persona files (5-file convention, semantics changed)

Files kept: `SOUL.md`, `BRAIN.md`, `HABITS.md`, `MEMORY.md`, `HEARTBEAT.md` per role.

Semantics change:

- **HEARTBEAT.md becomes a natural-language schedule**, not wake-up prose. Example for architect:

  ```markdown
  # Architect Agent — HEARTBEAT

  ## Every 30 seconds
  Call board.list_ready_for_type("architecture"). If any: claim top,
  work via CodingExecutor, commit, enqueue merge, update MEMORY.md, mark done.

  ## Every 30 minutes
  Read wiki/DECISIONS.md for any new architectural decisions from other agents.
  ```

- **MEMORY.md becomes agent-updated** (only file agents write). Every append is a git commit with author/timestamp/source.
- **SOUL/BRAIN/HABITS** stay human-edited (personality, decision framework, operating rules).

### 3.6 CLI surface

Backwards compat kept where possible:

| Command | Semantics in v2 |
|---|---|
| `orgos start --team-id X --spec-file …` | New name for `orgos run`. Starts async agents, returns when team is stopped. |
| `orgos run …` | Alias for `orgos start` for backwards compat. Documented as legacy. |
| `orgos stop --team-id X` | New. Sends SIGTERM to team supervisor; agents finish current stories then exit cleanly. |
| `orgos status --team-id X` | New. Prints live per-agent state (idle/working/crashed). |
| `orgos serve` | Unchanged. |
| `orgos report`, `orgos list-teams`, `orgos reset` | Unchanged. |
| `orgos watch` | Deprecated. Same behavior is now the default when `orgos start` is invoked without a stop condition. |

New flags on `orgos start`:

| Flag | Default | Purpose |
|---|---|---|
| `--coding-executor` | `opencode` | `opencode` / `aider` / `claude-code` |
| `--sprint-duration` | `14400` | Sprint-boundary interval (scrum_master's retro schedule). 4h per chapter default. |
| `--max-usd`, `--max-tokens`, `--stagnation-window` | as v1 | Stop conditions |
| `--n-workers-per-role` | `1` | v2 ships N=1; v3 will allow >1 |

## 4. Data flow

### 4.1 Startup

```
orgos start --team-id X --spec-file spec.md --coding-executor opencode
  ↓
  load or create workspace at .orgos_teams/X/
  copy spec.md → wiki/SPEC.md
  for each role in (po, scrum_master, architect, test, devsecops):
    ensure agents/<role>/{SOUL,BRAIN,HABITS,MEMORY,HEARTBEAT}.md exist
    ensure agents/<role>/worktree/ exists (git worktree add)
    parse HEARTBEAT.md → asyncio timer schedule
  start merge_worker (asyncio task)
  start supervisor with 5 AsyncAgent tasks
  start HTTP server for live report
  block on supervisor exit
```

### 4.2 Steady state — one agent

```
AsyncAgent.loop():
  while alive:
    schedule = HeartbeatScheduler(persona.heartbeat_md)
    for task in schedule.pending():             # e.g. "every 30s: check board"
      await task.execute()
    await asyncio.sleep(schedule.next_tick())

AsyncAgent.check_board():
  story = await board.try_claim_next_for(self.role)
  if story is None:
    return

  # Rebase before starting (get latest integration changes)
  async with git_op_lock:
    rebase_worktree_on_integration(self.worktree)

  # Run the coding executor
  result = await self.coding_executor.run_story(
    worktree=self.worktree,
    story=story,
    persona_scaffold=self.persona.combined_prompt(),
    session_id=self.session_id,
  )

  if not result.success:
    board.transition(story.id, "blocked", reason=result.error)
    return

  # Enqueue merge request; the merge worker handles serialization
  merge_queue.enqueue(MergeRequest(
    story_id=story.id,
    from_branch=self.branch,
    files_touched=result.files_touched,
  ))
  # Note: story stays in_progress until merge completes; board.transition
  # to "review" happens from the merge worker.

  # Update MEMORY.md (append learnings)
  await self.memory.append(f"[{story.id}] {result.learnings}")
```

### 4.3 Merge worker (separate asyncio task)

```
async def merge_worker():
  while alive:
    request = await merge_queue.dequeue()  # blocks
    async with git_op_lock:
      try:
        rebase_and_merge(request.from_branch → integration)
        board.transition(request.story_id, "review")
        # Peer review runs here or in a follow-up agent action
      except MergeConflict as e:
        board.transition(request.story_id, "blocked",
                          reason=f"merge_conflict:{e.paths}")
      emit_event("merge_completed" or "merge_conflict", ...)
```

### 4.4 Ceremonies

Ceremonies are HEARTBEAT-scheduled tasks on the responsible agent:

- **PO** — "every 30 min, if board has < 3 READY stories, run replan()"; "every 60 min, poll PR for feedback, ingest new comments"
- **Scrum Master** — "every 4 hours, run retrospective(), then trigger PO's replan"; "every 5 min, run poker on any draft/refinement stories"
- **Architect/Test/DevSecOps** — no ceremonies; just the pull-and-work loop

**No explicit sprint boundary**. A sprint boundary is whenever scrum_master runs retro. The 4h timer creates the "sprint" cadence.

### 4.5 Termination

- `orgos stop` → SIGTERM to supervisor process
- Supervisor sets `alive=False`
- Each agent finishes current story, drains merge queue, closes session, exits
- Report is re-rendered one last time
- Process exits with 0 on clean shutdown

## 5. Merge-conflict strategy

Adopted from industry patterns (Augment Code, Overstory framework, git rerere community).

1. **Prevention** — PO annotates `files_to_touch: [...]` on every story. Board rejects pulling a story whose `files_to_touch` overlaps with any currently `in_progress` or `review` story. Later story stays `ready`, waits its turn.
2. **git rerere enabled** in every worktree at init: `git config rerere.enabled true`. Conflict resolutions recorded once, auto-reapplied.
3. **Rebase before start** — agent rebases its worktree on latest integration before starting work.
4. **Rebase before merge** — merge worker rebases the agent's branch on latest integration before merging.
5. **FIFO merge queue** — agents don't push directly. Merge requests are serialized so only one merge happens at a time.
6. **Test baseline** — after each worktree creation, run pytest; store result on the workspace. Any post-work test failure is provably new.
7. **Escalation** — if rebase-and-merge fails, story is blocked with `merge_conflict:<paths>`. PO's next replan sees it and decides: re-scope, drop, or request human intervention. No auto-LLM resolution.

## 6. Supervisor strategy

Adopted from OpenClaw's Task Flows pattern.

- **Runtime supervisor** (an asyncio task) watches the 5 AsyncAgent tasks.
- On agent task raising an exception:
  - Log the exception, emit `agent_crashed` event
  - Persist last-known-good state to `agents/<role>/task_state.json` (already persisted per-story)
  - Wait N seconds (exponential backoff: 5s, 30s, 5min, 30min, 60min)
  - Restart the agent from the persisted state
- On supervisor itself crashing: process exits non-zero; `orgos start` can be re-run to resume from `task_state.json` files
- **Subagent spawning** — CodingExecutor exposes `spawn_subagent(prompt, timeout)` for delegating a specialized subtask (e.g., architect asks a subagent to "verify these tests pass"). Session-isolated; result flows back as text.

## 7. Testing

- **Unit** — `AsyncAgent` state machine (mock CodingExecutor + mock board); `HeartbeatScheduler` parsing; `merge_queue` FIFO + conflict detection; each `CodingExecutor` implementation with mocked subprocess.
- **Integration** — 2 mock agents + 3 stories → verify both agents claim work without collision; verify blocked-by-file-overlap works; verify merge queue serializes.
- **Real smoke** — Flask target repo + real OpenCode subprocess + 1 sprint boundary → verify done stories + retro written + no merge conflicts on non-overlapping stories.
- **Regression** — all 138 existing tests must pass. Delete tests for `dispatcher.py` and `multi_sprint.py` (they're gone); add new tests for new modules.

## 8. Migration from v1

The v1 codebase gets restructured, not thrown away. Concretely:

1. Delete `dispatcher.py`, `multi_sprint.py`, `dispatcher_briefs.py`.
2. Rework `team_workspace.py` to support per-agent worktrees.
3. Add new modules per §3.3.
4. Update CLI (`cli.py`) — new commands, deprecate `watch`.
5. Update `team_report.py` for per-agent status view + merge-queue tail.
6. Update every persona's HEARTBEAT.md to natural-language schedule.
7. Existing team workspaces from v1 are NOT compatible — v2 refuses to open them, prints a message with `orgos migrate` command (not built in v1→v2; users start fresh).

## 9. Risks and open questions

**Risks:**
- OpenCode's non-interactive mode has known gaps ([issue #13851](https://github.com/anomalyco/opencode/issues/13851)) around fully hands-off file ops. Mitigation: use `opencode serve` + `opencode run` combo (warm session). Fallback: Aider (more mature for subprocess automation).
- Async debuggability. Sync dispatcher was easy to reason about; 5 async agents are harder. Mitigation: live event feed already captures every action; per-agent task_state.json helps forensics.
- Merge conflicts still real — even with all prevention, agents will occasionally collide. Mitigation: escalation path is clear (blocked → PO replan → human).
- Cost. Continuous operation with per-agent LLM calls can burn tokens fast. Mitigation: `--max-usd` / `--max-tokens` caps (already in v1).

**Open questions (defer to plan / implementation):**
- Exact HEARTBEAT.md natural-language parsing grammar — v1 will support a small subset (`every N seconds/minutes/hours`, plus `every day at HH:MM`).
- Whether `spawn_subagent` should share the parent's session or start fresh (research suggests isolated is safer).
- What "peer review" looks like in async mode — is it a scheduled task on test/devsecops agents, or a subagent spawn?

## 10. Success criteria

1. `orgos start --team-id X --spec-file spec.md --coding-executor opencode` runs continuously with 5 async agents, no dispatcher in the codebase.
2. On the Flask target from v1 smoke tests, v2 delivers equivalent or better output (working app + tests + PR).
3. 138 existing regression tests still pass. New tests added for AsyncAgent, CodingExecutor, merge queue, supervisor.
4. Live report shows per-agent status (idle / working on story X / crashed).
5. Merge queue visibly serializes concurrent merges without corrupting git.
6. Supervisor restarts a crashed agent within 60s and it resumes claiming stories.
7. Retrospective still fires (via scrum_master's HEARTBEAT) at 4h intervals.
8. Cost of a full "task-tracker" spec-to-app run is within 20% of v1's cost.

## 11. Effort estimate

- Delete v1 dispatcher/multi_sprint/dispatcher_briefs: 0.5 day
- Rework team_workspace for per-agent worktrees: 1 day
- `CodingExecutor` protocol + `OpenCodeExecutor` (default): 1.5 days
- `AiderExecutor` + `ClaudeCodeExecutor`: 0.5 day
- `HeartbeatScheduler`: 0.5 day
- `AsyncAgent` + supervisor: 2 days
- `merge_queue` with rebase-before-merge: 1 day
- Ceremonies as scheduled tasks (retro, replan, poker moved off dispatcher): 1 day
- Update `board_store.py` for atomic claim + `files_to_touch` check: 0.5 day
- Update CLI (new commands, deprecate watch): 0.5 day
- Update `team_report.py` for per-agent status: 0.5 day
- New regression tests: 1 day
- End-to-end smoke on Flask target: 0.5 day
- **Total: ~10-11 days of focused work**

## 12. References

- [Chapter 4: Why AIs Are Waterfall Developers — Scrum at Machine Speed](../../../Chapter%204_%20Why%20AIs%20Are%20Waterfall%20Developers%20—%20Scrum%20at%20Machine%20Speed.txt) (in repo root)
- [OpenClaw HEARTBEAT/SOUL/Memory configuration guide (2026)](https://blink.new/blog/openclaw-heartbeat-soul-memory-configuration-guide-2026)
- [OpenClaw supervisor & Task Flows patterns](https://kenhuangus.substack.com/p/openclaw-design-patterns-part-3-of)
- [Augment Code — Git Worktrees for Parallel AI Agent Execution](https://www.augmentcode.com/guides/git-worktrees-parallel-ai-agent-execution)
- [Multi-Agent AI Coding Workflow: Git Worktrees That Scale](https://blog.appxlab.io/2026/03/31/multi-agent-ai-coding-workflow-git-worktrees/)
- [Self-Organizing Multi-Agent Systems for Continuous Software Development (arXiv)](https://arxiv.org/html/2603.25928v1)
- [Best AI Coding Agent 2026 — Terminal-Bench rankings](https://www.morphllm.com/ai-coding-agent)
- [OpenCode CLI docs — non-interactive automation](https://opencode.ai/docs/cli/)
