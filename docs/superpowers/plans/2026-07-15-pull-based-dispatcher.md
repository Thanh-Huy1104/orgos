# Plan: pull-based dispatcher (Plan 3)

**Goal**: replace the hard-coded sequential team pipeline in `run_pull_sprint`
with a real pull-based board where agents self-organize: PO drafts →
team refines → READY gate → workers pull top-of-ready → work → REVIEW →
DONE. Enables long-running, multi-issue "campaigns" where the team grinds
through a backlog.

**Not in this plan**: real GitHub Issues integration (uses filesystem
board), concurrent workers (sequential worker loop, but self-assigning),
multi-agent coalescing on one issue.

**Status of prerequisites (checked 2026-07-15):**
- `orgos/agile/board.py` — READY-gate logic exists and is pure (79 LOC). ✅
- `orgos/tools/github_board.py` — 338-LOC tool with the full action set exists
  but talks to real GitHub. We will NOT use this for the demo — a filesystem
  board is faster to iterate and works offline. This tool stays for a future
  path where a client wants real GH issues.
- Wiki MCP + compounding — done in previous work (B1). ✅
- `CompactionRunner` wired into sprint end — done. ✅

---

## Reference model

```
                 ┌─────────────────────────┐
     PO      →   │ DRAFT (raw issue text)  │
                 └───────────┬─────────────┘
                             │  refine (per-role reviewers add signoffs)
                             ▼
                 ┌─────────────────────────┐
   Refiners  →   │ REFINEMENT              │  labels: refined:architect|test|devsecops
                 └───────────┬─────────────┘
                             │  check_ready_gate() passes (all signoffs + size caps)
                             ▼
                 ┌─────────────────────────┐
                 │ READY  (fifo backlog)   │  top-of-queue prioritized by PO
                 └───────────┬─────────────┘
                             │  worker pulls_top and sets assignee
                             ▼
                 ┌─────────────────────────┐
   Workers   →   │ IN_PROGRESS             │  architect writes, tests run, commit
                 └───────────┬─────────────┘
                             │  architect emits completion envelope
                             ▼
                 ┌─────────────────────────┐
   Reviewers →   │ REVIEW                  │  test + devsecops verify, emit envelope
                 └───────────┬─────────────┘
                             │  release records mock PR
                             ▼
                 ┌─────────────────────────┐
                 │ DONE                    │  wiki decision + memory delta appended
                 └─────────────────────────┘
```

Every state transition passes through a **gate**. Gates are pure functions
(easy to unit-test) that read the story's current record and decide
whether the next transition is allowed. This is the load-bearing
mechanism — without gates, "pull-based" is just "sequential-with-extra-steps".

---

## Cross-cutting decisions (do not re-litigate)

1. **Board substrate = filesystem**, not GitHub. Path:
   `.orgos_board/<issue_id>.json`. One file per story. Simple, atomic
   rename-based transitions. Real-GH port is Plan 3.5, not this plan.
2. **Workers are sequential** in v1 (one at a time), but pull the top of
   READY at each iteration. Concurrent workers is Plan 3.7.
3. **Gate outcomes are envelopes**, not exceptions. A gate that rejects
   a transition writes a `blocked` envelope with the reason; the harness
   decides whether to loop back for refinement or abort.
4. **Refinement is capped at 2 rounds**. If the team can't reach READY in
   2 refinement passes, PO must re-scope the story or the harness drops
   it. Prevents infinite refinement loops.
5. **Every action writes to the story's audit trail**
   (`.orgos_board/<id>_audit.jsonl`). This is the artifact the report
   drilldown reads.
6. **Wiki grep before refinement** — refiners must consult the wiki once
   per story; captured in the story's audit trail. Compounding is the
   demo thesis.

---

## Files to create

### `orgos/agile/board_store.py` (~150 LOC)
Filesystem-backed board CRUD. Pure I/O, no LLM.

```python
class BoardStore:
    def __init__(self, root: Path = Path(".orgos_board")): ...

    # Creation
    def draft_story(self, issue_id: str, title: str, body: str, priority: int = 0) -> Story: ...

    # Read
    def read(self, issue_id: str) -> Story: ...
    def list_state(self, state: str) -> list[Story]: ...
    def list_ready_top(self, n: int = 5) -> list[Story]: ...  # priority DESC, then FIFO

    # Transitions (all gate-checked, all audit-logged)
    def transition(self, issue_id: str, new_state: str, actor: str, reason: str = "") -> Story: ...
    def add_refinement(self, issue_id: str, role: str, concern: str) -> Story: ...
    def add_signoff(self, issue_id: str, role: str) -> Story: ...
    def add_comment(self, issue_id: str, actor: str, body: str) -> Story: ...

@dataclass
class Story:
    issue_id: str
    title: str
    body: str
    state: str          # draft|refinement|ready|in_progress|review|done|blocked
    priority: int
    signoffs: dict[str, bool]  # {"architect": True, "test": False, "devsecops": False}
    assignee: str       # role name or ""
    refinement_rounds: int
    comments: list[dict]  # [{actor, ts, body}, ...]
    audit: list[dict]     # [{ts, actor, action, reason}, ...]
    created_at: str
    updated_at: str
```

Storage layout:
```
.orgos_board/
  index.json                     # {issue_id: state} — for O(1) list_state
  stories/
    B10-01-doc-takt.json         # full Story JSON
    B10-02-notes-field.json
    ...
  audit/
    B10-01-doc-takt.jsonl        # append-only audit trail
    ...
```

Atomic writes via `tmp + rename`. No SQLite — filesystem is fine at this scale.

### `orgos/agile/dispatcher.py` (~250 LOC)
The orchestration loop. Reads the board, applies gates, spawns agents.

```python
class Dispatcher:
    def __init__(self, board: BoardStore, model: str, repo_path: Path,
                 max_refinement_rounds: int = 2,
                 wiki_root: Path = Path("wiki")): ...

    def ingest_backlog(self, issues: list[dict]) -> None:
        """Draft every issue into DRAFT state via PO."""

    def run_campaign(self, *, until: str = "queue_empty",
                     max_issues: int | None = None,
                     max_wall_seconds: int | None = None) -> CampaignResult:
        """Main loop. Blocks until termination condition."""

    # Internal phases — each spawns one agent, writes one envelope, applies one gate
    def _phase_scope(self, story: Story) -> Story: ...     # PO
    def _phase_refine(self, story: Story) -> Story: ...    # architect/test/devsecops in turn
    def _phase_gate_ready(self, story: Story) -> Story: ... # deterministic READY gate
    def _phase_work(self, story: Story) -> Story: ...      # architect pulls, writes, commits
    def _phase_review(self, story: Story) -> Story: ...    # test + devsecops verify
    def _phase_release(self, story: Story) -> Story: ...   # mock PR
    def _phase_done(self, story: Story) -> Story: ...      # wiki decision, memory delta

@dataclass
class CampaignResult:
    started_at: str
    ended_at: str
    reason_stopped: str
    stories_processed: list[str]
    stories_done: list[str]
    stories_blocked: list[str]
    total_tokens: int
    total_cost_usd: float
```

### `orgos/agile/gates.py` (~100 LOC)
Pure gate functions. All return `GateResult(passed: bool, reason: str)`.

```python
def gate_draft_to_refinement(story: Story) -> GateResult: ...
    # Non-empty title, non-empty body, priority set.

def gate_refinement_to_ready(story: Story) -> GateResult: ...
    # Uses check_ready_gate from board.py + refinement_rounds > 0.

def gate_ready_to_in_progress(story: Story) -> GateResult: ...
    # No other IN_PROGRESS story (v1 concurrency = 1).

def gate_in_progress_to_review(story: Story) -> GateResult: ...
    # Architect envelope present, commit_sha non-empty.

def gate_review_to_done(story: Story) -> GateResult: ...
    # Test + devsecops envelopes present, both status=completed.
```

Gate functions live separately from BoardStore so they can be unit-tested
against synthetic Stories without any I/O.

### `scripts/run_campaign.py` (~50 LOC)
CLI wrapper mirroring `run_benchmark.py`:

```
python scripts/run_campaign.py --backlog benchmark_reports/pilot-10/corpus.json --model deepseek/deepseek-chat --run-id campaign-1
```

Outputs `.orgos_board/` plus a `campaign_reports/<run_id>/report.html`
using an extended `report.py` (adds "Board timeline" section showing
state transitions per story).

### `tests/agile/test_board_store.py` (~150 LOC)
Full CRUD, atomic-write, index-consistency, priority ordering.

### `tests/agile/test_gates.py` (~100 LOC)
One test per gate. Synthetic Story fixtures.

### `tests/agile/test_dispatcher.py` (~120 LOC)
Uses mock spawn (no real LLM) to verify the dispatcher walks the state
machine correctly, respects the refinement cap, handles blocked stories,
respects `until` and `max_issues` termination.

---

## Files to modify

### `orgos/agile/sprint.py`
Extract shared helpers used by both old `run_pull_sprint` and new
Dispatcher phases:
- `_wiki_grep_summary(issue)` — one wiki call, returns hits.
- `_write_wiki_decision(issue, summary)` — the DECISIONS.md append.
- `_log_sprint_to_wiki` already exists — keep, called by Dispatcher's
  `_phase_done`.

`run_pull_sprint` stays as a legacy path for the current benchmark. Not
deleted. Callable side-by-side.

### `orgos/agile/benchmark.py`
Add `run_team_campaign(backlog: list[dict], ...) -> list[BenchmarkRun]`
that uses Dispatcher instead of the per-issue `run_team` loop. The
benchmark harness stays the same for `--approaches solo`; a new
`--approaches team_campaign` uses the Dispatcher.

### `orgos/agile/report.py`
Add "Campaign timeline" section: one row per story showing state
transitions with timestamps + which agent triggered each. Reads from
`.orgos_board/audit/*.jsonl` when present.

---

## Success criteria

1. `pytest tests/agile/test_board_store.py tests/agile/test_gates.py tests/agile/test_dispatcher.py -q` → all green.
2. `python scripts/run_campaign.py --backlog benchmark_reports/pilot-10/corpus.json --run-id campaign-1` runs to completion.
3. Every story in the backlog ends in state `done` or `blocked` (not `in_progress` or `review` — no lost work).
4. `.orgos_board/audit/<id>.jsonl` contains ≥ 6 entries per successful story (scope, refinement×3, ready, work, review, release, done).
5. `wiki/SPRINT_LOG.md` and `wiki/DECISIONS.md` grow by one entry per completed story.
6. Total campaign wall-time is within 20% of `n_issues × single-sprint-time` (sequential v1 — no concurrency win).
7. `campaign_reports/<run_id>/report.html` renders the campaign timeline correctly.

---

## Rollout order (7 tasks, each independently testable)

| # | Task | Deliverable | Depends on |
|---|---|---|---|
| 1 | `BoardStore` + tests | CRUD works, index stays consistent, atomic writes | — |
| 2 | `gates.py` + tests | 5 pure gates, unit-tested with synthetic Stories | 1 (Story dataclass) |
| 3 | `Dispatcher` skeleton | Walks state machine with mock spawn; no real LLM | 1, 2 |
| 4 | `_phase_*` methods with real spawn | Each phase spawns the right agent with the right brief | 3, existing sprint.py briefs |
| 5 | `run_campaign.py` CLI | End-to-end run on 3-issue toy backlog produces done stories | 4 |
| 6 | `report.py` campaign timeline | HTML report shows per-story state transitions | 5 |
| 7 | 10-issue campaign run | Full pilot backlog, produce shareable report | 6, pilot corpus |

---

## Risks and honest caveats

1. **Refinement is the risky phase.** Making three role agents each add a
   *substantive* concern (not just "LGTM") without going in circles is
   hard on DeepSeek. If refinement produces empty signoffs, the READY
   gate should still pass on well-scoped stories — but if refinement
   goes to 2 rounds every time on trivial stories, campaign cost blows
   up. Mitigation: skip refinement on stories with `difficulty:trivial`.
2. **The demo advantage vs sequential is subtle.** Pull-based helps when:
   - Refinement genuinely improves scope
   - Wiki compounding actually reduces later-story confusion
   - The gate catches bad READY transitions
   None of these are guaranteed. The pilot data will tell us whether
   the current sequential team even *needs* pull-based — if team was
   already winning cleanly, this plan is over-engineering.
3. **Filesystem board = single-writer.** If we ever want concurrent
   workers, this needs SQLite or file-locking. v1 assumes one process.
4. **Wiki writes concurrent with dispatcher writes.** Compaction reads
   wiki mtimes; dispatcher writes to `.orgos_board/` and to wiki. Both
   are fine as separate roots — but keep them separate.
5. **What if a phase's spawn fails?** Story transitions to `blocked`
   with the exception recorded. Dispatcher loop moves on. Blocked
   stories can be retried manually (not automatically — auto-retry is a
   loop hazard).
6. **What "until" means.** Three options: `queue_empty` (process every
   story once), `max_issues=N` (stop after N done stories), or
   `max_wall_seconds=T` (stop when time budget exhausted, letting
   in-flight story finish). v1 supports all three.

---

## Estimated effort

Task 1–2: ~2 hours (mechanical, high test coverage).
Task 3–4: ~3 hours (real LLM integration, debug loop).
Task 5–6: ~1.5 hours (mostly UI polish).
Task 7: ~1 hour of runtime + review.

**Total: ~7-8 hours of focused work, ~$2-4 in DeepSeek to validate.**

Once pilot data is in, we decide whether this is the right next
investment or whether polishing the existing sequential team story is a
better client bet.
