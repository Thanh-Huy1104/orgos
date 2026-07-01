"""Read-only GitHub Issues tools.

Calls the GitHub REST API directly with the GITHUB_TOKEN env var. We do
not depend on PyGithub to keep the agent dependency surface small.
"""

from __future__ import annotations

import json
import os
from typing import Any

import urllib.request
import urllib.error
from crewai.tools import BaseTool
from pydantic import BaseModel, Field


def _gh_get(path: str, params: dict | None = None) -> Any:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN not set")
    url = f"https://api.github.com{path}"
    if params:
        from urllib.parse import urlencode
        url += "?" + urlencode(params)
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "orgos-agile",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 403 and "rate limit" in (e.headers.get("X-RateLimit-Remaining") or ""):
            raise RuntimeError("RateLimited") from e
        raise


def _normalise(raw: dict) -> dict:
    return {
        "issue_id": str(raw.get("number", "")),
        "number": raw.get("number"),
        "title": raw.get("title", ""),
        "body": raw.get("body", "") or "",
        "labels": [l["name"] for l in raw.get("labels", [])],
        "url": raw.get("html_url", ""),
    }


def _repo() -> str:
    r = os.environ.get("GITHUB_REPO")
    if not r:
        raise RuntimeError("GITHUB_REPO not set (owner/repo)")
    return r


class _ListArgs(BaseModel):
    labels: list[str] = Field(default_factory=list)
    state: str = Field(default="open")
    limit: int = Field(default=20)


class GitHubListIssuesTool(BaseTool):
    name: str = "github_list_issues"
    description: str = "List GitHub issues, optionally filtered by labels."
    args_schema: type[BaseModel] = _ListArgs
    tool_category: str = "read"

    def _run(self, labels: list[str] | None = None, state: str = "open",
             limit: int = 20) -> str:
        labels = labels or []
        raw = _gh_get(
            f"/repos/{_repo()}/issues",
            params={"state": state, "per_page": limit},
        )
        normalised = [_normalise(r) for r in raw if "pull_request" not in r]
        if labels:
            wanted = set(labels)
            normalised = [n for n in normalised if wanted.issubset(set(n["labels"]))]
        return json.dumps(normalised[:limit])


class _GetArgs(BaseModel):
    number: int = Field(description="Issue number")


class GitHubGetIssueTool(BaseTool):
    name: str = "github_get_issue"
    description: str = "Read a single GitHub issue."
    args_schema: type[BaseModel] = _GetArgs
    tool_category: str = "read"

    def _run(self, number: int) -> str:
        raw = _gh_get(f"/repos/{_repo()}/issues/{number}")
        return json.dumps(_normalise(raw))
