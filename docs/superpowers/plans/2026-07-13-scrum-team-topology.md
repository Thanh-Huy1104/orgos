# Scrum Team Topology — Implementation Plan (Plan 2)

> **Status:** Executed 2026-07-13. Retrospective document.

**Goal:** Replace the five-role engineering team (sprint-lead/PM/engineer/qa-validator/release-manager, defined in code) with the autonomous scrum team (PO/SM/Architect/Test/DevSecOps, defined by markdown persona files) running on top of the existing orgos governance layer.

**Architecture:** New `orgos/subagents/scrum_team.py` uses Plan 1's `RoleSpec.from_agent_dir()` to load agent identities from `agents/` directory. The old `engineering_team.py` is preserved as `engineering_team_legacy.py` for Plan 5 dual-team baseline. Three new envelope types (`RefinementEnvelope`, `ReadyEnvelope`, `PullEnvelope`) support the scrum-specific phases. `orgos/agile/sprint.py` gains `run_scrum_sprint()` which routes PO → SM → workers → release. Rubric expanded with refinement signoff, wiki consultation, and scope-drift criteria.

## File map

| Path | Action | Purpose |
|------|--------|---------|
| `agents/_principles/principles.md` | Modified | Added YAML frontmatter (version, layer: principles) |
| `agents/_worker_base/*.md` | Modified | Added YAML frontmatter to all 5 files (soul/brain/habits/memory/heartbeat) |
| `agents/architect/*.md` | Modified | Added YAML frontmatter; soul gets agent_name, tier: worker, is_worker: true |
| `agents/devsecops/*.md` | Modified | Same pattern, agent_name: DevSecOps_Agent |
| `agents/test/*.md` | Modified | Same pattern, agent_name: Test_Agent |
| `agents/scrum_master/*.md` | Modified | Added YAML frontmatter; tier: orchestrator, is_worker: false |
| `agents/po/*.md` | Modified | Added YAML frontmatter; tier: orchestrator, is_worker: false |
| `orgos/subagents/scrum_team.py` | Created | `po_role()`, `scrum_master_role()`, `architect_role()`, `test_role()`, `devsecops_role()` |
| `orgos/subagents/engineering_team_legacy.py` | Created | Copy of old engineering_team.py for Plan 5 baseline |
| `orgos/subagents/__init__.py` | Modified | Exports both old and new role factories |
| `orgos/agile/envelopes.py` | Modified | Added `RefinementEnvelope`, `ReadyEnvelope`, `PullEnvelope` |
| `orgos/agile/sprint.py` | Modified | Added `run_scrum_sprint()`; updated `_ROLE_TO_PHASE` and `_PHASE_TO_ENVELOPE` |
| `orgos/agile/rubric.py` | Modified | Added refinement_signoffs, wiki_consulted, scope_drift criteria; rebalanced weights |

## Verification

- 23/23 persona loader tests pass
- All 5 agents load correctly via `RoleSpec.from_agent_dir()`:
  - architect: tier=worker, prompt_len=46270
  - devsecops: tier=worker, prompt_len=43970
  - test: tier=worker, prompt_len=43499
  - scrum_master: tier=orchestrator, prompt_len=32494
  - po: tier=orchestrator, prompt_len=48476
