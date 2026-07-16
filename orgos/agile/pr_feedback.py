"""PR feedback ingestion — pull GH review comments back into the sprint loop.

Between sprints (or in `orgos watch`), if the team has an open PR, poll for
review comments made SINCE the last check. Each substantive comment becomes
a candidate story on the backlog — a real "reviewer asked for X, team goes
and does X" loop.

State: workspace.root/pr_feedback_seen.json tracks the last-seen comment id
so we don't re-ingest the same comment across sprints.

Requires `gh` CLI. If missing, this module no-ops gracefully.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from orgos.agile.board_store import BoardStore, VALID_TYPES
from orgos.agile.goal_decomposer import _slugify
from orgos.agile.live_events import EventEmitter
from orgos.agile.team_workspace import TeamWorkspace


@dataclass
class IngestedComment:
    comment_id: str          # unique per-comment id from gh
    author: str
    body: str
    created_at: str          # ISO
    story_id: str            # what we drafted for it (or "" if skipped)


_STATE_FILENAME = "pr_feedback_seen.json"


def _read_seen(workspace: TeamWorkspace) -> set[str]:
    p = workspace.root / _STATE_FILENAME
    if not p.exists():
        return set()
    try:
        return set(json.loads(p.read_text()))
    except Exception:
        return set()


def _write_seen(workspace: TeamWorkspace, ids: set[str]) -> None:
    p = workspace.root / _STATE_FILENAME
    p.write_text(json.dumps(sorted(ids)))


def _gh_available() -> bool:
    return shutil.which("gh") is not None


def _pr_number_from_url(url: str) -> Optional[str]:
    """Parse the trailing /pull/N from a gh PR URL."""
    if not url:
        return None
    m = re.search(r"/pull/(\d+)(?:$|/)", url)
    return m.group(1) if m else None


def _fetch_comments(worktree: Path, pr_number: str) -> list[dict]:
    """Return every review comment on the PR.

    Uses `gh pr view <n> --json comments,reviews` — comments are top-level PR
    comments; reviews carry inline code comments. We union both.
    """
    comments: list[dict] = []
    for kind in ("comments", "reviews"):
        try:
            r = subprocess.run(
                ["gh", "pr", "view", pr_number, "--json", kind],
                cwd=str(worktree), capture_output=True, text=True, timeout=30,
            )
            if r.returncode != 0:
                continue
            data = json.loads(r.stdout or "{}")
            for item in data.get(kind, []) or []:
                # Normalize into a common shape
                cid = str(item.get("id") or item.get("commit") or item.get("createdAt", ""))
                if not cid:
                    continue
                comments.append({
                    "comment_id": f"{kind}:{cid}",
                    "author": (item.get("author") or {}).get("login", "?"),
                    "body": item.get("body", ""),
                    "created_at": item.get("createdAt", ""),
                })
        except Exception:
            continue
    return comments


def _is_actionable(body: str) -> bool:
    """Heuristic: skip pure noise (thumbs-up, one-word "lgtm", empty bodies)."""
    s = (body or "").strip().lower()
    if len(s) < 8:
        return False
    if s in {"lgtm", "👍", "ship it", "approved", "merge", "looks good"}:
        return False
    return True


def _draft_story_from_comment(
    board: BoardStore, comment: dict, id_prefix: str, idx: int,
) -> str:
    """Turn a reviewer comment into a story draft. Returns the issue_id."""
    body = (comment.get("body", "") or "").strip()
    # Best-effort title = first sentence, cap 80 chars.
    first_line = body.splitlines()[0] if body else "review comment"
    title = re.split(r"[.\n!?]", first_line)[0].strip()[:80] or "review feedback"

    # Type guess based on wording
    lower = body.lower()
    story_type = "feature"
    if any(w in lower for w in ("bug", "broken", "fails", "error", "wrong", "fix")):
        story_type = "feature"  # fix is not in taxonomy; feature covers bug fix
    elif any(w in lower for w in ("test", "coverage", "assert")):
        story_type = "test"
    elif any(w in lower for w in ("secret", "auth", "injection", "escape", "sanitize", "vulner")):
        story_type = "security"
    elif any(w in lower for w in ("doc", "readme", "comment")):
        story_type = "docs"
    if story_type not in VALID_TYPES:
        story_type = "feature"

    author = comment.get("author", "?")
    full_body = (
        f"[From PR reviewer @{author}]\n\n"
        f"{body}\n\n"
        f"---\n"
        f"Original comment id: {comment.get('comment_id','?')}\n"
        f"Created: {comment.get('created_at','?')}"
    )
    issue_id = f"{id_prefix}-{idx:02d}-{_slugify(title)}"
    while board.exists(issue_id):
        issue_id = f"{issue_id}-x"
    board.draft_story(
        issue_id=issue_id,
        title=f"[PR feedback] {title}",
        body=full_body,
        story_type=story_type,
        priority=85,  # high — reviewer feedback is time-sensitive
        actor="pr_feedback",
    )
    return issue_id


def ingest_pr_feedback(
    *,
    workspace: TeamWorkspace,
    pr_url: str,
    board: BoardStore,
    emitter: EventEmitter,
    sprint_num: int,
) -> list[IngestedComment]:
    """Pull new PR comments and draft stories for each substantive one.

    Returns list of what was ingested. If no PR / no gh / no new comments,
    returns [] and emits an informational event.
    """
    if not pr_url:
        return []
    pr_num = _pr_number_from_url(pr_url)
    if not pr_num:
        emitter.emit("pr_feedback_skipped",
                     reason="could not parse PR number from URL",
                     summary=pr_url[:80])
        return []
    if not _gh_available():
        emitter.emit("pr_feedback_skipped", reason="gh CLI not installed",
                     summary="install `gh` to enable PR feedback ingestion")
        return []

    seen = _read_seen(workspace)
    all_comments = _fetch_comments(workspace.worktree, pr_num)
    new = [c for c in all_comments
            if c["comment_id"] not in seen and _is_actionable(c["body"])]

    if not new:
        emitter.emit("pr_feedback_none",
                     total_comments=len(all_comments),
                     summary=f"no new actionable comments (saw {len(all_comments)} total)")
        # Still record what we've seen so noise counts as seen
        _write_seen(workspace, seen | {c["comment_id"] for c in all_comments})
        return []

    id_prefix = f"PR{sprint_num}"
    ingested: list[IngestedComment] = []
    for idx, comment in enumerate(new):
        try:
            iid = _draft_story_from_comment(board, comment, id_prefix, idx)
            ingested.append(IngestedComment(
                comment_id=comment["comment_id"],
                author=comment["author"],
                body=comment["body"],
                created_at=comment["created_at"],
                story_id=iid,
            ))
        except Exception as e:
            emitter.emit("pr_feedback_error", error=str(e),
                          summary=f"could not draft story for comment: {e}")

    _write_seen(workspace, seen | {c["comment_id"] for c in all_comments})

    if ingested:
        emitter.emit(
            "pr_feedback_ingested",
            n_comments=len(ingested),
            summary=f"drafted {len(ingested)} stories from PR reviewer feedback",
        )
    return ingested
