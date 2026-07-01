"""Publish-category GitHub PR tool — always human-gated."""

from __future__ import annotations

import json
import os
import urllib.request

from pydantic import BaseModel, Field

from orgos.spawn.toolbase import GatedToolBase


def _gh_post(path: str, body: dict) -> dict:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN not set")
    repo = os.environ.get("GITHUB_REPO")
    if not repo:
        raise RuntimeError("GITHUB_REPO not set")
    url = f"https://api.github.com{path}"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "orgos-agile",
    }, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


class _Args(BaseModel):
    branch: str = Field(description="Head branch (already pushed to origin).")
    base: str = Field(default="main", description="Base branch.")
    title: str = Field(description="PR title.")
    body: str = Field(description="PR body markdown.")


class GitHubOpenPRTool(GatedToolBase):
    name: str = "github_open_pr"
    description: str = (
        "Open a GitHub PR from `branch` against `base`. Human approval required."
    )
    args_schema: type[BaseModel] = _Args
    tool_category: str = "publish"

    def _run(self, branch: str, base: str = "main", title: str = "", body: str = "") -> str:
        tool_input = {"branch": branch, "base": base, "title": title, "body": body}
        # Gate check via _check_gate() — properly routes to approval_fn(role, name, tool_input).
        if self._gate_required and not self._check_gate(tool_input):
            return f"DENIED: approval refused for github_open_pr with {tool_input}"
        repo = os.environ.get("GITHUB_REPO", "")
        resp = _gh_post(
            f"/repos/{repo}/pulls",
            {"head": branch, "base": base, "title": title, "body": body},
        )
        return resp.get("html_url", "")
