# Persona File Loader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the loader that turns the three-layer markdown persona files into a validated `RoleSpec`, so every downstream plan (topology, board, HEARTBEAT, benchmarking) can define agents in markdown instead of Python.

**Architecture:** A new `orgos/spawn/persona_loader.py` module reads three layers of markdown files (universal principles → optional worker base → agent-specific) from an `agents/` directory tree, validates each file's YAML frontmatter and body sections against a Pydantic schema, concatenates the layers into a single `system_prompt` string in the correct attention-ordering, and exposes `RoleSpec.from_agent_dir(agents_root, agent_name)` as the single entrypoint. No changes to spawn/engine or governance behavior — the loader produces the exact same `RoleSpec` shape the rest of orgos already consumes.

**Tech Stack:** Python 3.11, pydantic v2 (already installed), ruamel.yaml (already installed for evolve.py), pytest (existing test infrastructure).

## Global Constraints

- **RoleSpec shape is untouched.** The loader must produce a `RoleSpec` byte-for-byte equivalent to what `engineering_team.py`-style factories produce today. No new `RoleSpec` fields; no changes to `contracts.py` beyond the classmethod factory.
- **No new pip dependencies.** Use `ruamel.yaml` (already in requirements.txt) for YAML frontmatter; do not add `python-frontmatter` or `pyyaml`.
- **Governance layer is off-limits.** Do not modify `GatedToolBase`, `HandoffEnvelope`, `TierPolicy`, `PermissionTier`, `spawn()`, or `spawn_chain()`.
- **Filesystem convention is prescriptive.** Layer 1 lives at `<agents_root>/_principles/principles.md`. Layer 2 lives at `<agents_root>/_worker_base/{soul,brain,habits,memory,heartbeat}.md`. Layer 3 lives at `<agents_root>/<agent_name>/{soul,brain,habits,memory,heartbeat}.md`. Underscore-prefix marks inherited layers; the loader never treats them as agent directories.
- **Instance vs durable files.** MEMORY.md and HEARTBEAT.md are instance files — they get loaded like the others in Plan 1 (read-only) but are the ones Plan 4 will mutate. Plan 1 does not implement any writes.
- **Concatenation order is fixed.** Layer 1 → Layer 2 (soul → brain → habits → memory → heartbeat) → Layer 3 (soul → brain → habits → memory → heartbeat). HEARTBEAT loads last so it lands in the recency-attention window.
- **Validation is strict on frontmatter, warn-only on body sections.** Missing required frontmatter fields raise `PersonaValidationError`; missing body sections log a warning but do not fail load. Reason: schema pedantry blocks progress at this stage; we tighten in Plan 2 once agents actually exist.

---

## File Structure

Files created by this plan:

| Path | Responsibility |
|---|---|
| `orgos/spawn/persona_schema.py` | Pydantic models for per-file frontmatter (`SoulFrontmatter`, `BrainFrontmatter`, etc.); constants for required body sections per file type; `PersonaValidationError`. |
| `orgos/spawn/persona_loader.py` | `load_persona_file(path, file_type)` → parses YAML frontmatter + body; `load_layer(dir_path, file_types)` → loads a set of five files; `assemble_system_prompt(principles, worker_base, specific)` → concatenates layers with section headers; `load_agent(agents_root, agent_name)` → the top-level entrypoint that returns a `RoleSpec`. |
| `orgos/spawn/contracts.py` | Modified: add `RoleSpec.from_agent_dir(agents_root, agent_name)` classmethod that delegates to `persona_loader.load_agent`. Nothing else changes. |
| `tests/spawn/test_persona_loader.py` | Unit tests for each loader function + one golden integration test that loads a full sample agent. |
| `tests/spawn/fixtures/agents/_principles/principles.md` | Sample principles file used by tests. |
| `tests/spawn/fixtures/agents/_worker_base/{soul,brain,habits,memory,heartbeat}.md` | Sample worker-base files. |
| `tests/spawn/fixtures/agents/sample_worker/{soul,brain,habits,memory,heartbeat}.md` | Sample delivery-worker agent. |
| `tests/spawn/fixtures/agents/sample_po/{soul,brain,habits,memory,heartbeat}.md` | Sample non-worker agent (skips worker-base layer). |
| `tests/spawn/__init__.py` | Package marker if not present. |

No files are deleted.

---

## Interfaces (locked)

These signatures are the contract between tasks — later tasks depend on the exact names below.

```python
# persona_schema.py
class PersonaValidationError(ValueError): ...

class BaseFrontmatter(BaseModel):
    version: str  # semver-like, e.g. "1.0.0"
    layer: Literal["principles", "worker_base", "specific"]

class SoulFrontmatter(BaseFrontmatter):
    agent_name: str
    tier: Literal["worker", "validator", "publisher", "orchestrator"]
    description: str = ""
    model: str | None = None
    max_iter: int = 20
    is_worker: bool = False  # True => loader includes Layer 2 worker_base
    success_criteria: list[str] = Field(default_factory=list)

class SimpleFrontmatter(BaseFrontmatter):
    agent_name: str | None = None  # None for principles/worker_base; set for specific

# One frontmatter class per file type; SOUL carries the RoleSpec-shaping fields.

REQUIRED_SECTIONS: dict[str, list[str]] = {
    "principles": ["Delivery Philosophy", "Universal Identity Beliefs", "Universal Habits"],
    "soul":       ["Identity", "Values", "Stance", "Optimizes For"],
    "brain":      ["Decision Framework", "Domain Knowledge", "Reasoning Patterns"],
    "habits":     ["Habits"],
    "memory":     ["Foundational Principles", "Sprint History", "Recurring Patterns", "Key Decisions"],
    "heartbeat":  ["Current Task", "Recent Session Summary", "Next Actions"],
}

FILE_TYPES: tuple[str, ...] = ("soul", "brain", "habits", "memory", "heartbeat")
```

```python
# persona_loader.py
@dataclass(frozen=True)
class PersonaFile:
    file_type: str            # "principles" | "soul" | "brain" | "habits" | "memory" | "heartbeat"
    frontmatter: BaseModel    # concrete subclass depending on file_type
    body: str                 # markdown body with frontmatter stripped

def load_persona_file(path: Path, file_type: str) -> PersonaFile: ...

def load_layer(dir_path: Path, file_types: Sequence[str]) -> dict[str, PersonaFile]:
    """Load a full layer (a dict keyed by file_type). Missing files raise."""

def assemble_system_prompt(
    principles: PersonaFile,
    worker_base: dict[str, PersonaFile] | None,
    specific: dict[str, PersonaFile],
) -> str:
    """Concatenate the three layers with '=== LAYER: … ===' section headers,
    in the attention-aware order: principles → worker_base(soul→brain→habits→memory→heartbeat)
    → specific(soul→brain→habits→memory→heartbeat)."""

def load_agent(agents_root: Path, agent_name: str) -> RoleSpec:
    """The one entrypoint downstream code calls. Loads all layers, assembles the
    system_prompt, extracts RoleSpec fields from the specific SOUL frontmatter,
    returns a validated RoleSpec."""
```

```python
# contracts.py additions
class RoleSpec(BaseModel):
    ...  # existing fields untouched
    @classmethod
    def from_agent_dir(cls, agents_root: Path, agent_name: str) -> "RoleSpec":
        from orgos.spawn.persona_loader import load_agent
        return load_agent(agents_root, agent_name)
```

---

### Task 1: Persona schema

**Files:**
- Create: `orgos/spawn/persona_schema.py`
- Test: `tests/spawn/test_persona_loader.py` (create; tests for schema live here)

**Interfaces:**
- Produces: `PersonaValidationError`, `BaseFrontmatter`, `SoulFrontmatter`, `SimpleFrontmatter`, `REQUIRED_SECTIONS`, `FILE_TYPES`.

- [ ] **Step 1: Write the failing schema tests**

Create `tests/spawn/test_persona_loader.py` with the schema test group:

```python
"""Tests for the persona file loader (Plan 1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orgos.spawn.persona_schema import (
    FILE_TYPES,
    REQUIRED_SECTIONS,
    PersonaValidationError,
    SimpleFrontmatter,
    SoulFrontmatter,
)


class TestSchemaConstants:
    def test_file_types_are_the_five_expected(self):
        assert FILE_TYPES == ("soul", "brain", "habits", "memory", "heartbeat")

    def test_required_sections_covers_every_file_type_plus_principles(self):
        assert set(REQUIRED_SECTIONS.keys()) == {
            "principles", "soul", "brain", "habits", "memory", "heartbeat",
        }


class TestSoulFrontmatter:
    def test_minimal_valid_soul(self):
        fm = SoulFrontmatter(
            version="1.0.0",
            layer="specific",
            agent_name="architect",
            tier="worker",
        )
        assert fm.agent_name == "architect"
        assert fm.tier == "worker"
        assert fm.is_worker is False  # default
        assert fm.max_iter == 20  # default

    def test_soul_rejects_unknown_tier(self):
        with pytest.raises(ValidationError):
            SoulFrontmatter(
                version="1.0.0", layer="specific",
                agent_name="x", tier="janitor",
            )

    def test_soul_rejects_unknown_layer(self):
        with pytest.raises(ValidationError):
            SoulFrontmatter(
                version="1.0.0", layer="astral",
                agent_name="x", tier="worker",
            )


class TestPersonaValidationError:
    def test_is_valueerror_subclass(self):
        assert issubclass(PersonaValidationError, ValueError)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/spawn/test_persona_loader.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'orgos.spawn.persona_schema'`

- [ ] **Step 3: Implement `persona_schema.py`**

Create `orgos/spawn/persona_schema.py`:

```python
"""Schema for persona markdown files (autonomous scrum team model).

Every persona file starts with YAML frontmatter validated against one of the
models below, followed by a markdown body whose top-level ## sections must
include the entries listed in REQUIRED_SECTIONS for that file type.

Frontmatter is validated strictly (missing fields raise); body sections are
validated warn-only in Plan 1 (missing sections log but do not raise).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PersonaValidationError(ValueError):
    """Raised when a persona file's frontmatter is missing or malformed."""


FILE_TYPES: tuple[str, ...] = ("soul", "brain", "habits", "memory", "heartbeat")


REQUIRED_SECTIONS: dict[str, list[str]] = {
    "principles": [
        "Delivery Philosophy",
        "Universal Identity Beliefs",
        "Universal Habits",
    ],
    "soul": ["Identity", "Values", "Stance", "Optimizes For"],
    "brain": ["Decision Framework", "Domain Knowledge", "Reasoning Patterns"],
    "habits": ["Habits"],
    "memory": [
        "Foundational Principles",
        "Sprint History",
        "Recurring Patterns",
        "Key Decisions",
    ],
    "heartbeat": ["Current Task", "Recent Session Summary", "Next Actions"],
}


class BaseFrontmatter(BaseModel):
    """Common frontmatter across every persona file type."""

    version: str
    layer: Literal["principles", "worker_base", "specific"]


class SoulFrontmatter(BaseFrontmatter):
    """SOUL.md carries all the RoleSpec-shaping metadata for the agent."""

    agent_name: str
    tier: Literal["worker", "validator", "publisher", "orchestrator"]
    description: str = ""
    model: str | None = None
    max_iter: int = 20
    is_worker: bool = False  # True => include Layer 2 worker_base at load time
    success_criteria: list[str] = Field(default_factory=list)


class SimpleFrontmatter(BaseFrontmatter):
    """Frontmatter for brain/habits/memory/heartbeat/principles.

    agent_name is required for Layer 3 (specific) files and optional for
    inherited layers (principles / worker_base).
    """

    agent_name: str | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/spawn/test_persona_loader.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add orgos/spawn/persona_schema.py tests/spawn/test_persona_loader.py
git commit -m "feat(spawn): add persona file schema for autonomous scrum team"
```

---

### Task 2: Single-file loader — parse frontmatter + strip body

**Files:**
- Create: `orgos/spawn/persona_loader.py`
- Modify: `tests/spawn/test_persona_loader.py` (append test group)
- Create: `tests/spawn/fixtures/agents/_principles/principles.md`
- Create: `tests/spawn/fixtures/agents/sample_worker/soul.md`

**Interfaces:**
- Consumes: `SoulFrontmatter`, `SimpleFrontmatter`, `PersonaValidationError` from Task 1.
- Produces: `PersonaFile` dataclass, `load_persona_file(path, file_type) -> PersonaFile`.

- [ ] **Step 1: Write the failing single-file loader tests**

Append to `tests/spawn/test_persona_loader.py`:

```python
from pathlib import Path

from orgos.spawn.persona_loader import PersonaFile, load_persona_file

FIXTURES = Path(__file__).parent / "fixtures" / "agents"


class TestLoadPersonaFile:
    def test_loads_a_valid_soul_file(self):
        pf = load_persona_file(FIXTURES / "sample_worker" / "soul.md", "soul")
        assert isinstance(pf, PersonaFile)
        assert pf.file_type == "soul"
        assert pf.frontmatter.agent_name == "sample_worker"
        assert pf.frontmatter.tier == "worker"
        assert pf.frontmatter.is_worker is True
        assert "## Identity" in pf.body

    def test_loads_a_valid_principles_file(self):
        pf = load_persona_file(
            FIXTURES / "_principles" / "principles.md", "principles",
        )
        assert pf.file_type == "principles"
        assert pf.frontmatter.layer == "principles"
        assert "## Delivery Philosophy" in pf.body

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(PersonaValidationError, match="not found"):
            load_persona_file(tmp_path / "nope.md", "soul")

    def test_missing_frontmatter_raises(self, tmp_path):
        p = tmp_path / "bad.md"
        p.write_text("no frontmatter here\n## Identity\nx\n")
        with pytest.raises(PersonaValidationError, match="frontmatter"):
            load_persona_file(p, "soul")

    def test_bad_frontmatter_field_raises(self, tmp_path):
        p = tmp_path / "bad.md"
        p.write_text(
            "---\nversion: 1.0.0\nlayer: specific\nagent_name: x\n"
            "tier: janitor\n---\n## Identity\nx\n"
        )
        with pytest.raises(PersonaValidationError):
            load_persona_file(p, "soul")

    def test_missing_body_section_warns_but_loads(self, tmp_path, caplog):
        p = tmp_path / "soul.md"
        p.write_text(
            "---\nversion: 1.0.0\nlayer: specific\n"
            "agent_name: x\ntier: worker\n---\n"
            "## Identity\nx\n"  # missing Values / Stance / Optimizes For
        )
        pf = load_persona_file(p, "soul")
        assert pf is not None
        assert any("missing section" in r.message.lower() for r in caplog.records)
```

- [ ] **Step 2: Create the fixture files**

Create `tests/spawn/fixtures/agents/_principles/principles.md`:

```markdown
---
version: 1.0.0
layer: principles
---

## Delivery Philosophy

Finish beats track. Unfinished work is either blocked, deferred, or dropped.

## Universal Identity Beliefs

- I am a reasoner, not an executor.
- I leave traces.
- I work with what I have.

## Universal Habits

- Memory stewardship: end every session with a MEMORY delta.
- Adaptive error handling: errors are information, not stop signals.
- Label discipline: no ad-hoc labels.
```

Create `tests/spawn/fixtures/agents/sample_worker/soul.md`:

```markdown
---
version: 1.0.0
layer: specific
agent_name: sample_worker
tier: worker
description: Sample delivery worker used in unit tests.
is_worker: true
max_iter: 8
success_criteria:
  - Produces a valid HandoffEnvelope.
  - Diff <= 400 LOC.
---

## Identity
Sample worker for tests. Not a real agent.

## Values
Honesty. Small diffs. Legible commits.

## Stance
I captain a story or contribute to another agent's story.

## Optimizes For
Passing the rubric on the first review.
```

- [ ] **Step 3: Run tests to verify they fail on the loader import**

Run: `pytest tests/spawn/test_persona_loader.py -v`
Expected: FAIL with `ImportError: cannot import name 'PersonaFile' from 'orgos.spawn.persona_loader'` (module doesn't exist yet).

- [ ] **Step 4: Implement the single-file loader**

Create `orgos/spawn/persona_loader.py`:

```python
"""Loader for the three-layer persona markdown files.

This module reads `agents/<name>/*.md` files, validates their YAML frontmatter,
strips the frontmatter from the body, and (in Task 4) assembles them into a
`RoleSpec`. See `docs/superpowers/plans/2026-07-08-persona-file-loader.md` for
the design.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from pydantic import BaseModel, ValidationError
from ruamel.yaml import YAML

from orgos.spawn.persona_schema import (
    FILE_TYPES,
    REQUIRED_SECTIONS,
    PersonaValidationError,
    SimpleFrontmatter,
    SoulFrontmatter,
)

log = logging.getLogger(__name__)

_YAML = YAML(typ="safe")


@dataclass(frozen=True)
class PersonaFile:
    file_type: str
    frontmatter: BaseModel
    body: str


_FRONTMATTER_MODELS: dict[str, type[BaseModel]] = {
    "principles": SimpleFrontmatter,
    "soul": SoulFrontmatter,
    "brain": SimpleFrontmatter,
    "habits": SimpleFrontmatter,
    "memory": SimpleFrontmatter,
    "heartbeat": SimpleFrontmatter,
}


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Return (yaml_text, body_text). Raises if no closing '---' found."""
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        raise PersonaValidationError("file must start with YAML frontmatter (---)")
    # Skip the opening '---' line.
    rest = text.split("\n", 1)[1]
    if "\n---\n" not in rest and "\n---\r\n" not in rest:
        raise PersonaValidationError("frontmatter is not closed with a '---' line")
    yaml_text, body = rest.split("\n---", 1)
    # Body starts after the closing '---\n'; strip the leading newline.
    body = body.lstrip("\r\n")
    return yaml_text, body


def _warn_missing_sections(body: str, file_type: str, path: Path) -> None:
    required = REQUIRED_SECTIONS.get(file_type, [])
    for section in required:
        needle = f"## {section}"
        if needle not in body:
            log.warning(
                "persona: %s missing section %r (file_type=%s)",
                path, section, file_type,
            )


def load_persona_file(path: Path, file_type: str) -> PersonaFile:
    """Read one persona file, validate its frontmatter, return a PersonaFile."""
    if file_type not in _FRONTMATTER_MODELS:
        raise PersonaValidationError(
            f"unknown file_type {file_type!r}; expected one of "
            f"{sorted(_FRONTMATTER_MODELS)}"
        )
    if not path.exists():
        raise PersonaValidationError(f"persona file not found: {path}")

    text = path.read_text(encoding="utf-8")
    yaml_text, body = _split_frontmatter(text)

    try:
        data = _YAML.load(io.StringIO(yaml_text)) or {}
    except Exception as e:  # ruamel raises its own tree of errors
        raise PersonaValidationError(f"{path}: invalid YAML frontmatter: {e}") from e

    model_cls = _FRONTMATTER_MODELS[file_type]
    try:
        frontmatter = model_cls(**data)
    except ValidationError as e:
        raise PersonaValidationError(f"{path}: frontmatter validation failed: {e}") from e

    _warn_missing_sections(body, file_type, path)
    return PersonaFile(file_type=file_type, frontmatter=frontmatter, body=body)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/spawn/test_persona_loader.py -v`
Expected: PASS. All Task 1 and Task 2 tests green.

- [ ] **Step 6: Commit**

```bash
git add orgos/spawn/persona_loader.py \
        tests/spawn/test_persona_loader.py \
        tests/spawn/fixtures/agents/_principles/principles.md \
        tests/spawn/fixtures/agents/sample_worker/soul.md
git commit -m "feat(spawn): parse persona file frontmatter and body"
```

---

### Task 3: Layer loader — load a whole layer of five files

**Files:**
- Modify: `orgos/spawn/persona_loader.py` (add `load_layer`)
- Modify: `tests/spawn/test_persona_loader.py` (append test group)
- Create: remaining fixture files (`_worker_base/*.md`, `sample_worker/brain.md`, `sample_worker/habits.md`, `sample_worker/memory.md`, `sample_worker/heartbeat.md`)

**Interfaces:**
- Consumes: `load_persona_file`, `PersonaFile`, `FILE_TYPES` from earlier tasks.
- Produces: `load_layer(dir_path, file_types) -> dict[str, PersonaFile]`.

- [ ] **Step 1: Create the remaining fixture files**

For each of `brain.md`, `habits.md`, `memory.md`, `heartbeat.md` in `tests/spawn/fixtures/agents/sample_worker/` and each of `soul.md`, `brain.md`, `habits.md`, `memory.md`, `heartbeat.md` in `tests/spawn/fixtures/agents/_worker_base/`, create a minimal valid file matching this pattern (adjusted for file type and layer):

`tests/spawn/fixtures/agents/sample_worker/brain.md`:
```markdown
---
version: 1.0.0
layer: specific
agent_name: sample_worker
---

## Decision Framework
Pick the smallest change that satisfies acceptance criteria.

## Domain Knowledge
Test fixtures do not carry real domain knowledge.

## Reasoning Patterns
Read → plan → smallest edit → test → commit.
```

`tests/spawn/fixtures/agents/sample_worker/habits.md`:
```markdown
---
version: 1.0.0
layer: specific
agent_name: sample_worker
---

## Habits
- Trigger: story pulled → Response: read INDEX.md + last 3 ADRs → Outcome: grounded start. Anti-pattern: coding blind.
```

`tests/spawn/fixtures/agents/sample_worker/memory.md`:
```markdown
---
version: 1.0.0
layer: specific
agent_name: sample_worker
---

## Foundational Principles
- Sample principle.
## Sprint History
(empty at boot)
## Recurring Patterns
(empty at boot)
## Key Decisions
(empty at boot)
```

`tests/spawn/fixtures/agents/sample_worker/heartbeat.md`:
```markdown
---
version: 1.0.0
layer: specific
agent_name: sample_worker
---

## Current Task
None (fresh boot).

## Recent Session Summary
No prior session.

## Next Actions
Inspect the board.
```

For the `_worker_base/` layer, create the same five file types with `layer: worker_base` and `agent_name` omitted. Each body has the required sections with placeholder text (e.g., `_worker_base/soul.md` has `## Identity`, `## Values`, `## Stance`, `## Optimizes For` with worker-generic content).

- [ ] **Step 2: Write the failing layer-loader tests**

Append to `tests/spawn/test_persona_loader.py`:

```python
from orgos.spawn.persona_loader import load_layer
from orgos.spawn.persona_schema import FILE_TYPES


class TestLoadLayer:
    def test_loads_all_five_files_for_specific_layer(self):
        layer = load_layer(FIXTURES / "sample_worker", FILE_TYPES)
        assert set(layer.keys()) == set(FILE_TYPES)
        assert layer["soul"].frontmatter.agent_name == "sample_worker"

    def test_loads_worker_base_layer(self):
        layer = load_layer(FIXTURES / "_worker_base", FILE_TYPES)
        assert set(layer.keys()) == set(FILE_TYPES)
        assert layer["soul"].frontmatter.layer == "worker_base"

    def test_missing_file_in_layer_raises(self, tmp_path):
        d = tmp_path / "incomplete_agent"
        d.mkdir()
        (d / "soul.md").write_text(
            "---\nversion: 1.0.0\nlayer: specific\n"
            "agent_name: x\ntier: worker\n---\n## Identity\nx\n"
        )
        # brain / habits / memory / heartbeat missing
        with pytest.raises(PersonaValidationError, match="brain.md"):
            load_layer(d, FILE_TYPES)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/spawn/test_persona_loader.py::TestLoadLayer -v`
Expected: FAIL with `ImportError: cannot import name 'load_layer'`.

- [ ] **Step 4: Implement `load_layer`**

Append to `orgos/spawn/persona_loader.py`:

```python
def load_layer(
    dir_path: Path, file_types: Sequence[str],
) -> dict[str, PersonaFile]:
    """Load every file_type from dir_path. Missing files raise."""
    if not dir_path.is_dir():
        raise PersonaValidationError(f"layer directory not found: {dir_path}")
    out: dict[str, PersonaFile] = {}
    for ft in file_types:
        out[ft] = load_persona_file(dir_path / f"{ft}.md", ft)
    return out
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/spawn/test_persona_loader.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add orgos/spawn/persona_loader.py tests/spawn/test_persona_loader.py \
        tests/spawn/fixtures/agents/
git commit -m "feat(spawn): load a full persona layer of five files"
```

---

### Task 4: Assemble system prompt and integrate with RoleSpec

**Files:**
- Modify: `orgos/spawn/persona_loader.py` (add `assemble_system_prompt`, `load_agent`)
- Modify: `orgos/spawn/contracts.py` (add `RoleSpec.from_agent_dir` classmethod)
- Modify: `tests/spawn/test_persona_loader.py` (append)
- Create: `tests/spawn/fixtures/agents/sample_po/*.md` (five files, agent that is *not* a worker — `is_worker: false`)

**Interfaces:**
- Consumes: `load_layer`, `PersonaFile`, `SoulFrontmatter`.
- Produces: `assemble_system_prompt(...)`, `load_agent(agents_root, agent_name) -> RoleSpec`, `RoleSpec.from_agent_dir(agents_root, agent_name) -> RoleSpec`.

- [ ] **Step 1: Create the sample_po fixture (non-worker agent)**

Five files under `tests/spawn/fixtures/agents/sample_po/`. `soul.md` is:

```markdown
---
version: 1.0.0
layer: specific
agent_name: sample_po
tier: orchestrator
description: Sample product-owner-like agent that skips the worker_base layer.
is_worker: false
---

## Identity
Sample PO. Owns the backlog.

## Values
Ready > perfect. Order > estimation.

## Stance
I do not implement; I frame and prioritize.

## Optimizes For
Ready backlog quality.
```

The other four (`brain.md`, `habits.md`, `memory.md`, `heartbeat.md`) mirror the `sample_worker` versions with `agent_name: sample_po`.

- [ ] **Step 2: Write the failing assembly + load_agent tests**

Append to `tests/spawn/test_persona_loader.py`:

```python
from orgos.spawn.contracts import PermissionTier, RoleSpec
from orgos.spawn.persona_loader import assemble_system_prompt, load_agent


class TestAssembleSystemPrompt:
    def test_orders_layers_principles_then_worker_then_specific(self):
        principles = load_persona_file(
            FIXTURES / "_principles" / "principles.md", "principles",
        )
        worker_base = load_layer(FIXTURES / "_worker_base", FILE_TYPES)
        specific = load_layer(FIXTURES / "sample_worker", FILE_TYPES)

        prompt = assemble_system_prompt(principles, worker_base, specific)

        # principles come first
        assert prompt.index("=== LAYER: PRINCIPLES ===") < prompt.index(
            "=== LAYER: WORKER_BASE ==="
        )
        assert prompt.index("=== LAYER: WORKER_BASE ===") < prompt.index(
            "=== LAYER: SPECIFIC ==="
        )
        # heartbeat is last within specific → falls at the end of the prompt
        assert prompt.rstrip().endswith(specific["heartbeat"].body.rstrip())

    def test_skips_worker_base_when_not_a_worker(self):
        principles = load_persona_file(
            FIXTURES / "_principles" / "principles.md", "principles",
        )
        specific = load_layer(FIXTURES / "sample_po", FILE_TYPES)
        prompt = assemble_system_prompt(principles, None, specific)
        assert "=== LAYER: WORKER_BASE ===" not in prompt


class TestLoadAgent:
    def test_loads_a_worker_agent_end_to_end(self):
        role = load_agent(FIXTURES, "sample_worker")
        assert isinstance(role, RoleSpec)
        assert role.name == "sample_worker"
        assert role.tier == PermissionTier.WORKER
        assert role.max_iter == 8
        assert "=== LAYER: WORKER_BASE ===" in role.system_prompt
        assert role.success_criteria == [
            "Produces a valid HandoffEnvelope.",
            "Diff <= 400 LOC.",
        ]

    def test_loads_a_non_worker_agent_and_skips_worker_base(self):
        role = load_agent(FIXTURES, "sample_po")
        assert role.tier == PermissionTier.ORCHESTRATOR
        assert "=== LAYER: WORKER_BASE ===" not in role.system_prompt

    def test_from_agent_dir_classmethod_delegates(self):
        role = RoleSpec.from_agent_dir(FIXTURES, "sample_worker")
        assert role.name == "sample_worker"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/spawn/test_persona_loader.py::TestAssembleSystemPrompt tests/spawn/test_persona_loader.py::TestLoadAgent -v`
Expected: FAIL with import errors for `assemble_system_prompt`, `load_agent`, and `RoleSpec.from_agent_dir`.

- [ ] **Step 4: Implement `assemble_system_prompt` and `load_agent`**

Append to `orgos/spawn/persona_loader.py`:

```python
_LAYER_ORDER: tuple[str, ...] = FILE_TYPES  # soul → brain → habits → memory → heartbeat


def _render_layer_body(header: str, files: dict[str, PersonaFile]) -> str:
    parts = [f"=== LAYER: {header} ==="]
    for ft in _LAYER_ORDER:
        pf = files[ft]
        parts.append(f"--- {ft.upper()} ---")
        parts.append(pf.body.rstrip())
    return "\n\n".join(parts)


def assemble_system_prompt(
    principles: PersonaFile,
    worker_base: dict[str, PersonaFile] | None,
    specific: dict[str, PersonaFile],
) -> str:
    parts: list[str] = [
        "=== LAYER: PRINCIPLES ===",
        principles.body.rstrip(),
    ]
    if worker_base is not None:
        parts.append(_render_layer_body("WORKER_BASE", worker_base))
    parts.append(_render_layer_body("SPECIFIC", specific))
    return "\n\n".join(parts) + "\n"


def load_agent(agents_root: Path, agent_name: str) -> "RoleSpec":
    """Top-level entrypoint: load an agent's layers and return a RoleSpec."""
    # Deferred import to avoid a circular reference at module import time.
    from orgos.spawn.contracts import PermissionTier, RoleSpec

    if agent_name.startswith("_"):
        raise PersonaValidationError(
            f"agent_name must not start with '_' (reserved for layers): {agent_name!r}"
        )

    principles_path = agents_root / "_principles" / "principles.md"
    principles = load_persona_file(principles_path, "principles")

    specific_dir = agents_root / agent_name
    specific = load_layer(specific_dir, FILE_TYPES)
    soul_fm: SoulFrontmatter = specific["soul"].frontmatter  # type: ignore[assignment]

    worker_base: dict[str, PersonaFile] | None = None
    if soul_fm.is_worker:
        worker_base = load_layer(agents_root / "_worker_base", FILE_TYPES)

    system_prompt = assemble_system_prompt(principles, worker_base, specific)

    return RoleSpec(
        name=soul_fm.agent_name,
        description=soul_fm.description,
        tier=PermissionTier(soul_fm.tier),
        system_prompt=system_prompt,
        model=soul_fm.model,
        max_iter=soul_fm.max_iter,
        success_criteria=list(soul_fm.success_criteria),
    )
```

- [ ] **Step 5: Add `RoleSpec.from_agent_dir` in contracts.py**

Modify `orgos/spawn/contracts.py`: locate the `RoleSpec` class (around line 198) and add this classmethod after `effective_structured` (around line 274). Insert immediately before `_build_llm`:

```python
    @classmethod
    def from_agent_dir(cls, agents_root: Path, agent_name: str) -> "RoleSpec":
        """Build a RoleSpec from layered persona files.

        See docs/superpowers/plans/2026-07-08-persona-file-loader.md.
        """
        from orgos.spawn.persona_loader import load_agent
        return load_agent(agents_root, agent_name)
```

- [ ] **Step 6: Run all tests to verify they pass**

Run: `pytest tests/spawn/test_persona_loader.py -v`
Expected: PASS. Every test in the file green.

Then run the full spawn test suite to confirm nothing regressed:

Run: `pytest tests/spawn/ orgos/spawn/tests/ -v`
Expected: PASS. All existing tests still green.

- [ ] **Step 7: Commit**

```bash
git add orgos/spawn/persona_loader.py orgos/spawn/contracts.py \
        tests/spawn/test_persona_loader.py \
        tests/spawn/fixtures/agents/sample_po/
git commit -m "feat(spawn): RoleSpec.from_agent_dir loads layered persona files"
```

---

### Task 5: Golden integration test + module docstring polish

**Files:**
- Modify: `tests/spawn/test_persona_loader.py` (append `TestGolden`)
- Modify: `orgos/spawn/persona_loader.py` (top-level docstring cross-references)

**Interfaces:**
- Consumes: everything from Tasks 1-4.
- Produces: no new interfaces — a lockdown test that fails if the assembled prompt shape or the RoleSpec field mapping drifts.

- [ ] **Step 1: Write the golden test**

Append to `tests/spawn/test_persona_loader.py`:

```python
class TestGolden:
    """Snapshot the exact shape of an assembled worker RoleSpec so future
    changes to layer ordering, section headers, or field mapping surface as
    test failures rather than silently drifting the boot prompt."""

    def test_worker_role_shape_is_stable(self):
        role = RoleSpec.from_agent_dir(FIXTURES, "sample_worker")

        # Field mapping.
        assert role.name == "sample_worker"
        assert role.tier == PermissionTier.WORKER
        assert role.max_iter == 8
        assert role.description == "Sample delivery worker used in unit tests."
        assert role.model is None

        # Prompt structure (attention ordering matters, per spec §0.1).
        p = role.system_prompt
        i_principles = p.index("=== LAYER: PRINCIPLES ===")
        i_worker = p.index("=== LAYER: WORKER_BASE ===")
        i_specific = p.index("=== LAYER: SPECIFIC ===")
        assert i_principles < i_worker < i_specific

        # HEARTBEAT is the last section rendered inside the SPECIFIC layer.
        specific_block = p[i_specific:]
        assert specific_block.index("--- SOUL ---") < specific_block.index(
            "--- HEARTBEAT ---"
        )
        assert (
            specific_block.rindex("--- HEARTBEAT ---")
            == specific_block.rindex("--- ")
        ), "HEARTBEAT must be the last '--- X ---' section in the SPECIFIC block"
```

- [ ] **Step 2: Run the golden test to verify it passes**

Run: `pytest tests/spawn/test_persona_loader.py::TestGolden -v`
Expected: PASS.

- [ ] **Step 3: Add cross-references to the loader docstring**

Prepend to `orgos/spawn/persona_loader.py` module docstring so downstream readers find the spec and the plan:

```python
"""Loader for the three-layer persona markdown files.

Spec: docs/superpowers/specs/2026-07-07-autonomous-scrum-team-design.md
Plan: docs/superpowers/plans/2026-07-08-persona-file-loader.md
Roadmap: docs/superpowers/plans/2026-07-08-autonomous-scrum-team-roadmap.md

Layered inheritance:
  Layer 1 (principles)   → agents/_principles/principles.md
  Layer 2 (worker_base)  → agents/_worker_base/{soul,brain,habits,memory,heartbeat}.md
  Layer 3 (specific)     → agents/<agent_name>/{soul,brain,habits,memory,heartbeat}.md

Concatenation order in the assembled system_prompt is
  principles → worker_base(soul→brain→habits→memory→heartbeat)
             → specific(soul→brain→habits→memory→heartbeat)
so HEARTBEAT lands at the end of context (recency-attention window), per §0.1
of the spec.
"""
```

- [ ] **Step 4: Run full test suite one more time**

Run: `pytest tests/spawn/ orgos/spawn/tests/ tests/ -v`
Expected: PASS on everything the current main branch passes; no regressions.

- [ ] **Step 5: Final commit**

```bash
git add orgos/spawn/persona_loader.py tests/spawn/test_persona_loader.py
git commit -m "test(spawn): golden shape test + docstring cross-refs for persona loader"
```

---

## Self-Review

**Spec coverage:** every spec requirement for the loader lands in a task —
- Layered inheritance (principles → worker_base → specific): Tasks 3 + 4.
- Five files per agent (SOUL/BRAIN/HABITS/MEMORY/HEARTBEAT): Task 3 (`load_layer`) + Task 2 (single-file loader with per-type schema).
- Attention-aware concatenation order (HEARTBEAT last): Tasks 4 + 5.
- Frontmatter-driven `tier`/`model`/`max_iter`/`is_worker`: Tasks 1 + 4.
- Warn-only body-section validation: Task 2.
- Skip worker_base for non-workers (e.g. PO/SM): Task 4.
- `RoleSpec.from_agent_dir` as the single downstream entrypoint: Task 4.

Not in this plan (deferred, correctly): agent-directory discovery for the scheduler (Plan 4), HEARTBEAT/MEMORY writes at end-of-sprint (Plan 4), tools/mcp attachment (still done at spawn call site by Plans 2-4).

**Placeholder scan:** no TODOs; every step contains the actual code or command; sample fixture content is realistic enough to satisfy the section validators.

**Type consistency:** `PersonaFile.frontmatter` is `BaseModel` at the dataclass level; concrete type is `SoulFrontmatter` for `soul` files and `SimpleFrontmatter` for all others, resolved through `_FRONTMATTER_MODELS`. `load_agent` uses `SoulFrontmatter` typing via the runtime dict entry; the `# type: ignore` in Task 4 Step 4 documents the narrow at that call site. `FILE_TYPES` is the same tuple used for `load_layer` (Task 3) and `_LAYER_ORDER` (Task 4).

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-08-persona-file-loader.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
