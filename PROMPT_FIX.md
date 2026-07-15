# Agent Prompt Fix — Task Brief + Persona Tuning

## Problem

The pull-based sprint model spawns delivery workers (Architect, Test, DevSecOps) independently via `orgos/agile/sprint.py → run_pull_sprint()`. Each worker gets a persona (5 markdown files loaded by `orgos/spawn/persona_loader.py`) and a task brief (constructed by `_brief_for_pull_worker()`).

**Symptom:** Agents complete sprints (status=completed) but produce zero code changes. Audit trail shows 30+ read-only BashTool calls (type, dir, git log) and zero write calls (echo >, git add, git commit). The `git diff HEAD~1` shows only the base commit's diff, never the agent's work.

**Root cause:** The task brief is too vague for DeepSeek. It says "FILE TO MODIFY: orgos/agile/flow_metric.py" but the agent interprets this as a documentation task and explores without writing. The persona BRAIN file (`agents/_worker_base/BRAIN.md`) has codebase navigation and coding conventions but the agent burns its budget on exploration.

## What the task brief needs to change

### Current brief (from `sprint.py` line ~696):

```
FILE TO MODIFY: orgos/agile/flow_metric.py — read it with type, add docstring...
TASK: Add docstring to takt_time in flow_metric.py
EXACT SEQUENCE:
1. Read the target file: type orgos\agile\thefile.py
2. Modify it: echo ... > orgos\agile\thefile.py
...
```

### What it should be:

The brief should include the EXISTING file content and the DESIRED file content, so the agent can just run `echo` to write the modified version. No exploration needed. Example:

```
TASK: Add docstring to takt_time() in orgos/agile/flow_metric.py

EXISTING CODE (read with: type orgos\agile\flow_metric.py):
```python
def takt_time(duration_seconds: float, n_issues: int) -> float:
    if n_issues <= 0:
        return 0.0
    return duration_seconds / max(n_issues, 1)
```

MODIFIED CODE (write with: echo ... > orgos\agile\flow_metric.py):
```python
def takt_time(duration_seconds: float, n_issues: int) -> float:
    """Average calendar time per issue in seconds.

    Args:
        duration_seconds: Total sprint duration.
        n_issues: Number of issues processed.

    Returns:
        float: Seconds per issue, or 0.0 if n_issues <= 0.
    """
    if n_issues <= 0:
        return 0.0
    return duration_seconds / max(n_issues, 1)
```

STEPS:
1. Write the modified file: echo <content> > orgos\agile\flow_metric.py
2. Run tests: pytest tests/agile/test_flow_metric.py -v
3. git add -A && git -c user.name=o -c user.email=o@o commit -m "feat: docstring"
4. git rev-parse HEAD
5. Output JSON envelope with commit_sha
```

This eliminates exploration — the agent just echoes pre-resolved content.

## Where to make the change

File: `orgos/agile/sprint.py`
Function: `_brief_for_pull_worker()` (around line 693)
Variable: `brief.objective` — this is the task brief text sent to the worker.

## Persona files that matter

The assembled prompt order is:
1. `agents/_principles/principles.md` — 3KB (anti-waterfall anchor + delivery philosophy + identity + habits)
2. `agents/_worker_base/soul.md` — 2KB (worker identity, anti-waterfall anchor)
3. `agents/_worker_base/brain.md` — 5KB (codebase map, decision framework, common commands, envelope format)
4. `agents/_worker_base/habits.md` — 1KB (write first, verify before handoff)
5. `agents/_worker_base/memory.md` — 1KB (foundational knowledge)
6. `agents/_worker_base/heartbeat.md` — 2KB (wake-up instructions, sandbox workflow)
7. `agents/architect/soul.md` — 2KB (architect identity, values, stance)
8. `agents/architect/brain.md` — 2KB (decision framework, domain knowledge)
9. `agents/architect/habits.md` — 1KB (write first, verify before handoff)
10. `agents/architect/memory.md` — 1KB (foundational principles)
11. `agents/architect/heartbeat.md` — 1KB (architect wake-up)
12. Task brief — variable (from `_brief_for_pull_worker`)

Total persona prompt: ~13K chars per worker. HEARTBEAT sits last for recency attention.

## What NOT to change

- The persona file structure (5 files, YAML frontmatter, 3-layer inheritance)
- The `persona_loader.py` or `persona_schema.py` — they work correctly
- The `run_pull_sprint()` architecture — agents spawn independently and that's correct
- The quality evaluator or paired benchmark — they work correctly

## How to test

```bash
py -3.12 -c "
from pathlib import Path
from orgos.agile.sprint import run_pull_sprint
issue = {'issue_id':'TEST','title':'Write hello.txt','body':'Write hello.txt with hello world'}
s = run_pull_sprint(Path('.'), issue, model='deepseek/deepseek-chat', mock_pr=True, run_budget_tokens=1_500_000)
import subprocess
git = subprocess.run(['git','log','--oneline','-3'], cwd=f'.sprints/{s.id}', capture_output=True, text=True)
print(git.stdout)
"
```

Success means you see a new commit ON TOP of `d0d2e1b` (not just `d0d2e1b` alone).
