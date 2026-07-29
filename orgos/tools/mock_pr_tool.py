"""MockPRTool — non-publishing replacement for github_open_pr.

Used in:
  - Phase 1 (skeleton sprint, no GitHub yet)
  - Hook B replays (real publish-category tools would fail the tier check
    because the replay path never wires a human approval_fn)

MockPRTool subclasses GatedToolBase so it satisfies the publisher tier's
"every tool must be gateable" constraint. It runs `_check_gate` normally
against whatever approval_fn is wired at spawn time; run_sprint(mock_pr=True)
supplies an auto-approve callback so the mock always succeeds.
"""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, Field

from orgos.spawn.governance.toolbase import GatedToolBase


class _Args(BaseModel):
    branch: str = Field(description="git branch name to open the PR from")
    title: str = Field(description="PR title")
    body: str = Field(description="PR body (markdown)")


class MockPRTool(GatedToolBase):
    name: str = "mock_open_pr"
    description: str = (
        "Open a mock PR. Returns a deterministic mock://pr/<sha> URL. "
        "Use this when github_open_pr is unavailable (skeleton runs, replays)."
    )
    args_schema: type[BaseModel] = _Args
    # Category read: this tool never touches origin — the mock URL is a
    # deterministic hash of the inputs. Kept read (not publish) so replay
    # mode doesn't need can_publish=True on the running tier.
    tool_category: str = "read"

    def _run(self, branch: str, title: str, body: str) -> str:
        args = {"branch": branch, "title": title, "body": body}
        if not self._check_gate(args):
            return "DENIED: mock PR gate refused"
        h = hashlib.sha1(
            f"{branch}|{title}|{body}".encode("utf-8")
        ).hexdigest()[:12]
        return f"mock://pr/{h}"
