"""Task briefs for the dispatcher's work and review spawns.

Kept in a separate module so the dispatcher isn't a 900-line file.
"""

from __future__ import annotations

from pathlib import Path

from orgos.agile.board_store import Story
from orgos.spawn import TaskBrief


_WORK_BRIEF_TEMPLATE = """You are the {role_label}. You just pulled this story from the READY queue.

STORY
  issue_id: {issue_id}
  title:    {title}
  type:     {type}
  points:   {points}

BODY (the acceptance criteria):
{body}

YOU ARE HERE
  git worktree at: {worktree}
  branch:          {branch}
  BashTool runs commands in the worktree automatically. Use bare relative
  paths (`orgos/agile/foo.py`, not absolute). UNIX shell — use `cat`, `ls`,
  `pytest`, heredocs. NOT `type`, `dir`, `echo >`.

You share a persistent wiki with the rest of the team. Use these tools:
  - `wiki_read` on `DECISIONS.md` — read this FIRST for prior conventions.
  - `wiki_grep` — search wiki when you need to find prior decisions.
  - `wiki_write` (mode=append) — record any convention you set for future teammates.

DO THIS IN ORDER — no exploration, no explanation:

0. wiki_read `DECISIONS.md`. If a prior sprint recorded a convention that
   applies to your story (naming, unit, field order, error policy, API shape),
   FOLLOW IT EXACTLY. Two wiki calls max at this step.

1. Write the code the story asks for. Heredoc:
     cat > path/to/target <<'EOF'
     <full contents>
     EOF

2. If the story implies tests, write them and run:
     pytest <path> -v

3. Commit:
     git add -A
     git -c user.name={git_name} -c user.email={git_email} commit -m "{commit_prefix}: {title}"

4. Grab SHA:  git rev-parse HEAD

5. wiki_write (mode="append") to `DECISIONS.md`. If your work established a
   convention future teammates need to stay consistent, use this block form
   (include ALL three required fields):

     ## <topic> — sprint {issue_id}
     - author: {role_label}
     - timestamp: <ISO date, use `date -u +%Y-%m-%dT%H:%M:%SZ`>
     - source: {issue_id}
     - decision: <exact choice, as it appears in the code>
     - rationale: <why this over the alternative>
     - applies-to: <what future code should follow this>

   If you established no new convention, write a one-liner changelog:
     - author={role_label} timestamp=<ISO> source={issue_id} — {title}

6. Output ONLY the envelope JSON below. No prose, no markdown fences.

{{
  "role": "{role_lower}",
  "status": "completed",
  "summary": "<what you did in one line>",
  "success_criteria_met": true,
  "requires_human_approval": false,
  "payload": {{
    "commit_sha": "<sha from step 4>",
    "files_touched": ["<paths>"],
    "test_command": "<pytest cmd or empty>",
    "test_output": "<tail>",
    "test_passed": true,
    "wiki_updated": true
  }}
}}

HARD RULES:
  - Your FIRST BashTool call must be productive (heredoc or wiki_read), not
    an exploration like `ls`.
  - Do not modify governance files: orgos/spawn/**, TIER_POLICY, GatedToolBase.
  - Do not modify `.gitignore` — the team already committed a baseline.
  - Follow conventions from wiki/DECISIONS.md when they apply.
"""


_REVIEW_BRIEF_TEMPLATE = """You are the {role_label}. Peer-reviewing the work another agent just committed.

STORY UNDER REVIEW
  issue_id: {issue_id}
  title:    {title}
  type:     {type}
  points:   {points}
  written by: {author_role}

ACCEPTANCE CRITERIA (from the story body):
{body}

YOU ARE HERE
  git worktree at: {worktree}
  branch:          {branch}
  Shell is UNIX bash.

DO THIS:

1. `git log --oneline -3` to see the recent commit.
2. `git diff HEAD~1` to read the actual diff.
3. If any *.py test files were touched, run them:
     pytest <touched-test-path> -v

4. Judge whether the work meets the acceptance criteria in the body above.

5. Output ONLY this envelope JSON:

{{
  "role": "{role_lower}_reviewer",
  "review": "pass" or "fail",
  "summary": "<one-line verdict>",
  "success_criteria_met": true,
  "requires_human_approval": false,
  "payload": {{
    "reviewed_sha": "<sha>",
    "test_command": "<command or empty>",
    "test_passed": true,
    "concerns": ["<any concern>", ...]
  }}
}}

RULES:
  - Do NOT modify files. Read-only review.
  - PASS if the acceptance criteria are met AND tests pass AND diff is
    reasonable (no secrets, no governance-layer edits).
  - FAIL only when a concrete criterion is unmet OR tests fail. "Could be
    better" is not a fail reason.
"""


_ROLE_LABELS = {
    "architect": "Architect",
    "test":      "Test",
    "devsecops": "DevSecOps",
}


def build_work_brief(story: Story, worktree: Path, branch: str) -> TaskBrief:
    role_label = _ROLE_LABELS.get(story.assignee, story.assignee or "Developer")
    obj = _WORK_BRIEF_TEMPLATE.format(
        role_label=role_label,
        role_lower=(story.assignee or "developer").lower(),
        issue_id=story.issue_id,
        title=story.title,
        type=story.type,
        points=story.points if story.points is not None else "?",
        body=story.body or "(no body — infer from title)",
        worktree=str(worktree),
        branch=branch,
        git_name=f"orgos-{story.assignee}",
        git_email=f"{story.assignee}@orgos.local",
        commit_prefix=story.type,
    )
    return TaskBrief(
        objective=obj,
        expected_output="A HandoffEnvelope JSON.",
        success_criteria=[
            f"{role_label} committed to worktree",
            "Wiki updated per DoD",
        ],
        inputs={"issue_id": story.issue_id, "worktree": str(worktree)},
    )


def build_review_brief(story: Story, worktree: Path, branch: str,
                        author_role: str) -> TaskBrief:
    # Whoever is reviewing (we don't know their name in advance) — use a
    # generic label; the dispatcher spawns the reviewer role, which will
    # know its own identity from its persona.
    obj = _REVIEW_BRIEF_TEMPLATE.format(
        role_label="Reviewer",
        role_lower="reviewer",
        issue_id=story.issue_id,
        title=story.title,
        type=story.type,
        points=story.points if story.points is not None else "?",
        body=story.body or "(no body)",
        author_role=author_role,
        worktree=str(worktree),
        branch=branch,
    )
    return TaskBrief(
        objective=obj,
        expected_output="A HandoffEnvelope JSON with review: pass|fail.",
        success_criteria=[
            "Verdict is pass or fail",
            "No files modified",
        ],
        inputs={"issue_id": story.issue_id},
    )
