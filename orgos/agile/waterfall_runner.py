"""Waterfall comparison runner — same goal, same decomposed stories, no ceremony.

The scrum dispatcher decomposes the goal, refines with poker, and pulls
stories by type. The waterfall runner is given the SAME decomposed stories
and runs each one through the sequential 5-role pipeline
(PO → Architect → Test → DevSecOps → Release), no board, no refinement.

Both share the persistent worktree machinery — commits accumulate on the
team's branch across all stories.

The comparison is *not* fair on PO scoping (both use the same PO output).
It's a comparison of EXECUTION model: sequential handoff pipeline vs
pull-based specialization + shared wiki.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from orgos.agile.board_store import BoardStore
from orgos.agile.goal_decomposer import decompose_goal
from orgos.agile.live_events import EventEmitter
from orgos.agile.sprint import _extract_json_objects, _get_wiki_mcp
from orgos.agile.team_workspace import TeamWorkspace
from orgos.spawn.governance import TaskBrief, spawn
from orgos.subagents import (
    architect_role, devsecops_role, po_role, release_manager_role, test_role,
)
from orgos.tools.bash import BashTool
from orgos.tools.mock_pr_tool import MockPRTool


@dataclass
class WorkResult:
    story_id: str
    role: str
    status: str
    commit_sha: str = ""
    diff_summary: str = ""
    envelope: dict = field(default_factory=dict)
    tokens_input: int = 0
    tokens_output: int = 0
    wall_seconds: float = 0.0
    error: str = ""


@dataclass
class DispatchResult:
    team_id: str
    goal: str
    started_at: str
    ended_at: str
    reason_stopped: str
    stories_created: int
    stories_done: int
    stories_blocked: int
    total_tokens_input: int = 0
    total_tokens_output: int = 0
    per_story_results: list["WorkResult"] = field(default_factory=list)
    pr_url: str = ""


_WATERFALL_ARCH_BRIEF = """You are the Architect on a WATERFALL team. The story below was handed to you by the PO.

STORY
  issue_id: {issue_id}
  title:    {title}
  type:     {type}

BODY:
{body}

WORKTREE: {worktree}  (branch {branch})
UNIX shell. Use `cat`, heredocs, `pytest`, `git`.

STEPS:
1. Write the code the story asks for using heredoc.
2. If tests are implied, write + run them: pytest <path> -v
3. Commit:
     git add -A
     git -c user.name=orgos-arch -c user.email=arch@orgos.local commit -m "{type}: {title}"
4. git rev-parse HEAD
5. Output ONLY this envelope JSON:

{{
  "role": "architect",
  "status": "completed",
  "summary": "<what you did>",
  "success_criteria_met": true,
  "requires_human_approval": false,
  "payload": {{
    "commit_sha": "<sha>",
    "files_touched": ["<paths>"],
    "test_command": "<pytest cmd or empty>",
    "test_output": "<tail>",
    "test_passed": true
  }}
}}

RULES:
  - First bash call is productive (heredoc), not exploration.
  - No wiki tools available in waterfall mode.
  - Do not modify governance files (orgos/spawn/**).
"""


_WATERFALL_TEST_BRIEF = """You are Test on a WATERFALL team. Verify the Architect's commit for this story.

STORY
  issue_id: {issue_id}
  title:    {title}

WORKTREE: {worktree}  (branch {branch})

STEPS:
1. `git log --oneline -3`
2. `git diff HEAD~1 --stat`
3. Run any pytest touched by the last commit.
4. Emit envelope:

{{
  "role": "test",
  "status": "completed",
  "summary": "<verification result>",
  "success_criteria_met": true,
  "requires_human_approval": false,
  "payload": {{
    "verified_commit_sha": "<sha>",
    "test_command": "<cmd or empty>",
    "test_output": "<tail>",
    "test_passed": true
  }}
}}

RULES: Read-only. Do not modify files.
"""


_WATERFALL_SEC_BRIEF = """You are DevSecOps on a WATERFALL team. Review the Architect's commit for the story.

STORY
  issue_id: {issue_id}
  title:    {title}

WORKTREE: {worktree}  (branch {branch})

STEPS:
1. `git diff HEAD~1` — read the diff.
2. Confirm: no secrets, diff < 400 LOC, no writes to `.env` or `orgos/spawn/`.
3. Emit envelope:

{{
  "role": "devsecops",
  "status": "completed",
  "summary": "diff clean" | "concerns: <list>",
  "success_criteria_met": true,
  "requires_human_approval": false,
  "payload": {{
    "commit_sha": "<sha>",
    "diff_lines": <int>,
    "secrets_found": false,
    "governance_touched": false
  }}
}}

RULES: Read-only.
"""


@dataclass
class WaterfallResult:
    story_id: str
    status: str
    commit_sha: str = ""
    diff_summary: str = ""
    envelopes: dict = field(default_factory=dict)
    tokens_input: int = 0
    tokens_output: int = 0
    wall_seconds: float = 0.0
    error: str = ""


def _spawn_one(role, brief, budget=1_200_000):
    """Spawn wrapper that returns (envelope, prompt_tokens, completion_tokens)."""
    result = spawn(role, brief, run_budget_tokens=budget)
    tu = result.token_usage or {}
    tin = tu.get("prompt_tokens", 0)
    tout = tu.get("completion_tokens", 0)
    env: dict = {}
    for to in result.tasks_output:
        raw = getattr(to, "raw", "") or ""
        for blob in _extract_json_objects(raw):
            try:
                data = json.loads(blob)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and data.get("role"):
                env = data
                break
    return env, tin, tout


def _run_one_story_waterfall(
    story_dict: dict, workspace: TeamWorkspace, model: str,
) -> WaterfallResult:
    """Run one story through Architect → Test → DevSecOps → Release."""
    t0 = time.time()
    baseline_sha = workspace.current_head()
    ttl_in = 0
    ttl_out = 0
    envs: dict = {}

    # Architect
    arch = architect_role(
        model=model,
        extra_tools=[BashTool(default_working_dir=str(workspace.worktree))],
    )
    # Wiki tools stay enabled: real waterfall teams keep shared architecture
    # docs. Zeroing mcp_servers was starving the architect of cross-story
    # context that scrum's runtime gives for free.
    arch_brief = TaskBrief(
        objective=_WATERFALL_ARCH_BRIEF.format(
            issue_id=story_dict["issue_id"],
            title=story_dict["title"],
            type=story_dict["type"],
            body=story_dict["body"] or "(no body)",
            worktree=str(workspace.worktree),
            branch=workspace.manifest().branch,
        ),
        expected_output="Architect HandoffEnvelope JSON.",
        success_criteria=["Commit created."],
    )
    # One retry on no_commit — real bug-fix loop. Without this a single flaky
    # LLM response blocks a story that would land on retry.
    env = None
    committed = False
    head = workspace.current_head()
    for attempt in range(2):
        try:
            env, ti, to = _spawn_one(arch, arch_brief)
            ttl_in += ti; ttl_out += to
            envs[f"architect{'_retry' if attempt else ''}"] = env
        except Exception as e:
            if attempt == 1:
                return WaterfallResult(
                    story_id=story_dict["issue_id"], status="failed",
                    error=f"architect: {type(e).__name__}: {e}",
                    wall_seconds=round(time.time() - t0, 2),
                )
            continue
        head = workspace.current_head()
        committed = head and head != baseline_sha
        if committed:
            break
    if not committed:
        return WaterfallResult(
            story_id=story_dict["issue_id"], status="no_commit",
            envelopes=envs, tokens_input=ttl_in, tokens_output=ttl_out,
            wall_seconds=round(time.time() - t0, 2),
        )

    # Test
    tst = test_role(
        model=model,
        extra_tools=[BashTool(default_working_dir=str(workspace.worktree))],
    )
    tst_brief = TaskBrief(
        objective=_WATERFALL_TEST_BRIEF.format(
            issue_id=story_dict["issue_id"],
            title=story_dict["title"],
            worktree=str(workspace.worktree),
            branch=workspace.manifest().branch,
        ),
        expected_output="Test HandoffEnvelope JSON.",
        success_criteria=["Verification emitted."],
    )
    try:
        env, ti, to = _spawn_one(tst, tst_brief, budget=600_000)
        ttl_in += ti; ttl_out += to
        envs["test"] = env
    except Exception:
        pass

    # DevSecOps
    sec = devsecops_role(
        model=model,
        extra_tools=[BashTool(default_working_dir=str(workspace.worktree))],
    )
    sec_brief = TaskBrief(
        objective=_WATERFALL_SEC_BRIEF.format(
            issue_id=story_dict["issue_id"],
            title=story_dict["title"],
            worktree=str(workspace.worktree),
            branch=workspace.manifest().branch,
        ),
        expected_output="DevSecOps HandoffEnvelope JSON.",
        success_criteria=["Review emitted."],
    )
    try:
        env, ti, to = _spawn_one(sec, sec_brief, budget=500_000)
        ttl_in += ti; ttl_out += to
        envs["devsecops"] = env
    except Exception:
        pass

    diff_stat = workspace.diff_since(baseline_sha, stat_only=True)
    return WaterfallResult(
        story_id=story_dict["issue_id"],
        status="committed",
        commit_sha=head,
        diff_summary=diff_stat[:2000],
        envelopes=envs,
        tokens_input=ttl_in, tokens_output=ttl_out,
        wall_seconds=round(time.time() - t0, 2),
    )


def run_waterfall_campaign(
    *,
    workspace: TeamWorkspace,
    goal: str,
    model: str,
    max_stories_worked: int = 20,
    max_wall_seconds: int = 3600,
    prewritten_stories: list[dict] | None = None,
) -> DispatchResult:
    """Waterfall equivalent of Dispatcher.run_campaign.

    Same PO decomposition. No refinement, no poker. Each story sequentially
    handed to the pipeline. Commits accumulate on the team's branch.
    """
    started_at = datetime.now(timezone.utc).isoformat()
    t0 = time.time()
    board = BoardStore(workspace.board_dir)
    emitter = EventEmitter(workspace.root, console_log=lambda m: print(f"[waterfall] {m}", flush=True))

    emitter.emit("campaign_started", mode="waterfall", goal=goal[:200])

    # Phase 1: same decomposer the scrum dispatcher uses
    emitter.emit("goal_ingest_start", summary="PO decomposing goal (waterfall mode)")
    try:
        ids = decompose_goal(
            goal=goal, repo_root=workspace.source_repo,
            board=board, model=model,
            prewritten_stories=prewritten_stories,
        )
        emitter.emit("goal_ingest_done", n_stories=len(ids),
                     summary=f"created {len(ids)} stories")
        for iid in ids:
            s = board.read(iid)
            emitter.emit("story_drafted", story_id=iid,
                         title=s.title, type=s.type, priority=s.priority)
    except Exception as e:
        emitter.emit("goal_ingest_failed", summary=str(e)[:200])
        return DispatchResult(
            team_id=workspace.team_id, goal=goal,
            started_at=started_at,
            ended_at=datetime.now(timezone.utc).isoformat(),
            reason_stopped=f"ingest_failed: {e}",
            stories_created=0, stories_done=0, stories_blocked=0,
        )

    # No refinement — mark all DRAFT stories as READY directly (waterfall)
    for iid in ids:
        board.transition(iid, "refinement", actor="waterfall_po")
        board.transition(iid, "ready", actor="waterfall_po",
                          reason="waterfall_no_refinement")

    results: list[WorkResult] = []
    ttl_in = 0
    ttl_out = 0
    worked = 0
    reason = ""

    for iid in ids:
        if worked >= max_stories_worked:
            reason = f"max_stories_worked ({worked})"
            break
        if time.time() - t0 > max_wall_seconds:
            reason = "wall_time_exceeded"
            break

        story = board.read(iid)
        emitter.emit("story_pulled", story_id=iid, worker="waterfall_pipeline",
                     story_type=story.type, title=story.title[:80])
        story_dict = {
            "issue_id": story.issue_id, "title": story.title,
            "body": story.body, "type": story.type,
        }
        board.assign(iid, "waterfall_team")
        board.transition(iid, "in_progress", actor="waterfall_team")

        r = _run_one_story_waterfall(story_dict, workspace, model)
        ttl_in += r.tokens_input
        ttl_out += r.tokens_output

        if r.status == "committed":
            board.set_commit(iid, r.commit_sha, actor="waterfall_team")
            board.transition(iid, "review", actor="waterfall_team")
            board.transition(iid, "done", actor="waterfall_team")
            emitter.emit("commit_landed", story_id=iid, commit_sha=r.commit_sha[:7],
                         worker="waterfall_pipeline",
                         summary=f"pipeline committed {r.commit_sha[:7]}")
            emitter.emit("story_review_pass", story_id=iid,
                         summary=f"→ DONE ({r.commit_sha[:7]})")
        else:
            board.transition(iid, "blocked", actor="waterfall_team",
                              reason=r.status)
            emitter.emit("story_no_commit", story_id=iid, worker="waterfall_pipeline",
                         summary=r.status)

        results.append(WorkResult(
            story_id=r.story_id, role="waterfall_team", status=r.status,
            commit_sha=r.commit_sha, diff_summary=r.diff_summary,
            envelope=r.envelopes, tokens_input=r.tokens_input,
            tokens_output=r.tokens_output, wall_seconds=r.wall_seconds,
            error=r.error,
        ))
        worked += 1

    if not reason:
        reason = "backlog_empty"

    counts = board.counts_by_state()
    emitter.emit("campaign_finished", reason=reason,
                 stories_done=counts.get("done", 0),
                 stories_blocked=counts.get("blocked", 0),
                 total_tokens=ttl_in + ttl_out,
                 summary=f"stopped: {reason}")
    return DispatchResult(
        team_id=workspace.team_id, goal=goal,
        started_at=started_at,
        ended_at=datetime.now(timezone.utc).isoformat(),
        reason_stopped=reason,
        stories_created=sum(counts.values()),
        stories_done=counts.get("done", 0),
        stories_blocked=counts.get("blocked", 0),
        total_tokens_input=ttl_in,
        total_tokens_output=ttl_out,
        per_story_results=results,
    )
