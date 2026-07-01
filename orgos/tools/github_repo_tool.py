"""Sandbox-category git helpers operating inside a sprint's worktree."""

from __future__ import annotations

import subprocess

from crewai.tools import BaseTool
from pydantic import BaseModel, Field


class _PushArgs(BaseModel):
    branch: str = Field(description="Branch name to push.")
    worktree_path: str = Field(description="Absolute path to the sprint worktree.")


class GitWorktreePushTool(BaseTool):
    name: str = "git_worktree_push"
    description: str = "Push the sprint's branch from a worktree to origin."
    args_schema: type[BaseModel] = _PushArgs
    tool_category: str = "sandbox"

    def _run(self, branch: str, worktree_path: str) -> str:
        try:
            r = subprocess.run(
                ["git", "push", "origin", branch],
                cwd=worktree_path, capture_output=True, text=True, timeout=60,
            )
        except subprocess.TimeoutExpired:
            return "FAILED: git push timed out"
        if r.returncode != 0:
            return f"FAILED: {r.stderr.strip() or 'unknown'}"
        return f"pushed {branch} to origin"
