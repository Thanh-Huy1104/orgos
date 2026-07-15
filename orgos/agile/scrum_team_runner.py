"""Scrum team runner — N interchangeable full-stack developers with shared wiki.

Contrast:
  - Waterfall team (run_pull_sprint): PO -> Architect -> Test -> DevSecOps -> Release.
    Five specialized roles per story. Sequential handoff. Gates between phases.
  - Scrum team (this module): N identical full-stack developers.
    Any free worker takes the story. Whole job done by one worker.
    All workers share the wiki (compounding memory).
  - Solo (solo_baseline): 1 full-stack developer, no wiki.

v1 semantics for a single-issue run:
  - N=1: one worker does the story. Identical to solo BUT with wiki access.
  - N>1: worker 1 tries; if it fails to produce a commit or emit an envelope,
    worker 2 tries; and so on. Simulates "next free agent picks up."
    v1 is sequential-with-fallback, not parallel.

For a multi-issue campaign (future), workers pull from a shared inbox and
run in parallel — but that's Plan 3 dispatcher work, not this module.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

from orgos.agile.benchmark import BenchmarkRun, diff_stats, pytest_stats
from orgos.agile.pricing import cost_usd
from orgos.agile.sprint import (
    Sprint, _extract_json_objects, _get_wiki_mcp, _log_sprint_to_wiki,
    _make_worktree, _new_sprint_id, write_snapshot,
)
from orgos.spawn import PermissionTier, RoleSpec, TaskBrief, spawn
from orgos.tools.bash import BashTool


_FULLSTACK_SYSTEM_PROMPT = """You are a full-stack developer on a self-organizing Scrum team.

You handle a whole story yourself: scope, code, tests, commit, wiki log.
You have BashTool for code + git, and wiki tools (wiki_read, wiki_grep, wiki_write)
for the shared team knowledge base at wiki/.

Your team stays coherent across stories because everyone reads and writes wiki/DECISIONS.md.
Before you start, wiki_read DECISIONS.md — if a prior story established a convention
(naming style, unit, error policy, API shape) that applies to your work, FOLLOW IT.

Bias hard toward action: your first BashTool call writes a file, not explores.
After commit, wiki_write to DECISIONS.md — record decisions substantive enough that
the next teammate can stay consistent, or a one-line changelog if nothing new.
"""


_FULLSTACK_BRIEF_TEMPLATE = """You are a Scrum developer. You pulled this story from the inbox. Do the whole job.

STORY:
  issue_id: {issue_id}
  title: {title}
  description: {body}

WORKTREE: {worktree}  (branch {branch})
Shell is UNIX bash.

DO THIS IN ORDER — no exploration, no explanation:

0. WIKI READ (up to two calls): use `wiki_read` on `DECISIONS.md` first.
   If it returns "file not found", continue. If it exists, skim for any
   convention block relevant to your story (naming, unit, field order,
   error-handling policy, API shape). If you see something relevant, FOLLOW
   IT EXACTLY when you write code. Also use `wiki_grep` if you need to
   locate something. Max two wiki calls at this step.

1. Write the file(s) the story asks for using heredoc:
     cat > path/to/target <<'EOF'
     <full contents>
     EOF

2. If the story implies tests, write them too, then run:
     pytest <path> -v

3. Commit:
     git add -A
     git -c user.name=orgos-scrum -c user.email=scrum@orgos.local commit -m "feat: {title}"

4. git rev-parse HEAD

5. WIKI DECISION (one call): use `wiki_write` mode="append" on `DECISIONS.md`.
   If your work established a convention that a FUTURE teammate would need
   to stay consistent (naming, unit, field order, error policy, API shape),
   record it as a full block:

     ## <topic> — sprint {issue_id}
     - <decision>: <the exact choice, as it appears in the code>
     - Rationale: <why this over the alternative>
     - Applies to: <what future code should follow this>

   If your work established no new convention, append a one-line changelog:
     - <today ISO date> sprint {issue_id}: {title} — <one-line summary>

6. Output ONLY this envelope JSON. No prose, no markdown fences.

{{
  "role": "scrum_worker",
  "status": "completed",
  "summary": "<what you did>",
  "success_criteria_met": true,
  "requires_human_approval": false,
  "payload": {{
    "commit_sha": "<sha from step 4>",
    "files_touched": ["<paths>"],
    "test_command": "<pytest command or empty>",
    "test_output": "<tail>",
    "test_passed": true
  }}
}}

HARD RULES:
  - First BashTool call writes a file, not explores.
  - Follow conventions from wiki/DECISIONS.md when applicable.
  - If you cannot infer the target path, write NOTES.md and commit that.
"""


def _fullstack_role(model: str, worker_idx: int) -> RoleSpec:
    return RoleSpec(
        name=f"FullStack_Dev_{worker_idx}",
        description="Full-stack developer on a self-organizing Scrum team.",
        tier=PermissionTier.WORKER,
        system_prompt=_FULLSTACK_SYSTEM_PROMPT,
        model=model,
        max_iter=25,
        success_criteria=[
            "Wrote code addressing the story.",
            "Produced a commit with a valid SHA.",
            "Consulted wiki/DECISIONS.md and wrote back to it.",
            "Emitted the envelope JSON.",
        ],
        structured_output=False,
    )


def _worker_produced_commit(worktree: Path, baseline_sha: str) -> bool:
    current = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(worktree), capture_output=True, text=True, timeout=10,
    ).stdout.strip()
    return bool(current) and current != baseline_sha


def run_scrum(
    repo_path: Path,
    issue: dict,
    *,
    model: str,
    n_workers: int = 3,
    run_budget_tokens: int = 1_500_000,
) -> tuple[Sprint, BenchmarkRun]:
    """Run one issue through the Scrum team. Returns (Sprint, BenchmarkRun).

    Sequential-with-fallback: worker 1 tries; if it fails to commit, worker 2
    tries in the SAME worktree; and so on. Wiki is shared across all workers.
    """
    from datetime import datetime, timezone

    sprint_id = _new_sprint_id()
    started_at = datetime.now(timezone.utc).isoformat()
    branch = f"scrum/{sprint_id}"
    worktree = _make_worktree(repo_path, sprint_id, branch)
    repo = Path(repo_path)

    baseline_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(worktree), capture_output=True, text=True, timeout=10,
    ).stdout.strip()

    write_snapshot(
        Sprint(id=sprint_id, started_at=started_at, repo_path=repo,
               worktree_path=worktree, branch=branch, picked_issue=issue,
               envelopes={}, status="in_progress", baseline_sha=baseline_sha),
        backlog=[], heuristics=[],
    )

    wiki = _get_wiki_mcp()
    per_worker_budget = max(300_000, run_budget_tokens // max(1, n_workers))
    envelopes_by_worker: list[dict] = []
    total_in = 0
    total_out = 0
    raw_output = ""
    error = ""
    winner_idx: int | None = None

    t0 = time.time()

    for idx in range(1, n_workers + 1):
        # If a prior worker already produced a commit, we're done.
        if winner_idx is not None:
            break

        role = _fullstack_role(model, idx)
        role.tools = [BashTool(default_working_dir=str(worktree))]
        role.mcp_servers = [wiki]

        brief = TaskBrief(
            objective=_FULLSTACK_BRIEF_TEMPLATE.format(
                issue_id=issue.get("issue_id", "?"),
                title=issue.get("title", ""),
                body=issue.get("body", ""),
                worktree=str(worktree),
                branch=branch,
            ),
            expected_output=f"A HandoffEnvelope JSON from FullStack_Dev_{idx}.",
            success_criteria=[f"Worker {idx} completed the story."],
        )

        try:
            result = spawn(role, brief, run_budget_tokens=per_worker_budget)
            if result.token_usage:
                total_in += result.token_usage.get("prompt_tokens", 0)
                total_out += result.token_usage.get("completion_tokens", 0)
            envelope: dict = {}
            for tout in result.tasks_output:
                raw = getattr(tout, "raw", "") or ""
                raw_output = raw_output + raw
                for blob in _extract_json_objects(raw):
                    try:
                        data = json.loads(blob)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(data, dict) and data.get("role"):
                        envelope = {"worker_idx": idx, **data}
                        break
            if envelope:
                envelopes_by_worker.append(envelope)
            if _worker_produced_commit(worktree, baseline_sha):
                winner_idx = idx
        except Exception as e:
            error = f"worker {idx}: {type(e).__name__}: {e}"
            envelopes_by_worker.append({
                "worker_idx": idx, "role": f"scrum_worker_{idx}",
                "status": "failed", "summary": error,
            })

    wall = time.time() - t0

    files, added, removed, diff_text = diff_stats(worktree, baseline_sha)
    commit_produced = winner_idx is not None
    commit_sha = ""
    if commit_produced:
        commit_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(worktree), capture_output=True, text=True, timeout=10,
        ).stdout.strip()

    # Parse pytest counts from the WINNING worker's envelope
    test_output = ""
    if envelopes_by_worker:
        winner_env = envelopes_by_worker[-1]
        payload = winner_env.get("payload", {}) or {}
        test_output = payload.get("test_output", "") or ""
    tests_run, tests_passed, tests_failed = pytest_stats(test_output)

    # Compaction — same as run_pull_sprint
    try:
        sprint_stub = Sprint(
            id=sprint_id, started_at=started_at, repo_path=repo,
            worktree_path=worktree, branch=branch, picked_issue=issue,
            envelopes={"scrum": {"workers": envelopes_by_worker,
                                  "winner_idx": winner_idx}},
            status="completed" if commit_produced else "failed",
        )
        _log_sprint_to_wiki(sprint_id, issue, sprint_stub.envelopes,
                            sprint_stub.status)
    except Exception:
        pass

    # Quality evaluator on the diff
    quality_ac = quality_code = quality_tests = None
    quality_summary = ""
    try:
        from orgos.agile.evaluator import QualityEvaluator
        evaluator = QualityEvaluator(model=model)
        sprint_stub = Sprint(
            id=sprint_id, started_at=started_at, repo_path=repo,
            worktree_path=worktree, branch=branch, picked_issue=issue,
            envelopes={
                "scrum": {"workers": envelopes_by_worker, "winner_idx": winner_idx}
            },
            status="completed" if commit_produced else "failed",
            spawn_result=None,
        )
        q = evaluator.evaluate(sprint_stub, issue)
        scores = q.llm_scores or {}
        quality_ac = scores.get("ac_compliance")
        quality_code = scores.get("code_quality")
        quality_tests = scores.get("test_relevance")
        quality_summary = q.llm_summary or ""
    except Exception as e:
        quality_summary = f"evaluator error: {e}"

    sprint = Sprint(
        id=sprint_id, started_at=started_at, repo_path=repo,
        worktree_path=worktree, branch=branch, picked_issue=issue,
        envelopes={"scrum": {"workers": envelopes_by_worker,
                              "winner_idx": winner_idx}},
        status="completed" if commit_produced else "failed",
        spawn_result=None,
        baseline_sha=baseline_sha,
        total_tokens_input=total_in, total_tokens_output=total_out,
    )

    run = BenchmarkRun(
        issue_id=issue.get("issue_id", "?"),
        approach="scrum",
        model=model,
        started_at=started_at,
        wall_seconds=round(wall, 2),
        tokens_input=total_in,
        tokens_output=total_out,
        tokens_total=total_in + total_out,
        cost_usd=round(cost_usd(model, total_in, total_out), 6),
        commit_produced=commit_produced,
        commit_sha=commit_sha,
        files_changed=files,
        loc_added=added,
        loc_removed=removed,
        tests_run=tests_run,
        tests_passed=tests_passed,
        tests_failed=tests_failed,
        quality_ac=quality_ac,
        quality_code=quality_code,
        quality_tests=quality_tests,
        quality_summary=quality_summary,
        diff_text=diff_text,
        envelope_trail=envelopes_by_worker,
        raw_output=raw_output[-4000:],
        error=error,
    )
    return sprint, run
