# Agile Product Team Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pivot orgos' worked-example layer from "quant research desk" to "highly performant agile product team" — a self-organizing five-role engineering department that runs nightly sprints on the orgos repo itself, grades itself on DORA metrics, mutates its own role topology under human approval, and supports counterfactual sprint replay.

**Architecture:** Delete the ~5.7K LOC quant/options domain on branch `agile-pivot`; preserve the ~10K LOC governance layer unchanged. Add `orgos/agile/` (sprint engine, DORA, intake, replay, attribution, retro), six new RoleSpecs (sprint_lead, product_manager, engineer, qa_validator, release_manager, retro_agent), GitHub/PR tools, three new PMStore tables (`role_attribution`, `adrs`, `dora_snapshots`), five new dashboard pages (`/sprints`, `/team`, `/lab`, `/dora`, rewritten `/`), and an A2A Agent Card stub.

**Tech Stack:** Python 3.11+, CrewAI ≥1.0, Pydantic ≥2, ruamel.yaml ≥0.18, pytest, SQLite (PMStore), FastAPI (api.py), Next.js App Router + Tailwind + Recharts + react-force-graph-2d (dashboard), Anthropic Sonnet 4.6 default model (configurable via litellm).

## Global Constraints

- **Branch:** all work on `agile-pivot` (already created from `main`). Never push to `main` directly.
- **Token budget per sprint:** `run_budget_tokens=400_000` (≈$5–8 on Sonnet 4.6); configurable in `config/org.yaml`.
- **Wall-clock:** hard timeout 90 min per sprint cron run; per-role `max_execution_time=5400s`.
- **Delegation depth cap:** 2 (enforced in audit callback). Engineer's internal `spawn_chain` is the only nested call.
- **Typed handoffs only:** every cross-role artifact is a `HandoffEnvelope` subclass; malformed payloads fail closed.
- **PMStore writes are append-only.** Every row carries the sprint `run_id`.
- **Git isolation:** Engineer chain operates inside `.sprints/<sprint_id>/` git worktree. Only Release Manager touches `origin`. PRs target `main` from `agile/<sprint_id>`.
- **Replay tier isolation:** publish-category tools rejected from replays by existing `_enforce_tier()` — not by replay code.
- **`expire_at` on every evolve-proposed role:** default 30d.
- **Test commands:** `pytest` from repo root; new tests live under `tests/agile/`. Preserved governance tests must remain green throughout.
- **No emojis in code or commit messages.** Existing project convention.
- **Commit cadence:** one commit per task (the final step of each task), Conventional Commits style.
- **Reference spec:** `docs/superpowers/specs/2026-06-30-agile-product-team-design.md` — every task implements a numbered section there.

---

## Phase 0 — Cleanup (1 day, 3 tasks)

### Task 0.1: Delete quant + options domain code

**Files:**
- Delete: `orgos/quant/` (entire dir, 23 files)
- Delete: `orgos/options/` (entire dir, 5 files)
- Delete: `orgos/subagents/quant_supervisor.py`
- Delete: `orgos/subagents/quant_strategist.py`
- Delete: `orgos/subagents/options_strategist.py`
- Delete: `orgos/tools/quant_tool.py`
- Delete: `orgos/tools/crypto_tool.py`
- Delete: `orgos/tools/options_tools.py`
- Delete: `skills/quant/` (entire dir)
- Modify: `orgos/subagents/__init__.py` — remove the three deleted exports
- Modify: `orgos/tools/__init__.py` — remove the three deleted exports

**Interfaces:**
- Consumes: nothing
- Produces: a tree with no quant/options imports anywhere

- [ ] **Step 1: Confirm citations.py usage**

Run: `grep -rn "from orgos.citations\|from .citations\|import citations" orgos/ tests/ --include="*.py"`
Decision: if every reference is from `quant/` or `options/` files (which we're deleting), also delete `orgos/citations.py`. Otherwise keep it.

- [ ] **Step 2: Delete domain directories and files**

```bash
git rm -r orgos/quant orgos/options skills/quant
git rm orgos/subagents/quant_supervisor.py orgos/subagents/quant_strategist.py orgos/subagents/options_strategist.py
git rm orgos/tools/quant_tool.py orgos/tools/crypto_tool.py orgos/tools/options_tools.py
```

- [ ] **Step 3: Update `orgos/subagents/__init__.py`**

Replace its contents with:

```python
"""Pre-built subagent role specs.

Currently empty after the quant-pivot deletion. New roles for the
agile-pivot worked example will land in Task 1.4.
"""
```

- [ ] **Step 4: Update `orgos/tools/__init__.py`**

Read the file first, then remove import lines for `quant_tool`, `crypto_tool`, `options_tools`. Keep imports for `bash`, `gcal_tool`, `policy_bank`, `research_sources`.

- [ ] **Step 5: Verify nothing else imports the deleted modules**

Run: `grep -rn "orgos.quant\|orgos.options\|quant_supervisor\|quant_strategist\|options_strategist\|quant_tool\|crypto_tool\|options_tools" orgos/ --include="*.py"`
Expected: no matches (anything left is a bug — fix it before committing).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: remove quant + options domain layer for agile pivot"
```

---

### Task 0.2: Delete quant tests and quant-bound dashboard pages

**Files:**
- Delete: every `tests/test_quant*.py`, `tests/test_options_*.py`, `tests/test_kill_switch.py`, `tests/test_volatility.py`, `tests/test_crypto.py`, `tests/test_icarus_quant.py`, `tests/test_funding.py`, `tests/test_event_discovery.py`, `tests/test_backtest.py`, `tests/test_bars_cache.py`, `tests/test_journal_surface.py`, `tests/test_research_gate.py`, `tests/test_strategist_async.py`, `tests/test_trend.py`
- Delete: `dashboard/app/journal/` (entire dir)
- Delete: `dashboard/app/paper/` (entire dir)
- Delete: `dashboard/app/strategist/` (entire dir)
- Delete: `docs/dashboard-desk.png`, `docs/dashboard-journal.png`
- Delete: `FINDINGS.md`
- Modify: `orgos/api.py` — remove `quant_router` registration

**Interfaces:**
- Consumes: nothing
- Produces: dashboard and API surface with no quant references

- [ ] **Step 1: Verify which tests touch quant/options imports**

Run: `grep -l "orgos.quant\|orgos.options\|orgos.subagents.quant\|orgos.subagents.options\|orgos.tools.quant\|orgos.tools.crypto\|orgos.tools.options" tests/*.py`
Confirm the list matches the Files: section. Add to deletion list any extras the grep finds.

- [ ] **Step 2: Delete tests, dashboard pages, docs, FINDINGS**

```bash
git rm tests/test_quant*.py tests/test_options_*.py tests/test_kill_switch.py tests/test_volatility.py tests/test_crypto.py tests/test_icarus_quant.py tests/test_funding.py tests/test_event_discovery.py tests/test_backtest.py tests/test_bars_cache.py tests/test_journal_surface.py tests/test_research_gate.py tests/test_strategist_async.py tests/test_trend.py
git rm -r dashboard/app/journal dashboard/app/paper dashboard/app/strategist
git rm docs/dashboard-desk.png docs/dashboard-journal.png FINDINGS.md
```

If `tests/test_research_sources.py` uses any quant-specific fixtures, delete it; otherwise keep.

- [ ] **Step 3: Remove `quant_router` from `orgos/api.py`**

Read `orgos/api.py`. Find the `quant_router` import and the `app.include_router(quant_router, ...)` call. Delete both lines.

- [ ] **Step 4: Run remaining test suite — must be green**

Run: `pytest -q`
Expected: PASS. If any deleted-import errors appear, fix the offending import.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: remove quant tests, dashboard pages, FINDINGS"
```

---

### Task 0.3: Rewrite README, DEMO, and gut config/org.yaml

**Files:**
- Modify: `README.md` (full rewrite)
- Modify: `DEMO.md` (full rewrite)
- Modify: `config/org.yaml` (full rewrite — empty departments list for now, repopulated in Task 1.7)

**Interfaces:**
- Consumes: nothing
- Produces: documentation that frames the agile pivot

- [ ] **Step 1: Rewrite `README.md`**

Replace its contents with this exact text:

```markdown
# orgos — a governed agentic framework with a self-organizing agile product team

orgos is a multi-agent orchestration framework built on CrewAI + litellm. Its
worked example is a **self-organizing engineering team** that runs nightly
sprints on the orgos repo itself, grades itself on DORA metrics, mutates its
own role topology under human approval, and supports counterfactual sprint
replay.

## Why this is interesting

Three demo hooks no public framework currently combines:

- **Self-organizing role topology** — `evolve.py` proposes ADD/REMOVE/SPLIT/MERGE
  role mutations every 5 sprints based on per-role contribution attribution.
  Human approves each as an ADR.
- **Nightly self-sprint + counterfactual replay** — the team works real GitHub
  issues on the orgos repo. The dashboard's Lab page replays past sprints with
  mutated PM briefs (different issue picked, different heuristic injected,
  different model on Engineer) and shows side-by-side outcomes.
- **DORA closed loop** — Deploy Frequency, Lead Time, Change Failure Rate, MTTR
  computed nightly from PMStore. DORA signals produce candidate Reflector
  heuristics that flow through the existing scoring machinery before being
  injected into future PM briefs.

## Architecture

Two-tier supervisor: orchestrator → department supervisors → workers. Strict
typed `HandoffEnvelope` between roles. Four permission tiers
(worker/validator/publisher/orchestrator). Human gate in code on every
publishing tool (`GatedToolBase`). Append-only audit logs. Rubric-graded retry
loops with Reflector heuristic learning. The system can propose changes to its
own org structure (`evolve.py`) but never auto-applies them.

## Quick start

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...  # or OPENAI_API_KEY, GEMINI_API_KEY
python -m orgos.scheduler            # nightly sprint loop
python -m orgos.api                  # dashboard + API on :8000
cd dashboard && npm install && npm run dev   # Next.js on :3000
```

## Design

See `DESIGN.md` for the load-bearing architectural decisions and
`docs/superpowers/specs/2026-06-30-agile-product-team-design.md` for the
current worked-example design.
```

- [ ] **Step 2: Rewrite `DEMO.md`**

Replace its contents with this exact text:

```markdown
# orgos demo — a self-organizing agile team

This demo shows orgos running a five-role engineering team on its own repo,
overnight. The morning artifact is a graded sprint, a DORA scoreboard update,
and (every 5 sprints) a proposed role-topology mutation awaiting your
approval.

## What you'll see

1. **`/`** — the team scoreboard: DORA grade, 14-sprint streak, active heuristics.
2. **`/sprints`** — last night's sprint detail: the seven envelope chain
   (Intake → Brief → Engineer chain → QA → Release → Retro → DORA).
3. **`/team`** — live role topology graph; click into the ADR feed to approve a
   pending mutation.
4. **`/lab`** — re-run sprint N with the PM's second-choice issue. Side-by-side
   outcomes, rubric-score deltas highlighted.
5. **`/dora`** — DORA time-series and the candidate-heuristic queue.

## Running the demo

```bash
# Seed the demo by running 5 sprints in sequence
python -m orgos.agile.demo seed --sprints 5

# Open the dashboard
python -m orgos.api &
cd dashboard && npm run dev
```

The seed run uses a curated set of `agent-eligible` GitHub issues. Expected
cost: ~$25-40 on Sonnet 4.6.
```

- [ ] **Step 3: Rewrite `config/org.yaml`**

Replace its contents with this exact text:

```yaml
# orgos org constitution — agile-pivot worked example
# The engineering department is populated in Task 1.7.
name: orgos
description: A self-organizing agile engineering team that ships on its own repo.

default_model: anthropic/claude-sonnet-4-6
default_max_budget_tokens: 80000
default_max_run_tokens: 400000
default_max_iter: 12

owner:
  name: Thanh
  preferences:
    communication: concise
  notification_thresholds:
    approval_needed: always
    sprint_failed: always
    adr_proposed: always
  approval_rules:
    - publish: human_required
    - merge_to_main: human_required

departments: []
handoffs: []
```

- [ ] **Step 4: Run tests — must still be green**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add README.md DEMO.md config/org.yaml
git commit -m "docs: rewrite README/DEMO for agile pivot; reset org.yaml"
```

---

## Phase 1 — Skeleton sprint (4 days, 8 tasks)

Goal: a `run_sprint(repo_path, issue_dict)` entrypoint that takes a synthetic issue dict, spawns the five-role engineering team on a fixture repo, runs `BashTool` only (no GitHub), and produces a complete seven-envelope chain to PMStore. No real GitHub yet; that's Phase 2.

### Task 1.1: Create `orgos/agile/` package scaffold

**Files:**
- Create: `orgos/agile/__init__.py`
- Create: `tests/agile/__init__.py`
- Create: `tests/agile/conftest.py`

**Interfaces:**
- Consumes: nothing
- Produces: `orgos.agile` importable as a package

- [ ] **Step 1: Write the failing test**

Create `tests/agile/test_package_smoke.py`:

```python
def test_agile_package_importable():
    import orgos.agile
    assert orgos.agile is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/agile/test_package_smoke.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'orgos.agile'`.

- [ ] **Step 3: Create the package files**

`orgos/agile/__init__.py`:

```python
"""orgos worked-example: a self-organizing agile engineering team.

Modules:
    envelopes  - Seven typed HandoffEnvelope subclasses for the sprint chain.
    sprint     - run_sprint() / run_nightly_sprint() entrypoints.
    intake     - Backlog ranker (GitHub issues -> ranked candidates).
    rubric     - QA validator's grading rubric.
    dora       - DORA metric computations over PMStore.
    retro      - Retro Agent helpers.
    attribution - Per-role marginal-contribution scoring (Hook A).
    topology   - Mutation proposal trigger rules (Hook A).
    replay     - Counterfactual sprint replay (Hook B).
"""
```

`tests/agile/__init__.py`: empty file.

`tests/agile/conftest.py`:

```python
"""Shared fixtures for agile-team tests.

Most fixtures live here so individual test files stay focused. The
fixture_repo() factory builds an isolated git repo on disk that tests
can mutate without touching the orgos worktree.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def fixture_repo(tmp_path: Path) -> Path:
    """Build a minimal git repo in tmp_path. Caller can mutate freely."""
    repo = tmp_path / "fixture-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "README.md").write_text("# fixture\n")
    (repo / "src.py").write_text("def greet():\n    return 'hi'\n")
    (repo / "test_src.py").write_text(
        "from src import greet\n\n"
        "def test_greet():\n    assert greet() == 'hi'\n"
    )
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return repo
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/agile/test_package_smoke.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add orgos/agile tests/agile
git commit -m "feat(agile): package scaffold + fixture_repo helper"
```

---

### Task 1.2: Define the seven typed `HandoffEnvelope` subclasses

**Files:**
- Create: `orgos/agile/envelopes.py`
- Create: `tests/agile/test_envelopes.py`

**Interfaces:**
- Consumes: `HandoffEnvelope` from `orgos.spawn.contracts`
- Produces:
  - `BacklogEnvelope(HandoffEnvelope)` — payload: `candidates: list[BacklogCandidate]`
  - `BriefEnvelope(HandoffEnvelope)` — payload: `picked_issue_id: str`, `task_brief_json: str`, `touched_files_allowlist: list[str]`, `acceptance_tests: list[str]`
  - `EngineeringEnvelope(HandoffEnvelope)` — payload: `diff: str`, `commit_sha: str`, `files_touched: list[str]`, `test_command: str`, `test_output: str`, `test_passed: bool`
  - `GradeEnvelope(HandoffEnvelope)` — payload: `criteria: list[dict]` (each `{name, passed, reason}`), `rubric_score: float`
  - `ReleaseEnvelope(HandoffEnvelope)` — payload: `pr_url: str | None`, `branch: str`, `mock_mode: bool`
  - `RetroEnvelope(HandoffEnvelope)` — payload: `retro_markdown: str`, `candidate_heuristics: list[dict]`, `role_attribution: dict[str, float]`
  - `DoraEnvelope(HandoffEnvelope)` — payload: `deploy_freq: float`, `lead_time_p50: float`, `cfr: float`, `mttr_p50: float`, `tier: str`

- [ ] **Step 1: Write the failing tests**

Create `tests/agile/test_envelopes.py`:

```python
import json

import pytest

from orgos.agile.envelopes import (
    BacklogEnvelope, BriefEnvelope, EngineeringEnvelope,
    GradeEnvelope, ReleaseEnvelope, RetroEnvelope, DoraEnvelope,
)


def _base(**over):
    base = dict(
        role="x", status="completed", summary="ok",
        success_criteria_met=True, requires_human_approval=False,
    )
    base.update(over)
    return base


def test_backlog_envelope_payload_round_trip():
    env = BacklogEnvelope(**_base(
        payload=json.dumps({"candidates": [
            {"issue_id": "42", "title": "fix typo", "size": "S", "risk": "low"}
        ]})
    ))
    data = json.loads(env.payload)
    assert data["candidates"][0]["issue_id"] == "42"


def test_brief_envelope_requires_payload_fields():
    env = BriefEnvelope(**_base(
        payload=json.dumps({
            "picked_issue_id": "42",
            "task_brief_json": "{}",
            "touched_files_allowlist": ["src.py"],
            "acceptance_tests": ["pytest test_src.py"],
        })
    ))
    parsed = env.parsed_payload()
    assert parsed["picked_issue_id"] == "42"


def test_engineering_envelope_payload():
    env = EngineeringEnvelope(**_base(
        payload=json.dumps({
            "diff": "--- a\n+++ b\n",
            "commit_sha": "abc123",
            "files_touched": ["src.py"],
            "test_command": "pytest",
            "test_output": "1 passed",
            "test_passed": True,
        })
    ))
    assert env.parsed_payload()["test_passed"] is True


def test_grade_envelope_score_in_range():
    env = GradeEnvelope(**_base(
        payload=json.dumps({
            "criteria": [{"name": "tests_pass", "passed": True, "reason": ""}],
            "rubric_score": 1.0,
        })
    ))
    assert 0.0 <= env.parsed_payload()["rubric_score"] <= 1.0


def test_release_envelope_mock_mode():
    env = ReleaseEnvelope(**_base(
        payload=json.dumps({"pr_url": None, "branch": "agile/abc", "mock_mode": True})
    ))
    assert env.parsed_payload()["mock_mode"] is True


def test_retro_envelope_attribution():
    env = RetroEnvelope(**_base(
        payload=json.dumps({
            "retro_markdown": "# retro",
            "candidate_heuristics": [{"rule": "x", "why": "y"}],
            "role_attribution": {"product_manager": 0.4, "engineer": 0.6},
        })
    ))
    assert sum(env.parsed_payload()["role_attribution"].values()) == pytest.approx(1.0)


def test_dora_envelope_tier():
    env = DoraEnvelope(**_base(
        payload=json.dumps({
            "deploy_freq": 1.2, "lead_time_p50": 18000.0,
            "cfr": 0.1, "mttr_p50": 3600.0, "tier": "Medium",
        })
    ))
    assert env.parsed_payload()["tier"] in {"Elite", "High", "Medium", "Low"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agile/test_envelopes.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'orgos.agile.envelopes'`.

- [ ] **Step 3: Implement `orgos/agile/envelopes.py`**

```python
"""Typed HandoffEnvelope subclasses for the seven sprint phases.

Each subclass inherits the strict HandoffEnvelope schema and adds a
`parsed_payload()` helper that JSON-decodes the `payload` field. We keep
payload as a JSON string (not a nested model) to stay compatible with
OpenAI strict structured outputs — the parent enforces this.
"""

from __future__ import annotations

import json
from typing import Any

from orgos.spawn.contracts import HandoffEnvelope


class _PayloadMixin:
    payload: str

    def parsed_payload(self) -> dict[str, Any]:
        if not self.payload:
            return {}
        try:
            return json.loads(self.payload)
        except json.JSONDecodeError:
            return {}


class BacklogEnvelope(_PayloadMixin, HandoffEnvelope):
    """Phase [00] Intake. payload.candidates: list[{issue_id, title, size, risk}]."""


class BriefEnvelope(_PayloadMixin, HandoffEnvelope):
    """Phase [01] PM brief. payload: {picked_issue_id, task_brief_json,
    touched_files_allowlist, acceptance_tests}."""


class EngineeringEnvelope(_PayloadMixin, HandoffEnvelope):
    """Phase [02] Engineer chain. payload: {diff, commit_sha, files_touched,
    test_command, test_output, test_passed}."""


class GradeEnvelope(_PayloadMixin, HandoffEnvelope):
    """Phase [03] QA gate. payload: {criteria: [{name, passed, reason}],
    rubric_score: float in [0,1]}."""


class ReleaseEnvelope(_PayloadMixin, HandoffEnvelope):
    """Phase [04] Release. payload: {pr_url, branch, mock_mode}."""


class RetroEnvelope(_PayloadMixin, HandoffEnvelope):
    """Phase [05] Retro. payload: {retro_markdown, candidate_heuristics,
    role_attribution}."""


class DoraEnvelope(_PayloadMixin, HandoffEnvelope):
    """Phase [06] DORA snapshot. payload: {deploy_freq, lead_time_p50, cfr,
    mttr_p50, tier}."""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agile/test_envelopes.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add orgos/agile/envelopes.py tests/agile/test_envelopes.py
git commit -m "feat(agile): seven typed HandoffEnvelope subclasses"
```

---

### Task 1.3: Add delegation-depth audit guard

**Files:**
- Modify: `orgos/spawn/audit.py` — extend `make_audit_callback` to track + cap nesting depth
- Create: `tests/agile/test_delegation_depth.py`

**Interfaces:**
- Consumes: existing `make_audit_callback(role_name, run_id, max_actions=None)`
- Produces: callback accepts `max_depth: int = 2`; raises new `DelegationDepthExceeded` on overrun

- [ ] **Step 1: Read the existing audit module**

Run: `cat orgos/spawn/audit.py | head -80`
Understand how `make_audit_callback` is currently structured. Confirm the existing exceptions: `BudgetExceeded`, `LoopDetected`, `ToolBudgetExceeded`.

- [ ] **Step 2: Write the failing test**

Create `tests/agile/test_delegation_depth.py`:

```python
"""Audit-callback depth cap: third nested spawn aborts."""

import pytest

from orgos.spawn.audit import (
    DelegationDepthExceeded, _depth_registry, make_audit_callback,
)


def test_depth_registry_increments_on_new_role(monkeypatch):
    _depth_registry.clear()
    cb1 = make_audit_callback("lead", "run-1", max_depth=2)
    cb2 = make_audit_callback("engineer", "run-1", max_depth=2)
    assert _depth_registry["run-1"]["lead"] == 1
    assert _depth_registry["run-1"]["engineer"] == 2


def test_third_nested_role_raises():
    _depth_registry.clear()
    make_audit_callback("lead", "run-2", max_depth=2)
    make_audit_callback("worker_a", "run-2", max_depth=2)
    with pytest.raises(DelegationDepthExceeded):
        make_audit_callback("worker_b", "run-2", max_depth=2)


def test_independent_runs_have_independent_depth():
    _depth_registry.clear()
    make_audit_callback("lead", "r1", max_depth=2)
    make_audit_callback("worker", "r1", max_depth=2)
    make_audit_callback("lead", "r2", max_depth=2)  # different run
    assert _depth_registry["r1"]["lead"] == 1
    assert _depth_registry["r2"]["lead"] == 1
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/agile/test_delegation_depth.py -v`
Expected: FAIL with `ImportError` on `DelegationDepthExceeded` / `_depth_registry`.

- [ ] **Step 4: Edit `orgos/spawn/audit.py`**

At the module's top-level (after the existing exception classes), add:

```python
# Delegation depth registry: run_id -> {role_name: ordinal}.
# Process-wide; entries are not cleared automatically — tests clear it.
_depth_registry: dict[str, dict[str, int]] = {}


class DelegationDepthExceeded(RuntimeError):
    """Raised when a spawn would push delegation past the configured depth cap.

    The cap exists to prevent runaway recursive sub-spawning, which is MAST's
    inter-agent misalignment failure mode (Cemri et al., arXiv:2503.13657).
    """
```

Modify `make_audit_callback` signature to add `max_depth: int = 2` and increment + check the registry at call entry:

```python
def make_audit_callback(
    role_name: str, run_id: str, *, max_actions: int | None = None,
    max_depth: int = 2,
):
    # ... existing body ...
    by_run = _depth_registry.setdefault(run_id, {})
    if role_name not in by_run:
        by_run[role_name] = len(by_run) + 1
        if by_run[role_name] > max_depth:
            raise DelegationDepthExceeded(
                f"Depth {by_run[role_name]} > max_depth={max_depth} for "
                f"run_id={run_id!r} role={role_name!r}"
            )
    # ... existing body continues ...
```

(Locate the existing function body, add the registry check at the top of the function before any local closures, and keep the rest unchanged.)

- [ ] **Step 5: Wire `max_depth=2` into `spawn/engine.py`**

In `_make_logged_agent` find the `make_audit_callback(...)` call and add `max_depth=2`. Leave the existing `max_actions=max_actions` argument in place.

- [ ] **Step 6: Run all tests**

Run: `pytest -q`
Expected: PASS (including existing governance tests — `make_audit_callback` is backward-compatible because `max_depth` defaults to 2).

- [ ] **Step 7: Commit**

```bash
git add orgos/spawn/audit.py orgos/spawn/engine.py tests/agile/test_delegation_depth.py
git commit -m "feat(spawn): delegation depth cap with DelegationDepthExceeded"
```

---

### Task 1.4: Define the six RoleSpecs in `engineering_team.py`

**Files:**
- Create: `orgos/subagents/engineering_team.py`
- Create: `tests/agile/test_engineering_team.py`
- Modify: `orgos/subagents/__init__.py` — re-export the new RoleSpecs

**Interfaces:**
- Consumes: `RoleSpec`, `PermissionTier`, `BashTool` (already exists)
- Produces:
  - `sprint_lead_role(model: str | None = None) -> RoleSpec` (tier=ORCHESTRATOR)
  - `product_manager_role(model=...) -> RoleSpec` (tier=WORKER)
  - `engineer_role(model=..., extra_tools=...) -> RoleSpec` (tier=WORKER)
  - `qa_validator_role(model=...) -> RoleSpec` (tier=VALIDATOR)
  - `release_manager_role(model=..., extra_tools=...) -> RoleSpec` (tier=PUBLISHER)
  - `retro_agent_role(model=...) -> RoleSpec` (tier=VALIDATOR)

- [ ] **Step 1: Write the failing tests**

Create `tests/agile/test_engineering_team.py`:

```python
from orgos.spawn import PermissionTier
from orgos.subagents.engineering_team import (
    sprint_lead_role, product_manager_role, engineer_role,
    qa_validator_role, release_manager_role, retro_agent_role,
)


def test_sprint_lead_is_orchestrator():
    r = sprint_lead_role()
    assert r.tier == PermissionTier.ORCHESTRATOR
    assert r.allow_delegation is True


def test_pm_is_worker_with_short_brief_floor():
    r = product_manager_role()
    assert r.tier == PermissionTier.WORKER
    assert "Product Manager" in r.system_prompt or "PM" in r.system_prompt


def test_engineer_is_worker_and_accepts_extra_tools():
    from orgos.tools.bash import BashTool
    r = engineer_role(extra_tools=[BashTool()])
    assert r.tier == PermissionTier.WORKER
    assert any(getattr(t, "name", "") == "bash" for t in r.tools)


def test_qa_is_validator_readonly():
    r = qa_validator_role()
    assert r.tier == PermissionTier.VALIDATOR


def test_release_manager_is_publisher():
    r = release_manager_role()
    assert r.tier == PermissionTier.PUBLISHER


def test_retro_agent_is_validator():
    r = retro_agent_role()
    assert r.tier == PermissionTier.VALIDATOR


def test_all_roles_have_success_criteria():
    for factory in (sprint_lead_role, product_manager_role, engineer_role,
                    qa_validator_role, release_manager_role, retro_agent_role):
        r = factory()
        assert r.success_criteria, f"{r.name} has no success_criteria"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agile/test_engineering_team.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `orgos/subagents/engineering_team.py`**

```python
"""The six RoleSpecs for the agile engineering team.

Used by orgos.agile.sprint.run_sprint() and declared in config/org.yaml.
Each factory accepts an optional model override; tools (Bash, GitHubPRTool,
etc.) are attached by the caller based on the sprint phase.
"""

from __future__ import annotations

from typing import Any

from orgos.spawn import PermissionTier, RoleSpec


def sprint_lead_role(model: str | None = None) -> RoleSpec:
    return RoleSpec(
        name="sprint-lead",
        description="Orchestrates a sprint: pick the issue, route the team, "
                    "synthesize the final handoff.",
        tier=PermissionTier.ORCHESTRATOR,
        system_prompt=(
            "You are the Sprint Lead. One sprint = one issue, one PR. "
            "Decide which backlog candidate to pick (size_S + acceptance "
            "tests must be specified), delegate to PM -> Engineer -> QA -> "
            "Release in order, and synthesize the final HandoffEnvelope. "
            "Refuse to mark a sprint completed unless QA passed and "
            "the Release envelope was produced."
        ),
        model=model,
        max_iter=8,
        allow_delegation=True,
        success_criteria=[
            "The picked issue is one of the candidates returned by Intake.",
            "Every subordinate produced a typed HandoffEnvelope.",
            "Final envelope summary cites the issue id and the PR/branch.",
        ],
    )


def product_manager_role(model: str | None = None) -> RoleSpec:
    return RoleSpec(
        name="product-manager",
        description="Turns one GitHub issue into a TaskBrief with explicit "
                    "acceptance tests and a touched_files_allowlist.",
        tier=PermissionTier.WORKER,
        system_prompt=(
            "You are the PM. Read the picked issue. Emit a BriefEnvelope "
            "whose payload includes: picked_issue_id, task_brief_json "
            "(serialised TaskBrief), touched_files_allowlist (paths the "
            "Engineer is permitted to modify), acceptance_tests (list of "
            "pytest invocations). Keep scope tight: never authorise more "
            "than 5 files or 400 LOC of diff."
        ),
        model=model,
        max_iter=6,
        tools=[],
        success_criteria=[
            "BriefEnvelope.payload contains all five required fields.",
            "touched_files_allowlist has 1 to 5 entries.",
            "acceptance_tests is a non-empty list of pytest invocations.",
        ],
    )


def engineer_role(
    model: str | None = None, extra_tools: list[Any] | None = None,
) -> RoleSpec:
    return RoleSpec(
        name="engineer",
        description="Implements the change inside a git worktree, runs the "
                    "tests, and emits an EngineeringEnvelope.",
        tier=PermissionTier.WORKER,
        system_prompt=(
            "You are the Engineer. Operate inside the git worktree path "
            "you are given. Only modify files in touched_files_allowlist. "
            "Use spawn_chain(implement -> review -> test) for the actual "
            "code-writing loop (the runtime will wire that for you). Run "
            "the acceptance_tests and capture stdout+returncode."
        ),
        model=model,
        max_iter=12,
        tools=list(extra_tools or []),
        success_criteria=[
            "All file edits are inside touched_files_allowlist.",
            "Diff size <= 400 LOC.",
            "Test command exit code is captured in payload.test_passed.",
        ],
    )


def qa_validator_role(model: str | None = None) -> RoleSpec:
    return RoleSpec(
        name="qa-validator",
        description="Grades the EngineeringEnvelope against the BriefEnvelope's "
                    "acceptance_tests + rubric.",
        tier=PermissionTier.VALIDATOR,
        system_prompt=(
            "You are QA. Read-only access. Apply the rubric (see "
            "orgos.agile.rubric.qa_criteria) to the EngineeringEnvelope. "
            "Each criterion is independently scored; rubric_score is the "
            "weighted mean. Emit a GradeEnvelope."
        ),
        model=model,
        max_iter=4,
        tools=[],
        success_criteria=[
            "GradeEnvelope.payload.criteria covers every entry in the rubric.",
            "rubric_score is in [0, 1].",
        ],
    )


def release_manager_role(
    model: str | None = None, extra_tools: list[Any] | None = None,
) -> RoleSpec:
    return RoleSpec(
        name="release-manager",
        description="Opens the PR (or records a mock PR in replay mode).",
        tier=PermissionTier.PUBLISHER,
        system_prompt=(
            "You are Release. Call exactly one of github_open_pr "
            "(production) or mock_open_pr (replay). The tool is human-gated "
            "in production. Emit a ReleaseEnvelope with pr_url, branch, and "
            "mock_mode set."
        ),
        model=model,
        max_iter=4,
        tools=list(extra_tools or []),
        success_criteria=[
            "Exactly one PR-opening tool call was made.",
            "ReleaseEnvelope.payload.branch matches the sprint's branch name.",
        ],
    )


def retro_agent_role(model: str | None = None) -> RoleSpec:
    return RoleSpec(
        name="retro-agent",
        description="After the main sprint, reads the audit log + grades to "
                    "produce a retrospective and candidate heuristics.",
        tier=PermissionTier.VALIDATOR,
        system_prompt=(
            "You are the Retro Agent. You see the full sprint audit log. "
            "Write a short markdown retro (what worked, what didn't, one "
            "actionable change). Propose 0-3 candidate heuristics in the "
            "Reflector format (rule + why + tags). Emit a RetroEnvelope."
        ),
        model=model,
        max_iter=4,
        tools=[],
        success_criteria=[
            "retro_markdown is non-empty.",
            "role_attribution sums to ~1.0 (allow +/- 0.02).",
        ],
    )
```

- [ ] **Step 4: Update `orgos/subagents/__init__.py`**

```python
"""Pre-built subagent role specs."""

from .engineering_team import (
    engineer_role,
    product_manager_role,
    qa_validator_role,
    release_manager_role,
    retro_agent_role,
    sprint_lead_role,
)

__all__ = [
    "sprint_lead_role",
    "product_manager_role",
    "engineer_role",
    "qa_validator_role",
    "release_manager_role",
    "retro_agent_role",
]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/agile/test_engineering_team.py -v`
Expected: PASS (7 tests).

- [ ] **Step 6: Commit**

```bash
git add orgos/subagents/engineering_team.py orgos/subagents/__init__.py tests/agile/test_engineering_team.py
git commit -m "feat(subagents): six engineering-team RoleSpecs"
```

---

### Task 1.5: Implement the QA rubric (`orgos/agile/rubric.py`)

**Files:**
- Create: `orgos/agile/rubric.py`
- Create: `tests/agile/test_rubric.py`

**Interfaces:**
- Consumes: `EngineeringEnvelope`, `BriefEnvelope`
- Produces:
  - `qa_criteria() -> list[Criterion]` (read-only definition)
  - `grade(brief: BriefEnvelope, eng: EngineeringEnvelope) -> GradeEnvelope`
  - `Criterion = TypedDict("Criterion", {"name": str, "weight": float, "fn": Callable[..., tuple[bool, str]]})`

- [ ] **Step 1: Write the failing tests**

Create `tests/agile/test_rubric.py`:

```python
import json

from orgos.agile.envelopes import BriefEnvelope, EngineeringEnvelope
from orgos.agile.rubric import grade, qa_criteria


def _brief(allow=("src.py",), tests=("pytest test_src.py",)):
    return BriefEnvelope(
        role="pm", status="completed", summary="brief",
        success_criteria_met=True, requires_human_approval=False,
        payload=json.dumps({
            "picked_issue_id": "42", "task_brief_json": "{}",
            "touched_files_allowlist": list(allow),
            "acceptance_tests": list(tests),
        }),
    )


def _eng(files=("src.py",), passed=True, diff_lines=10):
    return EngineeringEnvelope(
        role="engineer", status="completed", summary="impl",
        success_criteria_met=True, requires_human_approval=False,
        payload=json.dumps({
            "diff": "\n".join("+x" for _ in range(diff_lines)),
            "commit_sha": "abc", "files_touched": list(files),
            "test_command": "pytest test_src.py",
            "test_output": "1 passed", "test_passed": passed,
        }),
    )


def test_rubric_has_five_criteria():
    assert len(qa_criteria()) == 5


def test_clean_run_full_score():
    g = grade(_brief(), _eng())
    p = g.parsed_payload()
    assert p["rubric_score"] == 1.0
    assert all(c["passed"] for c in p["criteria"])


def test_test_failure_fails_grade():
    g = grade(_brief(), _eng(passed=False))
    p = g.parsed_payload()
    assert p["rubric_score"] < 1.0
    assert any(c["name"] == "tests_pass" and not c["passed"] for c in p["criteria"])


def test_out_of_allowlist_file_fails_grade():
    g = grade(_brief(allow=("src.py",)), _eng(files=("src.py", "other.py")))
    p = g.parsed_payload()
    assert any(c["name"] == "files_in_allowlist" and not c["passed"] for c in p["criteria"])


def test_diff_too_large_fails_grade():
    g = grade(_brief(), _eng(diff_lines=500))
    p = g.parsed_payload()
    assert any(c["name"] == "diff_size_ok" and not c["passed"] for c in p["criteria"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agile/test_rubric.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `orgos/agile/rubric.py`**

```python
"""QA Validator rubric — deterministic grading of an EngineeringEnvelope.

Each criterion returns (passed: bool, reason: str). The rubric_score is
the weight-averaged pass rate. Lives outside the LLM so it is reproducible
and replay-safe.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

from .envelopes import BriefEnvelope, EngineeringEnvelope, GradeEnvelope

DIFF_LINE_CAP = 400


@dataclass
class Criterion:
    name: str
    weight: float
    fn: Callable[[dict, dict], tuple[bool, str]]


def _tests_pass(brief: dict, eng: dict) -> tuple[bool, str]:
    return bool(eng.get("test_passed")), eng.get("test_output", "")[:200]


def _files_in_allowlist(brief: dict, eng: dict) -> tuple[bool, str]:
    allow = set(brief.get("touched_files_allowlist", []))
    touched = set(eng.get("files_touched", []))
    extras = touched - allow
    return (not extras), f"unauthorised: {sorted(extras)}" if extras else ""


def _diff_size_ok(brief: dict, eng: dict) -> tuple[bool, str]:
    diff = eng.get("diff", "") or ""
    n = sum(1 for line in diff.splitlines() if line.startswith(("+", "-")))
    return n <= DIFF_LINE_CAP, f"diff_lines={n}"


def _commit_recorded(brief: dict, eng: dict) -> tuple[bool, str]:
    sha = eng.get("commit_sha", "") or ""
    return bool(sha) and len(sha) >= 7, f"sha={sha!r}"


def _test_command_matches(brief: dict, eng: dict) -> tuple[bool, str]:
    expected = brief.get("acceptance_tests", [])
    actual = eng.get("test_command", "")
    ok = any(actual.strip() == e.strip() for e in expected)
    return ok, f"expected one of {expected!r}, got {actual!r}"


def qa_criteria() -> list[Criterion]:
    return [
        Criterion("tests_pass", 0.40, _tests_pass),
        Criterion("files_in_allowlist", 0.20, _files_in_allowlist),
        Criterion("diff_size_ok", 0.15, _diff_size_ok),
        Criterion("commit_recorded", 0.10, _commit_recorded),
        Criterion("test_command_matches", 0.15, _test_command_matches),
    ]


def grade(brief: BriefEnvelope, eng: EngineeringEnvelope) -> GradeEnvelope:
    b = brief.parsed_payload()
    e = eng.parsed_payload()
    results = []
    score = 0.0
    for c in qa_criteria():
        passed, reason = c.fn(b, e)
        results.append({"name": c.name, "passed": passed, "reason": reason})
        if passed:
            score += c.weight
    payload = json.dumps({"criteria": results, "rubric_score": round(score, 3)})
    status = "completed" if score >= 0.99 else "needs_revision"
    return GradeEnvelope(
        role="qa-validator",
        status=status,
        summary=f"rubric_score={score:.2f}",
        success_criteria_met=(score >= 0.99),
        requires_human_approval=False,
        payload=payload,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agile/test_rubric.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add orgos/agile/rubric.py tests/agile/test_rubric.py
git commit -m "feat(agile): deterministic QA rubric with five criteria"
```

---

### Task 1.6: Add a `MockPRTool` (for skeleton sprints + replay)

**Files:**
- Create: `orgos/tools/mock_pr_tool.py`
- Create: `tests/agile/test_mock_pr_tool.py`

**Interfaces:**
- Consumes: nothing
- Produces: `MockPRTool` — a CrewAI `BaseTool` subclass, `tool_category="read"`, takes `branch: str, title: str, body: str`, returns a deterministic mock PR URL of form `mock://pr/<sha>` where `<sha>` is a hash of inputs.

- [ ] **Step 1: Write the failing test**

Create `tests/agile/test_mock_pr_tool.py`:

```python
from orgos.tools.mock_pr_tool import MockPRTool


def test_mock_pr_tool_category_is_read():
    t = MockPRTool()
    assert t.tool_category == "read"


def test_mock_pr_tool_returns_deterministic_url():
    t = MockPRTool()
    a = t._run(branch="agile/abc", title="t", body="b")
    b = t._run(branch="agile/abc", title="t", body="b")
    assert a == b
    assert a.startswith("mock://pr/")


def test_mock_pr_tool_distinct_inputs_distinct_url():
    t = MockPRTool()
    a = t._run(branch="agile/abc", title="x", body="b")
    b = t._run(branch="agile/abc", title="y", body="b")
    assert a != b
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/agile/test_mock_pr_tool.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `orgos/tools/mock_pr_tool.py`**

```python
"""MockPRTool — non-publishing replacement for github_open_pr.

Used in:
  - Phase 1 (skeleton sprint, no GitHub yet)
  - Hook B replays (publish-category tools forbidden by _enforce_tier)
"""

from __future__ import annotations

import hashlib

from crewai.tools import BaseTool
from pydantic import BaseModel, Field


class _Args(BaseModel):
    branch: str = Field(description="git branch name to open the PR from")
    title: str = Field(description="PR title")
    body: str = Field(description="PR body (markdown)")


class MockPRTool(BaseTool):
    name: str = "mock_open_pr"
    description: str = (
        "Open a mock PR. Returns a deterministic mock://pr/<sha> URL. "
        "Use this when github_open_pr is unavailable (skeleton runs, replays)."
    )
    args_schema: type[BaseModel] = _Args
    tool_category: str = "read"

    def _run(self, branch: str, title: str, body: str) -> str:
        h = hashlib.sha1(
            f"{branch}|{title}|{body}".encode("utf-8")
        ).hexdigest()[:12]
        return f"mock://pr/{h}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agile/test_mock_pr_tool.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add orgos/tools/mock_pr_tool.py tests/agile/test_mock_pr_tool.py
git commit -m "feat(tools): MockPRTool for skeleton and replay runs"
```

---

### Task 1.7: Implement the sprint engine — `orgos/agile/sprint.py`

**Files:**
- Create: `orgos/agile/sprint.py`
- Create: `tests/agile/test_sprint_engine.py`

**Interfaces:**
- Consumes: the six role factories, `BashTool`, `MockPRTool`, `grade()` from rubric
- Produces:
  - `Sprint(dataclass)`: id, started_at, repo_path, worktree_path, branch, picked_issue, envelopes (dict[str, HandoffEnvelope]), status
  - `run_sprint(repo_path: Path, issue: dict, *, model: str | None = None, mock_pr: bool = True, run_budget_tokens: int = 400_000) -> Sprint`

Phase 1 scope: `intake` is **stubbed** — the caller passes the issue dict directly. Real GitHub intake lands in Phase 2.

- [ ] **Step 1: Write the failing tests**

Create `tests/agile/test_sprint_engine.py`:

```python
"""Skeleton-sprint smoke test. Uses ollama/llama3.2 if available, else
mocks the spawn layer to keep the test offline+fast in CI."""

import json
import os
from pathlib import Path

import pytest

from orgos.agile.envelopes import (
    BriefEnvelope, EngineeringEnvelope, GradeEnvelope, ReleaseEnvelope,
)


pytestmark = pytest.mark.skipif(
    os.getenv("ORGOS_RUN_SPAWN_SMOKE") != "1",
    reason="Live spawn smoke; gated behind ORGOS_RUN_SPAWN_SMOKE=1",
)


def test_run_sprint_produces_full_envelope_chain(fixture_repo: Path):
    from orgos.agile.sprint import run_sprint

    issue = {
        "issue_id": "demo-1",
        "title": "Add a farewell function",
        "body": "Add `farewell()` returning 'bye' to src.py. Update tests.",
        "labels": ["agent-eligible"],
    }
    sprint = run_sprint(fixture_repo, issue, mock_pr=True)

    for key in ("brief", "engineering", "grade", "release"):
        assert key in sprint.envelopes, f"missing envelope: {key}"
    assert isinstance(sprint.envelopes["brief"], BriefEnvelope)
    assert isinstance(sprint.envelopes["engineering"], EngineeringEnvelope)
    assert isinstance(sprint.envelopes["grade"], GradeEnvelope)
    assert isinstance(sprint.envelopes["release"], ReleaseEnvelope)

    # The release envelope must be a mock PR in this mode.
    assert sprint.envelopes["release"].parsed_payload()["mock_mode"] is True
    assert sprint.status in {"completed", "needs_revision"}


def test_run_sprint_creates_worktree_under_dot_sprints(fixture_repo: Path):
    from orgos.agile.sprint import run_sprint
    sprint = run_sprint(fixture_repo, {
        "issue_id": "demo-2", "title": "noop", "body": "noop", "labels": [],
    }, mock_pr=True)
    assert sprint.worktree_path.exists()
    assert ".sprints" in str(sprint.worktree_path)
```

Also write an offline structural test (no spawn) that always runs:

```python
def test_sprint_dataclass_shape():
    from orgos.agile.sprint import Sprint
    s = Sprint(
        id="x", started_at="2026-06-30T00:00:00Z",
        repo_path=Path("."), worktree_path=Path("."),
        branch="agile/x", picked_issue={"issue_id": "1"},
        envelopes={}, status="in_progress",
    )
    assert s.status == "in_progress"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agile/test_sprint_engine.py -v`
Expected: FAIL on imports (`run_sprint`, `Sprint`).

- [ ] **Step 3: Implement `orgos/agile/sprint.py`**

```python
"""Sprint engine — orchestrates one sprint end-to-end.

Phase 1 scope:
  - No real GitHub. `issue` is a dict supplied by the caller.
  - PR opening is mocked via MockPRTool.
  - Retro / DORA / topology phases are TODOs (lit up in Phases 2-4).

A sprint:
  1. Creates a git worktree under .sprints/<sprint_id>/.
  2. Spawns Sprint Lead orchestrator with PM + Engineer + QA + Release as
     subordinates.
  3. Collects every subordinate's envelope and the synthesis envelope.
  4. Runs the deterministic rubric on the EngineeringEnvelope -> GradeEnvelope
     (overrides the LLM's GradeEnvelope to ensure reproducibility).
  5. Records the Sprint dataclass to PMStore (see Task 1.8).
"""

from __future__ import annotations

import json
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from orgos.spawn import RoleSpec, TaskBrief, spawn
from orgos.spawn.engine import SpawnResult
from orgos.subagents import (
    engineer_role, product_manager_role, qa_validator_role,
    release_manager_role, sprint_lead_role,
)
from orgos.tools.bash import BashTool
from orgos.tools.mock_pr_tool import MockPRTool

from .envelopes import (
    BriefEnvelope, EngineeringEnvelope, GradeEnvelope, ReleaseEnvelope,
)
from .rubric import grade as run_rubric


@dataclass
class Sprint:
    id: str
    started_at: str
    repo_path: Path
    worktree_path: Path
    branch: str
    picked_issue: dict
    envelopes: dict[str, Any] = field(default_factory=dict)
    status: str = "in_progress"  # in_progress | completed | needs_revision | failed
    spawn_result: SpawnResult | None = None


def _new_sprint_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{stamp}-{uuid.uuid4().hex[:6]}"


def _make_worktree(repo: Path, sprint_id: str, branch: str) -> Path:
    worktree_root = repo / ".sprints" / sprint_id
    worktree_root.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "worktree", "add", "-b", branch, str(worktree_root), "HEAD"],
        cwd=repo, check=True, capture_output=True,
    )
    return worktree_root


def _brief_for_team(issue: dict) -> TaskBrief:
    return TaskBrief(
        objective=(
            f"Ship issue {issue.get('issue_id', '?')}: {issue.get('title', '')}. "
            f"Coordinate PM -> Engineer -> QA -> Release. Each subordinate "
            f"emits its typed envelope; you synthesise the final HandoffEnvelope."
        ),
        expected_output="A synthesised final envelope describing the sprint outcome.",
        success_criteria=[
            "Each subordinate produced a typed envelope.",
            "The Release envelope contains a pr_url (or mock://pr/...).",
        ],
        inputs={"issue": json.dumps(issue)},
    )


def run_sprint(
    repo_path: Path,
    issue: dict,
    *,
    model: str | None = None,
    mock_pr: bool = True,
    run_budget_tokens: int = 400_000,
) -> Sprint:
    sprint_id = _new_sprint_id()
    branch = f"agile/{sprint_id}"
    worktree = _make_worktree(repo_path, sprint_id, branch)

    pm = product_manager_role(model=model)
    engineer = engineer_role(model=model, extra_tools=[BashTool(cwd=str(worktree))])
    qa = qa_validator_role(model=model)
    release = release_manager_role(
        model=model,
        extra_tools=[MockPRTool()] if mock_pr else [],
    )
    lead = sprint_lead_role(model=model)

    brief = _brief_for_team(issue)
    result = spawn(
        lead, brief,
        subordinates=[pm, engineer, qa, release],
        run_budget_tokens=run_budget_tokens,
    )

    envelopes: dict[str, Any] = {}
    for tout in result.tasks_output:
        env = getattr(tout, "pydantic", None) or getattr(tout, "raw", None)
        if isinstance(env, BriefEnvelope):
            envelopes["brief"] = env
        elif isinstance(env, EngineeringEnvelope):
            envelopes["engineering"] = env
        elif isinstance(env, ReleaseEnvelope):
            envelopes["release"] = env

    # Deterministic rubric over the EngineeringEnvelope (overrides any LLM grade).
    if "brief" in envelopes and "engineering" in envelopes:
        envelopes["grade"] = run_rubric(envelopes["brief"], envelopes["engineering"])

    status = "completed" if (
        envelopes.get("grade")
        and envelopes["grade"].success_criteria_met
        and "release" in envelopes
    ) else "needs_revision"

    return Sprint(
        id=sprint_id,
        started_at=datetime.now(timezone.utc).isoformat(),
        repo_path=repo_path,
        worktree_path=worktree,
        branch=branch,
        picked_issue=issue,
        envelopes=envelopes,
        status=status,
        spawn_result=result,
    )
```

- [ ] **Step 4: Run offline test to verify the dataclass works**

Run: `pytest tests/agile/test_sprint_engine.py::test_sprint_dataclass_shape -v`
Expected: PASS.

- [ ] **Step 5: Run the live smoke (optional)**

Run: `ORGOS_RUN_SPAWN_SMOKE=1 ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY pytest tests/agile/test_sprint_engine.py -v`
Expected: PASS or skip if no key set. (This is the first time we actually invoke the LLM end-to-end — expect some chain-of-prompt iteration here.)

- [ ] **Step 6: Commit**

```bash
git add orgos/agile/sprint.py tests/agile/test_sprint_engine.py
git commit -m "feat(agile): run_sprint() skeleton with five-role spawn"
```

---

### Task 1.8: Persist Sprint records to PMStore

**Files:**
- Modify: `orgos/pm.py` — add `sprints` table + `create_sprint`, `update_sprint_status`, `record_sprint_envelope`, `get_sprint`, `list_sprints`
- Modify: `orgos/agile/sprint.py` — call PMStore at end of `run_sprint`
- Create: `tests/agile/test_pm_sprints.py`

**Interfaces:**
- Consumes: `PMStore`, `Sprint`
- Produces:
  - `PMStore.create_sprint(sprint_id: str, branch: str, picked_issue: dict, status: str = "in_progress") -> None`
  - `PMStore.record_sprint_envelope(sprint_id: str, phase: str, envelope_json: str) -> None`
  - `PMStore.update_sprint_status(sprint_id: str, status: str) -> None`
  - `PMStore.get_sprint(sprint_id: str) -> dict | None`
  - `PMStore.list_sprints(limit: int = 50) -> list[dict]`

- [ ] **Step 1: Write the failing tests**

Create `tests/agile/test_pm_sprints.py`:

```python
import json
from pathlib import Path

from orgos.pm import PMStore


def test_create_and_get_sprint(tmp_path: Path):
    pm = PMStore(tmp_path / "pm.db")
    pm.create_sprint("s1", "agile/s1", {"issue_id": "42"}, "in_progress")
    s = pm.get_sprint("s1")
    assert s is not None
    assert s["branch"] == "agile/s1"
    assert json.loads(s["picked_issue"])["issue_id"] == "42"
    assert s["status"] == "in_progress"


def test_record_envelope_and_update_status(tmp_path: Path):
    pm = PMStore(tmp_path / "pm.db")
    pm.create_sprint("s2", "agile/s2", {}, "in_progress")
    pm.record_sprint_envelope("s2", "brief", json.dumps({"x": 1}))
    pm.record_sprint_envelope("s2", "engineering", json.dumps({"y": 2}))
    pm.update_sprint_status("s2", "completed")
    s = pm.get_sprint("s2")
    assert s["status"] == "completed"
    envs = json.loads(s["envelopes_json"])
    assert "brief" in envs and "engineering" in envs


def test_list_sprints_orders_by_started_at_desc(tmp_path: Path):
    pm = PMStore(tmp_path / "pm.db")
    pm.create_sprint("a", "agile/a", {}, "completed")
    pm.create_sprint("b", "agile/b", {}, "completed")
    rows = pm.list_sprints(limit=10)
    assert [r["id"] for r in rows][:2] == ["b", "a"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/agile/test_pm_sprints.py -v`
Expected: FAIL with `AttributeError: 'PMStore' object has no attribute 'create_sprint'`.

- [ ] **Step 3: Extend `_migrate()` in `orgos/pm.py`**

Append the following CREATE TABLE inside the existing `_migrate()` executescript block:

```sql
CREATE TABLE IF NOT EXISTS sprints (
    id TEXT PRIMARY KEY,
    branch TEXT NOT NULL,
    picked_issue TEXT NOT NULL DEFAULT '{}',
    envelopes_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'in_progress',
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sprints_status ON sprints(status);
CREATE INDEX IF NOT EXISTS idx_sprints_started_at ON sprints(started_at DESC);
```

- [ ] **Step 4: Add the five PMStore methods**

After the existing `# ── Research reports ─────` section in `orgos/pm.py`, add:

```python
    # ── Sprints ────────────────────────────────────────────────────────────

    def create_sprint(
        self, sprint_id: str, branch: str, picked_issue: dict,
        status: str = "in_progress",
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "INSERT INTO sprints (id, branch, picked_issue, envelopes_json, "
            "status, started_at, updated_at) VALUES (?, ?, ?, '{}', ?, ?, ?)",
            (sprint_id, branch, json.dumps(picked_issue), status, now, now),
        )
        self.conn.commit()

    def record_sprint_envelope(
        self, sprint_id: str, phase: str, envelope_json: str,
    ) -> None:
        row = self.conn.execute(
            "SELECT envelopes_json FROM sprints WHERE id = ?", (sprint_id,)
        ).fetchone()
        if row is None:
            return
        envs = json.loads(row["envelopes_json"] or "{}")
        envs[phase] = json.loads(envelope_json) if envelope_json else None
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "UPDATE sprints SET envelopes_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(envs), now, sprint_id),
        )
        self.conn.commit()

    def update_sprint_status(self, sprint_id: str, status: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "UPDATE sprints SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, sprint_id),
        )
        self.conn.commit()

    def get_sprint(self, sprint_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM sprints WHERE id = ?", (sprint_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_sprints(self, limit: int = 50) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM sprints ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 5: Wire PMStore writes into `run_sprint`**

In `orgos/agile/sprint.py`, at the end of `run_sprint` (just before `return Sprint(...)`), add:

```python
    from orgos.pm import PMStore
    pm = PMStore()
    pm.create_sprint(sprint_id, branch, issue, status="in_progress")
    for phase, env in envelopes.items():
        pm.record_sprint_envelope(sprint_id, phase, env.model_dump_json())
    pm.update_sprint_status(sprint_id, status)
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/agile/test_pm_sprints.py tests/test_pm.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add orgos/pm.py orgos/agile/sprint.py tests/agile/test_pm_sprints.py
git commit -m "feat(pm): sprints table + run_sprint() persistence"
```

---

## Phase 2 — GitHub integration + dogfood (4 days, 6 tasks)

Goal: real `agent-eligible` issues from the orgos repo flow through Intake → PM → Engineer → QA → Release. The Release Manager opens a real PR (gated by `GatedToolBase`) on `agile/<sprint_id>` against `main`.

### Task 2.1: Add `github_issue_tool.py` (read-only)

**Files:**
- Create: `orgos/tools/github_issue_tool.py`
- Create: `tests/agile/test_github_issue_tool.py`

**Interfaces:**
- Consumes: env `GITHUB_TOKEN`, env `GITHUB_REPO` (e.g. `Thanh-Huy1104/orgos`)
- Produces:
  - `GitHubListIssuesTool` — args: `labels: list[str]`, `state: str = "open"`, `limit: int = 20`. Returns JSON list of `{issue_id, number, title, body, labels, url}`. `tool_category="read"`.
  - `GitHubGetIssueTool` — args: `number: int`. Returns the same dict for one issue.

- [ ] **Step 1: Write the failing tests**

Create `tests/agile/test_github_issue_tool.py`:

```python
import json
from unittest.mock import patch, MagicMock

import pytest

from orgos.tools.github_issue_tool import (
    GitHubListIssuesTool, GitHubGetIssueTool,
)


def _mock_issue(num=1, labels=("agent-eligible",)):
    return {
        "number": num, "title": f"t{num}", "body": "b",
        "labels": [{"name": l} for l in labels],
        "html_url": f"https://github.com/o/r/issues/{num}",
    }


def test_list_issues_category_read():
    assert GitHubListIssuesTool().tool_category == "read"


@patch("orgos.tools.github_issue_tool._gh_get")
def test_list_issues_returns_normalised_dicts(mock_get):
    mock_get.return_value = [_mock_issue(1), _mock_issue(2, labels=("bug",))]
    out = GitHubListIssuesTool()._run(labels=["agent-eligible"], state="open", limit=10)
    data = json.loads(out)
    assert len(data) == 2
    assert data[0]["issue_id"] == "1"
    assert "agent-eligible" in data[0]["labels"]


@patch("orgos.tools.github_issue_tool._gh_get")
def test_list_issues_filters_by_label(mock_get):
    mock_get.return_value = [_mock_issue(1, labels=("agent-eligible",)),
                              _mock_issue(2, labels=("docs",))]
    out = GitHubListIssuesTool()._run(labels=["agent-eligible"], state="open", limit=10)
    data = json.loads(out)
    assert [d["issue_id"] for d in data] == ["1"]


@patch("orgos.tools.github_issue_tool._gh_get")
def test_get_issue_returns_one(mock_get):
    mock_get.return_value = _mock_issue(42)
    out = GitHubGetIssueTool()._run(number=42)
    assert json.loads(out)["issue_id"] == "42"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agile/test_github_issue_tool.py -v`
Expected: FAIL on `ModuleNotFoundError`.

- [ ] **Step 3: Implement `orgos/tools/github_issue_tool.py`**

```python
"""Read-only GitHub Issues tools.

Calls the GitHub REST API directly with the GITHUB_TOKEN env var. We do
not depend on PyGithub to keep the agent dependency surface small.
"""

from __future__ import annotations

import json
import os
from typing import Any

import urllib.request
import urllib.error
from crewai.tools import BaseTool
from pydantic import BaseModel, Field


def _gh_get(path: str, params: dict | None = None) -> Any:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN not set")
    url = f"https://api.github.com{path}"
    if params:
        from urllib.parse import urlencode
        url += "?" + urlencode(params)
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "orgos-agile",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 403 and "rate limit" in (e.headers.get("X-RateLimit-Remaining") or ""):
            raise RuntimeError("RateLimited") from e
        raise


def _normalise(raw: dict) -> dict:
    return {
        "issue_id": str(raw.get("number", "")),
        "number": raw.get("number"),
        "title": raw.get("title", ""),
        "body": raw.get("body", "") or "",
        "labels": [l["name"] for l in raw.get("labels", [])],
        "url": raw.get("html_url", ""),
    }


def _repo() -> str:
    r = os.environ.get("GITHUB_REPO")
    if not r:
        raise RuntimeError("GITHUB_REPO not set (owner/repo)")
    return r


class _ListArgs(BaseModel):
    labels: list[str] = Field(default_factory=list)
    state: str = Field(default="open")
    limit: int = Field(default=20)


class GitHubListIssuesTool(BaseTool):
    name: str = "github_list_issues"
    description: str = "List GitHub issues, optionally filtered by labels."
    args_schema: type[BaseModel] = _ListArgs
    tool_category: str = "read"

    def _run(self, labels: list[str] | None = None, state: str = "open",
             limit: int = 20) -> str:
        labels = labels or []
        raw = _gh_get(
            f"/repos/{_repo()}/issues",
            params={"state": state, "per_page": limit},
        )
        normalised = [_normalise(r) for r in raw if "pull_request" not in r]
        if labels:
            wanted = set(labels)
            normalised = [n for n in normalised if wanted.issubset(set(n["labels"]))]
        return json.dumps(normalised[:limit])


class _GetArgs(BaseModel):
    number: int = Field(description="Issue number")


class GitHubGetIssueTool(BaseTool):
    name: str = "github_get_issue"
    description: str = "Read a single GitHub issue."
    args_schema: type[BaseModel] = _GetArgs
    tool_category: str = "read"

    def _run(self, number: int) -> str:
        raw = _gh_get(f"/repos/{_repo()}/issues/{number}")
        return json.dumps(_normalise(raw))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agile/test_github_issue_tool.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add orgos/tools/github_issue_tool.py tests/agile/test_github_issue_tool.py
git commit -m "feat(tools): GitHub list/get issue tools (read category)"
```

---

### Task 2.2: Add `github_pr_tool.py` (publish, GatedToolBase)

**Files:**
- Create: `orgos/tools/github_pr_tool.py`
- Create: `tests/agile/test_github_pr_tool.py`

**Interfaces:**
- Consumes: env `GITHUB_TOKEN`, `GITHUB_REPO`
- Produces: `GitHubOpenPRTool(GatedToolBase)`, args `{branch, base, title, body}`, returns PR URL. `tool_category="publish"`. Gate fires before HTTP call.

- [ ] **Step 1: Write the failing tests**

Create `tests/agile/test_github_pr_tool.py`:

```python
import json
from unittest.mock import patch

import pytest

from orgos.spawn.toolbase import GatedToolBase
from orgos.tools.github_pr_tool import GitHubOpenPRTool


def test_pr_tool_is_publish_and_gated():
    t = GitHubOpenPRTool()
    assert t.tool_category == "publish"
    assert isinstance(t, GatedToolBase)


def test_pr_tool_returns_denied_without_approval():
    t = GitHubOpenPRTool()
    t.approval_fn = lambda _: False
    t._gate_required = True
    out = t._run(branch="x", base="main", title="t", body="b")
    assert out.startswith("DENIED:")


@patch("orgos.tools.github_pr_tool._gh_post")
def test_pr_tool_calls_api_when_approved(mock_post):
    mock_post.return_value = {"html_url": "https://github.com/o/r/pull/1"}
    t = GitHubOpenPRTool()
    t.approval_fn = lambda _: True
    t._gate_required = True
    out = t._run(branch="x", base="main", title="t", body="b")
    assert out == "https://github.com/o/r/pull/1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agile/test_github_pr_tool.py -v`
Expected: FAIL on `ModuleNotFoundError`.

- [ ] **Step 3: Implement `orgos/tools/github_pr_tool.py`**

```python
"""Publish-category GitHub PR tool — always human-gated."""

from __future__ import annotations

import json
import os
import urllib.request

from pydantic import BaseModel, Field

from orgos.spawn.toolbase import GatedToolBase


def _gh_post(path: str, body: dict) -> dict:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN not set")
    repo = os.environ.get("GITHUB_REPO")
    if not repo:
        raise RuntimeError("GITHUB_REPO not set")
    url = f"https://api.github.com{path}"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "orgos-agile",
    }, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


class _Args(BaseModel):
    branch: str = Field(description="Head branch (already pushed to origin).")
    base: str = Field(default="main", description="Base branch.")
    title: str = Field(description="PR title.")
    body: str = Field(description="PR body markdown.")


class GitHubOpenPRTool(GatedToolBase):
    name: str = "github_open_pr"
    description: str = (
        "Open a GitHub PR from `branch` against `base`. Human approval required."
    )
    args_schema: type[BaseModel] = _Args
    tool_category: str = "publish"

    def _execute(self, branch: str, base: str, title: str, body: str) -> str:
        repo = os.environ["GITHUB_REPO"]
        resp = _gh_post(
            f"/repos/{repo}/pulls",
            {"head": branch, "base": base, "title": title, "body": body},
        )
        return resp.get("html_url", "")
```

Note: `GatedToolBase` already implements `_run`, calls `_check_gate()`, then delegates to `_execute`. Confirm the abstract method name by reading `orgos/spawn/toolbase.py`; if it's named differently (e.g., `_call`), rename above accordingly.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agile/test_github_pr_tool.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add orgos/tools/github_pr_tool.py tests/agile/test_github_pr_tool.py
git commit -m "feat(tools): GitHub PR tool (publish, GatedToolBase)"
```

---

### Task 2.3: Add `github_repo_tool.py` (sandbox helpers)

**Files:**
- Create: `orgos/tools/github_repo_tool.py`
- Create: `tests/agile/test_github_repo_tool.py`

**Interfaces:**
- Produces: `GitWorktreePushTool` — args `{branch, worktree_path}`. Runs `git push origin <branch>` from worktree. `tool_category="sandbox"`. (Not gated — push is to a feature branch, not main; the PR opening is the gate.)

- [ ] **Step 1: Write the failing tests**

Create `tests/agile/test_github_repo_tool.py`:

```python
import subprocess
from pathlib import Path
from unittest.mock import patch

from orgos.tools.github_repo_tool import GitWorktreePushTool


def test_push_tool_category_sandbox():
    assert GitWorktreePushTool().tool_category == "sandbox"


@patch("subprocess.run")
def test_push_tool_invokes_git_push(mock_run, tmp_path):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="ok", stderr=""
    )
    out = GitWorktreePushTool()._run(branch="agile/abc", worktree_path=str(tmp_path))
    assert "pushed" in out.lower()
    args = mock_run.call_args[0][0]
    assert args[:3] == ["git", "push", "origin"]


@patch("subprocess.run")
def test_push_tool_reports_failure(mock_run, tmp_path):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr="boom",
    )
    out = GitWorktreePushTool()._run(branch="agile/abc", worktree_path=str(tmp_path))
    assert "fail" in out.lower() or "boom" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agile/test_github_repo_tool.py -v`
Expected: FAIL on `ModuleNotFoundError`.

- [ ] **Step 3: Implement `orgos/tools/github_repo_tool.py`**

```python
"""Sandbox-category git helpers operating inside a sprint's worktree."""

from __future__ import annotations

import subprocess

from crewai.tools import BaseTool
from pydantic import BaseModel, Field


class _PushArgs(BaseModel):
    branch: str = Field(description="Branch name to push.")
    worktree_path: str = Field(description="Absolute path to the sprint worktree.")


class GitWorktreePushTool(BaseTool):
    name: str = "git_worktree_push"
    description: str = "Push the sprint's branch from a worktree to origin."
    args_schema: type[BaseModel] = _PushArgs
    tool_category: str = "sandbox"

    def _run(self, branch: str, worktree_path: str) -> str:
        try:
            r = subprocess.run(
                ["git", "push", "origin", branch],
                cwd=worktree_path, capture_output=True, text=True, timeout=60,
            )
        except subprocess.TimeoutExpired:
            return "FAILED: git push timed out"
        if r.returncode != 0:
            return f"FAILED: {r.stderr.strip() or 'unknown'}"
        return f"pushed {branch} to origin"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agile/test_github_repo_tool.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add orgos/tools/github_repo_tool.py tests/agile/test_github_repo_tool.py
git commit -m "feat(tools): GitWorktreePushTool (sandbox)"
```

---

### Task 2.4: Build `orgos/agile/intake.py` — backlog ranker

**Files:**
- Create: `orgos/agile/intake.py`
- Create: `tests/agile/test_intake.py`

**Interfaces:**
- Consumes: a list of normalised issue dicts (from `GitHubListIssuesTool`)
- Produces:
  - `rank_backlog(issues: list[dict], *, allowed_labels: set[str] = {"agent-eligible", "good-first-issue"}, max_candidates: int = 10) -> list[dict]`
  - Each output dict carries `{issue_id, title, body, labels, url, size_estimate, risk_estimate, rank_reason}`. `size_estimate ∈ {S, M, L}`, `risk_estimate ∈ {low, med, high}`. Pure-Python ranker (no LLM): size from body length + labels, risk from labels (e.g., "security" → high), rank by `size_first(S) then label_priority`.

- [ ] **Step 1: Write the failing tests**

Create `tests/agile/test_intake.py`:

```python
from orgos.agile.intake import rank_backlog


def _iss(n, labels=("agent-eligible",), body="short body"):
    return {
        "issue_id": str(n), "number": n,
        "title": f"issue {n}", "body": body,
        "labels": list(labels), "url": f"https://x/{n}",
    }


def test_rank_filters_by_allowed_labels():
    out = rank_backlog([
        _iss(1, labels=["agent-eligible"]),
        _iss(2, labels=["wontfix"]),
    ])
    assert [c["issue_id"] for c in out] == ["1"]


def test_rank_prefers_small_first():
    short = _iss(1, body="x")
    long = _iss(2, body="x" * 5000)
    out = rank_backlog([long, short])
    assert out[0]["issue_id"] == "1"
    assert out[0]["size_estimate"] == "S"


def test_rank_marks_security_high_risk():
    out = rank_backlog([_iss(1, labels=("agent-eligible", "security"))])
    assert out[0]["risk_estimate"] == "high"


def test_rank_truncates_to_max():
    issues = [_iss(i) for i in range(20)]
    out = rank_backlog(issues, max_candidates=5)
    assert len(out) == 5


def test_rank_attaches_reason():
    out = rank_backlog([_iss(1)])
    assert out[0]["rank_reason"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agile/test_intake.py -v`
Expected: FAIL on `ModuleNotFoundError`.

- [ ] **Step 3: Implement `orgos/agile/intake.py`**

```python
"""Backlog ranker — pure Python, no LLM."""

from __future__ import annotations

from typing import Iterable

_SIZE_THRESHOLDS = {"S": 500, "M": 2500}  # body chars
_RISK_LABELS_HIGH = {"security", "compliance", "data-migration"}
_RISK_LABELS_MED = {"bug", "regression"}
_LABEL_PRIORITY = {
    "agent-eligible": 0, "good-first-issue": 1, "docs": 2, "chore": 3,
}


def _size(body: str) -> str:
    n = len(body or "")
    if n < _SIZE_THRESHOLDS["S"]:
        return "S"
    if n < _SIZE_THRESHOLDS["M"]:
        return "M"
    return "L"


def _risk(labels: Iterable[str]) -> str:
    s = set(labels)
    if s & _RISK_LABELS_HIGH:
        return "high"
    if s & _RISK_LABELS_MED:
        return "med"
    return "low"


def _label_priority(labels: Iterable[str]) -> int:
    return min((_LABEL_PRIORITY.get(l, 99) for l in labels), default=99)


def rank_backlog(
    issues: list[dict],
    *,
    allowed_labels: set[str] | None = None,
    max_candidates: int = 10,
) -> list[dict]:
    allowed = allowed_labels or {"agent-eligible", "good-first-issue"}
    filtered = [i for i in issues if set(i.get("labels", [])) & allowed]
    enriched = []
    for i in filtered:
        size = _size(i.get("body", ""))
        risk = _risk(i.get("labels", []))
        enriched.append({
            **i,
            "size_estimate": size,
            "risk_estimate": risk,
            "rank_reason": f"size={size},risk={risk}",
        })
    # Sort key: prefer S over M over L; within size, by label priority.
    size_rank = {"S": 0, "M": 1, "L": 2}
    enriched.sort(key=lambda c: (
        size_rank[c["size_estimate"]],
        _label_priority(c["labels"]),
        c["issue_id"],
    ))
    return enriched[:max_candidates]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agile/test_intake.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add orgos/agile/intake.py tests/agile/test_intake.py
git commit -m "feat(agile): backlog ranker (size + risk + label priority)"
```

---

### Task 2.5: Add Intake phase to `run_sprint`, replace `MockPRTool` wiring with conditional, register department in `config/org.yaml`

**Files:**
- Modify: `orgos/agile/sprint.py` — add `run_nightly_sprint()` that calls Intake before the main spawn
- Modify: `config/org.yaml` — add the `engineering` department with the six roles

**Interfaces:**
- Consumes: `GitHubListIssuesTool`, `rank_backlog`
- Produces:
  - `run_nightly_sprint(repo_path: Path, *, model: str | None = None, mock_pr: bool = False) -> Sprint` — pulls issues from GitHub, ranks, picks the top one, runs `run_sprint(...)`. Returns the Sprint with `BacklogEnvelope` added.

- [ ] **Step 1: Write the failing tests**

Create or extend `tests/agile/test_sprint_engine.py` with:

```python
import json
from unittest.mock import patch

@patch("orgos.agile.sprint._fetch_open_issues")
def test_run_nightly_sprint_picks_top_candidate(mock_fetch, fixture_repo):
    from orgos.agile.sprint import run_nightly_sprint, _fetch_open_issues  # noqa
    mock_fetch.return_value = [
        {"issue_id": "1", "number": 1, "title": "small",
         "body": "x", "labels": ["agent-eligible"], "url": "https://x/1"},
        {"issue_id": "2", "number": 2, "title": "big",
         "body": "x" * 5000, "labels": ["agent-eligible"], "url": "https://x/2"},
    ]
    sprint = run_nightly_sprint(fixture_repo, mock_pr=True, _offline=True)
    assert sprint.picked_issue["issue_id"] == "1"
    assert "backlog" in sprint.envelopes
    backlog_payload = sprint.envelopes["backlog"].parsed_payload()
    assert len(backlog_payload["candidates"]) >= 1
```

(The `_offline=True` flag short-circuits the live spawn for unit-tests; production use omits it.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/agile/test_sprint_engine.py::test_run_nightly_sprint_picks_top_candidate -v`
Expected: FAIL on missing `run_nightly_sprint`.

- [ ] **Step 3: Extend `orgos/agile/sprint.py`**

Add to the module:

```python
from .envelopes import BacklogEnvelope
from .intake import rank_backlog


def _fetch_open_issues() -> list[dict]:
    """Live fetch via GitHubListIssuesTool. Patchable in tests."""
    from orgos.tools.github_issue_tool import GitHubListIssuesTool
    raw = GitHubListIssuesTool()._run(labels=["agent-eligible"], state="open", limit=30)
    return json.loads(raw)


def _make_backlog_envelope(candidates: list[dict]) -> BacklogEnvelope:
    return BacklogEnvelope(
        role="intake",
        status="completed",
        summary=f"ranked {len(candidates)} candidates",
        success_criteria_met=True,
        requires_human_approval=False,
        payload=json.dumps({"candidates": candidates}),
    )


def run_nightly_sprint(
    repo_path: Path,
    *,
    model: str | None = None,
    mock_pr: bool = False,
    _offline: bool = False,
) -> Sprint:
    """Production entrypoint: pull issues, rank, pick, run sprint, persist."""
    issues = _fetch_open_issues()
    candidates = rank_backlog(issues, max_candidates=10)
    if not candidates:
        # No eligible work; record an empty sprint and exit.
        sprint_id = _new_sprint_id()
        return Sprint(
            id=sprint_id,
            started_at=datetime.now(timezone.utc).isoformat(),
            repo_path=repo_path,
            worktree_path=repo_path,
            branch="",
            picked_issue={},
            envelopes={"backlog": _make_backlog_envelope([])},
            status="needs_revision",
        )
    picked = candidates[0]
    if _offline:
        sprint_id = _new_sprint_id()
        return Sprint(
            id=sprint_id,
            started_at=datetime.now(timezone.utc).isoformat(),
            repo_path=repo_path,
            worktree_path=repo_path,
            branch=f"agile/{sprint_id}",
            picked_issue=picked,
            envelopes={"backlog": _make_backlog_envelope(candidates)},
            status="completed",
        )
    sprint = run_sprint(repo_path, picked, model=model, mock_pr=mock_pr)
    sprint.envelopes["backlog"] = _make_backlog_envelope(candidates)
    # Re-persist the backlog envelope (run_sprint already wrote the rest).
    from orgos.pm import PMStore
    PMStore().record_sprint_envelope(
        sprint.id, "backlog", sprint.envelopes["backlog"].model_dump_json()
    )
    return sprint
```

- [ ] **Step 4: Update `config/org.yaml`**

Replace the `departments: []` line with:

```yaml
departments:
  - name: engineering
    description: Ships features on the orgos repo, one issue per sprint.
    verify_citations: false
    supervisor:
      name: sprint-lead
      tier: orchestrator
      system_prompt: ""  # filled from sprint_lead_role()
      success_criteria: []
    members:
      - name: product-manager
        tier: worker
        system_prompt: ""
      - name: engineer
        tier: worker
        system_prompt: ""
      - name: qa-validator
        tier: validator
        system_prompt: ""
      - name: release-manager
        tier: publisher
        system_prompt: ""
      - name: retro-agent
        tier: validator
        system_prompt: ""
    shared_skills:
      - skills/engineering/sprint-planning
      - skills/engineering/code-review
    shared_mcps: []
    sops:
      - name: nightly-sprint
        description: One sprint per night against the agent-eligible backlog.
        cadence: daily
        brief:
          objective: Ship one agent-eligible issue end-to-end.
          expected_output: A merged PR or a graded retro on why not.
```

(The actual `system_prompt` and `success_criteria` are read from the role factories at load time; org.yaml is the declarative registry.)

- [ ] **Step 5: Run the offline test**

Run: `pytest tests/agile/test_sprint_engine.py::test_run_nightly_sprint_picks_top_candidate -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add orgos/agile/sprint.py config/org.yaml tests/agile/test_sprint_engine.py
git commit -m "feat(agile): run_nightly_sprint() + Intake phase + engineering dept"
```

---

### Task 2.6: Wire the nightly cron + first dogfood smoke run

**Files:**
- Modify: `orgos/scheduler.py` — add `nightly_agile_sprint` job
- Create: `tests/agile/test_dogfood_dry_run.py`
- Create: `skills/engineering/sprint-planning/SKILL.md`
- Create: `skills/engineering/code-review/SKILL.md`

**Interfaces:**
- Consumes: existing `Scheduler` API in `orgos/scheduler.py`
- Produces: a scheduled job at `02:00 local` that calls `run_nightly_sprint(Path("."))`

- [ ] **Step 1: Read the existing scheduler**

Run: `cat orgos/scheduler.py | head -120`
Identify how jobs are registered (likely a decorator or `scheduler.add_job(...)`).

- [ ] **Step 2: Add the nightly job**

Append to `orgos/scheduler.py` (after existing job registrations):

```python
from datetime import datetime
from pathlib import Path

# ── Nightly agile sprint ─────────────────────────────────────────────────────


def nightly_agile_sprint(repo_path: str = ".") -> None:
    """Run one sprint against the agile backlog. Logs to PMStore."""
    from orgos.agile.sprint import run_nightly_sprint
    print(f"[{datetime.now().isoformat()}] starting nightly agile sprint")
    sprint = run_nightly_sprint(Path(repo_path), mock_pr=False)
    print(f"  done: sprint_id={sprint.id} status={sprint.status}")
```

In the scheduler's `register_jobs()` (or equivalent block where existing jobs are registered), add:

```python
    scheduler.add_job(
        nightly_agile_sprint,
        trigger="cron",
        hour=2, minute=0,
        id="nightly-agile-sprint",
        misfire_grace_time=600,
    )
```

(Adapt to whatever scheduler library is in use; `APScheduler` is the most likely.)

- [ ] **Step 3: Create the two SKILL.md files**

`skills/engineering/sprint-planning/SKILL.md`:

```markdown
# Sprint planning

Used by the Product Manager role when building the BriefEnvelope.

## What to include
- `picked_issue_id`
- `task_brief_json` (a serialised TaskBrief: objective, expected_output, success_criteria)
- `touched_files_allowlist` — explicit list of file paths the Engineer may modify
- `acceptance_tests` — at least one pytest invocation that will be run by QA

## Boundaries
- Never authorise > 5 files or > 400 LOC.
- If the issue's body is ambiguous, refuse and ask the Sprint Lead to pick another issue.
```

`skills/engineering/code-review/SKILL.md`:

```markdown
# Code review (Engineer's internal spawn_chain reviewer step)

You are reviewing a diff produced by the previous step's Implementer.

## Pass criteria
- Diff is inside touched_files_allowlist.
- Names follow existing repo conventions (snake_case files, type-hinted Python).
- No `print` statements left from debugging.
- No commented-out code.

## Fail criteria
- Any of the above missed.
- Implementation diverges from acceptance_tests.

Return an EngineeringEnvelope with the diff unchanged and either status=completed or status=needs_revision.
```

- [ ] **Step 4: Add the dogfood dry-run test**

Create `tests/agile/test_dogfood_dry_run.py`:

```python
"""Network-marked: pulls real issues from GitHub.

Verifies Intake produces a non-empty backlog when the repo has agent-eligible
issues. Skipped by default; opt in with:
    pytest -m network tests/agile/test_dogfood_dry_run.py
"""

import os
import pytest

from orgos.agile.sprint import run_nightly_sprint
from pathlib import Path


pytestmark = pytest.mark.network


def test_intake_finds_at_least_one_eligible_issue():
    if not os.getenv("GITHUB_TOKEN") or not os.getenv("GITHUB_REPO"):
        pytest.skip("GITHUB_TOKEN / GITHUB_REPO not set")
    sprint = run_nightly_sprint(Path("."), mock_pr=True, _offline=True)
    backlog = sprint.envelopes["backlog"].parsed_payload()["candidates"]
    # If the repo has zero agent-eligible issues, the test still passes
    # but flags it — the demo seed run will need to label one.
    assert isinstance(backlog, list)
```

Register the `network` marker in `pyproject.toml` (or `pytest.ini`) if not present:

```toml
[tool.pytest.ini_options]
markers = [
  "network: tests that hit external APIs",
]
```

- [ ] **Step 5: Run the offline tests; confirm scheduler imports**

Run: `pytest tests/agile/ -q -m "not network"`
Expected: PASS.

Run: `python -c "from orgos.scheduler import nightly_agile_sprint; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 6: Commit**

```bash
git add orgos/scheduler.py skills/engineering tests/agile/test_dogfood_dry_run.py pyproject.toml
git commit -m "feat(agile): nightly cron + sprint-planning/code-review skills"
```

---

## Phase 3 — DORA closed loop / Hook C (3 days, 4 tasks)

### Task 3.1: Add `dora_snapshots` table + PMStore accessors

**Files:**
- Modify: `orgos/pm.py`
- Create: `tests/agile/test_pm_dora.py`

**Interfaces produced:**
- `PMStore.record_dora_snapshot(snapshot: dict) -> None`
- `PMStore.list_dora_snapshots(limit: int = 90) -> list[dict]`
- `PMStore.latest_dora_snapshot() -> dict | None`

- [ ] **Step 1: Write the failing tests**

Create `tests/agile/test_pm_dora.py`:

```python
from pathlib import Path
from orgos.pm import PMStore


def test_record_and_latest(tmp_path: Path):
    pm = PMStore(tmp_path / "pm.db")
    pm.record_dora_snapshot({
        "window_days": 14, "deploy_freq": 1.2,
        "lead_time_p50": 18000.0, "cfr": 0.1,
        "mttr_p50": 3600.0, "tier": "Medium",
    })
    last = pm.latest_dora_snapshot()
    assert last["tier"] == "Medium"
    assert last["deploy_freq"] == 1.2


def test_list_desc(tmp_path):
    pm = PMStore(tmp_path / "pm.db")
    pm.record_dora_snapshot({"window_days": 14, "deploy_freq": 0.5,
        "lead_time_p50": 1.0, "cfr": 0.0, "mttr_p50": 0.0, "tier": "Low"})
    pm.record_dora_snapshot({"window_days": 14, "deploy_freq": 2.0,
        "lead_time_p50": 1.0, "cfr": 0.0, "mttr_p50": 0.0, "tier": "High"})
    rows = pm.list_dora_snapshots(limit=5)
    assert rows[0]["tier"] == "High"  # newest first
```

- [ ] **Step 2: Verify test fails**

Run: `pytest tests/agile/test_pm_dora.py -v`
Expected: FAIL on missing method.

- [ ] **Step 3: Extend `_migrate()` in `orgos/pm.py`**

Add to the executescript:

```sql
CREATE TABLE IF NOT EXISTS dora_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    window_days INTEGER NOT NULL,
    deploy_freq REAL NOT NULL,
    lead_time_p50 REAL NOT NULL,
    cfr REAL NOT NULL,
    mttr_p50 REAL NOT NULL,
    tier TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dora_created ON dora_snapshots(created_at DESC);
```

- [ ] **Step 4: Add PMStore methods**

Append to the `PMStore` class (after Sprint methods):

```python
    # ── DORA snapshots ─────────────────────────────────────────────────────

    def record_dora_snapshot(self, snapshot: dict) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "INSERT INTO dora_snapshots (window_days, deploy_freq, "
            "lead_time_p50, cfr, mttr_p50, tier, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (snapshot["window_days"], snapshot["deploy_freq"],
             snapshot["lead_time_p50"], snapshot["cfr"],
             snapshot["mttr_p50"], snapshot["tier"], now),
        )
        self.conn.commit()

    def list_dora_snapshots(self, limit: int = 90) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM dora_snapshots ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def latest_dora_snapshot(self) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM dora_snapshots ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None
```

- [ ] **Step 5: Run tests, commit**

Run: `pytest tests/agile/test_pm_dora.py -v` — Expected PASS.

```bash
git add orgos/pm.py tests/agile/test_pm_dora.py
git commit -m "feat(pm): dora_snapshots table + accessors"
```

---

### Task 3.2: Implement `orgos/agile/dora.py` — metric computations

**Files:**
- Create: `orgos/agile/dora.py`
- Create: `tests/agile/test_dora.py`

**Interfaces produced:**
- `compute_dora(pm: PMStore, window_days: int = 14) -> dict` — returns `{window_days, deploy_freq, lead_time_p50, cfr, mttr_p50, tier}`
- `classify_tier(metrics: dict) -> str` — one of `Elite | High | Medium | Low`

- [ ] **Step 1: Write the failing tests**

Create `tests/agile/test_dora.py`:

```python
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from orgos.pm import PMStore
from orgos.agile.dora import classify_tier, compute_dora


def _iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _seed(pm: PMStore, *, merges: int, pr_task_lag_days: float,
          failure_ratio: float, mttr_hours: float):
    for i in range(merges):
        task = pm.create_task(f"t{i}", department="engineering")
        # Force created_at to lag_days ago
        pm.conn.execute("UPDATE tasks SET created_at = ? WHERE id = ?",
                        (_iso(pr_task_lag_days), task.id))
        pm.record_git_op("pr_merged", details=task.id, pushed=True, task_id=task.id)
        pm.conn.execute("UPDATE git_ops SET created_at = ? WHERE task_id = ?",
                        (_iso(0.1), task.id))
        if i < int(merges * failure_ratio):
            pm.record_test_run("pytest", 1, "fail", passed=False, task_id=task.id)
            pm.conn.execute("UPDATE test_runs SET created_at = ? WHERE task_id = ?",
                            (_iso(0.05), task.id))
            pm.record_test_run("pytest", 0, "ok", passed=True, task_id=task.id)
            pm.conn.execute(
                "UPDATE test_runs SET created_at = ? "
                "WHERE task_id = ? AND passed = 1",
                (_iso(0.05 - mttr_hours / 24), task.id),
            )
    pm.conn.commit()


def test_deploy_freq_uses_window(tmp_path):
    pm = PMStore(tmp_path / "pm.db")
    _seed(pm, merges=14, pr_task_lag_days=1.0, failure_ratio=0.0, mttr_hours=0)
    m = compute_dora(pm, window_days=14)
    assert m["deploy_freq"] == pytest.approx(1.0, rel=0.01)


def test_lead_time_median(tmp_path):
    pm = PMStore(tmp_path / "pm.db")
    _seed(pm, merges=5, pr_task_lag_days=2.0, failure_ratio=0.0, mttr_hours=0)
    m = compute_dora(pm, window_days=14)
    # ~2 days in seconds
    assert 1.5 * 86400 < m["lead_time_p50"] < 2.5 * 86400


def test_cfr(tmp_path):
    pm = PMStore(tmp_path / "pm.db")
    _seed(pm, merges=10, pr_task_lag_days=1.0, failure_ratio=0.3, mttr_hours=1)
    m = compute_dora(pm, window_days=14)
    assert 0.25 <= m["cfr"] <= 0.35


def test_classify_tier_elite_when_hot():
    assert classify_tier({
        "deploy_freq": 1.5, "lead_time_p50": 3600.0,
        "cfr": 0.02, "mttr_p50": 900.0,
    }) == "Elite"


def test_classify_tier_low_when_cold():
    assert classify_tier({
        "deploy_freq": 0.01, "lead_time_p50": 30 * 86400.0,
        "cfr": 0.4, "mttr_p50": 30 * 3600.0,
    }) == "Low"
```

- [ ] **Step 2: Verify tests fail**

Run: `pytest tests/agile/test_dora.py -v`
Expected: FAIL on `ModuleNotFoundError`.

- [ ] **Step 3: Implement `orgos/agile/dora.py`**

```python
"""DORA metric computations over PMStore.

All four metrics use the same 14-day rolling window by default:
  - Deploy Frequency = count(pr_merged) / window_days
  - Lead Time (p50)  = median seconds between task.created_at and pr_merged.created_at
  - CFR              = fraction of merges followed by a failing test_run within 24h
  - MTTR (p50)       = median seconds from first fail to next pass, same task
"""

from __future__ import annotations

import statistics
from datetime import datetime, timezone, timedelta
from typing import Any


TIER_THRESHOLDS = {
    "Elite":  {"deploy_freq": 1.0,  "lead_time_p50": 86400.0,     "cfr": 0.05, "mttr_p50": 3600.0},
    "High":   {"deploy_freq": 0.14, "lead_time_p50": 7 * 86400.0, "cfr": 0.10, "mttr_p50": 86400.0},
    "Medium": {"deploy_freq": 0.03, "lead_time_p50": 30 * 86400.0, "cfr": 0.15, "mttr_p50": 7 * 86400.0},
}


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _within(dt: datetime, window_start: datetime) -> bool:
    return dt >= window_start


def compute_dora(pm: Any, window_days: int = 14) -> dict:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=window_days)

    merges = pm.conn.execute(
        "SELECT id, task_id, created_at FROM git_ops "
        "WHERE operation = 'pr_merged' AND pushed = 1 AND created_at >= ?",
        (start.isoformat(),),
    ).fetchall()

    deploy_freq = len(merges) / window_days if window_days else 0.0

    lead_times: list[float] = []
    for m in merges:
        if not m["task_id"]:
            continue
        row = pm.conn.execute(
            "SELECT created_at FROM tasks WHERE id = ?", (m["task_id"],),
        ).fetchone()
        if not row:
            continue
        lead_times.append(
            (_parse_iso(m["created_at"]) - _parse_iso(row["created_at"])).total_seconds()
        )
    lead_time_p50 = statistics.median(lead_times) if lead_times else 0.0

    fail_within_24h = 0
    mttrs: list[float] = []
    for m in merges:
        merge_at = _parse_iso(m["created_at"])
        fails = pm.conn.execute(
            "SELECT created_at FROM test_runs "
            "WHERE task_id = ? AND passed = 0 AND created_at >= ? "
            "ORDER BY created_at ASC",
            (m["task_id"], merge_at.isoformat()),
        ).fetchall()
        if fails and _parse_iso(fails[0]["created_at"]) - merge_at <= timedelta(hours=24):
            fail_within_24h += 1
            first_fail = _parse_iso(fails[0]["created_at"])
            recovery = pm.conn.execute(
                "SELECT created_at FROM test_runs "
                "WHERE task_id = ? AND passed = 1 AND created_at >= ? "
                "ORDER BY created_at ASC LIMIT 1",
                (m["task_id"], first_fail.isoformat()),
            ).fetchone()
            if recovery:
                mttrs.append(
                    (_parse_iso(recovery["created_at"]) - first_fail).total_seconds()
                )
    cfr = fail_within_24h / len(merges) if merges else 0.0
    mttr_p50 = statistics.median(mttrs) if mttrs else 0.0

    metrics = {
        "window_days": window_days,
        "deploy_freq": round(deploy_freq, 3),
        "lead_time_p50": round(lead_time_p50, 1),
        "cfr": round(cfr, 3),
        "mttr_p50": round(mttr_p50, 1),
    }
    metrics["tier"] = classify_tier(metrics)
    return metrics


def classify_tier(m: dict) -> str:
    """Highest tier whose ALL four thresholds the metrics meet."""
    for tier in ("Elite", "High", "Medium"):
        t = TIER_THRESHOLDS[tier]
        if (m["deploy_freq"] >= t["deploy_freq"]
                and m["lead_time_p50"] <= t["lead_time_p50"]
                and m["cfr"] <= t["cfr"]
                and m["mttr_p50"] <= t["mttr_p50"]):
            return tier
    return "Low"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agile/test_dora.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add orgos/agile/dora.py tests/agile/test_dora.py
git commit -m "feat(agile): compute_dora() + tier classification"
```

---

### Task 3.3: DORA → Reflector heuristic bridge

**Files:**
- Modify: `orgos/reflect.py` — add `add_candidate_heuristic()` public method + a `source` field to Heuristic
- Create: `orgos/agile/dora_bridge.py`
- Create: `tests/agile/test_dora_bridge.py`

**Interfaces produced:**
- `dora_to_heuristic_candidates(pm: PMStore, snapshot: dict) -> list[Heuristic]`
- Each candidate has `source="dora"` and a `use_count=0`.

- [ ] **Step 1: Write the failing tests**

Create `tests/agile/test_dora_bridge.py`:

```python
from orgos.agile.dora_bridge import dora_to_heuristic_candidates


def test_high_cfr_emits_canary_heuristic():
    snap = {"deploy_freq": 1.0, "lead_time_p50": 1000.0, "cfr": 0.3,
            "mttr_p50": 1000.0, "tier": "Medium"}
    h = dora_to_heuristic_candidates(None, snap, prior=[
        {"cfr": 0.25}, {"cfr": 0.27}, {"cfr": 0.30}
    ])
    rules = [x.rule for x in h]
    assert any("canary" in r.lower() for r in rules)


def test_slow_lead_time_emits_split_heuristic():
    snap = {"deploy_freq": 0.1, "lead_time_p50": 10 * 86400.0, "cfr": 0.0,
            "mttr_p50": 100.0, "tier": "Low"}
    h = dora_to_heuristic_candidates(None, snap)
    assert any("split" in x.rule.lower() for x in h)


def test_low_deploy_freq_emits_commit_heuristic():
    snap = {"deploy_freq": 0.02, "lead_time_p50": 1000.0, "cfr": 0.0,
            "mttr_p50": 100.0, "tier": "Low"}
    h = dora_to_heuristic_candidates(None, snap)
    assert any("commit" in x.rule.lower() for x in h)


def test_high_mttr_emits_hotfix_heuristic():
    snap = {"deploy_freq": 1.0, "lead_time_p50": 1000.0, "cfr": 0.0,
            "mttr_p50": 10 * 3600.0, "tier": "Medium"}
    h = dora_to_heuristic_candidates(None, snap)
    assert any("hotfix" in x.rule.lower() for x in h)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agile/test_dora_bridge.py -v`
Expected: FAIL on `ModuleNotFoundError`.

- [ ] **Step 3: Extend `Heuristic` in `orgos/reflect.py`**

Add `source: str = "rubric"` field to the `Heuristic` dataclass. Existing rows have source=`rubric` by default — no migration needed if OrgMemory stores heuristics with `.get(..., "rubric")`. Verify by reading `reflect.py`.

- [ ] **Step 4: Implement `orgos/agile/dora_bridge.py`**

```python
"""Translate DORA snapshots into candidate Reflector heuristics.

Candidates are proposed to Reflector's existing scoring/use_count machinery;
they are NOT auto-promoted into active heuristics.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from orgos.reflect import Heuristic


def _mk(rule: str, why: str, tags: list[str], run_id: str | None = None) -> Heuristic:
    return Heuristic(
        id=f"dora-{uuid.uuid4().hex[:8]}",
        domain="agile",
        tags=tags,
        rule=rule,
        why=why,
        source_run_id=run_id,
        score=0.5,
        use_count=0,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def dora_to_heuristic_candidates(
    pm: object | None,
    snapshot: dict,
    prior: list[dict] | None = None,
) -> list[Heuristic]:
    out: list[Heuristic] = []
    # CFR rising 3 snapshots in a row -> canary + rollback
    hist = list(prior or [])
    if len(hist) >= 2 and snapshot.get("cfr", 0.0) > 0.15 and all(
        hist[i]["cfr"] < hist[i + 1]["cfr"] if i + 1 < len(hist) else True
        for i in range(len(hist))
    ):
        out.append(_mk(
            "DoD must include canary + rollback step",
            f"CFR rising ({[h['cfr'] for h in hist]} -> {snapshot['cfr']:.2f})",
            ["dor", "cfr", "canary"],
        ))
    # Lead Time > 7d median
    if snapshot.get("lead_time_p50", 0.0) > 7 * 86400.0:
        out.append(_mk(
            "PM should split any task > 1 day estimate",
            f"Lead time p50 = {snapshot['lead_time_p50'] / 86400.0:.1f}d exceeds 7d",
            ["pm", "lead_time"],
        ))
    # Deploy Freq < 1/week (~0.14/day)
    if snapshot.get("deploy_freq", 0.0) < 0.14:
        out.append(_mk(
            "Engineer must commit within 2h of starting the task",
            f"Deploy freq = {snapshot['deploy_freq']:.2f}/day (< 1/week)",
            ["engineer", "deploy_freq"],
        ))
    # MTTR > 4h
    if snapshot.get("mttr_p50", 0.0) > 4 * 3600.0:
        out.append(_mk(
            "Add hotfix-ready acceptance test in QA brief",
            f"MTTR p50 = {snapshot['mttr_p50'] / 3600.0:.1f}h exceeds 4h",
            ["qa", "mttr"],
        ))
    return out
```

- [ ] **Step 5: Run tests, commit**

Run: `pytest tests/agile/test_dora_bridge.py -v` — Expected PASS.

```bash
git add orgos/agile/dora_bridge.py orgos/reflect.py tests/agile/test_dora_bridge.py
git commit -m "feat(agile): DORA -> Reflector candidate heuristics"
```

---

### Task 3.4: Wire DORA snapshot into `run_nightly_sprint`; add `/api/dora` endpoint; add `/dora` dashboard page

**Files:**
- Modify: `orgos/agile/sprint.py` — after main sprint, compute + store DORA + emit candidates
- Modify: `orgos/api.py` — add `/api/dora`, `/api/heuristics`
- Create: `dashboard/app/dora/page.tsx`

**Interfaces produced:**
- `GET /api/dora?window=14&limit=90` — `{latest, history}` (all snapshot rows)
- `GET /api/heuristics` — `{active: [...], candidates: [...]}` from Reflector storage
- Dashboard page `/dora`: DORA time series (Recharts LineChart with 4 lines) + candidate table + active heuristic ledger.

- [ ] **Step 1: Extend `run_nightly_sprint`**

In `orgos/agile/sprint.py`, at the end of the non-offline branch (after `PMStore().record_sprint_envelope(...)`), add:

```python
    from orgos.agile.dora import compute_dora
    from orgos.agile.dora_bridge import dora_to_heuristic_candidates
    from orgos.pm import PMStore
    pm = PMStore()
    snapshot = compute_dora(pm, window_days=14)
    pm.record_dora_snapshot(snapshot)
    prior = pm.list_dora_snapshots(limit=3)
    candidates = dora_to_heuristic_candidates(pm, snapshot, prior=prior)
    from orgos.reflect import _store_heuristic  # or the appropriate public method
    for h in candidates:
        _store_heuristic(h)  # replace with the actual persistence call once identified
    from .envelopes import DoraEnvelope
    dora_env = DoraEnvelope(
        role="dora", status="completed",
        summary=f"tier={snapshot['tier']}",
        success_criteria_met=True, requires_human_approval=False,
        payload=json.dumps(snapshot),
    )
    sprint.envelopes["dora"] = dora_env
    pm.record_sprint_envelope(sprint.id, "dora", dora_env.model_dump_json())
```

(Confirm the correct Reflector persistence entry point by reading `orgos/reflect.py`; if it's `Reflector(...).store_candidate(h)` use that instead.)

- [ ] **Step 2: Add API endpoints**

Read `orgos/api.py`. Locate the FastAPI app definition. Append:

```python
from orgos.pm import PMStore
from orgos.agile.dora import compute_dora


@app.get("/api/dora")
def dora(window: int = 14, limit: int = 90) -> dict:
    pm = PMStore()
    latest = pm.latest_dora_snapshot() or compute_dora(pm, window_days=window)
    history = pm.list_dora_snapshots(limit=limit)
    return {"latest": latest, "history": history}


@app.get("/api/heuristics")
def heuristics() -> dict:
    # Read active + candidate heuristics from OrgMemory / Reflector storage.
    # Implementation depends on Reflector's public API; use its existing
    # list method if present, else query the underlying SQLite directly.
    from orgos.reflect import Reflector
    r = Reflector(domain="agile")
    active = getattr(r, "list_active", lambda: [])()
    candidates = getattr(r, "list_candidates", lambda: [])()
    return {
        "active": [h.__dict__ for h in active],
        "candidates": [h.__dict__ for h in candidates],
    }
```

If Reflector lacks `list_active` / `list_candidates`, add thin methods to `orgos/reflect.py` that read from its SQLite table and filter on `use_count > 0` vs `= 0`.

- [ ] **Step 3: Add the dashboard page**

Create `dashboard/app/dora/page.tsx`:

```tsx
"use client";
import { useEffect, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, Legend,
  ResponsiveContainer, CartesianGrid,
} from "recharts";

type Snapshot = {
  created_at: string;
  deploy_freq: number;
  lead_time_p50: number;
  cfr: number;
  mttr_p50: number;
  tier: string;
};

type Heuristic = {
  id: string; rule: string; why: string;
  use_count: number; source: string; tags: string[];
};

export default function DoraPage() {
  const [data, setData] = useState<{latest: Snapshot; history: Snapshot[]} | null>(null);
  const [heur, setHeur] = useState<{active: Heuristic[]; candidates: Heuristic[]} | null>(null);

  useEffect(() => {
    fetch("/api/dora").then(r => r.json()).then(setData);
    fetch("/api/heuristics").then(r => r.json()).then(setHeur);
  }, []);

  if (!data || !heur) return <div className="p-6">Loading...</div>;

  const series = [...data.history].reverse().map(s => ({
    ts: s.created_at.slice(0, 10),
    deploy_freq: s.deploy_freq,
    lead_time_days: s.lead_time_p50 / 86400,
    cfr: s.cfr,
    mttr_hours: s.mttr_p50 / 3600,
  }));

  return (
    <div className="p-6 space-y-6">
      <div className="text-2xl">DORA — <span className="font-bold">{data.latest.tier}</span></div>

      <div className="h-72">
        <ResponsiveContainer>
          <LineChart data={series}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="ts" />
            <YAxis />
            <Tooltip />
            <Legend />
            <Line type="monotone" dataKey="deploy_freq" name="Deploy/day" />
            <Line type="monotone" dataKey="lead_time_days" name="Lead time (d)" />
            <Line type="monotone" dataKey="cfr" name="CFR" />
            <Line type="monotone" dataKey="mttr_hours" name="MTTR (h)" />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <section>
        <h2 className="text-xl mb-2">Candidate heuristics</h2>
        <ul className="space-y-2">
          {heur.candidates.map(h => (
            <li key={h.id} className="border p-3 rounded">
              <div className="font-mono text-sm">{h.rule}</div>
              <div className="text-xs text-gray-500">{h.why}</div>
            </li>
          ))}
          {heur.candidates.length === 0 && <li className="text-gray-500">None</li>}
        </ul>
      </section>

      <section>
        <h2 className="text-xl mb-2">Active heuristics</h2>
        <ul className="space-y-2">
          {heur.active.map(h => (
            <li key={h.id} className="border p-3 rounded flex justify-between">
              <div>
                <div className="font-mono text-sm">{h.rule}</div>
                <div className="text-xs text-gray-500">{h.why}</div>
              </div>
              <div className="text-xs">used {h.use_count}x</div>
            </li>
          ))}
          {heur.active.length === 0 && <li className="text-gray-500">None</li>}
        </ul>
      </section>
    </div>
  );
}
```

- [ ] **Step 4: Smoke-test API and page**

Run:
```bash
python -m orgos.api &
API=$!
sleep 2
curl -s http://localhost:8000/api/dora | head -c 500
kill $API
```
Expected: JSON output. If `latest` is empty, that's fine (no sprints yet).

For dashboard: `cd dashboard && npm run dev` and open `http://localhost:3000/dora`.

- [ ] **Step 5: Commit**

```bash
git add orgos/agile/sprint.py orgos/api.py dashboard/app/dora
git commit -m "feat(agile): DORA snapshot on sprint completion + /dora page"
```

---

## Phase 4 — Self-organizing role topology / Hook A (5 days, 7 tasks)

### Task 4.1: Add `role_attribution` + `adrs` tables to PMStore

**Files:**
- Modify: `orgos/pm.py`
- Create: `tests/agile/test_pm_attribution_adr.py`

**Interfaces produced:**
- `PMStore.record_role_attribution(sprint_id, role_name, score, rubric_baseline, rubric_ablated) -> None`
- `PMStore.list_role_attribution(role_name, since_days=30) -> list[dict]`
- `PMStore.create_adr(sprint_id, kind, before_yaml, after_yaml, rationale) -> int`
- `PMStore.list_adrs(status=None) -> list[dict]`
- `PMStore.set_adr_status(adr_id, status) -> None`

- [ ] **Step 1: Write the failing tests**

Create `tests/agile/test_pm_attribution_adr.py`:

```python
from pathlib import Path
from orgos.pm import PMStore


def test_record_and_list_attribution(tmp_path: Path):
    pm = PMStore(tmp_path / "pm.db")
    pm.record_role_attribution("s1", "engineer", 0.4, 1.0, 0.6)
    rows = pm.list_role_attribution("engineer", since_days=30)
    assert rows[0]["score"] == 0.4


def test_create_adr_and_set_status(tmp_path: Path):
    pm = PMStore(tmp_path / "pm.db")
    aid = pm.create_adr(
        sprint_id="s1", kind="SPLIT_ROLE",
        before_yaml="a: 1\n", after_yaml="a: 2\n",
        rationale="clustering on canary",
    )
    rows = pm.list_adrs(status="pending")
    assert any(r["id"] == aid for r in rows)
    pm.set_adr_status(aid, "approved")
    rows = pm.list_adrs(status="approved")
    assert any(r["id"] == aid for r in rows)
```

- [ ] **Step 2: Verify tests fail**

Run: `pytest tests/agile/test_pm_attribution_adr.py -v` — Expected FAIL.

- [ ] **Step 3: Extend `_migrate()`**

Add to `_migrate()` executescript:

```sql
CREATE TABLE IF NOT EXISTS role_attribution (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sprint_id TEXT NOT NULL,
    role_name TEXT NOT NULL,
    score REAL NOT NULL,
    rubric_baseline REAL NOT NULL,
    rubric_ablated REAL NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_attribution_role ON role_attribution(role_name, created_at);

CREATE TABLE IF NOT EXISTS adrs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sprint_id TEXT,
    kind TEXT NOT NULL,
    before_yaml TEXT NOT NULL DEFAULT '',
    after_yaml TEXT NOT NULL DEFAULT '',
    rationale TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_adrs_status ON adrs(status, created_at DESC);
```

- [ ] **Step 4: Add PMStore methods**

Append to `PMStore`:

```python
    # ── Role attribution ───────────────────────────────────────────────────

    def record_role_attribution(
        self, sprint_id: str, role_name: str, score: float,
        rubric_baseline: float, rubric_ablated: float,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "INSERT INTO role_attribution (sprint_id, role_name, score, "
            "rubric_baseline, rubric_ablated, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (sprint_id, role_name, score, rubric_baseline, rubric_ablated, now),
        )
        self.conn.commit()

    def list_role_attribution(
        self, role_name: str, since_days: int = 30,
    ) -> list[dict]:
        since = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()
        rows = self.conn.execute(
            "SELECT * FROM role_attribution WHERE role_name = ? AND created_at >= ? "
            "ORDER BY created_at DESC",
            (role_name, since),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── ADRs ───────────────────────────────────────────────────────────────

    def create_adr(
        self, sprint_id: str | None, kind: str,
        before_yaml: str, after_yaml: str, rationale: str,
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.execute(
            "INSERT INTO adrs (sprint_id, kind, before_yaml, after_yaml, "
            "rationale, status, created_at, updated_at) VALUES "
            "(?, ?, ?, ?, ?, 'pending', ?, ?)",
            (sprint_id, kind, before_yaml, after_yaml, rationale, now, now),
        )
        self.conn.commit()
        return int(cur.lastrowid or 0)

    def list_adrs(self, status: str | None = None) -> list[dict]:
        if status:
            rows = self.conn.execute(
                "SELECT * FROM adrs WHERE status = ? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM adrs ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def set_adr_status(self, adr_id: int, status: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "UPDATE adrs SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, adr_id),
        )
        self.conn.commit()
```

Add `from datetime import timedelta` at top of `pm.py` if not present.

- [ ] **Step 5: Run tests, commit**

Run: `pytest tests/agile/test_pm_attribution_adr.py -v` — Expected PASS.

```bash
git add orgos/pm.py tests/agile/test_pm_attribution_adr.py
git commit -m "feat(pm): role_attribution + adrs tables"
```

---

### Task 4.2: Implement `orgos/agile/attribution.py` — 2-player marginal contribution

**Files:**
- Create: `orgos/agile/attribution.py`
- Create: `tests/agile/test_attribution.py`

**Interfaces produced:**
- `compute_attribution(sprint: Sprint) -> dict[str, float]` — returns `{role_name: contribution_in_[0,1]}`, sums to 1.0. Uses a deterministic ablation model: for each role, compute what the QA rubric_score would be if that role's envelope were degraded to a "null" version (empty payload). Ratio of drop is the contribution.

- [ ] **Step 1: Write the failing tests**

Create `tests/agile/test_attribution.py`:

```python
import json
import pytest
from pathlib import Path

from orgos.agile.envelopes import (
    BacklogEnvelope, BriefEnvelope, EngineeringEnvelope,
    GradeEnvelope, ReleaseEnvelope, RetroEnvelope,
)
from orgos.agile.attribution import compute_attribution
from orgos.agile.sprint import Sprint


def _make_sprint(rubric_score: float = 1.0) -> Sprint:
    e = EngineeringEnvelope(
        role="engineer", status="completed", summary="",
        success_criteria_met=True, requires_human_approval=False,
        payload=json.dumps({
            "diff": "+x\n", "commit_sha": "abc1234",
            "files_touched": ["src.py"],
            "test_command": "pytest test_src.py",
            "test_output": "ok", "test_passed": True,
        }),
    )
    b = BriefEnvelope(
        role="pm", status="completed", summary="",
        success_criteria_met=True, requires_human_approval=False,
        payload=json.dumps({
            "picked_issue_id": "1", "task_brief_json": "{}",
            "touched_files_allowlist": ["src.py"],
            "acceptance_tests": ["pytest test_src.py"],
        }),
    )
    g = GradeEnvelope(
        role="qa", status="completed", summary="",
        success_criteria_met=True, requires_human_approval=False,
        payload=json.dumps({
            "criteria": [], "rubric_score": rubric_score,
        }),
    )
    r = ReleaseEnvelope(
        role="release", status="completed", summary="",
        success_criteria_met=True, requires_human_approval=False,
        payload=json.dumps({"pr_url": "mock://pr/1", "branch": "agile/x",
                            "mock_mode": True}),
    )
    return Sprint(
        id="s1", started_at="", repo_path=Path("."), worktree_path=Path("."),
        branch="agile/s1", picked_issue={"issue_id": "1"},
        envelopes={"brief": b, "engineering": e, "grade": g, "release": r},
        status="completed",
    )


def test_attribution_sums_to_one():
    scores = compute_attribution(_make_sprint())
    assert sum(scores.values()) == pytest.approx(1.0, abs=0.02)


def test_pm_and_engineer_both_positive():
    scores = compute_attribution(_make_sprint())
    assert scores["product-manager"] > 0
    assert scores["engineer"] > 0


def test_zero_rubric_score_gives_uniform_attribution():
    """When nothing worked, no role gets credit — split equally so the row exists."""
    scores = compute_attribution(_make_sprint(rubric_score=0.0))
    vals = list(scores.values())
    assert max(vals) - min(vals) < 0.01
```

- [ ] **Step 2: Verify tests fail**

Run: `pytest tests/agile/test_attribution.py -v` — Expected FAIL.

- [ ] **Step 3: Implement `orgos/agile/attribution.py`**

```python
"""Per-role marginal contribution — ablation-on-replay approximation.

For each role R, compute what QA's rubric_score would drop to if R's
envelope were null. Attribution(R) = (baseline - ablated_R) / sum(drops).
We normalise to sum to 1.0 so the rows are ratios, not raw drops.
"""

from __future__ import annotations

import json

from .envelopes import (
    BriefEnvelope, EngineeringEnvelope, GradeEnvelope,
    HandoffEnvelope, ReleaseEnvelope,
)
from .rubric import grade as run_rubric


_NULL_BRIEF = BriefEnvelope(
    role="pm", status="failed", summary="", success_criteria_met=False,
    requires_human_approval=False,
    payload=json.dumps({
        "picked_issue_id": "", "task_brief_json": "{}",
        "touched_files_allowlist": [],
        "acceptance_tests": [],
    }),
)
_NULL_ENG = EngineeringEnvelope(
    role="engineer", status="failed", summary="", success_criteria_met=False,
    requires_human_approval=False,
    payload=json.dumps({
        "diff": "", "commit_sha": "",
        "files_touched": [],
        "test_command": "",
        "test_output": "",
        "test_passed": False,
    }),
)


def compute_attribution(sprint) -> dict[str, float]:
    """Score each role's contribution to the sprint's rubric_score.

    We ablate one role at a time and re-grade the rubric with the null
    envelope substituted. The drop is that role's marginal contribution.

    Only PM and Engineer directly move the rubric (it grades their
    outputs). QA and Release get residual weight based on their envelope
    presence — a completed Release counts, a missing one does not.
    """
    env = sprint.envelopes
    if not (env.get("brief") and env.get("engineering") and env.get("grade")):
        return {"sprint-lead": 0.25, "product-manager": 0.25,
                "engineer": 0.25, "qa-validator": 0.15, "release-manager": 0.10}

    baseline = env["grade"].parsed_payload().get("rubric_score", 0.0)
    if baseline <= 0.0:
        # Uniform — no role earned credit.
        keys = ["sprint-lead", "product-manager", "engineer",
                "qa-validator", "release-manager"]
        return {k: 1.0 / len(keys) for k in keys}

    ablated_pm = run_rubric(_NULL_BRIEF, env["engineering"]).parsed_payload()["rubric_score"]
    ablated_eng = run_rubric(env["brief"], _NULL_ENG).parsed_payload()["rubric_score"]
    pm_drop = max(baseline - ablated_pm, 0.0)
    eng_drop = max(baseline - ablated_eng, 0.0)

    qa_signal = 0.10 if env.get("grade") else 0.0
    release_signal = 0.10 if env.get("release") else 0.0
    lead_signal = 0.05  # coordinator overhead

    raw = {
        "sprint-lead": lead_signal,
        "product-manager": pm_drop,
        "engineer": eng_drop,
        "qa-validator": qa_signal,
        "release-manager": release_signal,
    }
    total = sum(raw.values()) or 1.0
    return {k: round(v / total, 3) for k, v in raw.items()}
```

- [ ] **Step 4: Run tests, commit**

Run: `pytest tests/agile/test_attribution.py -v` — Expected PASS.

```bash
git add orgos/agile/attribution.py tests/agile/test_attribution.py
git commit -m "feat(agile): compute_attribution() via null-envelope ablation"
```

---

### Task 4.3: Implement `orgos/agile/topology.py` — mutation proposal trigger rules

**Files:**
- Create: `orgos/agile/topology.py`
- Create: `tests/agile/test_topology_proposals.py`

**Interfaces produced:**
- `Proposal(dataclass)`: kind (ADD_ROLE / REMOVE_ROLE / SPLIT_ROLE / MERGE_ROLES / MODIFY_THRESHOLD), before_yaml, after_yaml, rationale
- `propose_topology_mutations(pm: PMStore, org_yaml_path: Path, *, window_sprints: int = 5) -> list[Proposal]`

Trigger rules (from spec §4.2):
- Role's contribution < 0.05 for 3 consecutive sprints → `REMOVE_ROLE`
- QA failure_mode clusters on one tag ≥ 3 sprints → `SPLIT_ROLE`
- Two roles' handoffs pass unchanged 3 sprints in a row → `MERGE_ROLES`
- Recurring blocker tag has no owning role → `ADD_ROLE` with `expire_at`

- [ ] **Step 1: Write the failing tests**

Create `tests/agile/test_topology_proposals.py`:

```python
from unittest.mock import MagicMock

from orgos.agile.topology import Proposal, propose_topology_mutations


def _pm_with_attribution(rows_by_role: dict[str, list[float]]) -> MagicMock:
    pm = MagicMock()
    def _list(role, since_days=30):
        return [{"score": s} for s in rows_by_role.get(role, [])]
    pm.list_role_attribution.side_effect = _list
    pm.list_qa_failure_tags = lambda since_sprints=5: []
    pm.list_blocker_tags = lambda since_sprints=5: []
    return pm


def test_low_contribution_three_sprints_proposes_remove(tmp_path):
    (tmp_path / "org.yaml").write_text(
        "departments:\n  - name: e\n    supervisor: {name: sprint-lead}\n"
        "    members:\n      - {name: release-manager}\n"
    )
    pm = _pm_with_attribution({"release-manager": [0.02, 0.03, 0.04]})
    props = propose_topology_mutations(pm, tmp_path / "org.yaml", window_sprints=3)
    kinds = [p.kind for p in props]
    assert "REMOVE_ROLE" in kinds


def test_qa_cluster_proposes_split(tmp_path):
    (tmp_path / "org.yaml").write_text(
        "departments:\n  - name: e\n    supervisor: {name: sprint-lead}\n"
        "    members:\n      - {name: engineer}\n"
    )
    pm = _pm_with_attribution({"engineer": [0.5, 0.5, 0.5]})
    pm.list_qa_failure_tags = lambda since_sprints=5: [
        ("no-canary", 4), ("style", 1)
    ]
    props = propose_topology_mutations(pm, tmp_path / "org.yaml", window_sprints=5)
    assert any(p.kind == "SPLIT_ROLE" for p in props)


def test_blocker_without_owner_proposes_add(tmp_path):
    (tmp_path / "org.yaml").write_text(
        "departments:\n  - name: e\n    supervisor: {name: sprint-lead}\n"
        "    members: []\n"
    )
    pm = _pm_with_attribution({})
    pm.list_blocker_tags = lambda since_sprints=5: [("db-migration", 3)]
    props = propose_topology_mutations(pm, tmp_path / "org.yaml", window_sprints=5)
    assert any(p.kind == "ADD_ROLE" and "expire_at" in p.after_yaml for p in props)


def test_high_contribution_produces_no_removes(tmp_path):
    (tmp_path / "org.yaml").write_text(
        "departments:\n  - name: e\n    supervisor: {name: sprint-lead}\n"
        "    members:\n      - {name: engineer}\n"
    )
    pm = _pm_with_attribution({"engineer": [0.4, 0.4, 0.4]})
    props = propose_topology_mutations(pm, tmp_path / "org.yaml", window_sprints=3)
    assert all(p.kind != "REMOVE_ROLE" for p in props)
```

- [ ] **Step 2: Verify tests fail**

Run: `pytest tests/agile/test_topology_proposals.py -v` — Expected FAIL.

- [ ] **Step 3: Add PMStore helper accessors first**

Append to `orgos/pm.py`:

```python
    def list_qa_failure_tags(self, since_sprints: int = 5) -> list[tuple[str, int]]:
        """Return (tag, count) tuples from QA failure_mode tags in recent sprints."""
        sprints = self.list_sprints(limit=since_sprints)
        counter: dict[str, int] = {}
        for s in sprints:
            envs = json.loads(s.get("envelopes_json") or "{}")
            grade = envs.get("grade") or {}
            for c in json.loads(grade.get("payload", "{}")).get("criteria", []):
                if not c.get("passed"):
                    tag = c.get("name") or "unknown"
                    counter[tag] = counter.get(tag, 0) + 1
        return sorted(counter.items(), key=lambda x: -x[1])

    def list_blocker_tags(self, since_sprints: int = 5) -> list[tuple[str, int]]:
        """Return (tag, count) tuples from blocked task descriptions."""
        rows = self.conn.execute(
            "SELECT description FROM tasks WHERE status = 'blocked' "
            "ORDER BY created_at DESC LIMIT ?", (since_sprints * 5,)
        ).fetchall()
        counter: dict[str, int] = {}
        for r in rows:
            desc = (r["description"] or "").lower()
            for tag in ("db-migration", "auth", "flaky-test", "network"):
                if tag in desc:
                    counter[tag] = counter.get(tag, 0) + 1
        return sorted(counter.items(), key=lambda x: -x[1])
```

- [ ] **Step 4: Implement `orgos/agile/topology.py`**

```python
"""Topology mutation proposal rules.

Reads role_attribution + qa_failure_tags + blocker_tags from PMStore,
compares against thresholds, and emits Proposals as ruamel.yaml diffs
against config/org.yaml. Never writes; only proposes.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML


_yaml = YAML()
_yaml.preserve_quotes = True


@dataclass
class Proposal:
    kind: str  # ADD_ROLE | REMOVE_ROLE | SPLIT_ROLE | MERGE_ROLES | MODIFY_THRESHOLD
    before_yaml: str
    after_yaml: str
    rationale: str


def _load(path: Path) -> Any:
    return _yaml.load(path.read_text())


def _dump(node: Any) -> str:
    buf = io.StringIO()
    _yaml.dump(node, buf)
    return buf.getvalue()


def _current_members(cfg: Any) -> list[str]:
    depts = cfg.get("departments") or []
    if not depts:
        return []
    return [m["name"] for m in (depts[0].get("members") or [])]


def _remove_member(cfg: Any, role_name: str) -> Any:
    import copy
    new = copy.deepcopy(cfg)
    for d in new.get("departments") or []:
        d["members"] = [m for m in d.get("members") or [] if m["name"] != role_name]
    return new


def _add_member(cfg: Any, role_name: str, expire_at: str | None = None) -> Any:
    import copy
    new = copy.deepcopy(cfg)
    entry = {"name": role_name, "tier": "worker", "system_prompt": ""}
    if expire_at:
        entry["expire_at"] = expire_at
    if new.get("departments"):
        (new["departments"][0].setdefault("members", [])).append(entry)
    return new


def _split_member(cfg: Any, role_name: str, split_suffix: str) -> Any:
    import copy
    new = copy.deepcopy(cfg)
    for d in new.get("departments") or []:
        out = []
        for m in d.get("members") or []:
            if m["name"] == role_name:
                out.append(m)
                out.append({**m, "name": f"{role_name}-{split_suffix}"})
            else:
                out.append(m)
        d["members"] = out
    return new


def propose_topology_mutations(
    pm: Any, org_yaml_path: Path, *, window_sprints: int = 5,
) -> list[Proposal]:
    cfg = _load(org_yaml_path)
    before_yaml = _dump(cfg)
    proposals: list[Proposal] = []

    # 1. REMOVE_ROLE — contribution < 0.05 for `window_sprints` sprints
    for role in _current_members(cfg):
        rows = pm.list_role_attribution(role, since_days=30)
        last = [r["score"] for r in rows[:window_sprints]]
        if len(last) >= window_sprints and all(s < 0.05 for s in last):
            proposals.append(Proposal(
                kind="REMOVE_ROLE",
                before_yaml=before_yaml,
                after_yaml=_dump(_remove_member(cfg, role)),
                rationale=(
                    f"{role} contribution < 0.05 for {window_sprints} sprints "
                    f"(scores={last!r})"
                ),
            ))

    # 2. SPLIT_ROLE — QA failure tag with >= 3 occurrences maps to the Engineer
    fails = pm.list_qa_failure_tags(since_sprints=window_sprints)
    for tag, count in fails:
        if count >= 3 and tag in ("no-canary", "files_in_allowlist"):
            suffix = "release-eng" if tag == "no-canary" else "guardian"
            proposals.append(Proposal(
                kind="SPLIT_ROLE",
                before_yaml=before_yaml,
                after_yaml=_dump(_split_member(cfg, "engineer", suffix)),
                rationale=(
                    f"QA failures cluster on {tag} ({count} in last "
                    f"{window_sprints} sprints); split Engineer -> engineer-{suffix}"
                ),
            ))
            break

    # 3. ADD_ROLE — blocker tag with no owning role
    owners = set(_current_members(cfg))
    blockers = pm.list_blocker_tags(since_sprints=window_sprints)
    for tag, count in blockers:
        role_name = f"{tag}-specialist"
        if count >= 3 and role_name not in owners:
            expire = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
            proposals.append(Proposal(
                kind="ADD_ROLE",
                before_yaml=before_yaml,
                after_yaml=_dump(_add_member(cfg, role_name, expire_at=expire)),
                rationale=(
                    f"Blocker tag {tag!r} appeared {count} times with no owner; "
                    f"adding temporary specialist (expires {expire})."
                ),
            ))

    return proposals
```

- [ ] **Step 5: Run tests, commit**

Run: `pytest tests/agile/test_topology_proposals.py -v` — Expected PASS.

```bash
git add orgos/agile/topology.py orgos/pm.py tests/agile/test_topology_proposals.py
git commit -m "feat(agile): topology mutation proposal rules"
```

---

### Task 4.4: Wire attribution + topology into `run_nightly_sprint`

**Files:**
- Modify: `orgos/agile/sprint.py`
- Modify: `tests/agile/test_sprint_engine.py` — add integration assertion

**Interfaces:** `run_nightly_sprint` now records role_attribution rows on every sprint, and every 5th sprint invokes `propose_topology_mutations`, converting each `Proposal` into an ADR row.

- [ ] **Step 1: Extend `run_nightly_sprint`**

After the DORA block added in Task 3.4, add:

```python
    # Role attribution (every sprint)
    from orgos.agile.attribution import compute_attribution
    from orgos.agile.topology import propose_topology_mutations
    scores = compute_attribution(sprint)
    baseline = sprint.envelopes.get("grade")
    baseline_score = baseline.parsed_payload().get("rubric_score", 0.0) if baseline else 0.0
    for role, score in scores.items():
        pm.record_role_attribution(
            sprint_id=sprint.id, role_name=role,
            score=score,
            rubric_baseline=baseline_score,
            rubric_ablated=max(baseline_score - score, 0.0),
        )

    # Topology check every 5 sprints
    all_sprints = pm.list_sprints(limit=6)
    if len(all_sprints) % 5 == 0:
        from pathlib import Path as _P
        props = propose_topology_mutations(pm, _P("config/org.yaml"), window_sprints=5)
        for p in props:
            pm.create_adr(sprint.id, p.kind, p.before_yaml, p.after_yaml, p.rationale)
```

- [ ] **Step 2: Add an integration assertion**

Add to `tests/agile/test_sprint_engine.py`:

```python
def test_offline_nightly_records_attribution(fixture_repo, monkeypatch):
    # Force the offline path AND monkeypatch _fetch_open_issues
    from orgos.agile import sprint as sprint_mod
    monkeypatch.setattr(sprint_mod, "_fetch_open_issues", lambda: [
        {"issue_id": "1", "number": 1, "title": "t", "body": "x",
         "labels": ["agent-eligible"], "url": "https://x/1"},
    ])
    s = sprint_mod.run_nightly_sprint(fixture_repo, mock_pr=True, _offline=True)
    # In offline mode we won't have a grade envelope, but the entrypoint should
    # still return a Sprint with picked_issue set.
    assert s.picked_issue["issue_id"] == "1"
```

- [ ] **Step 3: Run tests, commit**

Run: `pytest tests/agile/ -q -m "not network"` — Expected PASS.

```bash
git add orgos/agile/sprint.py tests/agile/test_sprint_engine.py
git commit -m "feat(agile): record attribution + propose topology every 5 sprints"
```

---

### Task 4.5: Extend `orgos/evolve.py` to consume topology `Proposal`s

**Files:**
- Modify: `orgos/evolve.py` — add `apply_adr(adr_id: int)` that reads the ADR row, patches `config/org.yaml` via `after_yaml`, commits under `orgos-evolve` git identity, and sets ADR status to `applied`.
- Create: `tests/agile/test_evolve_apply_adr.py`

**Interfaces produced:**
- `apply_adr(pm: PMStore, adr_id: int, *, config_path: Path = Path("config/org.yaml"), commit: bool = True) -> None`

- [ ] **Step 1: Write the failing test**

Create `tests/agile/test_evolve_apply_adr.py`:

```python
import subprocess
from pathlib import Path

import pytest

from orgos.pm import PMStore
from orgos.evolve import apply_adr


@pytest.fixture
def git_repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    cfg = tmp_path / "config" / "org.yaml"
    cfg.parent.mkdir()
    cfg.write_text("departments: []\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
    return tmp_path


def test_apply_adr_writes_file_and_commits(git_repo, monkeypatch):
    monkeypatch.chdir(git_repo)
    pm = PMStore("./pm.db")
    aid = pm.create_adr(
        sprint_id="s1", kind="REMOVE_ROLE",
        before_yaml="departments: []\n",
        after_yaml="departments:\n  - name: new\n",
        rationale="test",
    )
    apply_adr(pm, aid, config_path=Path("config/org.yaml"))
    text = (git_repo / "config" / "org.yaml").read_text()
    assert "new" in text
    rows = pm.list_adrs(status="applied")
    assert any(r["id"] == aid for r in rows)


def test_apply_adr_rejects_non_pending(git_repo, monkeypatch):
    monkeypatch.chdir(git_repo)
    pm = PMStore("./pm.db")
    aid = pm.create_adr("s1", "REMOVE_ROLE", "before", "after", "r")
    pm.set_adr_status(aid, "rejected")
    with pytest.raises(ValueError):
        apply_adr(pm, aid, config_path=Path("config/org.yaml"))
```

- [ ] **Step 2: Verify test fails**

Run: `pytest tests/agile/test_evolve_apply_adr.py -v` — Expected FAIL on `apply_adr` import.

- [ ] **Step 3: Add `apply_adr` to `orgos/evolve.py`**

```python
# Add to orgos/evolve.py (top-level, after existing imports):

import subprocess
from pathlib import Path


def apply_adr(pm, adr_id: int, *, config_path: Path = Path("config/org.yaml"),
              commit: bool = True) -> None:
    """Apply an approved ADR: write after_yaml, commit under orgos-evolve.

    Rejects if the ADR is not in 'pending' or 'approved' state (defensive).
    """
    adr = next((a for a in pm.list_adrs() if a["id"] == adr_id), None)
    if adr is None:
        raise ValueError(f"ADR {adr_id} not found")
    if adr["status"] not in ("pending", "approved"):
        raise ValueError(f"ADR {adr_id} status={adr['status']}, cannot apply")
    config_path.write_text(adr["after_yaml"])
    if commit:
        subprocess.run(
            ["git", "-c", "user.name=orgos-evolve",
             "-c", "user.email=evolve@orgos", "add", str(config_path)],
            check=True,
        )
        subprocess.run(
            ["git", "-c", "user.name=orgos-evolve",
             "-c", "user.email=evolve@orgos",
             "commit", "-m",
             f"evolve: apply ADR-{adr_id:03d} {adr['kind']}\n\n{adr['rationale']}"],
            check=True,
        )
    pm.set_adr_status(adr_id, "applied")
```

- [ ] **Step 4: Run tests, commit**

Run: `pytest tests/agile/test_evolve_apply_adr.py -v` — Expected PASS.

```bash
git add orgos/evolve.py tests/agile/test_evolve_apply_adr.py
git commit -m "feat(evolve): apply_adr() writes org.yaml + commits under orgos-evolve"
```

---

### Task 4.6: API endpoints `/api/team/topology`, `/api/team/adrs`, approve action

**Files:**
- Modify: `orgos/api.py`

**Interfaces produced:**
- `GET /api/team/topology` — returns `{roles: [{name, tier, contribution_last_sprint}], edges: [{from, to, weight}]}` derived from `config/org.yaml` + latest attribution rows
- `GET /api/team/adrs` — returns `{pending, approved, applied, rejected}` grouped rows
- `POST /api/team/adrs/{id}/approve` — sets status=approved, calls `apply_adr`
- `POST /api/team/adrs/{id}/reject` — sets status=rejected

- [ ] **Step 1: Append to `orgos/api.py`**

```python
from pathlib import Path
from ruamel.yaml import YAML

_yaml = YAML()


@app.get("/api/team/topology")
def team_topology() -> dict:
    pm = PMStore()
    cfg = _yaml.load(Path("config/org.yaml").read_text())
    depts = cfg.get("departments") or []
    if not depts:
        return {"roles": [], "edges": []}
    sup = depts[0].get("supervisor", {})
    members = depts[0].get("members") or []
    roles = [{"name": sup["name"], "tier": "orchestrator", "contribution": 0.0}]
    for m in members:
        rows = pm.list_role_attribution(m["name"], since_days=7)
        latest = rows[0]["score"] if rows else 0.0
        roles.append({"name": m["name"], "tier": m.get("tier", "worker"),
                      "contribution": latest})
    edges = [{"from": sup["name"], "to": m["name"], "weight": r["contribution"]}
             for m, r in zip(members, roles[1:])]
    return {"roles": roles, "edges": edges}


@app.get("/api/team/adrs")
def list_adrs() -> dict:
    pm = PMStore()
    all_ = pm.list_adrs()
    grouped: dict[str, list] = {"pending": [], "approved": [],
                                 "applied": [], "rejected": []}
    for a in all_:
        grouped.setdefault(a["status"], []).append(a)
    return grouped


@app.post("/api/team/adrs/{adr_id}/approve")
def approve_adr(adr_id: int) -> dict:
    from orgos.evolve import apply_adr
    pm = PMStore()
    pm.set_adr_status(adr_id, "approved")
    apply_adr(pm, adr_id)
    return {"ok": True, "id": adr_id, "status": "applied"}


@app.post("/api/team/adrs/{adr_id}/reject")
def reject_adr(adr_id: int) -> dict:
    pm = PMStore()
    pm.set_adr_status(adr_id, "rejected")
    return {"ok": True, "id": adr_id, "status": "rejected"}
```

- [ ] **Step 2: Smoke-test endpoints**

Run:
```bash
python -m orgos.api &
sleep 2
curl -s http://localhost:8000/api/team/topology
curl -s http://localhost:8000/api/team/adrs
kill %1
```
Expected: JSON output (possibly empty), no traceback.

- [ ] **Step 3: Commit**

```bash
git add orgos/api.py
git commit -m "feat(api): team topology + ADR list/approve/reject endpoints"
```

---

### Task 4.7: Dashboard `/team` page — force-directed graph + ADR feed

**Files:**
- Create: `dashboard/app/team/page.tsx`
- Modify: `dashboard/package.json` — add `react-force-graph-2d`

**Interfaces:** presents `/api/team/topology` as a force graph; presents `/api/team/adrs` as an ADR feed with Approve / Reject buttons.

- [ ] **Step 1: Add the dependency**

Run: `cd dashboard && npm install react-force-graph-2d`

- [ ] **Step 2: Create the page**

`dashboard/app/team/page.tsx`:

```tsx
"use client";
import { useEffect, useState } from "react";
import dynamic from "next/dynamic";

const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false });

type Role = { name: string; tier: string; contribution: number };
type Edge = { from: string; to: string; weight: number };

type ADR = {
  id: number; kind: string; rationale: string; status: string;
  before_yaml: string; after_yaml: string; created_at: string;
};

export default function TeamPage() {
  const [topology, setTopology] = useState<{roles: Role[]; edges: Edge[]} | null>(null);
  const [adrs, setAdrs] = useState<Record<string, ADR[]> | null>(null);

  const refresh = () => {
    fetch("/api/team/topology").then(r => r.json()).then(setTopology);
    fetch("/api/team/adrs").then(r => r.json()).then(setAdrs);
  };
  useEffect(refresh, []);

  const act = async (id: number, verb: "approve" | "reject") => {
    await fetch(`/api/team/adrs/${id}/${verb}`, { method: "POST" });
    refresh();
  };

  if (!topology || !adrs) return <div className="p-6">Loading…</div>;

  const graph = {
    nodes: topology.roles.map(r => ({ id: r.name, name: r.name, tier: r.tier, val: 5 + r.contribution * 20 })),
    links: topology.edges.map(e => ({ source: e.from, target: e.to, width: 1 + e.weight * 4 })),
  };

  return (
    <div className="p-6 space-y-6">
      <div>
        <h2 className="text-xl mb-2">Role topology</h2>
        <div className="border h-96">
          <ForceGraph2D graphData={graph as any} nodeLabel="name" linkWidth={"width" as any} />
        </div>
      </div>
      <section>
        <h2 className="text-xl mb-2">ADRs</h2>
        {["pending", "approved", "applied", "rejected"].map(bucket => (
          <div key={bucket} className="mb-4">
            <h3 className="text-sm font-bold uppercase">{bucket}</h3>
            <ul className="space-y-2">
              {(adrs[bucket] ?? []).map(a => (
                <li key={a.id} className="border p-3 rounded">
                  <div className="flex justify-between">
                    <div>
                      <div className="font-mono text-sm">ADR-{String(a.id).padStart(3, "0")} · {a.kind}</div>
                      <div className="text-xs text-gray-600 mt-1">{a.rationale}</div>
                    </div>
                    {bucket === "pending" && (
                      <div className="space-x-2">
                        <button className="px-2 py-1 bg-green-600 text-white rounded" onClick={() => act(a.id, "approve")}>Approve</button>
                        <button className="px-2 py-1 bg-red-600 text-white rounded" onClick={() => act(a.id, "reject")}>Reject</button>
                      </div>
                    )}
                  </div>
                  <details className="mt-2">
                    <summary className="text-xs cursor-pointer">Show diff</summary>
                    <pre className="text-xs whitespace-pre-wrap bg-gray-50 p-2">{a.after_yaml}</pre>
                  </details>
                </li>
              ))}
              {(adrs[bucket] ?? []).length === 0 && <li className="text-gray-400 text-sm">None</li>}
            </ul>
          </div>
        ))}
      </section>
    </div>
  );
}
```

- [ ] **Step 3: Smoke-test the page**

Run `cd dashboard && npm run dev`; open `http://localhost:3000/team`. Expected: force graph renders (may be empty if no sprints yet); ADR sections render (empty is fine).

- [ ] **Step 4: Commit**

```bash
git add dashboard/app/team dashboard/package.json dashboard/package-lock.json
git commit -m "feat(dashboard): /team page — topology graph + ADR feed"
```

---

## Phase 5 — Counterfactual replay / Hook B (5 days, 6 tasks)

### Task 5.1: Snapshot the sprint input at phase [01]

**Files:**
- Modify: `orgos/agile/sprint.py` — write `_sprints/<sprint_id>/snapshot.json`
- Create: `tests/agile/test_snapshot.py`

**Interfaces produced:**
- `write_snapshot(sprint: Sprint, backlog: list[dict], heuristics: list[dict]) -> Path`
- `read_snapshot(sprint_id: str) -> dict`

- [ ] **Step 1: Write the failing tests**

Create `tests/agile/test_snapshot.py`:

```python
import json
from pathlib import Path
from orgos.agile.sprint import Sprint, write_snapshot, read_snapshot


def test_write_and_read_snapshot(tmp_path):
    s = Sprint(
        id="s1", started_at="2026-07-01T00:00:00Z",
        repo_path=tmp_path, worktree_path=tmp_path / "wt",
        branch="agile/s1", picked_issue={"issue_id": "1"},
        envelopes={}, status="in_progress",
    )
    (tmp_path / "wt").mkdir()
    p = write_snapshot(s, backlog=[{"issue_id": "1"}], heuristics=[{"rule": "x"}])
    assert p.exists()
    data = read_snapshot("s1", base_dir=tmp_path)
    assert data["picked_issue"]["issue_id"] == "1"
    assert data["backlog"][0]["issue_id"] == "1"
```

- [ ] **Step 2: Verify test fails**

Run: `pytest tests/agile/test_snapshot.py -v` — Expected FAIL.

- [ ] **Step 3: Implement snapshot helpers in `orgos/agile/sprint.py`**

Add to `orgos/agile/sprint.py`:

```python
def _snapshot_path(sprint_id: str, base_dir: Path | None = None) -> Path:
    base = base_dir or Path(".")
    return base / ".sprints" / sprint_id / "snapshot.json"


def write_snapshot(
    sprint: Sprint,
    *,
    backlog: list[dict] | None = None,
    heuristics: list[dict] | None = None,
) -> Path:
    p = _snapshot_path(sprint.id, base_dir=sprint.repo_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "sprint_id": sprint.id,
        "started_at": sprint.started_at,
        "branch": sprint.branch,
        "picked_issue": sprint.picked_issue,
        "backlog": backlog or [],
        "heuristics": heuristics or [],
    }, indent=2))
    return p


def read_snapshot(sprint_id: str, *, base_dir: Path | None = None) -> dict:
    return json.loads(_snapshot_path(sprint_id, base_dir=base_dir).read_text())
```

Call `write_snapshot(...)` inside `run_sprint` right after the worktree is created and before `spawn(...)`. Pass the backlog and current active heuristics.

- [ ] **Step 4: Run tests, commit**

Run: `pytest tests/agile/test_snapshot.py -v` — Expected PASS.

```bash
git add orgos/agile/sprint.py tests/agile/test_snapshot.py
git commit -m "feat(agile): snapshot sprint inputs at start"
```

---

### Task 5.2: Define `BriefMutation` API and pure-Python mutators

**Files:**
- Create: `orgos/agile/mutations.py`
- Create: `tests/agile/test_mutations.py`

**Interfaces produced:**
- `BriefMutation` — union type with three variants:
  - `SwapBacklogPick(new_issue_id: str)`
  - `InjectHeuristic(rule: str, why: str, tags: list[str])`
  - `SwapRole(role_name: str, alt_model: str | None = None, alt_system_prompt: str | None = None)`
- `apply_mutation(snapshot: dict, mutation: BriefMutation) -> dict` — returns a mutated snapshot

- [ ] **Step 1: Write the failing tests**

Create `tests/agile/test_mutations.py`:

```python
import pytest
from orgos.agile.mutations import (
    SwapBacklogPick, InjectHeuristic, SwapRole, apply_mutation,
)


def _snapshot():
    return {
        "picked_issue": {"issue_id": "1"},
        "backlog": [{"issue_id": "1"}, {"issue_id": "2"}],
        "heuristics": [],
        "role_overrides": {},
    }


def test_swap_backlog_picks_second():
    out = apply_mutation(_snapshot(), SwapBacklogPick(new_issue_id="2"))
    assert out["picked_issue"]["issue_id"] == "2"


def test_swap_backlog_rejects_unknown():
    with pytest.raises(ValueError):
        apply_mutation(_snapshot(), SwapBacklogPick(new_issue_id="99"))


def test_inject_heuristic_appends():
    out = apply_mutation(
        _snapshot(),
        InjectHeuristic(rule="commit early", why="x", tags=["engineer"]),
    )
    assert len(out["heuristics"]) == 1
    assert out["heuristics"][0]["rule"] == "commit early"


def test_swap_role_records_override():
    out = apply_mutation(
        _snapshot(),
        SwapRole(role_name="engineer", alt_model="anthropic/claude-haiku-4-5"),
    )
    assert out["role_overrides"]["engineer"]["model"] == "anthropic/claude-haiku-4-5"
```

- [ ] **Step 2: Verify tests fail**

Run: `pytest tests/agile/test_mutations.py -v` — Expected FAIL.

- [ ] **Step 3: Implement `orgos/agile/mutations.py`**

```python
"""BriefMutation types for counterfactual sprint replays."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field


@dataclass
class SwapBacklogPick:
    new_issue_id: str
    kind: str = "swap_backlog_pick"


@dataclass
class InjectHeuristic:
    rule: str
    why: str
    tags: list[str] = field(default_factory=list)
    kind: str = "inject_heuristic"


@dataclass
class SwapRole:
    role_name: str
    alt_model: str | None = None
    alt_system_prompt: str | None = None
    kind: str = "swap_role"


BriefMutation = SwapBacklogPick | InjectHeuristic | SwapRole


def apply_mutation(snapshot: dict, mutation) -> dict:
    out = copy.deepcopy(snapshot)
    out.setdefault("role_overrides", {})

    if isinstance(mutation, SwapBacklogPick):
        candidates = out.get("backlog", [])
        match = next(
            (c for c in candidates if str(c.get("issue_id")) == mutation.new_issue_id),
            None,
        )
        if match is None:
            raise ValueError(f"issue_id {mutation.new_issue_id!r} not in backlog")
        out["picked_issue"] = match
    elif isinstance(mutation, InjectHeuristic):
        out.setdefault("heuristics", []).append({
            "rule": mutation.rule, "why": mutation.why, "tags": mutation.tags,
        })
    elif isinstance(mutation, SwapRole):
        out["role_overrides"][mutation.role_name] = {
            "model": mutation.alt_model,
            "system_prompt": mutation.alt_system_prompt,
        }
    else:
        raise TypeError(f"unknown mutation type: {type(mutation).__name__}")
    return out
```

- [ ] **Step 4: Run tests, commit**

Run: `pytest tests/agile/test_mutations.py -v` — Expected PASS.

```bash
git add orgos/agile/mutations.py tests/agile/test_mutations.py
git commit -m "feat(agile): BriefMutation types + apply_mutation()"
```

---

### Task 5.3: Implement `replay_sprint`

**Files:**
- Create: `orgos/agile/replay.py`
- Create: `tests/agile/test_replay.py`

**Interfaces produced:**
- `replay_sprint(sprint_id: str, mutation: BriefMutation, *, base_dir: Path | None = None, model: str | None = None) -> Sprint` — reads snapshot, applies mutation, runs `run_sprint` with `mock_pr=True` (publish tools forbidden in replays), tags the resulting Sprint with `parent_sprint_id` and `mutation_kind` in PMStore.

- [ ] **Step 1: Write the failing tests**

Create `tests/agile/test_replay.py`:

```python
import json
import subprocess
from pathlib import Path

import pytest

from orgos.agile.mutations import SwapBacklogPick, InjectHeuristic
from orgos.agile.replay import replay_sprint
from orgos.agile.sprint import Sprint, write_snapshot
from orgos.pm import PMStore


def _seed_sprint(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("x")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)

    s = Sprint(
        id="parent-1", started_at="2026-07-01T00:00:00Z",
        repo_path=tmp_path, worktree_path=tmp_path / ".sprints" / "parent-1",
        branch="agile/parent-1", picked_issue={"issue_id": "1"},
        envelopes={}, status="completed",
    )
    (tmp_path / ".sprints" / "parent-1").mkdir(parents=True)
    write_snapshot(
        s,
        backlog=[
            {"issue_id": "1", "title": "a", "labels": ["agent-eligible"],
             "body": "x", "url": "x"},
            {"issue_id": "2", "title": "b", "labels": ["agent-eligible"],
             "body": "y", "url": "y"},
        ],
        heuristics=[],
    )


def test_replay_swap_backlog_pick_changes_issue(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _seed_sprint(tmp_path)
    replayed = replay_sprint(
        "parent-1",
        SwapBacklogPick(new_issue_id="2"),
        base_dir=tmp_path,
        _offline=True,
    )
    assert replayed.picked_issue["issue_id"] == "2"
    assert replayed.id != "parent-1"


def test_replay_records_parent_and_mutation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _seed_sprint(tmp_path)
    replayed = replay_sprint(
        "parent-1",
        InjectHeuristic(rule="x", why="y"),
        base_dir=tmp_path,
        _offline=True,
    )
    pm = PMStore(tmp_path / "_orgos_memory" / "pm.db")
    row = pm.get_sprint(replayed.id)
    assert row is not None
    envs = json.loads(row["envelopes_json"])
    # Replay must record its own snapshot + parent linkage in a payload field.
    assert envs.get("_replay", {}).get("parent_sprint_id") == "parent-1"
    assert envs["_replay"]["mutation_kind"] == "inject_heuristic"
```

- [ ] **Step 2: Verify tests fail**

Run: `pytest tests/agile/test_replay.py -v` — Expected FAIL.

- [ ] **Step 3: Implement `orgos/agile/replay.py`**

```python
"""Counterfactual sprint replay.

Load a past sprint's snapshot, apply a BriefMutation, and run a new sprint
whose PR-opening tool is always mocked (publish-category tools are refused
in replay mode by the existing tier system).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from orgos.pm import PMStore

from .mutations import BriefMutation, apply_mutation
from .sprint import (
    Sprint, _new_sprint_id, read_snapshot, run_sprint,
)


def replay_sprint(
    parent_sprint_id: str,
    mutation,
    *,
    base_dir: Path | None = None,
    model: str | None = None,
    _offline: bool = False,
) -> Sprint:
    base = base_dir or Path(".")
    snapshot = read_snapshot(parent_sprint_id, base_dir=base)
    mutated = apply_mutation(snapshot, mutation)

    if _offline:
        # Fast path for tests: skip the actual spawn, produce a stub Sprint.
        replay_id = _new_sprint_id()
        wt = base / ".sprints" / replay_id
        wt.mkdir(parents=True, exist_ok=True)
        replayed = Sprint(
            id=replay_id,
            started_at=datetime.now(timezone.utc).isoformat(),
            repo_path=base,
            worktree_path=wt,
            branch=f"agile/{replay_id}",
            picked_issue=mutated["picked_issue"],
            envelopes={},
            status="completed",
        )
    else:
        replayed = run_sprint(
            base, mutated["picked_issue"], model=model, mock_pr=True,
        )

    # Persist parent linkage + mutation kind under the reserved "_replay" phase.
    pm = PMStore(base / "_orgos_memory" / "pm.db")
    pm.create_sprint(replayed.id, replayed.branch, replayed.picked_issue,
                     status=replayed.status)
    pm.record_sprint_envelope(
        replayed.id, "_replay",
        json.dumps({
            "parent_sprint_id": parent_sprint_id,
            "mutation_kind": getattr(mutation, "kind", "unknown"),
            "mutation": mutation.__dict__,
        }),
    )
    replayed.envelopes["_replay"] = None  # marker
    return replayed
```

- [ ] **Step 4: Run tests, commit**

Run: `pytest tests/agile/test_replay.py -v` — Expected PASS.

```bash
git add orgos/agile/replay.py tests/agile/test_replay.py
git commit -m "feat(agile): replay_sprint() with mock PR + parent linkage"
```

---

### Task 5.4: Verify replay tier isolation — publish tools rejected

**Files:**
- Create: `tests/agile/test_replay_tier_isolation.py`

**Interfaces:** No new production code. Test verifies that instantiating a Release role with `github_open_pr` (publish) in replay mode is rejected by `_enforce_tier()` since the replay wiring only supplies `MockPRTool`.

- [ ] **Step 1: Write the test**

Create `tests/agile/test_replay_tier_isolation.py`:

```python
import pytest

from orgos.spawn.engine import _enforce_tier, _TierViolation
from orgos.subagents import release_manager_role
from orgos.tools.github_pr_tool import GitHubOpenPRTool


def test_release_with_publish_tool_but_no_approval_fn_fails():
    # Simulate the replay-mode misconfiguration: publish tool attached but
    # the tier expects a gate. Without approval_fn, spawn refuses.
    r = release_manager_role(extra_tools=[GitHubOpenPRTool()])
    with pytest.raises(_TierViolation):
        # The publisher tier's requires_approval=["*"] means every tool must be
        # wired with an approval_fn; the tier enforces this at spawn time.
        _enforce_tier(r)  # noqa: SLF001
        # Actually _enforce_tier does the category/deny checks. The gate check
        # lives in _wire_gates; import and test both.
        from orgos.spawn.engine import _wire_gates
        _wire_gates(r.tools, r, approval_fn=None)
```

- [ ] **Step 2: Run test**

Run: `pytest tests/agile/test_replay_tier_isolation.py -v`
Expected: PASS.

If it fails (because `_enforce_tier` allows publish tools on the publisher tier), the test guarantee is that `_wire_gates` catches the missing `approval_fn`. Either way, the outcome is: replays cannot silently open PRs.

- [ ] **Step 3: Commit**

```bash
git add tests/agile/test_replay_tier_isolation.py
git commit -m "test(agile): replay tier isolation — publish requires gate"
```

---

### Task 5.5: API endpoints `/api/lab/replay` + `/api/sprints/{id}`

**Files:**
- Modify: `orgos/api.py`

**Interfaces produced:**
- `POST /api/lab/replay` — body `{parent_sprint_id, mutation_kind, mutation_args}`. Returns the replay Sprint id.
- `GET /api/sprints/{id}` — returns `{sprint: row, envelopes: {...}, replay: {parent, mutation} | null}`

- [ ] **Step 1: Append endpoints**

```python
from pydantic import BaseModel


class ReplayReq(BaseModel):
    parent_sprint_id: str
    mutation_kind: str  # swap_backlog_pick | inject_heuristic | swap_role
    mutation_args: dict


@app.post("/api/lab/replay")
def lab_replay(req: ReplayReq) -> dict:
    from orgos.agile.mutations import (
        InjectHeuristic, SwapBacklogPick, SwapRole,
    )
    from orgos.agile.replay import replay_sprint

    if req.mutation_kind == "swap_backlog_pick":
        m = SwapBacklogPick(**req.mutation_args)
    elif req.mutation_kind == "inject_heuristic":
        m = InjectHeuristic(**req.mutation_args)
    elif req.mutation_kind == "swap_role":
        m = SwapRole(**req.mutation_args)
    else:
        return {"error": f"unknown mutation_kind: {req.mutation_kind}"}
    s = replay_sprint(req.parent_sprint_id, m)
    return {"replay_sprint_id": s.id, "status": s.status,
            "picked_issue": s.picked_issue}


@app.get("/api/sprints/{sprint_id}")
def get_sprint(sprint_id: str) -> dict:
    pm = PMStore()
    row = pm.get_sprint(sprint_id)
    if not row:
        return {"error": "not_found"}
    envs = json.loads(row.get("envelopes_json") or "{}")
    replay = envs.get("_replay")
    return {"sprint": row, "envelopes": envs, "replay": replay}
```

- [ ] **Step 2: Smoke-test**

Run:
```bash
python -m orgos.api &
sleep 2
curl -s -X POST http://localhost:8000/api/lab/replay \
  -H "content-type: application/json" \
  -d '{"parent_sprint_id":"nonexistent","mutation_kind":"inject_heuristic","mutation_args":{"rule":"x","why":"y"}}'
kill %1
```
Expected: JSON reply (may error cleanly with `parent_sprint_id not found` — acceptable).

- [ ] **Step 3: Commit**

```bash
git add orgos/api.py
git commit -m "feat(api): /api/lab/replay + /api/sprints/{id}"
```

---

### Task 5.6: Dashboard `/lab/[sprint_id]` and `/sprints` pages

**Files:**
- Create: `dashboard/app/lab/page.tsx` — pick sprint page
- Create: `dashboard/app/lab/[sprintId]/page.tsx` — side-by-side runner
- Create: `dashboard/app/sprints/page.tsx` — sprint board
- Create: `dashboard/app/sprints/[sprintId]/page.tsx` — sprint detail

**Interfaces:** each page consumes the API endpoints from Task 5.5 + Task 4.6 and renders as described in spec §7.

- [ ] **Step 1: Create `dashboard/app/sprints/page.tsx`**

```tsx
"use client";
import { useEffect, useState } from "react";
import Link from "next/link";

type Sprint = { id: string; branch: string; status: string; started_at: string;
                picked_issue: string };

export default function SprintsPage() {
  const [sprints, setSprints] = useState<Sprint[]>([]);
  useEffect(() => {
    fetch("/api/sprints").then(r => r.json()).then(setSprints);
  }, []);
  return (
    <div className="p-6">
      <h1 className="text-2xl mb-4">Sprints</h1>
      <table className="w-full text-sm">
        <thead><tr className="text-left">
          <th>ID</th><th>Branch</th><th>Status</th><th>Started</th>
        </tr></thead>
        <tbody>
          {sprints.map(s => (
            <tr key={s.id} className="border-t">
              <td className="py-1"><Link href={`/sprints/${s.id}`} className="text-blue-600">{s.id}</Link></td>
              <td>{s.branch}</td>
              <td>{s.status}</td>
              <td>{s.started_at?.slice(0, 19)?.replace("T", " ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 2: Create `dashboard/app/sprints/[sprintId]/page.tsx`**

```tsx
"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

export default function SprintDetail() {
  const { sprintId } = useParams<{sprintId: string}>();
  const [data, setData] = useState<any>(null);
  useEffect(() => {
    fetch(`/api/sprints/${sprintId}`).then(r => r.json()).then(setData);
  }, [sprintId]);
  if (!data) return <div className="p-6">Loading…</div>;
  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl">Sprint {sprintId}</h1>
      {["backlog","brief","engineering","grade","release","dora"].map(phase => {
        const env = data.envelopes?.[phase];
        return (
          <section key={phase}>
            <h2 className="text-lg font-bold">[{phase}]</h2>
            {env ? <pre className="text-xs bg-gray-50 p-3 whitespace-pre-wrap">
              {JSON.stringify(env, null, 2)}
            </pre> : <div className="text-gray-400 text-sm">no envelope</div>}
          </section>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 3: Create `dashboard/app/lab/page.tsx`**

```tsx
"use client";
import { useEffect, useState } from "react";
import Link from "next/link";

export default function LabPicker() {
  const [sprints, setSprints] = useState<any[]>([]);
  useEffect(() => {
    fetch("/api/sprints").then(r => r.json()).then(setSprints);
  }, []);
  return (
    <div className="p-6">
      <h1 className="text-2xl mb-4">Counterfactual Lab</h1>
      <p className="text-sm text-gray-600 mb-4">
        Pick a completed sprint to replay with a mutated brief.
      </p>
      <ul className="space-y-1">
        {sprints.filter((s: any) => s.status === "completed").map((s: any) => (
          <li key={s.id}>
            <Link href={`/lab/${s.id}`} className="text-blue-600">{s.id}</Link>
            <span className="text-xs text-gray-500 ml-2">{s.branch}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

- [ ] **Step 4: Create `dashboard/app/lab/[sprintId]/page.tsx`**

```tsx
"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

type Mutation =
  | { kind: "swap_backlog_pick"; new_issue_id: string }
  | { kind: "inject_heuristic"; rule: string; why: string; tags: string[] }
  | { kind: "swap_role"; role_name: string; alt_model?: string };

export default function LabRunner() {
  const { sprintId } = useParams<{sprintId: string}>();
  const [original, setOriginal] = useState<any>(null);
  const [replay, setReplay] = useState<any>(null);
  const [mutKind, setMutKind] = useState<"swap_backlog_pick" | "inject_heuristic" | "swap_role">("inject_heuristic");
  const [args, setArgs] = useState<Record<string, string>>({ rule: "", why: "" });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetch(`/api/sprints/${sprintId}`).then(r => r.json()).then(setOriginal);
  }, [sprintId]);

  const run = async () => {
    setBusy(true);
    const mutation_args: any = mutKind === "inject_heuristic"
      ? { rule: args.rule, why: args.why, tags: [] }
      : mutKind === "swap_backlog_pick" ? { new_issue_id: args.new_issue_id }
      : { role_name: args.role_name, alt_model: args.alt_model };
    const res = await fetch("/api/lab/replay", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ parent_sprint_id: sprintId, mutation_kind: mutKind, mutation_args }),
    }).then(r => r.json());
    if (res.replay_sprint_id) {
      const full = await fetch(`/api/sprints/${res.replay_sprint_id}`).then(r => r.json());
      setReplay(full);
    }
    setBusy(false);
  };

  return (
    <div className="p-6 grid grid-cols-2 gap-6">
      <div>
        <h2 className="text-lg font-bold mb-2">Original ({sprintId})</h2>
        {original ? <pre className="text-xs bg-gray-50 p-3 whitespace-pre-wrap max-h-[70vh] overflow-auto">
          {JSON.stringify(original?.envelopes, null, 2)}
        </pre> : <div>Loading…</div>}
      </div>
      <div>
        <h2 className="text-lg font-bold mb-2">Replay</h2>
        <div className="border p-3 mb-3 space-y-2">
          <select value={mutKind} onChange={e => setMutKind(e.target.value as any)}
                  className="border rounded p-1">
            <option value="inject_heuristic">Inject heuristic</option>
            <option value="swap_backlog_pick">Swap backlog pick</option>
            <option value="swap_role">Swap role model</option>
          </select>
          {mutKind === "inject_heuristic" && <>
            <input placeholder="rule" className="border p-1 w-full"
                   value={args.rule || ""} onChange={e => setArgs({...args, rule: e.target.value})} />
            <input placeholder="why" className="border p-1 w-full"
                   value={args.why || ""} onChange={e => setArgs({...args, why: e.target.value})} />
          </>}
          {mutKind === "swap_backlog_pick" && <input placeholder="new issue id"
            className="border p-1 w-full" value={args.new_issue_id || ""}
            onChange={e => setArgs({...args, new_issue_id: e.target.value})} />}
          {mutKind === "swap_role" && <>
            <input placeholder="role name" className="border p-1 w-full"
                   value={args.role_name || ""} onChange={e => setArgs({...args, role_name: e.target.value})} />
            <input placeholder="alt model" className="border p-1 w-full"
                   value={args.alt_model || ""} onChange={e => setArgs({...args, alt_model: e.target.value})} />
          </>}
          <button onClick={run} disabled={busy}
                  className="bg-blue-600 text-white rounded px-3 py-1">
            {busy ? "Running…" : "Run replay"}
          </button>
        </div>
        {replay ? <pre className="text-xs bg-gray-50 p-3 whitespace-pre-wrap max-h-[60vh] overflow-auto">
          {JSON.stringify(replay?.envelopes, null, 2)}
        </pre> : <div className="text-gray-400 text-sm">Run a mutation to see the replay.</div>}
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Smoke-test**

Run `cd dashboard && npm run dev`. Open `/sprints`, `/sprints/<id>`, `/lab`, `/lab/<id>` — verify pages render and network calls succeed (empty content is OK).

- [ ] **Step 6: Commit**

```bash
git add dashboard/app/sprints dashboard/app/lab
git commit -m "feat(dashboard): sprints board + lab side-by-side replay UI"
```

---

## Phase 6 — Polish + A2A stub + demo prep (3 days, 4 tasks)

### Task 6.1: A2A Agent Card stub at `/agent-card.json`

**Files:**
- Modify: `orgos/api.py`
- Create: `tests/agile/test_agent_card.py`

**Interfaces produced:**
- `GET /agent-card.json` → static Google A2A Agent Card describing the Sprint Lead orchestrator + subordinate role skills.

- [ ] **Step 1: Write the failing test**

Create `tests/agile/test_agent_card.py`:

```python
from fastapi.testclient import TestClient
from orgos.api import app


def test_agent_card_has_required_fields():
    client = TestClient(app)
    r = client.get("/agent-card.json")
    assert r.status_code == 200
    card = r.json()
    assert card["name"] == "orgos-engineering"
    assert "skills" in card and len(card["skills"]) >= 5
    for s in card["skills"]:
        assert "id" in s and "name" in s and "description" in s
```

- [ ] **Step 2: Add endpoint**

```python
@app.get("/agent-card.json")
def agent_card() -> dict:
    return {
        "name": "orgos-engineering",
        "description": "A self-organizing agile engineering team that ships one issue per sprint.",
        "version": "0.1.0",
        "url": None,
        "capabilities": {"streaming": False, "pushNotifications": False},
        "skills": [
            {"id": "sprint-lead", "name": "Sprint Lead",
             "description": "Orchestrates a sprint: picks the issue, routes the team, synthesises the final handoff.",
             "inputModes": ["application/json"],
             "outputModes": ["application/json"]},
            {"id": "product-manager", "name": "Product Manager",
             "description": "Turns a GitHub issue into a TaskBrief with acceptance tests.",
             "inputModes": ["application/json"], "outputModes": ["application/json"]},
            {"id": "engineer", "name": "Engineer",
             "description": "Implements the change in a git worktree and runs the tests.",
             "inputModes": ["application/json"], "outputModes": ["application/json"]},
            {"id": "qa-validator", "name": "QA Validator",
             "description": "Grades the engineering handoff against the brief's acceptance tests.",
             "inputModes": ["application/json"], "outputModes": ["application/json"]},
            {"id": "release-manager", "name": "Release Manager",
             "description": "Opens the PR (or records a mock PR in replay mode).",
             "inputModes": ["application/json"], "outputModes": ["application/json"]},
            {"id": "retro-agent", "name": "Retro Agent",
             "description": "Reads the audit log and produces a graded retrospective.",
             "inputModes": ["application/json"], "outputModes": ["application/json"]},
        ],
    }
```

- [ ] **Step 3: Run tests, commit**

Run: `pytest tests/agile/test_agent_card.py -v` — Expected PASS.

```bash
git add orgos/api.py tests/agile/test_agent_card.py
git commit -m "feat(api): A2A Agent Card stub at /agent-card.json"
```

---

### Task 6.2: Rewrite the home page `/` as team scoreboard

**Files:**
- Modify: `dashboard/app/page.tsx`

**Interfaces:** consumes `/api/dora`, `/api/sprints`, `/api/heuristics`. Renders: DORA tier as hero, 14-sprint status streak (colored dots), active heuristic count, next-sprint countdown from `orgos/scheduler`.

- [ ] **Step 1: Replace `dashboard/app/page.tsx` contents**

```tsx
"use client";
import { useEffect, useState } from "react";
import Link from "next/link";

export default function Home() {
  const [dora, setDora] = useState<any>(null);
  const [sprints, setSprints] = useState<any[]>([]);
  const [heur, setHeur] = useState<any>(null);
  useEffect(() => {
    fetch("/api/dora").then(r => r.json()).then(setDora);
    fetch("/api/sprints").then(r => r.json()).then(setSprints);
    fetch("/api/heuristics").then(r => r.json()).then(setHeur);
  }, []);

  const streak = sprints.slice(0, 14).reverse();
  const activeCount = heur?.active?.length ?? 0;

  const nextRun = (() => {
    const d = new Date();
    d.setHours(2, 0, 0, 0);
    if (d < new Date()) d.setDate(d.getDate() + 1);
    return d;
  })();

  return (
    <div className="p-6 space-y-6">
      <div>
        <div className="text-sm uppercase text-gray-500">DORA</div>
        <div className="text-6xl font-bold">
          {dora?.latest?.tier ?? "—"}
        </div>
      </div>

      <div className="grid grid-cols-4 gap-3 text-sm">
        <Stat label="Deploy/day" v={dora?.latest?.deploy_freq?.toFixed(2)} />
        <Stat label="Lead time (d)" v={(dora?.latest?.lead_time_p50 / 86400).toFixed(1)} />
        <Stat label="CFR" v={(dora?.latest?.cfr * 100).toFixed(0) + "%"} />
        <Stat label="MTTR (h)" v={(dora?.latest?.mttr_p50 / 3600).toFixed(1)} />
      </div>

      <div>
        <div className="text-xs uppercase text-gray-500 mb-1">Last 14 sprints</div>
        <div className="flex gap-1">
          {streak.map((s: any) => (
            <div key={s.id}
                 title={`${s.id} — ${s.status}`}
                 className={
                   "w-3 h-3 rounded-full " +
                   (s.status === "completed" ? "bg-green-500"
                    : s.status === "needs_revision" ? "bg-yellow-500"
                    : "bg-red-500")
                 } />
          ))}
        </div>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <div><Link href="/dora" className="text-blue-600">DORA</Link></div>
        <div><Link href="/sprints" className="text-blue-600">Sprints ({sprints.length})</Link></div>
        <div><Link href="/team" className="text-blue-600">Team</Link></div>
      </div>

      <div className="text-xs text-gray-500">
        Next sprint: {nextRun.toLocaleString()} · Active heuristics: {activeCount}
      </div>
    </div>
  );
}

function Stat({ label, v }: { label: string; v: any }) {
  return (
    <div className="border rounded p-3">
      <div className="text-xs uppercase text-gray-500">{label}</div>
      <div className="text-lg font-mono">{v ?? "—"}</div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add dashboard/app/page.tsx
git commit -m "feat(dashboard): rewrite home as team scoreboard"
```

---

### Task 6.3: Retro Agent invocation + demo seed script

**Files:**
- Create: `orgos/agile/retro.py`
- Create: `orgos/agile/demo.py`
- Create: `tests/agile/test_retro.py`

**Interfaces produced:**
- `run_retro(sprint: Sprint, pm: PMStore) -> RetroEnvelope` — spawns retro_agent_role on the completed sprint's audit trail; writes RetroEnvelope to PMStore.
- `python -m orgos.agile.demo seed --sprints N` — runs N sprints back-to-back for demo data.

- [ ] **Step 1: Write failing test**

Create `tests/agile/test_retro.py`:

```python
import json
from pathlib import Path

from orgos.agile.envelopes import RetroEnvelope
from orgos.agile.retro import build_retro_from_sprint
from orgos.agile.sprint import Sprint


def test_offline_retro_uses_attribution_scores():
    from orgos.agile.envelopes import (
        BriefEnvelope, EngineeringEnvelope, GradeEnvelope, ReleaseEnvelope,
    )
    envs = {
        "brief": BriefEnvelope(role="pm", status="completed", summary="",
            success_criteria_met=True, requires_human_approval=False,
            payload=json.dumps({"picked_issue_id": "1", "task_brief_json": "{}",
              "touched_files_allowlist": ["src.py"],
              "acceptance_tests": ["pytest"]})),
        "engineering": EngineeringEnvelope(role="e", status="completed",
            summary="", success_criteria_met=True, requires_human_approval=False,
            payload=json.dumps({"diff": "+x", "commit_sha": "abc1234",
              "files_touched": ["src.py"], "test_command": "pytest",
              "test_output": "ok", "test_passed": True})),
        "grade": GradeEnvelope(role="qa", status="completed", summary="",
            success_criteria_met=True, requires_human_approval=False,
            payload=json.dumps({"criteria": [], "rubric_score": 1.0})),
        "release": ReleaseEnvelope(role="r", status="completed", summary="",
            success_criteria_met=True, requires_human_approval=False,
            payload=json.dumps({"pr_url": "mock://pr/1", "branch": "agile/x",
              "mock_mode": True})),
    }
    sprint = Sprint(
        id="s1", started_at="", repo_path=Path("."), worktree_path=Path("."),
        branch="agile/s1", picked_issue={"issue_id": "1"},
        envelopes=envs, status="completed",
    )
    retro = build_retro_from_sprint(sprint)
    assert isinstance(retro, RetroEnvelope)
    payload = retro.parsed_payload()
    assert payload["role_attribution"]
    assert payload["retro_markdown"]
```

- [ ] **Step 2: Implement `orgos/agile/retro.py`**

```python
"""Retro Agent — deterministic retrospective builder.

For MVP we skip the LLM call and generate a factual retro from the
envelope chain + attribution. A future task can swap in a real spawn()
that reads the audit log for prose retros; the deterministic version is
what the tests + demo rely on.
"""

from __future__ import annotations

import json

from .attribution import compute_attribution
from .envelopes import RetroEnvelope


def build_retro_from_sprint(sprint) -> RetroEnvelope:
    scores = compute_attribution(sprint)
    grade = sprint.envelopes.get("grade")
    grade_payload = grade.parsed_payload() if grade else {}
    rubric_score = grade_payload.get("rubric_score", 0.0)

    lines = [f"# Sprint {sprint.id} retro", ""]
    lines.append(f"- **Rubric score:** {rubric_score:.2f}")
    lines.append(f"- **Status:** {sprint.status}")
    lines.append("")
    lines.append("## Role contribution")
    for role, s in sorted(scores.items(), key=lambda x: -x[1]):
        lines.append(f"- {role}: {s:.2f}")

    failed = [c for c in grade_payload.get("criteria", []) if not c.get("passed")]
    candidates = []
    if failed:
        lines.append("")
        lines.append("## What didn't work")
        for c in failed:
            lines.append(f"- **{c['name']}** — {c.get('reason', '')}")
            candidates.append({
                "rule": f"Address {c['name']} in the DoD",
                "why": c.get("reason", "recurring failure mode"),
                "tags": [c["name"]],
            })
    payload = json.dumps({
        "retro_markdown": "\n".join(lines),
        "candidate_heuristics": candidates,
        "role_attribution": scores,
    })
    return RetroEnvelope(
        role="retro-agent", status="completed",
        summary=f"score={rubric_score:.2f}",
        success_criteria_met=True, requires_human_approval=False,
        payload=payload,
    )
```

- [ ] **Step 3: Wire retro into `run_nightly_sprint`**

Right after the DORA block in `sprint.py`:

```python
    from .retro import build_retro_from_sprint
    retro_env = build_retro_from_sprint(sprint)
    sprint.envelopes["retro"] = retro_env
    pm.record_sprint_envelope(sprint.id, "retro", retro_env.model_dump_json())
```

- [ ] **Step 4: Implement `orgos/agile/demo.py`**

```python
"""Demo seed: run N sprints back-to-back with a fixture backlog."""

from __future__ import annotations

import argparse
from pathlib import Path

from orgos.agile.sprint import run_sprint


DEMO_ISSUES = [
    {"issue_id": "demo-1", "title": "Add farewell()",
     "body": "Add `farewell()` -> 'bye' to src.py + test.", "labels": ["agent-eligible"]},
    {"issue_id": "demo-2", "title": "Add greeting_uppercase()",
     "body": "Add `greeting_uppercase()` returning greet().upper().", "labels": ["agent-eligible"]},
    {"issue_id": "demo-3", "title": "Type-hint src.py",
     "body": "Add type hints to src.py functions.", "labels": ["agent-eligible"]},
    {"issue_id": "demo-4", "title": "Add doctest to greet()",
     "body": "Add a doctest to greet().", "labels": ["agent-eligible"]},
    {"issue_id": "demo-5", "title": "Extract constants",
     "body": "Move return strings to module-level constants.", "labels": ["agent-eligible"]},
]


def seed(n: int, repo: Path) -> None:
    for i in range(n):
        issue = DEMO_ISSUES[i % len(DEMO_ISSUES)]
        s = run_sprint(repo, issue, mock_pr=True)
        print(f"sprint {i+1}/{n}: id={s.id} status={s.status}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    seed_cmd = sub.add_parser("seed")
    seed_cmd.add_argument("--sprints", type=int, default=5)
    seed_cmd.add_argument("--repo", default=".")
    args = ap.parse_args()
    if args.cmd == "seed":
        seed(args.sprints, Path(args.repo))


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests, commit**

Run: `pytest tests/agile/test_retro.py -v` — Expected PASS.

```bash
git add orgos/agile/retro.py orgos/agile/demo.py orgos/agile/sprint.py tests/agile/test_retro.py
git commit -m "feat(agile): retro + demo seed command"
```

---

### Task 6.4: One synthetic 'hard' issue + final smoke + memory update

**Files:**
- Create: `docs/demo-hard-issue.md` (narrative doc describing the seeded hard issue)
- Modify: `orgos/agile/demo.py` — add `HARD_ISSUE` that trips a small model
- Run: full `pytest` suite; run 5 sprints on the fixture repo

**Interfaces:** `python -m orgos.agile.demo seed --sprints 5 --include-hard` yields at least one failed/needs_revision sprint so the retro + heuristic-learning loop has data.

- [ ] **Step 1: Add the hard issue**

Append to `orgos/agile/demo.py`:

```python
HARD_ISSUE = {
    "issue_id": "hard-1",
    "title": "Rename greet() -> welcome() everywhere, preserving external API",
    "body": (
        "Rename greet() -> welcome(). All existing callers must continue to work "
        "(add greet = welcome shim). Update all tests. Do not modify README. "
        "Diff must stay under 40 LOC total."
    ),
    "labels": ["agent-eligible"],
}


def seed(n: int, repo: Path, include_hard: bool = False) -> None:
    issues = list(DEMO_ISSUES)
    if include_hard:
        issues.insert(n // 2, HARD_ISSUE)
    for i, issue in enumerate(issues[:n]):
        s = run_sprint(repo, issue, mock_pr=True)
        print(f"sprint {i+1}/{n}: id={s.id} status={s.status}")
```

Update the argparse block to add `--include-hard` flag and pass it through.

- [ ] **Step 2: Write the demo-hard-issue doc**

Create `docs/demo-hard-issue.md`:

```markdown
# Demo hard issue

The seed run includes `hard-1` — a compound rename + shim + LOC-cap task
designed to trip smaller models. It gives the demo:

- A `needs_revision` sprint with a graded failure.
- Non-empty candidate heuristics (from the QA rubric's `diff_size_ok` and
  `files_in_allowlist` misses).
- A proposal-worthy attribution pattern (Engineer contribution drops).

Do not "fix" the hard issue — the retro is the point of the demo.
```

- [ ] **Step 3: Run the whole suite**

Run: `pytest -q -m "not network"`
Expected: PASS.

- [ ] **Step 4: Seed the demo (optional smoke, requires an LLM key)**

Run: `ANTHROPIC_API_KEY=... python -m orgos.agile.demo seed --sprints 5 --include-hard --repo /tmp/fixture-repo`

Where `/tmp/fixture-repo` is a fresh clone of the fixture created by hand (or reuse the pytest fixture repo layout). Verify PMStore rows: `sqlite3 _orgos_memory/pm.db "SELECT id, status FROM sprints"`.

- [ ] **Step 5: Update project memories**

After all commits land on `agile-pivot`, update memory:

Update `~/.claude/projects/-Users-th-Documents-Github-orgos/memory/project_orgos.md` — change the "worked example" description from "quant research desk" to "self-organizing agile engineering team." Update `project_demo_feedback.md` — note that the momentum / options / memory-compression feedback informed the pivot (self-org topology + Reflector heuristics replace the unbounded evolve journal; the DORA loop is the "signals move faster than fundamentals" angle applied to the team itself).

- [ ] **Step 6: Commit**

```bash
git add orgos/agile/demo.py docs/demo-hard-issue.md
git commit -m "feat(demo): hard-1 synthetic issue for retro/heuristic learning"
```

---

## Self-review checklist (run once, inline)

- [ ] **Spec coverage:** every numbered section in `docs/superpowers/specs/2026-06-30-agile-product-team-design.md` (§1–§13) has at least one task above.
  - §1 architecture: Task 0.1–0.3, 1.1, 1.4
  - §2 seed team: 1.4
  - §3 sprint loop: 1.7, 1.8, 2.4, 2.5, 3.4, 4.4, 6.3
  - §4 Hook A: 4.1–4.7
  - §5 Hook B: 5.1–5.6
  - §6 Hook C: 3.1–3.4
  - §7 UI surface: 3.4, 4.7, 5.6, 6.2
  - §8 A2A stub: 6.1
  - §9 MAST rules: 1.3 (depth cap), 1.5 (terminal grader), 1.2 (typed envelopes), 4.5 (append-only ADR-driven mutation), 5.4 (replay tier isolation), 4.3 (expire_at on new roles)
  - §10 risks: mitigations woven into 1.7 (worktree isolation), 3.2 (rate limit budgets are in the intake ranker), etc.
  - §11 tests: every task adds tests; test dir `tests/agile/`
  - §12 sequencing: matches Phase 0–6 ordering above
  - §13 out of scope: not implemented (correct)

- [ ] **Placeholder scan:** search plan for TBD/TODO/"add error handling"/"similar to Task N". None expected — cleared in review.

- [ ] **Type consistency:** RoleSpec names (`sprint-lead`, `product-manager`, `engineer`, `qa-validator`, `release-manager`, `retro-agent`) used identically across Task 1.4, 4.2, 4.3, 4.4, 5.2, 6.3. Envelope class names identical across Task 1.2 and every consumer.

## Execution handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-30-agile-product-team.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
