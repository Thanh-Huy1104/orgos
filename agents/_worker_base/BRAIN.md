---
version: 1.0.0
layer: worker_base
---

# BRAIN — Worker (shared base)

This file defines reasoning and domain knowledge shared by all delivery workers.

## Codebase Map — Where everything lives

You are working inside a git worktree that mirrors the orgos repo. Use BashTool to explore.

**Key directories:**
```
orgos/agile/        — sprint.py, rubric.py, board.py, flow_metric.py, compaction.py, conductor.py, quality_rubric.py, evaluator.py, envelopes.py, paired_run.py, mutations.py, replay.py
orgos/spawn/        — contracts.py, persona_loader.py, persona_schema.py, engine.py
orgos/mcps/         — wiki_mcp.py, internet_mcp.py (MCP servers)
orgos/tools/        — bash.py, mock_pr_tool.py, github_issue_tool.py, github_pr_tool.py
orgos/subagents/    — scrum_team.py, engineering_team_legacy.py
tests/agile/        — test_board.py, test_rubric.py, test_compaction.py, test_conductor.py, test_flow_metric.py, test_quality_rubric.py
tests/mcps/         — test_wiki_mcp.py
tests/spawn/        — test_persona_loader.py
```

**Path convention:** `orgos/agile/board.py` → tests are at `tests/agile/test_board.py`. Module path and test path mirror each other.

## Decision Framework

**Step-by-step process:**
1. Read the task brief. Identify which file(s) needs to change.
2. Use BashTool to explore the target file: `type orgos\agile\board.py` (Windows) or `cat orgos/agile/board.py` (Linux).
3. Write the change. Use `echo` to append, or explore with `dir` first.
4. Run the relevant test suite: `pytest tests/agile/test_board.py -v`.
5. If tests pass, commit: `git add -A && git -c user.name=orgos-worker -c user.email=worker@orgos.local commit -m "message"`.
6. Get the commit SHA: `git rev-parse HEAD`.
7. Produce a HandoffEnvelope JSON.

**Before writing any code, answer:**
- Which specific file needs to change? (use `dir` to confirm it exists)
- What does the current code look like? (use `type` to read it)
- What test file covers this area? (run `dir tests\` to find it)

## Common operations (Windows)

```bash
# Explore codebase
dir                                # list files in worktree root
dir orgos\agile                    # list agile module files
dir tests\agile                    # list test files

# Read files
type orgos\agile\board.py          # read a source file
type tests\agile\test_board.py     # read a test file

# Run tests
pytest tests/agile/test_board.py -v          # run specific test file
pytest tests/agile/test_board.py::TestCheckReadyGate -v  # run specific test class

# Git workflow
git status                                    # check what changed
git add -A                                    # stage all changes
git -c user.name=orgos-worker -c user.email=worker@orgos.local commit -m "feat: add type hints to check_ready_gate"
git rev-parse HEAD                            # get the commit SHA
git diff HEAD~1                               # see what changed
```

## Coding conventions

- All Python files start with `from __future__ import annotations` and a docstring.
- Functions have type hints. Use `-> None` for void functions.
- Test classes follow pattern: `class TestFunctionName:`.
- Tests use `tmp_path` for temp dirs, `monkeypatch.setenv` for env vars.
- Dataclasses use `from dataclasses import dataclass, field`.
- Docstrings are Google-style with brief description + Args/Returns.
- Keep diffs under 400 lines. Prefer minimal changes.

## Envelope format

After completing your work, output ONLY this JSON (no markdown, no prose):

```json
{
  "role": "architect",
  "status": "completed",
  "summary": "Added type hints to check_ready_gate in board.py",
  "success_criteria_met": true,
  "requires_human_approval": false,
  "payload": {
    "commit_sha": "abc123def...",
    "files_touched": ["orgos/agile/board.py"],
    "test_command": "pytest tests/agile/test_board.py -v",
    "test_output": "... all tests passed ...",
    "test_passed": true
  }
}
```

Status must be one of: completed, needs_revision, blocked, failed.
The payload.commit_sha must come from `git rev-parse HEAD`.
