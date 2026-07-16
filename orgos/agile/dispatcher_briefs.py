"""Task briefs for the dispatcher's work and review spawns.

Kept in a separate module so the dispatcher isn't a 900-line file.
"""

from __future__ import annotations

from pathlib import Path

from orgos.agile.board_store import Story
from orgos.agile.environment import RepoEnvironment, environment_hint_for_brief
from orgos.spawn import TaskBrief


_WORK_BRIEF_TEMPLATE = """You are the {role_label}. You just pulled this story from the READY queue.

STORY
  issue_id: {issue_id}
  title:    {title}
  type:     {type}
  points:   {points}

BODY (the acceptance criteria):
{body}

{env_hint}
YOU ARE HERE
  git worktree at: {worktree}
  branch:          {branch}

TOOLS YOU HAVE (prefer these over raw bash for editing files):
  - `read_file` (path, start_line, max_lines) → read a file's contents.
    Prefer this to `cat` on large files (caps at 400 lines by default).
  - `write_file` (path, content) → create a new file or fully replace one.
    Use for NEW files.
  - `edit_file` (path, old, new) → find + replace a unique literal string in
    an EXISTING file. Preferred for narrow edits — avoids rewriting the
    whole file just to change a few lines. `old` must appear exactly once,
    or the tool refuses (widen with context to disambiguate).
  - BashTool → run pytest, git, npm, or any shell command in the worktree.
    Use bare relative paths. UNIX shell (cat, ls, pytest, git).
  - `wiki_read` / `wiki_grep` / `wiki_write` → shared team knowledge base.

Rule of thumb: edit_file is your default for existing files, write_file for
new ones. Reserve `cat > file <<EOF` for cases where nothing else fits.

DO THIS IN ORDER — no exploration, no explanation:

0. wiki_read `DECISIONS.md`. If a prior sprint recorded a convention that
   applies to your story (naming, unit, field order, error policy, API shape),
   FOLLOW IT EXACTLY. Two wiki calls max at this step.

1. Write the code the story asks for:
     - New file          → use `write_file`
     - Small edit to existing file → use `edit_file` (specify unique `old` + `new`)
     - Large rewrite of a file (rare) → BashTool heredoc is fine
   For existing files, use `read_file` first if you need to see current contents.

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


_REVIEW_BRIEF_TEMPLATE = """You are the {role_label}. Adversarial peer review of the work {author_role} just committed.

STORY UNDER REVIEW
  issue_id: {issue_id}
  title:    {title}
  type:     {type}
  points:   {points}
  written by: {author_role}

ACCEPTANCE CRITERIA (from the story body — every one of these must be met):
{body}

YOU ARE HERE
  git worktree at: {worktree}
  branch:          {branch}
  Shell is UNIX bash.

YOUR JOB IS TO FIND WHAT'S WRONG. Reviewers who rubber-stamp are useless.
Approach this as if {author_role} might have made a mistake — because they might have.
Before you can PASS you MUST name at least two concrete concerns and
address each one. If you can't find two concerns, look harder — no diff is perfect.

DO THIS:

1. `git log --oneline -3` — see the commit.
2. `git diff HEAD~1` — read the actual diff line by line.
3. Enumerate concerns FIRST, before deciding pass/fail. Ask yourself:
     - Does the diff literally satisfy each acceptance criterion? Which line?
     - What edge cases are unhandled? (empty input, None, negative numbers,
       unicode, very long strings, concurrent access, missing fields)
     - Are error paths tested, or only the happy path?
     - Any silent try/except that swallows bugs?
     - Any hard-coded values that should be constants or config?
     - Any test that asserts implementation instead of behavior?
     - Does the code introduce a security issue (path traversal, injection,
       secrets in logs, unauthenticated endpoint)?
     - Any file touched that this story shouldn't have touched?
4. Re-run any *.py tests the diff touched:  pytest <path> -v
   For non-Python projects, run the appropriate test command based on the
   files touched (npm test, go test, cargo test, etc.).
5. Decide pass/fail based on ALL of:
     - Every acceptance criterion has a specific line/test in the diff that satisfies it.
     - Tests actually pass.
     - No secrets, no writes to .env or governance layer.
     - Concerns list is either empty (rare) or every listed concern is minor.
6. Output ONLY this envelope JSON:

{{
  "role": "{role_lower}_reviewer",
  "review": "pass" or "fail",
  "summary": "<one-line verdict, honest — 'PASS with 2 minor concerns' is fine>",
  "success_criteria_met": true,
  "requires_human_approval": false,
  "payload": {{
    "reviewed_sha": "<sha>",
    "test_command": "<command or empty>",
    "test_passed": true,
    "concerns": ["<concrete concern 1>", "<concrete concern 2>", ...]
  }}
}}

RULES:
  - Do NOT modify files. Read-only review.
  - FAIL any of these:
      * an acceptance criterion is unsatisfied (name which one)
      * tests fail
      * secrets leaked or .env / governance layer touched
      * story clearly implements the WRONG thing (misread the spec)
  - You may PASS with concerns listed — reviewers are expected to see
    imperfections. A pass with 3 minor concerns is more useful than a
    silent pass with none.
"""


_ROLE_LABELS = {
    "architect": "Architect",
    "test":      "Test",
    "devsecops": "DevSecOps",
}


def build_work_brief(story: Story, worktree: Path, branch: str,
                      env: RepoEnvironment | None = None) -> TaskBrief:
    role_label = _ROLE_LABELS.get(story.assignee, story.assignee or "Developer")
    env_hint = environment_hint_for_brief(env) if env else ""
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
        env_hint=env_hint,
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
