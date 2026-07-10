# Handoff — autonomous scrum team direction

Read this if you're picking up the autonomous-scrum-team direction in a new session, with a new model, or in a different agentic harness (Claude Code, OpenCode, Cursor agent, etc.). It's the "start here" pointer that survives context loss across sessions.

## Current state (as of last update)

- **Repo branch:** `main`. Plan 1 landed via fast-forward.
- **Latest program commit:** the persona-file loader + docs + `agents/` scaffold.
- **Tests:** `pytest tests/spawn/test_persona_loader.py` — 23/23 pass. Full spawn suite: 135/139 (four pre-existing DeepSeek-API failures unrelated to this program; they fail on `main` before this branch too).

## What's done

- **Plan 1 — Foundation.** `RoleSpec.from_agent_dir(agents_root, agent_name)` loads three-layer markdown persona files into a validated `RoleSpec`. Governance layer (`GatedToolBase`, `HandoffEnvelope`, `TierPolicy`, `spawn()`, `spawn_chain()`) untouched. See `docs/superpowers/plans/2026-07-08-persona-file-loader.md` for the executed plan.

## What's next

Plans 2-5 are outlined in the roadmap but not yet written in full. The roadmap is `docs/superpowers/plans/2026-07-08-autonomous-scrum-team-roadmap.md`. In order:

1. **Plan 2 — Team topology.** Five-role scrum team (PO / SM / Architect / Test / DevSecOps) + envelopes. Replaces the current `sprint-lead/PM/engineer/qa-validator/release-manager` factories in `orgos/subagents/engineering_team.py`.
2. **Plan 3 — Wiki + board substrate.** Filesystem wiki MCP + GitHub-Issue-with-labels board (READY gate + pull-based work). See §0.1 of the spec for the flow.
3. **Plan 4 — HEARTBEAT loop + compaction.** Self-writing tasks + conductor + sprint-end compaction + scope brake.
4. **Plan 5 — Metrics + benchmarking.** Flow-metric scorer (takt-time / velocity-delta) + `swap_topology` for dual-team paired-run reports.

## Locked architectural decisions (do not re-litigate without explicit reason)

- **Persona file structure is settled** — three inheritance layers (`_principles` → `_worker_base` → per-agent), five files per agent (SOUL / BRAIN / HABITS / MEMORY / HEARTBEAT), strict YAML frontmatter, warn-only body-section validation, CRLF-normalized, agents whose name starts with `_` are rejected.
- **Assembled prompt ordering:** principles → worker_base(soul→brain→habits→memory→heartbeat) → specific(soul→brain→habits→memory→heartbeat). HEARTBEAT sits last so it lands in the LLM's recency-attention window. Do not reorder.
- **Board substrate = GitHub Issue + labels + comments.** State via `state:draft|refinement|ready|in_progress|review|done` labels. Role signoffs via `refined:architect|test|devsecops` labels. Comments carry refinement. GitHub Projects v2 is optional viz on top; source of truth is the issue.
- **Wiki = filesystem, MCP with `list / read / grep / recent(n)`.** No vectorization. Corpus is team-scale; grep + read is faster and more precise than vectors, and rebuild-free.
- **Sprint cadence: 4h** at the start; each boundary is a compaction event.
- **Story = shared blackboard.** GitHub issue comments for team-visible state; `_orgos_memory/` for internal scratch.
- **Self-organizing with scope brake.** HEARTBEAT-authored tasks pass through the same `TaskBrief` validator as PM briefs. Rubric criterion for scope drift. Publishing tools still route through `GatedToolBase`.

## Load-bearing risks (worth restating every time)

- **Sycophancy in shared Worker Base.** All three delivery workers inherit the same Layer-2 reasoning. Mitigations required before dual-team benchmarking: cross-model pairing (different provider per seat) + refinement phase must produce at least one substantive disagreement between roles.
- **Runaway HEARTBEAT scope.** Self-authored next-task can monotonically grow. Enforced by re-validation against size caps and a scope-drift rubric criterion.
- **Attribution refactor.** `orgos/agile/attribution.py` currently assumes distinct role labels on distinct artifacts. Must move to per-artifact attribution before Plan 5's dual-team story is meaningful.
- **Flow-metric formula.** Working reconstruction (takt-time / velocity-delta) but the exact aggregation is not confirmed. Plan 5 is unblocked structurally but the specific formula needs external verification.

## Confidentiality rule (READ THIS)

The reference model was shared by an external collaborator under confidentiality. **Do not write their name or the metric author's name in any committed file, commit message, PR description, memory file, or public artifact.** Refer to the model as "the autonomous scrum team model" / "the reference spec" / "external methodology" — never with names attached.

If you're an AI assistant reading this, treat it as a hard constraint that overrides your default behavior of attributing sources.

## Where things live

| Concern | Path |
|---|---|
| Feasibility spec | `docs/superpowers/specs/2026-07-07-autonomous-scrum-team-design.md` |
| Program roadmap (Plans 1-5) | `docs/superpowers/plans/2026-07-08-autonomous-scrum-team-roadmap.md` |
| Plan 1 (executed, retrospective) | `docs/superpowers/plans/2026-07-08-persona-file-loader.md` |
| Loader code | `orgos/spawn/persona_loader.py`, `orgos/spawn/persona_schema.py` |
| RoleSpec factory (added by Plan 1) | `orgos/spawn/contracts.py` — search for `from_agent_dir` |
| Tests + fixtures | `tests/spawn/test_persona_loader.py`, `tests/spawn/fixtures/agents/` |
| Agents scaffold (empty; to be authored by hand) | `agents/README.md` and role directories |
| Governance decisions (untouched by this program) | `DESIGN.md` |
| Prior worked-example (agile-team) design | `docs/superpowers/specs/2026-06-30-agile-product-team-design.md` |

## Progress ledger (harness-agnostic)

If it exists, `.superpowers/sdd/progress.md` in the repo root records which tasks landed. It's local scratch (git-ignored by convention) but survives across sessions on the same machine. If missing, reconstruct from `git log --oneline main`.

## Paste-this-first prompt for a new session or model

Use this as your first message in a fresh session (any harness — Claude Code, OpenCode, Cursor agent). Adjust the last line based on what you actually want to work on.

```
You are helping me continue work on the "autonomous scrum team" direction
for my orgos repo. Please read the following files in this order before
doing anything else:

1. docs/HANDOFF.md            — start here; current state + locked decisions
2. docs/superpowers/specs/2026-07-07-autonomous-scrum-team-design.md
                              — the feasibility spec
3. docs/superpowers/plans/2026-07-08-autonomous-scrum-team-roadmap.md
                              — the five-plan program roadmap
4. DESIGN.md                  — orgos's governance / architecture canon

Two rules that override defaults:

- CONFIDENTIALITY: the reference model came from an external collaborator
  whose name I have not shared with you and must not appear anywhere.
  Refer to it as "the autonomous scrum team model" or "the reference
  spec". Do not attempt to guess or research the source.
- GOVERNANCE LAYER IS OFF-LIMITS: do not modify GatedToolBase,
  HandoffEnvelope, TierPolicy, PermissionTier, spawn(), spawn_chain(),
  or the TIER_POLICY table without explicit permission.

Plan 1 (persona-file loader) is done and merged to main. Plans 2-5 are
outlined in the roadmap but not yet written in full.

I want to work on: [FILL IN — e.g. "write Plan 2 in full", "author real
persona bodies in agents/architect/", "confirm the flow-metric formula",
"scope Plan 3's GitHub board integration"]
```

## Notes on porting to OpenCode (or any non-Claude-Code harness)

- The persona loader itself is pure Python — no harness dependency. `RoleSpec.from_agent_dir()` works the same whether it's driven by Claude Code, OpenCode, a script, or a scheduled job.
- Superpowers skills are markdown + scripts under a plugin directory. If your harness supports skills, install the superpowers plugin per its own README. If it doesn't, the skills' prescriptive rules (TDD, verification-before-completion, writing-plans structure) can still be followed manually — the templates in the superpowers repo describe what a good plan/review looks like.
- Model selection: orgos uses litellm under the hood, so any provider (Anthropic, OpenAI, Google, DeepSeek, Ollama, etc.) works. If you switch primary model, remember cross-model pairing is a *design* requirement for the dual-team story — pick two different providers for the paired seats.
- Memory: this repo does not depend on Claude Code's per-project memory. If your new harness has a memory system, seed it with two facts: (1) the confidentiality rule above, and (2) a pointer to this file. Everything else is derivable from the repo.
