# agents/ — persona protocol files

This directory holds the markdown protocol files that define each agent on the autonomous scrum team. The loader (`orgos/spawn/persona_loader.py`) reads them and produces a validated `RoleSpec`.

## Structure

```
agents/
  _principles/               ← Layer 1: universal, inherited by every agent
    principles.md
  _worker_base/              ← Layer 2: shared by delivery workers only
    soul.md
    brain.md
    habits.md
    memory.md
    heartbeat.md
  po/                        ← Layer 3: per-agent
    soul.md
    brain.md
    habits.md
    memory.md
    heartbeat.md
  scrum_master/
    (five files)
  architect/                 ← delivery worker (inherits _worker_base)
    (five files)
  test/                      ← delivery worker
    (five files)
  devsecops/                 ← delivery worker
    (five files)
```

Underscore-prefixed directories (`_principles`, `_worker_base`) are inherited layers, not agents — the loader refuses to load them as agents.

## Usage

```python
from pathlib import Path
from orgos.spawn.contracts import RoleSpec

architect = RoleSpec.from_agent_dir(Path("agents"), "architect")
```

The loader:
- Reads `_principles/principles.md` (Layer 1).
- If the agent's `soul.md` frontmatter has `is_worker: true`, reads all five files in `_worker_base/` (Layer 2).
- Reads all five files in the agent's own directory (Layer 3).
- Concatenates layers in order 1 → 2 → 3 with `--- SECTION ---` markers between files. HEARTBEAT sits at the end of the assembled prompt (recency-attention window).
- Extracts `tier`, `description`, `model`, `max_iter`, `success_criteria`, `is_worker` from the specific SOUL frontmatter.

## File contract

Every file has YAML frontmatter and a markdown body.

**Frontmatter** — required fields per file:
- `version` — semver string.
- `layer` — one of `"principles"`, `"worker_base"`, `"specific"`.

SOUL adds: `agent_name`, `tier` (`worker|validator|publisher|orchestrator`), optionally `description`, `model`, `max_iter`, `is_worker`, `success_criteria`.

**Body** — top-level `## Section` headers per file type:
- soul: Identity, Values, Stance, Optimizes For
- brain: Decision Framework, Domain Knowledge, Reasoning Patterns
- habits: Habits (with trigger → response → outcome + anti-patterns entries)
- memory: Foundational Principles, Sprint History, Recurring Patterns, Key Decisions
- heartbeat: Current Task, Recent Session Summary, Next Actions
- principles: Delivery Philosophy, Universal Identity Beliefs, Universal Habits

Missing frontmatter fields raise `PersonaValidationError`. Missing body sections log a warning but do not fail load.

## Templates

The fastest way to start authoring is to copy an existing valid template from the test fixtures:

```bash
# Copy the sample delivery-worker as a starting point for Architect / Test / DevSecOps:
cp -r tests/spawn/fixtures/agents/sample_worker agents/architect
cp -r tests/spawn/fixtures/agents/sample_worker agents/test
cp -r tests/spawn/fixtures/agents/sample_worker agents/devsecops

# Copy the sample non-worker as a starting point for PO / Scrum Master:
cp -r tests/spawn/fixtures/agents/sample_po agents/po
cp -r tests/spawn/fixtures/agents/sample_po agents/scrum_master

# Copy the shared layers:
cp tests/spawn/fixtures/agents/_principles/principles.md agents/_principles/
cp tests/spawn/fixtures/agents/_worker_base/*.md agents/_worker_base/
```

Then edit `soul.md` in each directory to fix `agent_name`, `description`, and `success_criteria`, and flesh out the body sections with real content.

## Notes for authors

- **HEARTBEAT and MEMORY are instance files.** They will be rewritten by the agent itself at end-of-sprint (per Plan 4). Author them once at bootstrap; after that they're live state.
- **The Worker Base is shared.** Editing `_worker_base/brain.md` changes the reasoning of Architect, Test, AND DevSecOps at once. That's intentional — it's the point of inheritance — but review those changes carefully.
- **Persona files are trust-boundary content.** The loader treats them as any user-supplied prompt: they're compiled into the system prompt and inherit the same prompt-injection posture as any other input.
