"""MockPRTool — non-publishing replacement for github_open_pr.

Used in:
  - Phase 1 (skeleton sprint, no GitHub yet)
  - Hook B replays (publish-category tools forbidden by _enforce_tier)
"""

from __future__ import annotations

import hashlib

from crewai.tools import BaseTool
from pydantic import BaseModel, Field


class _Args(BaseModel):
    branch: str = Field(description="git branch name to open the PR from")
    title: str = Field(description="PR title")
    body: str = Field(description="PR body (markdown)")


class MockPRTool(BaseTool):
    name: str = "mock_open_pr"
    description: str = (
        "Open a mock PR. Returns a deterministic mock://pr/<sha> URL. "
        "Use this when github_open_pr is unavailable (skeleton runs, replays)."
    )
    args_schema: type[BaseModel] = _Args
    tool_category: str = "read"

    def _run(self, branch: str, title: str, body: str) -> str:
        h = hashlib.sha1(
            f"{branch}|{title}|{body}".encode("utf-8")
        ).hexdigest()[:12]
        return f"mock://pr/{h}"
