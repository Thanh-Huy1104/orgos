"""Team workspace — persistent codebase per team instance.

Contrast with `sprint._make_worktree`, which creates a FRESH worktree per
sprint (per issue). That's fine for isolated benchmarks but wrong for real
Scrum: a real team works on ONE codebase across many stories, and commits
accumulate.

Layout for a team instance:

    .orgos_teams/<team_id>/
        worktree/     ← git worktree, one branch, commits accumulate
        board/        ← BoardStore state (per-team stories)
        wiki/         ← per-team wiki (falls back to shared repo wiki if absent)
        audit/        ← per-team audit trail
        manifest.json ← team_id, goal, source_repo, model, created_at

The worktree is a `git worktree add` off the source repo's HEAD. Everything
the team does — every story, every commit — lands on that single branch. When
the goal is done, the branch is ready for a PR (or a hand-over).

Rebuilds are cheap: `TeamWorkspace.reset()` removes .orgos_teams/<team_id>/
and prunes the worktree registration.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


TEAMS_ROOT = ".orgos_teams"


_BASELINE_GITIGNORE = """# orgos team scratch — auto-generated, do not commit above this line
snapshot.json
retro.md
_orgos_memory/
_audit_logs/
__pycache__/
*.pyc
.pytest_cache/
"""


@dataclass
class TeamManifest:
    team_id: str
    goal: str
    source_repo: str
    model: str
    created_at: str
    branch: str
    baseline_sha: str


class TeamWorkspaceExists(RuntimeError):
    """Raised when trying to create a team_id that already has a workspace."""


class TeamWorkspaceMissing(RuntimeError):
    """Raised when trying to open a team_id that has no workspace."""


class TeamWorkspace:
    """Persistent codebase + board + wiki for one team instance."""

    def __init__(self, team_id: str, source_repo: Path):
        self.team_id = team_id
        self.source_repo = Path(source_repo).resolve()
        self.root = self.source_repo / TEAMS_ROOT / team_id
        self.worktree = self.root / "worktree"
        self.board_dir = self.root / "board"
        self.wiki_dir = self.root / "wiki"
        self.audit_dir = self.root / "audit"
        self.manifest_path = self.root / "manifest.json"

    # ── Creation / lookup ────────────────────────────────────────────────

    def exists(self) -> bool:
        return self.manifest_path.exists()

    @classmethod
    def create(cls, team_id: str, source_repo: Path, *, goal: str,
               model: str) -> "TeamWorkspace":
        """Create a fresh workspace: worktree + branch + dirs + manifest.

        Raises TeamWorkspaceExists if the team_id already exists — callers
        should use TeamWorkspace.open() to resume, or reset() to rebuild.
        """
        ws = cls(team_id, source_repo)
        if ws.exists():
            raise TeamWorkspaceExists(
                f"team_id={team_id!r} already exists at {ws.root}. "
                f"Use TeamWorkspace.open() to resume, or reset() first."
            )

        ws.root.mkdir(parents=True, exist_ok=True)
        ws.board_dir.mkdir(parents=True, exist_ok=True)
        ws.wiki_dir.mkdir(parents=True, exist_ok=True)
        ws.audit_dir.mkdir(parents=True, exist_ok=True)

        branch = f"team/{team_id}"
        # `git worktree add -b <branch> <path> HEAD` fails if the path exists.
        # Since we just made ws.root and ws.worktree doesn't exist yet, we're fine.
        subprocess.run(
            ["git", "worktree", "add", "-b", branch, str(ws.worktree), "HEAD"],
            cwd=ws.source_repo, check=True, capture_output=True,
        )

        # Baseline .gitignore so scratch never leaks into the agent's diff.
        # (Same rationale as sprint._make_worktree — per-worktree info/exclude
        # is dead code in git 2.5+, .gitignore is the reliable path.)
        (ws.worktree / ".gitignore").write_text(_BASELINE_GITIGNORE)
        subprocess.run(
            ["git", "add", ".gitignore"],
            cwd=ws.worktree, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "-c", "user.name=orgos-team", "-c", "user.email=team@orgos.local",
             "commit", "-m", f"chore(team-{team_id}): baseline .gitignore"],
            cwd=ws.worktree, check=True, capture_output=True,
        )

        baseline_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ws.worktree, capture_output=True, text=True, timeout=10,
        ).stdout.strip()

        manifest = TeamManifest(
            team_id=team_id,
            goal=goal,
            source_repo=str(ws.source_repo),
            model=model,
            created_at=datetime.now(timezone.utc).isoformat(),
            branch=branch,
            baseline_sha=baseline_sha,
        )
        ws.manifest_path.write_text(json.dumps(manifest.__dict__, indent=2))
        return ws

    @classmethod
    def open(cls, team_id: str, source_repo: Path) -> "TeamWorkspace":
        """Reopen an existing team workspace. Raises if missing."""
        ws = cls(team_id, source_repo)
        if not ws.exists():
            raise TeamWorkspaceMissing(
                f"no workspace for team_id={team_id!r} at {ws.root}"
            )
        return ws

    # ── Access ───────────────────────────────────────────────────────────

    def manifest(self) -> TeamManifest:
        if not self.manifest_path.exists():
            raise TeamWorkspaceMissing(f"no manifest at {self.manifest_path}")
        data = json.loads(self.manifest_path.read_text())
        return TeamManifest(**data)

    def current_head(self) -> str:
        """Current HEAD of the team's branch."""
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.worktree, capture_output=True, text=True, timeout=10,
        ).stdout.strip()

    def head_advanced_since(self, since_sha: str) -> bool:
        """True if HEAD is not equal to since_sha (i.e. someone committed)."""
        head = self.current_head()
        return bool(head) and head != since_sha

    def diff_since(self, since_sha: str, *, stat_only: bool = False) -> str:
        args = ["git", "diff", f"{since_sha}..HEAD"]
        if stat_only:
            args.append("--stat")
        return subprocess.run(
            args, cwd=self.worktree, capture_output=True, text=True, timeout=30,
        ).stdout

    # ── Teardown ─────────────────────────────────────────────────────────

    def reset(self) -> None:
        """Delete the workspace and prune the git worktree registration.

        Destructive. Only call when you want a clean re-create.
        """
        if self.worktree.exists():
            # Try `git worktree remove --force`; fall back to rmtree + prune.
            try:
                subprocess.run(
                    ["git", "worktree", "remove", "--force", str(self.worktree)],
                    cwd=self.source_repo, check=True, capture_output=True,
                )
            except subprocess.CalledProcessError:
                shutil.rmtree(self.worktree, ignore_errors=True)
                subprocess.run(
                    ["git", "worktree", "prune"],
                    cwd=self.source_repo, check=False, capture_output=True,
                )
        # Kill the branch too (best-effort — may not exist).
        m = None
        try:
            m = self.manifest()
        except TeamWorkspaceMissing:
            pass
        if m:
            subprocess.run(
                ["git", "branch", "-D", m.branch],
                cwd=self.source_repo, check=False, capture_output=True,
            )
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)


def list_team_ids(source_repo: Path) -> list[str]:
    """List all team_ids that have a workspace under source_repo/.orgos_teams/."""
    teams_root = Path(source_repo) / TEAMS_ROOT
    if not teams_root.exists():
        return []
    return sorted(
        p.name for p in teams_root.iterdir()
        if p.is_dir() and (p / "manifest.json").exists()
    )
