# Autonomous Scrum Team — Implementation Roadmap

**Goal:** Implement the autonomous scrum team architecture on top of orgos's governance layer, producing a research platform for measuring how agent teams learn under a Scrum flow-efficiency metric.

**Spec:** [`docs/superpowers/specs/2026-07-07-autonomous-scrum-team-design.md`](../specs/2026-07-07-autonomous-scrum-team-design.md)

**Approach:** Five sequential sub-plans, each producing working software independently. Each plan ships something you can run and grade before starting the next.

---

## Program summary

The old orgos worked-example team (`sprint-lead → PM → engineer → qa-validator → release-manager`, defined in code) is replaced by the autonomous scrum team (`PO / SM / Architect / Test / DevSecOps`, defined by markdown protocol files) running on top of the existing orgos governance layer (`GatedToolBase`, audit logs, rubric grading, HandoffEnvelope, evolve.py). The `replay.py` counterfactual harness is extended to swap entire topologies for dual-team benchmarking. A new flow-efficiency scorer sits alongside `rubric.py` and `dora.py`.

Nothing about the governance layer changes. The domain layer (`orgos/subagents/`, `orgos/agile/`) is where the work lands.

## Plan sequence

| # | Plan | Deliverable | Why this order |
|---|------|-------------|----------------|
| 1 | **Foundation** — layered persona-file loader | `RoleSpec.from_agent_dir(path)` produces a valid RoleSpec from `agents/<name>/*.md` files with layered inheritance | Everything else depends on this. Nothing else runs without an agent identity loader. |
| 2 | **Team topology** — five-role scrum team + envelopes | Sprint runs end-to-end with PO/SM/Architect/Test/DevSecOps replacing the current five roles | The team is what the rest of the platform serves. Get it running before adding the pull-based board or wiki. |
| 3 | **Wiki + board substrate** — filesystem wiki MCP + team board with READY gate | Agents can read the wiki via MCP; PO can draft stories; team refines; stories move DRAFT→REFINEMENT→READY→IN_PROGRESS→REVIEW→DONE; agents pull from top of READY | The persistent memory + coordination substrate. Enables self-organization. |
| 4 | **HEARTBEAT loop + compaction** — self-writing tasks, conductor, sprint-end compaction, scope brake | Agents author their own next task in HEARTBEAT.md; conductor reads it on next boot; sprint-end produces wiki delta + MEMORY delta + retro; scope brake prevents runaway | Real autonomy. Without compaction, context grows unbounded. Without scope brake, autonomy is dangerous. |
| 5 | **Metrics + benchmarking** — Scrum flow metric + swap_topology for dual-team | Every sprint scored by rubric + DORA + flow-metric; `replay.swap_topology(agents_dir_a, agents_dir_b)` produces paired-run reports for N ≥ 20 issues | The measurement layer. Without this we can't defend or falsify the 2-3x productivity claim, which is the publishable contribution. |

## Cross-cutting decisions locked in the spec

These apply to every plan and don't need re-litigating:

- **Persona files are five per agent** (`SOUL.md / BRAIN.md / HABITS.md / MEMORY.md / HEARTBEAT.md`) plus two inherited layers (`_principles/principles.md`, `_worker_base/*.md`).
- **Governance layer is untouched.** `GatedToolBase`, `HandoffEnvelope`, `PermissionTier`, audit callback all stay.
- **No vectorization.** Wiki + memory retrieval via `list / read / grep / recent(n)` MCP tools. Filesystem-backed.
- **Story = shared blackboard.** GitHub issue comments are the team-visible state. `_orgos_memory/` is internal scratch.
- **Sprint cadence: 4h.** `orgos/scheduler.py` shifts to interval-based scheduling.
- **Rubric + DORA + flow-metric all run side-by-side.** No metric replaces another.

## Scope decisions NOT settled yet

- **Exact flow-metric formula.** Working reconstruction in Plan 5 (`takt-time = duration/n_issues; velocity_delta[i] = expected_finish[i] − actual_finish[i]`) but needs external confirmation.
- **Claude Code integration path** (plugin vs subprocess executor). Deferred until Plan 5 ships and the core works.
- **Attribution / IP** on the flow-metric formula. Non-technical decision, deferred.

## Success signals for the whole program

Ordered by strength:

1. A dual-team paired benchmark over ≥ 20 real GitHub issues on the orgos repo shows either replication or falsification of the 2-3x productivity claim under the flow-metric, with both results grounded in orgos's rubric and DORA.
2. The five-role scrum team ships PRs autonomously with all publishing still human-gated; no unauthorised commits.
3. Wiki accumulates real decisions across sprints; DoD-enforcement means wiki freshness never regresses.
4. Sprint-end compaction keeps agent context bounded — evolve.py runs without blowup at N > 100 sprints.
5. External methodology reviewers can inspect the platform end-to-end.

## Where each plan will live

- Plan 1: `docs/superpowers/plans/2026-07-08-persona-file-loader.md` (produced next)
- Plan 2: `docs/superpowers/plans/2026-07-XX-scrum-team-topology.md`
- Plan 3: `docs/superpowers/plans/2026-07-XX-wiki-and-board.md`
- Plan 4: `docs/superpowers/plans/2026-07-XX-heartbeat-loop.md`
- Plan 5: `docs/superpowers/plans/2026-07-XX-flow-metric-benchmarking.md`

Only Plan 1 is written in full at this stage. Plans 2-5 are outlined below as scoping stubs; each becomes a full plan when its predecessor ships.

---

## Plan 2 outline — Team topology

**Files created:**
- `orgos/subagents/scrum_team.py` — `po_role()`, `scrum_master_role()`, `architect_role()`, `test_role()`, `devsecops_role()` factories that load from `agents/`.
- `orgos/agile/envelopes.py` — add `RefinementEnvelope`, `ReadyEnvelope`, `PullEnvelope`; keep existing `BriefEnvelope`, `EngineeringEnvelope`, `GradeEnvelope`, `ReleaseEnvelope`, `RetroEnvelope` where applicable.
- `agents/po/`, `agents/scrum_master/`, `agents/architect/`, `agents/test/`, `agents/devsecops/` — five `.md` files per agent, all validated by Plan 1's loader.
- `agents/_principles/principles.md`, `agents/_worker_base/{soul,brain,habits,memory,heartbeat}.md`.

**Files modified:**
- `orgos/agile/sprint.py` — swap phase routing from `sprint-lead → PM → engineer → qa-validator → release-manager` to the new scrum flow.
- `orgos/agile/rubric.py` — add criteria that fit new envelope shapes.

**Old code deleted:** `orgos/subagents/engineering_team.py` (five old factories), unless retained behind a flag for A/B replay tests. Recommendation: keep as `orgos/subagents/engineering_team_legacy.py` for Plan 5 dual-team baseline.

**Depends on:** Plan 1 (loader).

## Plan 3 outline — Wiki + board substrate

**Files created:**
- `orgos/mcps/wiki_mcp.py` — MCP server exposing `list(path)`, `read(path)`, `grep(pattern, path?)`, `recent(n)`, `write(path, content)`.
- `orgos/tools/github_board.py` — column-aware wrapper around GitHub Projects v2 (or Issues with labels if Projects is too heavy): draft / refine / mark_ready / prioritize / pull_top / update_status. All mutations pass through the audit callback.
- `orgos/agile/board.py` — pure logic for the READY gate: given a story, has each required role signed off? Does it fit size caps?
- `wiki/INDEX.md`, `wiki/DECISIONS.md`, `wiki/architecture/`, `wiki/business/`, `wiki/ADRs/` — initial scaffold.

**Files modified:**
- `orgos/agile/sprint.py` — add refinement phase before pull; pull step reads from GitHub board via `pull_top`.
- `orgos/agile/rubric.py` — new criterion: `wiki_updated_when_required`.
- `agents/*/HABITS.md` — story-start habit: `read INDEX.md + last 3 ADRs + grep for story keywords`.

**Depends on:** Plan 2 (team must exist to refine stories).

## Plan 4 outline — HEARTBEAT loop + compaction

**Files created:**
- `orgos/agile/conductor.py` — reads `agents/<name>/HEARTBEAT.md` on boot; produces `TaskBrief`; validates against scope cap; hands to `spawn()`.
- `orgos/agile/compaction.py` — end-of-sprint pipeline: emit wiki delta, per-agent MEMORY delta, retro heuristic candidates, compacted audit summary. Prunes `_audit_logs/` beyond a window into `_audit_logs/_compacted/`.

**Files modified:**
- `orgos/scheduler.py` — 4h interval; call `conductor.boot(agent)` on each cycle; `compaction.run(sprint)` at end.
- `orgos/agile/rubric.py` — new criterion: `story_completed_matches_story_booted` (scope-drift detection).
- `orgos/spawn/engine.py` — HEARTBEAT-authored briefs go through the same `TaskBrief` validator as PM briefs; publishing tools still gate through `GatedToolBase`.

**Depends on:** Plan 2 (team) + Plan 3 (wiki + board — compaction writes to wiki).

## Plan 5 outline — Metrics + benchmarking

**Files created:**
- `orgos/agile/flow_metric.py` — `takt_time(sprint)`, `velocity_delta(sprint)`, `flow_score(sprint)`. Reads timestamps from PMStore.
- `orgos/agile/paired_run.py` — SHA-pinned paired execution: given issue + two `agents/` directories, freeze repo, run both, collect envelopes + rubric + DORA + flow_score, produce comparison report.

**Files modified:**
- `orgos/agile/replay.py` — new mutation `swap_topology(agents_dir)`; extend existing mutation dispatch.
- `orgos/api.py` + dashboard Lab page — surface paired-run reports.

**Depends on:** all prior plans (needs a working team + board + wiki + compaction to run a benchmark against).

---

**Next step: read Plan 1 (produced now) and decide whether to execute or refine.**
