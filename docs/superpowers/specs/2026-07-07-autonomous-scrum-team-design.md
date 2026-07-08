# Autonomous Scrum Team — feasibility notes for orgos

**Status:** Exploration — pre-brainstorm.
**Date:** 2026-07-07 (initial), 2026-07-08 (revised)
**Author:** Thanh, notes captured with Claude
**Related:** [`2026-06-30-agile-product-team-design.md`](2026-06-30-agile-product-team-design.md), `DESIGN.md`

---

## 0. The reference model

A five-agent autonomous scrum team defined by markdown protocol files. Agents: PO ("Morgan"), Scrum Master ("River"), Architect, Test, DevSecOps. The three delivery agents (Architect, Test, DevSecOps) share a common Worker Base and specialize on top of it. Sprint efficiency is measured against Scrum flow-efficiency metrics (takt-time / velocity-delta lineage) rather than pure output count.

**Three-layer inheritance architecture:**

- **Layer 1 — Agent Principles** (every agent): delivery philosophy, three universal identity beliefs (*Reasoner Not Executor*, *I Leave Traces*, *I Work With What I Have*), universal habits (memory stewardship, adaptive error handling, label discipline).
- **Layer 2 — Worker Base** (Architect + Test + DevSecOps only): shared worker SOUL/BRAIN/HABITS/MEMORY/HEARTBEAT — the "captain-and-swarm" model where one worker captains a story and the rest contribute to planning and review.
- **Layer 3 — Specific Agent Files** (per agent): five files each — `SOUL.md` (identity), `BRAIN.md` (role reasoning), `HABITS.md` (trigger → response → outcome + anti-patterns), `MEMORY.md` (cross-sprint knowledge), `HEARTBEAT.md` (current operational state).

**Boot merging** concatenates layers 1 → 2 → 3 with universal principles first and HEARTBEAT last — deliberately exploiting the U-shaped attention profile of LLMs (recency + primacy). Content at the *end* of context gets highest attention; putting HEARTBEAT there means current operational state dominates reasoning.

**Instance files + self-directing loop.** `MEMORY.md` and `HEARTBEAT.md` are per-deployment instance files. At end-of-session, the agent **writes its own next task into HEARTBEAT.md**. A conductor reads that and hands it back as the boot instruction next session. Agents set their own agenda; no external orchestrator is required for task assignment.

Additional constraints: model-agnostic, runs alongside Claude Code, publishable.

### 0.1 Operational model

**Sprint cadence: 4 hours at the start.** Short sprints for fast learning; each boundary is a compaction event. `orgos/scheduler.py` shifts from nightly to interval-based (`run_sprint_on_interval(4h)`). Tradeoff: ceremony cost is a real % of each sprint at 4h, so compaction/DoD/wiki-update must be cheap.

**Wiki as durable memory.** Filesystem-backed (`wiki/`) with hierarchy: `INDEX.md`, `DECISIONS.md` (chronological ADRs), `architecture/`, `business/`, `ADRs/`. Agents access via an MCP exposing `list / read / grep / recent(n)`. **No vectorization** — the corpus is small, precision matters more than recall, structured navigation preserves hierarchy, and every serious code-agent system (Claude Code, aider, Cursor, Devin) has walked away from vector RAG toward grep+read. Wiki updates are a DoD-enforced rubric criterion; skipping wiki updates fails the sprint.

**Story as shared context.** GitHub issue comments are the team-visible blackboard (decisions, blockers, handoffs). `_orgos_memory/` remains for internal scratch. New tool wraps GitHub issue commenting so all state changes flow through the audit callback.

**Team board with READY gate and pull-based work assignment.** The board has columns: `DRAFT → REFINEMENT → READY → IN_PROGRESS → REVIEW → DONE`. Flow:

1. **PO drafts** a story from the backlog (title, acceptance criteria, initial size estimate).
2. **Team refines** — each delivery agent (Architect, Test, DevSecOps) adds role-specific perspective (design impact, test approach, security/deployment concerns). Each adds a labelled comment on the issue.
3. **Grooming session** — the team collectively marks the story `READY` when all role perspectives have signed off AND the story fits size caps (≤ 5 files, ≤ 400 LOC).
4. **Prioritization** — PO orders `READY` stories into the ranked backlog.
5. **Pull, don't push.** Any delivery agent may pull the top `READY` story, mark itself captain, and begin work. No orchestrator assigns tasks.

This is a real architectural shift from the current orgos model where `sprint-lead` picks the issue and routes. In the new model, the sprint lead role dissolves into the PO+SM ceremony; agents self-select from a curated ready backlog.

**Self-organizing with scope brake.** Because agents pull their own work and HEARTBEAT can author next tasks, there must be a hard scope brake:
- Every self-authored task must produce a valid `TaskBrief` that passes the same size caps as PM-authored briefs.
- Rubric criterion: story-completed must match story-booted; mid-sprint scope drift fails the sprint.
- Any publishing tool still routes through `GatedToolBase` — self-organization does not extend to shipping without gates.

**Sprint-end compaction event.** At every 4h boundary, the sprint produces:
1. Wiki delta (edits to `wiki/*.md`).
2. Per-agent MEMORY delta (append to `agents/<name>/MEMORY.md` — durable).
3. Retro heuristic candidates (existing `retro.py`).
4. Compacted audit summary (raw log stays in `_audit_logs/` for forensics but is not loaded on next boot).

Compaction directly addresses the demo-feedback item ("self-evolving system context blowup at scale") — bounded context per boundary makes evolve.py sustainable.

---

## 1. Why this is a fit for orgos specifically

The existing orgos worked example (`docs/superpowers/specs/2026-06-30-agile-product-team-design.md`) already ships:

- A five-role engineering team defined in `orgos/subagents/engineering_team.py`.
- Counterfactual sprint replay (`orgos/agile/replay.py`) — same issue, mutated brief/heuristic/model.
- Per-role attribution (`orgos/agile/attribution.py`) — marginal contribution scoring already exists.
- DORA closed loop (`orgos/agile/dora.py`) — Deploy Freq / Lead Time / CFR / MTTR.
- Rubric-graded outputs (`orgos/agile/rubric.py`) — deterministic grading outside the LLM.

The reference model's ideas map onto orgos primitives with **surprisingly little new plumbing**. This is the honest headline: most of the changes are a data-format change and a topology swap on top of what's already there, not a rewrite.

| Reference-model idea | Where it lands in orgos today | Effort |
|---|---|---|
| Layered persona files (Principles → Worker Base → Specific agent, five files each) | `RoleSpec` is currently flat code in `engineering_team.py`. Add a loader that concatenates layers 1→2→3, plus `RoleSpec` inheritance (currently absent). Universal principles slot naturally into `config/policy-bank.yaml` as the source of Layer 1. | Medium: loader + schema + inheritance. Layer 1 aligns with existing policy-bank; Layers 2-3 need directory convention (`agents/_worker_base/*.md`, `agents/<name>/*.md`). |
| Five-role scrum team (PO / SM / Architect / Test / DevSecOps) | Replaces the current five-role team (`sprint-lead / PM / engineer / qa-validator / release-manager`) with the reference-model five. Sprint phase machinery in `orgos/agile/sprint.py` already routes phases; role factories are swapped, not the routing. | Medium: new role factories in `subagents/`, new envelope types in `agile/envelopes.py` if the outputs differ, updated rubric criteria in `agile/rubric.py`. |
| Self-writing HEARTBEAT loop | `orgos/scheduler.py` already runs the nightly sprint; extend it to read the agent's HEARTBEAT.md as the boot instruction and to accept HEARTBEAT writes at session end. Governance-critical: HEARTBEAT writes need to pass through the audit callback (`make_audit_callback`) so the agent's self-authored agenda is logged, and any HEARTBEAT-driven action that publishes must still route through `GatedToolBase`. | Medium-high: this is the load-bearing new architecture. Also the highest-risk piece — a runaway agent could keep authoring bigger scopes for itself if there's no scope brake. |
| Dual teams on same GitHub issue | `replay.py` already does "same issue, different variable." Extend the mutation set from `swap_backlog_pick / inject_heuristic / swap_role` to `swap_topology` (load a different `agents/` directory). | Medium: machinery exists; SHA-pinning + paired-run bookkeeping is the new work. |
| Sprint efficiency metric (Scrum flow-metric lineage) | New scorer in `orgos/agile/flow_metric.py` alongside `rubric.py` and `dora.py`. Working operationalization: takt-time = sprint_duration / n_issues; velocity_delta[i] = expected_finish[i] − actual_finish[i]; aggregate into flow_score. All input data (sprint start/end, merge timestamps) already in PMStore. | Small once the exact formula is confirmed. |
| Model-agnostic | Already true. CrewAI + litellm; `RoleSpec.model` is per-role. No work. | Zero. |
| Run alongside Claude Code (the CLI) | New. Wrap Claude Code as a *tool* the framework can invoke, or as an *executor* for a specific role (subprocess with structured I/O). Both are reasonable. | Medium: needs a `ClaudeCodeExecutor` role backend and I/O contract. |
| Publishable | The governance layer + dual-team benchmarking is the differentiator. See §4. | Comms/positioning work, not code. |

---

## 2. Feasibility assessment — the three things worth thinking hard about

### 2.1 Layered persona files vs a single system prompt

At first glance splitting a system prompt into five files across three inherited layers looks like ceremony. But there's a real reason to keep the layers separated:

- **soul** = stable identity. Rarely edited. Sets voice, values, refusal patterns.
- **brain** = skills, tools, decision procedures. Edited when capabilities change.
- **habits** = trigger → response → outcome patterns.
- **memory** = durable cross-sprint knowledge.
- **heartbeat** = current operational state, self-authored by the agent.

The value of splitting them is **change management**. When the org evolves (`orgos/evolve.py` already proposes ADD/REMOVE/SPLIT/MERGE mutations), you want to be able to mutate a *brain* without disturbing a *soul*, and diff those separately in review. Inheritance lets a shared Worker Base change apply to all delivery agents at once without touching per-agent files.

Persona-file-as-primitive is an emerging pattern in the field (see `soul.md` / OpenClaw-style layouts). The specific claims that hold up empirically:
- Persona drift after ~8 turns is mathematically guaranteed (Li et al., COLM 2024) — persistent identity files help re-anchor.
- Personas have "largely random" effects on factual accuracy (Zheng et al., EMNLP 2024) — do not over-claim capability gains.
- The real benefits are brand consistency, tone alignment, and behavior traceability — human ergonomics and audit surface, not raw model capability.

**Verdict:** worth doing for change management and audit surface. Do not claim it makes agents smarter.

**Risk:** without a schema, files drift into free-form vibes and become unauditable. Mitigation: required sections per file type + strict frontmatter validation at load time (implemented in `orgos/spawn/persona_loader.py`). The loader also treats user-editable persona files as a **trust boundary** — the same prompt-injection posture as any other user-supplied content.

### 2.2 Sycophancy risk in shared Worker Base

The three delivery workers inherit the same Worker BRAIN / SOUL / HABITS. On questions downstream of that shared reasoning ("how do we approach this story"), they will tend to agree. Research on multi-agent debate shows homogeneous debate can yield *lower* accuracy than single-agent baselines when sycophancy dominates (arXiv:2509.23055). Related work: stance homogenization (arXiv:2606.03032), isolated self-correction beating unguided debate (arXiv:2605.00914).

The reference model's specialization on top of the Worker Base mitigates this — Architect / Test / DevSecOps *do* have distinct BRAIN/HABITS at Layer 3 — but the shared substrate is real. Recommended guardrails:

- **Cross-model requirement.** Force different providers (Claude on one seat, GPT/Gemini on another) so the seats do not literally share weights.
- **Explicit disagreement in refinement.** During the DRAFT → REFINEMENT transition, require each role to name at least one substantive concern about approach; if all three roles produce agreement-only comments, the refinement is re-spawned with different seeds.
- **Attribution refactor.** Current `orgos/agile/attribution.py` assumes distinct role labels on distinct artifacts. For a team where any delivery role can captain any story, attribution needs to move to per-*artifact* labels (who authored this file, this test, this fix) rather than per-*role*.

**Verdict:** high-value setup, but attribution and diversity-injection need explicit design.

### 2.3 Dual teams on the same issue — cost and confound control

The mechanics are cheap: `swap_topology` in the replay module. The hard parts are:

- **Cost.** 2x LLM spend per sprint. Fine at low volume; needs budget caps + a "run dual on N% of sprints" knob to be sustainable.
- **Confounds.** If Team A picks issue X on Monday and Team B runs on Tuesday, main has moved. Solution: replay Team B against the exact repo SHA Team A saw. `replay.py` already thinks in terms of frozen inputs; extend it.
- **Statistical honesty.** Two runs on one issue is an anecdote, not a comparison. Need to plan for N ≥ 20 paired issues before claiming a winner. Publish the methodology up front. Existing SWE-bench work explicitly calls out "confounded scaffold-model effects" (arXiv:2604.03515) — SHA-pinned paired trials are a real gap in the literature.

**Verdict:** feasible; the harness needs to enforce SHA-pinning and paired-run bookkeeping. This is the actual publishable contribution.

---

## 3. Model-agnostic + runs alongside Claude Code

Two distinct claims often conflated:

**Model-agnostic** — orgos already is. `RoleSpec.model` accepts any litellm-supported provider. No work needed.

**Runs alongside Claude Code (the CLI)** — new and more interesting. Two viable shapes:

- **Claude Code as a role backend.** A `ClaudeCodeExecutor` that spawns the Claude Code CLI in a subprocess to fulfil a role. Structured I/O via the CLI's stream mode. Pro: users get Claude Code's toolbelt for free. Con: CLI is stateful and less scriptable than the API.
- **orgos as a Claude Code plugin.** Publish orgos as an installable Claude Code plugin (skills + a `/orgos` command). Users trigger a dual-team sprint from within a Claude Code session; orgos manages the crew and returns results. Pro: distribution is trivial. Con: framework's governance model has to survive being nested inside another orchestrator.

**Recommendation:** ship *both*. The plugin path is the higher-leverage one for adoption.

---

## 4. Is this publishable?

Yes, and the framing writes itself:

> *"OpenHands and CrewAI let you build one team. We let you build two teams and find out which topology performs better on the same work. Agents are defined as five-file layered markdown personas; the org can mutate its own topology and we measure the effect."*

The specific claims to publish, in order of novelty:

1. **Dual-team benchmarking on the same GitHub issues, with SHA-pinned replay.** This is the headline. No public framework does this today.
2. **Layered persona-file inheritance (universal → worker base → specific), with topology mutations as diffs on those files.** Agent-as-config is common; agent-as-*layered-inheritance* is a real position.
3. **Pluggable success metrics** — Scrum flow-efficiency, orgos rubric, DORA — running side-by-side on identical runs. Where they disagree is the interesting result.

Citation targets: Anthropic's multi-agent post (Jun 2025), MAST failure taxonomy (Cemri et al., arXiv:2503.13657), OpenHands (ICLR 2025), sycophancy-in-multi-agent-debate (arXiv:2509.23055), SWE-bench scaffold-taxonomy (arXiv:2604.03515).

---

## 5. Risks and open questions

- **Metric-formula confirmation.** The takt-time / velocity-delta reconstruction is a working guess. Confirm the exact aggregation before running the benchmark.
- **Attribution refactor.** `attribution.py` must move from per-role to per-artifact before dual-team benchmarks are meaningful.
- **Cost governance.** Dual runs double spend. Need a budget cap in `sprint.py` and a "sample N% of issues for dual runs" policy.
- **Claude Code plugin distribution.** Confirm the plugin surface supports long-running crews, HITL gates, audit log persistence.
- **Self-writing HEARTBEAT scope brake.** Runaway-agenda risk is real; scope validation on HEARTBEAT-authored briefs is load-bearing.
- **Sycophancy in shared Worker Base.** Cross-model pairing and disagreement-required refinement are the guardrails; without them the dual-team benchmark may show homogeneous teams underperforming.

---

## 6. Recommended next steps

1. **Confirm the exact flow-metric formula** — blocks §2.3's headline result.
2. **Prototype `swap_topology`** in `replay.py` against 5–10 backlog issues before committing to N ≥ 20.
3. **Decide plugin vs executor** for the Claude Code integration. Plugin first for distribution.
4. **Draft a positioning post** only after real dual-team results exist.
