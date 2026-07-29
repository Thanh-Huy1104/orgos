---
version: 1.0.0
layer: worker_base
---

# BRAIN — Worker (shared base)

This file defines reasoning and domain knowledge shared by all delivery workers.

## Codebase Map — Where everything lives

You are working inside a git worktree of the TARGET repository. When the target is orgos itself, the map below applies; for any other repo, ignore the map — explore with BashTool and follow the brief's environment hints (language, install command, test command).

**Key directories:**
```
orgos/agile/        — sprint.py, rubric.py, board.py, flow_metric.py, compaction.py, conductor.py, quality_rubric.py, evaluator.py, envelopes.py, paired_run.py, mutations.py, replay.py
(governance engine — contracts, persona loader, spawn() — lives at `orgos/spawn/`; import via `orgos.spawn.governance`, never modify it)
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
1. Read the task brief. Identify which file(s) need to change.
2. Write the change directly — the brief usually tells you the target file, so don't waste a turn exploring first.
3. If a heredoc write, use `cat > path/to/file <<'EOF' ... EOF`.
4. Run the repo's test command from the brief's environment hints (e.g. `pytest tests/x/test_y.py -v`, `npm test`, `go test ./...`).
5. If tests pass, commit: `git add -A && git -c user.name=orgos-worker -c user.email=worker@orgos.local commit -m "message"`.
6. Get the commit SHA: `git rev-parse HEAD`.
7. Produce a HandoffEnvelope JSON.

**Bias:** write first, explore only if the brief is genuinely ambiguous. Exploration burns your turn budget without producing output.

## Common operations (UNIX bash)

The worktree shell is bash on Mac or Linux. Use unix commands — do NOT use `type`, `dir`, or Windows-style `echo >`.

```bash
# Explore (only if needed)
ls                                 # list files in worktree root
ls orgos/agile                     # list agile module files
cat orgos/agile/board.py           # read a source file

# Write a file (heredoc — quoted 'EOF' prevents $ expansion)
cat > orgos/agile/board.py <<'EOF'
<full file contents here>
EOF

# Append to a file
cat >> tests/agile/test_board.py <<'EOF'
<content to append>
EOF

# Run tests
pytest tests/agile/test_board.py -v
pytest tests/agile/test_board.py::TestCheckReadyGate -v

# Git workflow
git status
git add -A
git -c user.name=orgos-worker -c user.email=worker@orgos.local commit -m "feat: add type hints to check_ready_gate"
git rev-parse HEAD
git diff HEAD~1
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
