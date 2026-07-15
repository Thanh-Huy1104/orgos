# Plan: Agent Scrum Team Platform

**Product name (working):** Agent Scrum Team Platform.
**One-line pitch:** point it at a git repo, give it a goal, get a Scrum team
of AI agents that decomposes, refines, and delivers — with every wiki
claim traceable to an author, timestamp, and source.

**Demo hook (the sharp one):** the first team's first goal is to build the
missing parts of the platform it runs on. If it works, we ran the team
against itself and shipped an improved template. If it fails, we know
exactly which part of the platform broke, and we've handed the client
the diagnostic they need.

**Comparison baseline:** the existing waterfall pipeline (5-role
sequential handoff) given the *same* goal, no board, no refinement.
Same repo, same tokens, side-by-side numbers.

---

## What we have today (reusable)

- **5 agent personas** in `agents/` — PO, Scrum Master, Architect, Test, DevSecOps. Each with SOUL / BRAIN / HABITS / MEMORY / HEARTBEAT.
- **Persona loader** — `RoleSpec.from_agent_dir(agents_root, agent_name)`.
- **Waterfall runner** — `run_pull_sprint` (misnamed; it's the 5-role handoff pipeline).
- **Scrum runner v1** — `run_scrum_team_runner.py` (N interchangeable workers, shared wiki, single story at a time).
- **Wiki MCP** — read / grep / write / recent to `wiki/`.
- **Board scaffolding** — `orgos/agile/board.py` (pure READY-gate logic), `orgos/tools/github_board.py` (real GH tool).
- **Compaction runner** — sprint-end wiki delta + memory delta.
- **Governance** — `GatedToolBase`, tier enforcement, spawn engine, audit callback.
- **Benchmark harness** — `scripts/run_benchmark.py` + 3-column HTML report.

## What's missing (the plan)

Ten components. Each is one PR / one task-level chunk.

| # | Component | Why | Effort | Novel? |
|---|---|---|---|---|
| 1 | Persistent codebase per team instance | Fixes the linked-pilot's core flaw. Commits accumulate across stories. | 3-4h | small |
| 2 | Board substrate (`.orgos_board/` state machine) | The multi-story blackboard. | 4-5h | reuse `board.py` |
| 3 | Goal decomposer (PO produces typed stories) | Turns "build auth" into 8 tickets. | 3-4h | new prompt |
| 4 | Story type taxonomy + specialized pull | Architect pulls architecture stories, Test pulls test stories, etc. | 3-4h | small |
| 5 | Planning poker (vote + justify) | Client-requested ceremony. | 3-4h | novel |
| 6 | Refinement discussion (triggered on divergent votes) | Poker's teeth. | 4-5h | novel |
| 7 | Peer review before DONE | Second pair of eyes. Same type filter. | 2-3h | small |
| 8 | Wiki 3-field validation + DoD enforcement | Author + timestamp + source. No unsourced claims. | 3-4h | new invariant |
| 9 | Deployment CLI + multi-instance isolation | `orgos run --repo X --goal Y --team-id T`. Each team gets its own board + worktree. | 4-5h | new entry point |
| 10 | Waterfall comparison runner + report | Same goal, no ceremony, side-by-side. | 3-4h | reuse |
| **Total** | | | **~35-45h / 5-6 days** | |

## Phasing (my recommendation)

**Phase 1 — Bootstrap (Days 1-2, ~15h).** Get end-to-end working without ceremony.
Components 1, 2, 3, 4, 9, 10. **No poker, no discussion, no peer review yet.**
Deliverable: `orgos run --repo <local-clone> --goal "..."` decomposes into
stories, workers pull by type, work accumulates on one branch, waterfall
runs the same goal for comparison. Report shows both.

**Phase 2 — Ceremony (Day 3, ~10h).** Add components 5, 6, 7 IF Phase 1
shows PO is producing under-refined stories that hurt quality. If Phase 1
runs clean, defer ceremony (client can still see the diagram + argument).

**Phase 3 — Governance (Day 4, ~6h).** Component 8 — the wiki 3-field
invariant + DoD hook. This is a client-requested guardrail and deserves
its own phase to test properly.

**Phase 4 — Self-referential demo (Day 5, ~6h).** Use the platform (from
Phases 1-3) to build its OWN Phase 5 features (e.g., "add cross-instance
template rollout"). This IS the demo.

**Phase 5 — Optional polish (Day 6-7 if there's time).** Multi-instance
runtime, template upgrade path, docs, README.

Total: 5-6 days for a full showable product. Phase 1 alone (2 days) is
already demoable.

---

## Design decisions I'm making (unless you object)

### Bootstrap — self-referential doesn't mean chicken-and-egg
The first team runs on the **current partial platform** (Phase 1 code) and
its stories ARE Phase 2 / 3 / 5 components. It can't use features it hasn't
built yet — but it can use everything from Phase 1. Subsequent team
instances launched from the improved template get all features.

### Persistent codebase = one branch per team instance
Each team instance has ONE git worktree, ONE branch. All stories commit to
that branch. When the goal is achieved, we open a single PR (or hand over
the branch). This is the model the client asked for, and it fixes the
linked-pilot's compounding flaw as a side effect.

### Waterfall gets the same decomposed stories, not the same top-level goal
If waterfall's PO tried to scope "build the platform" as one story, the
comparison would be a farce. Fairest is: scrum's PO decomposes; both teams
work through the same decomposed list. That way we're comparing execution
model, not scoping ability.

Alternative I rejected: give waterfall the raw goal and let it choke. Too
easy a win, tells us nothing useful.

### Poker mechanic — vote + justify + trigger-based discussion
- Each specialist gets the story and votes 1|2|3|5|8|13|"?" from Fibonacci.
- Each attaches a 2-sentence justification.
- If votes span > 2 Fibonacci steps AND the justifications reveal
  different assumptions (heuristic: check for keyword divergence on
  nouns and verbs across justifications), trigger 1 round of discussion.
- Each agent gets ONE turn to respond to the disagreement.
- Re-vote. Take the median.
- If still divergent after re-vote, PO re-scopes or splits the story.

**Discussion budget cap:** 500 tokens per agent per turn. Kills runaway.

You said different personas produce different votes — yes, but their
different .md files bias them toward different concerns (architect will
vote higher on integration risk, test will vote higher on test coverage
needed). That's what makes poker useful here, not the numbers themselves.

### Story types — start with 5
`architecture` | `test` | `security` | `feature` | `docs`
Every story gets exactly one type (PO decides during decomposition).
Specialists filter their pull queue by type:
- Architect → `architecture` + `feature`
- Test → `test` + verifies any story's tests
- DevSecOps → `security` + reviews any story's diff for secrets

`docs` and `feature` are pullable by anyone if their primary specialist
is busy — prevents starvation.

### Wiki 3-field validation — enforce at write time
Extend `wiki_write` MCP tool to require `author`, `timestamp`, `source`
in the content OR as separate params. If missing, tool returns an error.
The agent has to include them in its next attempt. This is the safest
enforcement point — anything downstream is cleanup work.

**Bootstrap exception:** the CURRENT `wiki/DECISIONS.md` from prior
sprints has entries without these fields. We keep them (mark as legacy)
but new entries must comply.

### DoD wiki-update — enforced at story-transition time
When a story transitions to `review`, run a check: did this story's
commits touch code that changes a technical or business decision?
Heuristic v1: if the story's type is `architecture` or `security`, OR
the diff touches files in `orgos/agile/` or `orgos/spawn/`, wiki update
is required. If required but not done, story can't reach `done` — back
to `in_progress` with a comment explaining the miss.

Heuristic v2 (later): LLM-scored "does this diff represent a decision
worth recording?"

### Multi-instance isolation — one team, one board, one worktree
Path convention:
```
.orgos_teams/<team_id>/
    board/          # this team's story files
    worktree/       # this team's git worktree
    wiki/           # this team's wiki (or shared root? see open q)
    audit/          # this team's audit trail
```
Team IDs are user-provided or auto-generated. `orgos run --team-id auth-team ...`

### Deployment shape — a Python module + CLI
```
pip install -e .   # from the orgos repo root
orgos run --repo <path-or-url> --goal "<text>" --model deepseek/deepseek-chat --team-id <name>
orgos run --repo <path-or-url> --goal "<text>" --waterfall  # comparison mode
orgos report --team-id <name>  # produces the HTML report
```

`--repo` can be a local path (safe demo) or a git URL (real deploy). For
git URLs, we clone into `.orgos_teams/<team_id>/worktree/`. For local
paths, we `git worktree add` off it.

---

## Open questions I still need answered

Three, and I need answers before touching code. Everything else I've
decided above.

1. **Local clone vs. real GitHub push during the demo?** Rec: local for
   the demo (zero risk of accidental commits to client's real repo);
   real GH URL support baked in but not exercised on the demo call.

2. **Is the demo before or after phase 3 (wiki 3-field enforcement)?**
   Determines whether we build the ceremony (P2) or the governance (P3)
   next after P1.

3. **Waterfall comparison — same decomposed stories or same raw goal?**
   Rec: same decomposed stories. Removes PO from the comparison but
   makes it about execution model (which is what we're actually
   claiming).

---

## What I need to check on the pilot report first

Two harness bugs I spotted in the last run — worth fixing before we
build more, since the new Phase 1 harness will reuse the same error
handling:

**Bug 1: One side's error skips the whole issue.** In
`scripts/run_benchmark.py`, when the `team` side errors, we `continue`
the outer loop, skipping `scrum` and `solo` for that issue. Should be
per-side try/except that only skips that side.

**Bug 2: Timeout guard fires silently.** No log line when the 10-min
guard fires; just a mysterious `ERROR:`. Should log which side timed
out and how long we waited.

Both are 15-min fixes. I'll roll them in with Phase 1.

---

## Risks I want to flag before we execute

1. **Poker may be theater.** If personas vote the same numbers, the
   whole ceremony is expensive noise. Mitigation: measure vote variance
   in Phase 2's pilot; if variance < 1 Fibonacci step across 5 stories,
   we drop poker and use single-PO estimates.

2. **Wiki 3-field enforcement may fight LLMs.** DeepSeek isn't great at
   remembering to include all three fields on every write. Mitigation:
   the enforced tool returns a *specific* error saying which field was
   missing, so the retry is one-shot rather than exploratory.

3. **DoD wiki-update heuristic will misfire.** v1 heuristic will block
   some stories that didn't need wiki updates and let through some that
   did. Mitigation: log misfires, tune weekly. Not a demo-blocker.

4. **Self-referential first run may loop.** If the team's stories
   include "add poker mechanic" and the team is CURRENTLY playing poker
   (Phase 2 on), things get weird. Mitigation: run the self-referential
   demo on a *reset* platform state, so no in-flight ceremony conflicts
   with the ceremony being built.

5. **Waterfall may just win the demo.** If DeepSeek's single-shot is
   good enough that waterfall's overhead is offset by its 5 review
   passes, and scrum's ceremony adds nothing, we ship a demo where the
   comparison is a tie or worse. Fallback narrative: even a tie is a
   win, because scrum's *long-run* value comes from compounding across
   many goals, not one goal. First-goal parity is expected; second-goal
   divergence is where scrum should pull ahead.

---

## Success signals for the demo

1. `orgos run --repo <local-orgos-clone> --goal "add planning poker with vote-and-justify"` runs to completion.
2. The scrum team's PO decomposes into ≥ 4 stories.
3. At least one story is fully DONE with a commit on the worktree branch.
4. Wiki has ≥ 3 entries with all three fields (author, timestamp, source).
5. `orgos run --waterfall --same-goal` runs to completion for comparison.
6. Report shows: cost, time, commits, quality, on both sides.

Nice-to-haves (not blocking):
- The self-referential run's DONE stories are actually merged and used to run a second demo.
- Wiki entries after 5 sprints show meaningful decision blocks (not just changelog lines).

---

## The story I want to be able to tell after this build

> "I gave the scrum team a real goal: extend the platform it runs on. It
> decomposed it into 8 stories. It refined them — one story got split
> because the architect and the test agent disagreed on scope. It worked
> through them across 6 hours and produced a branch with 5 commits, 3
> new modules, and a wiki with 4 sourced decision entries. Then I gave
> the same goal to the waterfall version — no board, no refinement.
> Same tokens, different execution: fewer commits, more churn, one
> unsourced claim in the wiki (which is why the wiki invariant matters).
> The scrum team's branch is ready to merge. This is a product you can
> point at any repo now."

That's the demo I'm building toward. If Phase 1 lands and Phase 2 works,
that story is available.
