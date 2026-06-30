# Agile Product Team — orgos worked-example pivot

**Status:** Design — pre-implementation
**Date:** 2026-06-30
**Branch:** `agile-pivot`
**Author:** Thanh, with Claude

---

## Vision

Pivot orgos's worked example from "quant research desk" to "highly performant agile product team." The governance/spawn layer (~10K LOC) is unchanged; the domain layer (~5.7K LOC of quant + options) is deleted. The new worked example is a five-role engineering department that runs nightly sprints on the orgos repo itself (dogfooding), grades itself on DORA metrics, mutates its own role topology under human approval, and supports counterfactual sprint replay.

**Three demo hooks no public framework currently combines:**

- **Hook A — Self-organizing role topology.** `evolve.py` proposes ADD / REMOVE / SPLIT / MERGE role mutations every 5 sprints based on per-role contribution attribution. Human approves each as an ADR; topology mutations are auditable diffs.
- **Hook B — Nightly self-sprint + counterfactual replay.** Sprint runs nightly on the orgos repo from real GitHub issues. The dashboard's "Lab" page replays past sprints with mutated PM briefs (different issue picked, different heuristic injected, different model on Engineer) and shows side-by-side outcomes.
- **Hook C — DORA closed loop.** Deploy Frequency / Lead Time / Change Failure Rate / MTTR are computed nightly from PMStore. DORA signals produce candidate Reflector heuristics that flow through the existing scoring machinery before being injected into future PM briefs.

**The framework to differentiate against** is OpenHands (~78k stars, ICLR 2025, V1 SDK arXiv 2511.03690). OpenHands is single-agent-centric: no role-topology evolution, no DORA loop, no counterfactual replay. That is the orgos gap.

**Architectural canon to cite:** Anthropic's *How we built our multi-agent research system* (Jun 2025) — orchestrator + parallel subagents, explicit objective/output/tool/boundary per subagent. Validates orgos' typed handoffs. Plus the MAST failure taxonomy (Cemri et al., arXiv:2503.13657, Mar 2025) — informs the hard rules in §6.

---

## 1. Architecture

### 1.1 Branch strategy

`agile-pivot` is a clean break from `main`. The quant/options worked-example code is **deleted in the first commit on the branch**, not feature-flagged. The governance layer remains identical to `main`.

### 1.2 Files deleted in commit 1

**Domain code (~5.7K LOC):**

- `orgos/quant/` (entire directory, 23 files, ~4061 LOC)
- `orgos/options/` (entire directory, 5 files, ~1659 LOC)
- `orgos/subagents/quant_supervisor.py`
- `orgos/subagents/quant_strategist.py`
- `orgos/subagents/options_strategist.py`
- `orgos/tools/quant_tool.py`
- `orgos/tools/crypto_tool.py`
- `orgos/tools/options_tools.py`
- `skills/quant/` (entire directory)

**Dashboard:**

- `dashboard/app/journal/`
- `dashboard/app/paper/`
- `dashboard/app/strategist/`
- Any quant-typed API client in `dashboard/lib/`
- `docs/dashboard-desk.png`, `docs/dashboard-journal.png` (regenerate later)

**Tests:** all `tests/test_quant*.py`, `tests/test_options_*.py`, `tests/test_kill_switch.py`, `tests/test_volatility.py`, `tests/test_crypto.py`, `tests/test_icarus_quant.py`, `tests/test_funding.py`. Keep `tests/test_research_sources.py` only if it's not bound to quant queries (verify; keep if generic).

**Docs:** `FINDINGS.md` (quant strategy log). `DEMO.md` and `README.md` are **rewritten** for the agile pivot, not deleted.

**Config:** `config/org.yaml` contents replaced; structure preserved. `config/policy-bank.yaml` untouched.

**Verify before delete:** `orgos/citations.py` — keep if any non-quant code uses it.

**Memory:** the two project memories (`project_orgos.md`, `project_demo_feedback.md`) are updated *after* the branch lands, not before.

### 1.3 Files added

**New domain module — `orgos/agile/`:**

| File | Purpose |
|---|---|
| `sprint.py` | `Sprint` dataclass, `run_sprint()` and `run_nightly_sprint()` entrypoints, PMStore snapshot helpers |
| `dora.py` | `compute_dora(window)` → DeployFreq, LeadTime, ChangeFailureRate, MTTR |
| `intake.py` | GitHub issues → ranked sprint backlog |
| `attribution.py` | Per-role marginal-contribution score from rubric outcomes (ablation-on-replay) |
| `retro.py` | Retro Agent: graded retro markdown + Reflector heuristic candidates |
| `replay.py` | Counterfactual sprint replay (`swap_backlog_pick`, `inject_heuristic`, `swap_role`) |
| `rubric.py` | QA Validator rubric (uses existing `spawn_until` machinery) |
| `envelopes.py` | Seven typed `HandoffEnvelope` subclasses |
| `topology.py` | Mutation proposal trigger rules; emits `Proposal`s for evolve.py |

**New tools (`orgos/tools/`):**

- `github_issue_tool.py` — read GitHub issues (category=read)
- `github_pr_tool.py` — open PR (category=publish, GatedToolBase, human-gated)
- `github_repo_tool.py` — clone / worktree / commit helpers (category=sandbox)
- `dora_tool.py` — surface computed DORA metrics to agents (category=read)
- `mock_pr_tool.py` — non-publishing replacement for replay mode (category=read)

**New subagents (`orgos/subagents/`):**

- `engineering_team.py` — the five RoleSpecs (`sprint_lead`, `product_manager`, `engineer`, `qa_validator`, `release_manager`) plus `retro_agent` (validator, runs in phase 05).

**New skills (`skills/`):**

- `skills/engineering/sprint-planning/` — PM brief construction playbook
- `skills/engineering/code-review/` — review checklist for the Engineer's review step inside `spawn_chain`

**Org config (`config/org.yaml`):** one `engineering` department with the six RoleSpecs above; existing tier policies, MCP wiring, audit/budget machinery reused unchanged.

---

## 2. The seed team

One `Department` called `engineering`. Compiled into a single `spawn(orchestrator=SprintLead, subordinates=[PM, Engineer, QA, ReleaseManager])` call per sprint. The Retro Agent runs as a separate `spawn()` after the main sprint envelope chain.

```
Sprint Lead (orchestrator tier)
  ├─ Product Manager (worker)    → reads GitHub issue → emits TaskBrief
  ├─ Engineer (worker)           → runs spawn_chain(implement → review → test)
  ├─ QA Validator (validator)    → read-only, grades acceptance criteria
  └─ Release Manager (publisher) → GitHubPRTool, human-gated

(After main spawn:)
Retro Agent (validator)          → reads audit log + grades → markdown retro + heuristic candidates
```

**Why MetaGPT-inspired:** maps cleanly onto orgos' existing tier model (no new tier required) and onto the existing `spawn()` orchestrator+subordinates pattern. Retro is separated so it has full visibility of the main chain's audit log.

**Token budget:** `run_budget_tokens=400_000` per sprint (~$5–8 on Sonnet 4.6, configurable in `config/org.yaml`).

**Wall-clock:** hard timeout 90 min on the cron job; per-role `max_execution_time=5400s`.

---

## 3. The nightly sprint loop

Cron-triggered at 02:00 local time via `orgos.scheduler`. One sprint = one `spawn()` of the engineering department + one follow-up Retro `spawn()`.

### 3.1 Phases

Phases [00]–[04] run inside one `spawn()` call (the main sprint). Phases [05]–[07] run as **post-sprint jobs**: phase [05] is a separate `spawn()` of the Retro Agent (separated so it has full audit-log visibility of the main chain); phases [06]–[07] are deterministic SQL/Python jobs with no LLM calls.

```
─── Main spawn() ────────────────────────────────────────────
[00] Intake          GitHub issues + DORA window + Reflector heuristics → ranked backlog
        ↓ BacklogEnvelope (5-10 ranked candidates with size/risk estimate)
[01] PM brief        Sprint Lead picks 1 issue → PM writes TaskBrief
        ↓ BriefEnvelope (objective, success_criteria, acceptance_tests, tool_call_budget, touched_files_allowlist)
[02] Engineer chain  spawn_chain(implement → review → test) on a git worktree
        ↓ EngineeringEnvelope (diff, test results, files touched, commit SHA)
[03] QA gate         Validator runs acceptance tests against the branch
        ↓ GradeEnvelope (per-criterion pass/fail, rubric score)
[04] Release         Release Manager opens PR via GitHubPRTool (creates approval request; non-blocking)
        ↓ ReleaseEnvelope (PR URL, status, requires_human_approval=true)
─── Post-sprint jobs ────────────────────────────────────────
[05] Retro           Separate spawn() of Retro Agent — reads audit log + grades
        ↓ RetroEnvelope (retro.md, candidate heuristics, attribution scores per role)
[06] DORA snapshot   compute_dora(window=14d) → write to PMStore  (no LLM)
[07] Topology check  Every 5 sprints: attribution.py → evolve.py proposes role mutations  (no LLM)
        ↓ ADR drafts → human approval queue
```

**On human approval at phase [04]:** opening the PR is non-blocking — the Release Manager records the PR URL and `requires_human_approval=true` in the envelope, then the sprint proceeds to phases [05]–[07]. The human handles the PR approval asynchronously through the normal GitHub UI. A sprint is considered `completed` when QA passes AND the Release envelope was either resolved (approved-merged OR declined) by the time the next nightly sprint fires; otherwise it carries `pending_release` until the human acts.

### 3.2 Hard guarantees (encoded in code, not prompts)

- Capped delegation depth = 2. Audit callback raises `DelegationDepthExceeded` on a third nested spawn.
- Terminal grader on every spawn. `run_sprint()` refuses to mark a sprint `completed` unless the QA envelope passes the rubric AND the Release envelope was either approved-and-merged OR explicitly skipped by the human.
- All handoffs are typed `HandoffEnvelope` subclasses (Pydantic schemas in `envelopes.py`).
- Append-only PMStore writes; sprint `run_id` ties every row to one sprint.
- Git isolation: Engineer chain works in `.sprints/<sprint_id>/` git worktree. Only Release Manager touches origin. PRs target `main` from `agile/<sprint_id>` branch.
- Failure path: any envelope returning `status="failed"` or `"blocked"` short-circuits to Retro (failed sprints still produce retros — that's where Hook A learns most).

---

## 4. Hook A — Self-organizing role topology

### 4.1 Attribution (per-sprint, deterministic, zero LLM)

For each role R in a completed sprint, compute the marginal contribution by ablation-on-replay: take the recorded sprint trace, mask R's handoff, and grade the rubric outcome with R removed. The drop in rubric score is R's contribution. This is a 2-player Shapley approximation — same trick used by Stochastic Self-Organization in MAS (arXiv:2510.00685).

Output: `{role_name: contribution_score}` written to a new PMStore table `role_attribution(sprint_id, role_name, score, rubric_baseline, rubric_ablated, created_at)`.

### 4.2 Mutation proposals (every 5 sprints)

`evolve.py` reads the rolling 5-sprint attribution window and emits typed `Proposal`s using existing types plus two new ones:

| Pattern | Proposal |
|---|---|
| Role's contribution score < 0.05 for 3 consecutive sprints | `REMOVE_ROLE` |
| Role's QA failure mode clusters on one tag (e.g., "missing canary") | `SPLIT_ROLE` (new) |
| Two roles' handoffs always pass through each other unchanged | `MERGE_ROLES` (new) |
| Recurring blocker tag has no role owning it | `ADD_ROLE` with `expire_at` = now + 30d (uses existing temporary-contract feature) |

### 4.3 Human approval

Every proposal is written as an ADR row in a new PMStore table `adrs(id, sprint_id, kind, before_yaml, after_yaml, rationale, status)`. The dashboard `/team` page shows the YAML diff; human approves → `config/org.yaml` is patched and committed under `git_user=orgos-evolve`. The system **never auto-applies**.

### 4.4 Demo narrative example

> "Sprint 7's QA grades clustered on missing canary deploys (3/5 failures tagged `no-canary`). Proposal: SPLIT_ROLE Engineer → Implementer + ReleaseEngineer, with ReleaseEngineer owning the canary acceptance test. Approved by Thanh; committed as ADR-014; next sprint runs with the new topology."

---

## 5. Hook B — Counterfactual sprint replay

### 5.1 Snapshot model

At phase [01] each sprint, write `_sprints/<sprint_id>/snapshot.json` containing: PM brief, backlog candidates, current Reflector heuristics, seed RNG, model identifiers per role. The audit log captures everything else. **Snapshot + audit log + PMStore = enough to deterministically reconstruct any past sprint's inputs.**

### 5.2 Replay entrypoint

`replay_sprint(sprint_id, mutation: BriefMutation) → SprintResult`

Mutations supported in this branch:

- `swap_backlog_pick(new_issue_id)` — "what if PM had picked task B?"
- `inject_heuristic(heuristic_text)` — "what if last sprint's lesson had already been learned?"
- `swap_role(role_name, alt_rolespec)` — "what if Engineer were on a smaller model?"

Replays run on a parallel `git worktree`; rows are tagged with `parent_sprint_id` and `mutation_kind` in PMStore.

### 5.3 Tier isolation (replays never publish)

`GitHubPRTool` is `publish` category and only granted to Release Manager. Replay mode swaps it for `MockPRTool` (category=`read`). The existing `_enforce_tier()` in `spawn/engine.py` rejects any publish-category tool call from a replayed sprint — replay safety is enforced by the tier system, not by replay code.

### 5.4 UI

`/lab/[sprint_id]` — pick a sprint, pick a mutation, click run. Original sprint's envelope chain on the left, replayed chain on the right, rubric-score deltas highlighted per phase, total token cost of the replay shown. "Run another mutation" keeps the original frozen.

Cost guard: replays count against the same `run_budget_tokens` cap as live sprints; `/lab` shows projected cost before the run button enables.

---

## 6. Hook C — DORA closed loop

### 6.1 Metrics (zero LLM, all SQL over PMStore)

- **Deploy Frequency** = `count(git_ops where operation='pr_merged' and pushed=1) / window_days`
- **Lead Time** = `median(git_ops.created_at for pr_merged - tasks.created_at for the originating task)`
- **Change Failure Rate** = `count(test_runs where passed=0 within 24h of pr_merged) / count(pr_merged)`
- **MTTR** = `median(time from first failing test_run on main → next passing test_run on same surface)`

Computed nightly; written to a new PMStore table `dora_snapshots(window_days, deploy_freq, lead_time_p50, cfr, mttr_p50, tier, created_at)`. Each metric tagged Elite/High/Medium/Low per DORA 2025 thresholds.

### 6.2 Reflector bridge

New function `dora_to_heuristic_candidates(snapshot) → list[Heuristic]`. Trigger rules:

| DORA signal | Candidate heuristic |
|---|---|
| CFR rising 3 snapshots in a row | "DoD must include canary + rollback step" |
| Lead Time > 7d median | "PM should split any task > 1 day estimate" |
| Deploy Freq < 1/week | "Engineer must commit within 2h of starting task" |
| MTTR > 4h | "Add hotfix-ready acceptance test in QA brief" |

Candidates flow through Reflector's **existing** scoring/use_count machinery — they're not auto-injected. Reflector decides whether a candidate beats the heuristic-retention threshold; if so, future PM briefs receive it as the existing constant-cost bullet list.

### 6.3 Demo narrative example

> "Current team grade: Medium on Change Failure Rate. Last week the Reflector adopted heuristic H-031 ('DoD must include canary'). This week's CFR is down 22%. H-031 promoted from candidate to active."

---

## 7. UI surface

### 7.1 Pages

| Page | Purpose |
|---|---|
| `/` (rewritten) | Team scoreboard: DORA grade hero panel; 14-sprint streak; WIP; active heuristics count; next-sprint countdown |
| `/sprints` | Sprint board: list of sprints with id/date/issue/grade/PR; click into detail (vertical envelope chain) |
| `/team` | Force-directed role topology graph + ADR feed (Hook A surface) |
| `/lab` | Counterfactual sprint lab: pick sprint, pick mutation, side-by-side run (Hook B showpiece) |
| `/dora` | DORA time series + candidate heuristics queue + active heuristics ledger (Hook C credibility) |

Generic pages preserved: `/org`, `/calendar`, `/logs`, `/policies`, `/projects`, `/proposals`, `/requests`.

### 7.2 API endpoints

| Endpoint | Source |
|---|---|
| `GET /api/sprints` | PMStore: list sprints, filter by status/date |
| `GET /api/sprints/{id}` | PMStore + audit log: full envelope chain |
| `POST /api/sprints/run-now` | trigger `run_nightly_sprint()` on demand (admin gate) |
| `GET /api/dora` | dora_snapshots over a window |
| `GET /api/team/topology` | parse `config/org.yaml` + last sprint's attribution scores |
| `GET /api/team/adrs` | list ADR proposals |
| `POST /api/team/adrs/{id}/approve` | applies the YAML diff under git_user=orgos-evolve |
| `GET /api/heuristics` | Reflector heuristic ledger + candidates |
| `POST /api/lab/replay` | `replay_sprint(sprint_id, mutation)` |
| `GET /agent-card.json` | static A2A Agent Card (stub, see §8) |

API endpoints deleted: all of `quant_router` in `orgos/quant/api.py`.

### 7.3 Frontend stack notes

Next.js App Router + Tailwind (existing). Topology graph uses `react-force-graph-2d` (≈30KB gz). DORA time series reuses whatever charting library `/projects` already uses (verify; likely Recharts).

---

## 8. A2A protocol stub

`/agent-card.json` returns a static Google A2A Agent Card describing the Sprint Lead orchestrator:

- `name`: "orgos-engineering"
- `description`: text
- `skills`: each of the five subordinate roles + Retro Agent surfaced as A2A skills, with their `HandoffEnvelope` subclass schemas as input/output JSONSchema.

No task lifecycle, no OAuth — just the discovery surface. Phase 2 (out of scope for this branch): full A2A task lifecycle + OAuth2 so external A2A agents can trigger sprints.

This is the minimum to credibly demo to enterprise viewers who'll check for A2A by mid-2026 (Linux Foundation, 150+ orgs as of April 2026).

---

## 9. MAST-informed hard rules

Encoded in code, not prompts:

1. **Capped delegation depth = 2.** New `_delegation_depth` counter in the audit callback; third nested spawn aborts with `DelegationDepthExceeded`.
2. **Terminal grader on every spawn.** `run_sprint()` refuses `completed` without QA pass + Release resolved.
3. **Typed handoffs as wire protocol.** Seven `HandoffEnvelope` subclasses; existing fail-closed parser rejects malformed payloads.
4. **Append-only Reflector heuristics with ADRs.** Heuristic retirement also writes an ADR row.
5. **Replays are tier-isolated.** Publish-category tools rejected from replays by `_enforce_tier()` — not by replay code.
6. **`expire_at` on every evolve-proposed role.** Default 30d. Forces deliberate renewal.

---

## 10. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Dogfooding agent breaks main | Sprint Lead can only push to `agile/<sprint_id>`; merging to main requires human PR approval (Publisher tier + GatedToolBase). |
| Shapley attribution is noisy with 1 sample | 5-sprint rolling window; mutation proposals require 3 consecutive low-contribution sprints. |
| Token blowup on replays | Same `run_budget_tokens` cap as live sprints; `/lab` UI shows projected cost before the run button enables. |
| Reflector heuristics conflict | Existing scoring/use_count machinery already handles this — losers age out. |
| Sprint hangs | Existing `max_execution_time=5400s` per role; cron has 90 min wall-clock timeout. |
| GitHub API rate limits | Shared rate-limit-aware client; sprint aborts with `RateLimited` envelope when exhausted. |
| Issue intake picks junk | Label allowlist (`good-first-issue`, `agent-eligible`) by default; configurable. PM has `tool_call_budget=3` for backlog inspection. |
| Demo loses narrative because nothing fails | Keep one synthetic "hard" issue in the demo repo expected to trip a small model — produces the retro and heuristic-learning moment. |

---

## 11. Test strategy

### 11.1 New unit tests (target: ~60)

- `tests/agile/test_dora.py` — DORA computations against seeded PMStore fixtures.
- `tests/agile/test_attribution.py` — ablation-replay attribution against canned sprint traces.
- `tests/agile/test_envelopes.py` — each typed envelope variant round-trips through `output_pydantic`.
- `tests/agile/test_intake.py` — issue ranker on a fixture of mock GitHub issues.
- `tests/agile/test_replay.py` — replay determinism; replay tier isolation (publisher tool rejected).
- `tests/agile/test_topology_proposals.py` — each trigger rule produces the expected `Proposal`.
- `tests/agile/test_dora_reflector_bridge.py` — each DORA signal produces the expected candidate heuristic.
- `tests/agile/test_delegation_depth.py` — third nested spawn raises `DelegationDepthExceeded`.

### 11.2 New integration tests

- `tests/agile/test_sprint_loop_smoke.py` — full sprint on a tiny fixture repo with a cheap deterministic LLM (`ollama/llama3.2` if available, otherwise mocked). Asserts all seven envelopes present, audit log expected entries, no tier violations.
- `tests/agile/test_dogfood_dry_run.py` — runs intake + PM brief on the real orgos repo, asserts a `BriefEnvelope` is produced, asserts `tool_call_budget` honored. Marked `@pytest.mark.network`.

### 11.3 Preserved tests

All `tests/test_spawn_*.py`, `tests/test_handoff_*.py`, `tests/test_tier_policy*.py`, `tests/test_audit*.py`, `tests/test_evolve*.py`, `tests/test_reflect*.py`, `tests/test_memory*.py`, `tests/test_pm.py`, `tests/test_departments.py`, `tests/test_scheduler.py` remain green throughout — the pivot must not regress the governance layer.

### 11.4 QA rubric (initial)

In `orgos/agile/rubric.py`, used by `spawn_until`:

- All acceptance tests in the PM brief pass.
- No unrelated test files modified.
- Touched files ⊆ PM-declared `touched_files_allowlist`.
- Diff size ≤ 400 LOC (configurable per sprint).
- Reviewer envelope from `spawn_chain` has `status="completed"`.

---

## 12. Sequencing

**~4 weeks of focused work, 6 phases.**

| Phase | Deliverable | Days |
|---|---|---|
| **0. Cleanup** | Branch `agile-pivot`; delete quant/options/subagents/tools/skills/tests/pages; rewrite README/DEMO; gut `config/org.yaml`; CI green on governance tests only. | 1 |
| **1. Skeleton sprint** | `orgos/agile/sprint.py` + 6 RoleSpecs + 7 envelope schemas + `BashTool`-only Engineer (no GitHub yet); runs one sprint on a fixture repo to completion. | 4 |
| **2. GitHub integration + dogfood** | `github_issue_tool`, `github_pr_tool` (gated), `intake.py`, real run on orgos repo with `agent-eligible` label. PR opens on `agile/<sprint_id>` branch, human-gated to main. | 4 |
| **3. Hook C — DORA loop** | `dora.py`, `dora_to_heuristic_candidates`, `/dora` page, dora_snapshots table. Nightly cron wired. | 3 |
| **4. Hook A — self-org topology** | `attribution.py`, evolve.py extensions, ADR table, `/team` page with topology graph + ADR feed. | 5 |
| **5. Hook B — counterfactual replay** | Snapshot model, `replay.py`, `MockPRTool`, `/lab` page with side-by-side UI. | 5 |
| **6. Polish + A2A stub + demo prep** | `/agent-card.json`, `/sprints` page, `/` rewrite, demo script, 1 synthetic "hard" issue, run 5 sprints on dogfood to seed the demo data. | 3 |

**Critical path:** Phase 1 → 2 → 4 (Hook A is the biggest engineering lift). Hooks B and C are parallelizable after Phase 2 if a second engineer is available.

**Demo-readiness milestone:** end of Phase 4 = defensible demo (DORA + self-org). End of Phase 5 = wow demo. End of Phase 6 = polished.

**Steady-state cost:** ~$200/mo (nightly sprint at $5–8 × 30). Replays during demo prep ≈ $50 one-time.

---

## 13. Out of scope for this branch

Documented now to prevent scope creep:

- Full A2A task lifecycle + OAuth2 (stub only this branch)
- Multi-repo orgos-points-at-customer-repo workflow
- Semantic memory / embeddings on OrgMemory
- Voice / spoken standups
- Multi-department agile org (e.g., engineering + design + ops). This branch ships one department; the framework already supports multi-department from `main`.
- N-player Shapley (this branch ships the 2-player marginal approximation)
- SWE-Bench / TheAgentCompany benchmark runs (interesting but a separate research branch)

---

## References

- MetaGPT — Hong et al., arXiv:2308.00352 (Aug 2023)
- ChatDev — Qian et al., arXiv:2307.07924 (Jul 2023)
- ALMAS — arXiv:2510.03463 (Nov 2025)
- *Why Do Multi-Agent LLM Systems Fail?* (MAST) — Cemri et al., arXiv:2503.13657 (Mar 2025)
- Anthropic — *How we built our multi-agent research system* (Jun 2025)
- Stochastic Self-Organization in MAS — arXiv:2510.00685 (Oct 2025)
- AgentNet — arXiv:2504.00587 (Apr 2025)
- AFlow — arXiv:2410.10762 (ICLR 2025)
- SWE-Lancer — arXiv:2502.12115
- OpenHands V1 SDK — arXiv:2511.03690
- Google A2A protocol / Linux Foundation announcement (Apr 2025)
- 2025 DORA Report (Google Cloud)
- TheAgentCompany — arXiv:2412.14161
- Team Topologies — Skelton & Pais (2019)
- Accelerate / DORA — Forsgren, Humble, Kim (2018)
- Marty Cagan — Empowered Teams, Dual-Track Agile (SVPG)
