"""GitHub-issue-as-board tool — team coordination substrate.

Implements the autonomous scrum team board on top of GitHub Issues with labels
as columns. State is conveyed through label conventions:

  Board columns (state:<column>):
    draft  →  refinement  →  ready  →  in_progress  →  review  →  done

  Role signoffs (refined:<role>):
    refined:architect  refined:test  refined:devsecops

  Priority labels: p0 p1 p2 p3

Usage:
    from orgos.tools.github_board import GitHubBoardTool
    board = GitHubBoardTool()
    board._run(action="draft_story", title="...", body="...")
"""

from __future__ import annotations

import json
import os
from typing import Any

import urllib.error
import urllib.request
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from orgos.agile.board import check_ready_gate, story_fits_size_caps

LABEL_STATE_PREFIX = "state:"
LABEL_REFINED_PREFIX = "refined:"
VALID_STATES = ("draft", "refinement", "ready", "in_progress", "review", "done")
REQUIRED_ROLES = ("architect", "test", "devsecops")


def _repo() -> str:
    r = os.environ.get("GITHUB_REPO")
    if not r:
        raise RuntimeError("GITHUB_REPO not set (owner/repo)")
    return r


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
        return {"error": str(e), "status": e.code}


def _gh_post(path: str, body: dict) -> Any:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN not set")
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.github.com{path}", data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "orgos-agile",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": str(e), "status": e.code}


def _gh_post_comment(issue_number: int, body: str) -> dict:
    return _gh_post(f"/repos/{_repo()}/issues/{issue_number}/comments", {"body": body})


def _gh_replace_labels(issue_number: int, labels: list[str]) -> dict:
    token = os.environ.get("GITHUB_TOKEN")
    data = json.dumps({"labels": labels}).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.github.com/repos/{_repo()}/issues/{issue_number}",
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "orgos-agile",
        },
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": str(e), "status": e.code}


def _current_labels(issue_number: int) -> list[str]:
    raw = _gh_get(f"/repos/{_repo()}/issues/{issue_number}")
    return [l["name"] for l in raw.get("labels", [])]


def _state_label(issue_number: int) -> str | None:
    for lbl in _current_labels(issue_number):
        if lbl.startswith(LABEL_STATE_PREFIX):
            return lbl[len(LABEL_STATE_PREFIX):]
    return None


def _set_state(issue_number: int, new_state: str, current_labels: list[str] | None = None) -> dict:
    if new_state not in VALID_STATES:
        return {"error": f"invalid state: {new_state}"}
    labels = current_labels or _current_labels(issue_number)
    new_prefix = f"{LABEL_STATE_PREFIX}{new_state}"
    labels = [l for l in labels if not l.startswith(LABEL_STATE_PREFIX)]
    labels.append(new_prefix)
    return _gh_replace_labels(issue_number, labels)


def _add_label(issue_number: int, label: str) -> dict:
    labels = _current_labels(issue_number)
    if label not in labels:
        labels.append(label)
    return _gh_replace_labels(issue_number, labels)


def _normalise_issue(raw: dict) -> dict:
    return {
        "number": raw.get("number"),
        "title": raw.get("title", ""),
        "body": raw.get("body", "") or "",
        "labels": [l["name"] for l in raw.get("labels", [])],
        "url": raw.get("html_url", ""),
    }


def _list_state_issues(state: str, limit: int = 30) -> list[dict]:
    label = f"{LABEL_STATE_PREFIX}{state}"
    raw = _gh_get(
        f"/repos/{_repo()}/issues",
        params={"labels": label, "state": "open", "per_page": limit},
    )
    if isinstance(raw, dict) and "error" in raw:
        return []
    return [_normalise_issue(r) for r in raw if "pull_request" not in r]


class _BoardArgs(BaseModel):
    action: str = Field(description=(
        "Board action to perform: draft_story, read_story, refine_story, "
        "signoff_story, mark_ready, list_ready, pull_top, update_status, "
        "add_comment, list_labels"
    ))
    title: str = Field(default="", description="Story title (for draft_story).")
    body: str = Field(default="", description="Story body / comment text.")
    number: int = Field(default=0, description="Issue number.")
    role: str = Field(default="", description="Agent role (for signoff_story).")
    concern: str = Field(default="", description="Refinement concern text.")
    state: str = Field(default="", description="Target state for update_status.")
    estimated_files: int = Field(default=0, description="Estimated files touched.")
    estimated_loc: int = Field(default=0, description="Estimated LOC.")


class GitHubBoardTool(BaseTool):
    name: str = "github_board"
    description: str = (
        "Team board operations via GitHub Issues: draft stories, refine with role "
        "signoffs, move through the DRAFT→REFINEMENT→READY→IN_PROGRESS→REVIEW→DONE "
        "flow. Labels encode state (state:draft|refinement|ready|in_progress|review|done) "
        "and role signoffs (refined:architect|test|devsecops)."
    )
    args_schema: type[BaseModel] = _BoardArgs
    tool_category: str = "orchestrate"

    def _run(
        self,
        action: str,
        title: str = "",
        body: str = "",
        number: int = 0,
        role: str = "",
        concern: str = "",
        state: str = "",
        estimated_files: int = 0,
        estimated_loc: int = 0,
    ) -> str:
        try:
            result = self._dispatch(
                action, title, body, number, role, concern, state,
                estimated_files, estimated_loc,
            )
            return json.dumps(result)
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    def _dispatch(
        self, action: str, title: str, body: str, number: int, role: str,
        concern: str, state: str, estimated_files: int, estimated_loc: int,
    ) -> dict:
        if action == "draft_story":
            return self._do_draft_story(title, body)
        elif action == "read_story":
            return self._do_read_story(number)
        elif action == "refine_story":
            return self._do_refine_story(number, role, concern)
        elif action == "signoff_story":
            return self._do_signoff_story(number, role)
        elif action == "mark_ready":
            return self._do_mark_ready(number, estimated_files, estimated_loc)
        elif action == "list_ready":
            return self._do_list_ready()
        elif action == "pull_top":
            return self._do_pull_top()
        elif action == "update_status":
            return self._do_update_status(number, state)
        elif action == "add_comment":
            return self._do_add_comment(number, body)
        elif action == "list_labels":
            return self._do_list_labels()
        else:
            return {"error": f"unknown action: {action}"}

    def _do_draft_story(self, title: str, body: str) -> dict:
        if not title.strip():
            return {"error": "title is required"}
        raw = _gh_post(f"/repos/{_repo()}/issues", {
            "title": title,
            "body": body or "",
            "labels": [f"{LABEL_STATE_PREFIX}draft"],
        })
        if isinstance(raw, dict) and "error" in raw:
            return raw
        return _normalise_issue(raw)

    def _do_read_story(self, number: int) -> dict:
        if not number:
            return {"error": "issue number is required"}
        raw = _gh_get(f"/repos/{_repo()}/issues/{number}")
        if isinstance(raw, dict) and "error" in raw:
            return raw
        return _normalise_issue(raw)

    def _do_refine_story(self, number: int, role: str, concern: str) -> dict:
        if not number or not role:
            return {"error": "issue number and role are required"}
        if not concern.strip():
            return {"error": "refinement concern text is required"}
        comment = f"**Refinement — {role}**\n\n{concern}"
        return _gh_post_comment(number, comment)

    def _do_signoff_story(self, number: int, role: str) -> dict:
        if not number or not role:
            return {"error": "issue number and role are required"}
        if role not in REQUIRED_ROLES:
            return {"error": f"unknown role: {role}"}
        return _add_label(number, f"{LABEL_REFINED_PREFIX}{role}")

    def _do_mark_ready(self, number: int, estimated_files: int = 0,
                       estimated_loc: int = 0) -> dict:
        if not number:
            return {"error": "issue number is required"}
        issue = self._do_read_story(number)
        if "error" in issue:
            return issue

        labels = _current_labels(number)
        signoffs: dict[str, bool] = {}
        for role in REQUIRED_ROLES:
            signoffs[role] = f"{LABEL_REFINED_PREFIX}{role}" in labels

        gate = check_ready_gate(
            title=issue.get("title", ""),
            acceptance_criteria=[issue.get("body", "")] if issue.get("body") else [],
            estimated_files=estimated_files,
            estimated_loc=estimated_loc,
            role_signoffs=signoffs,
        )

        if not gate.ready:
            return {"ready": False, "reason": gate.reason}

        return _set_state(number, "ready", current_labels=labels)

    def _do_list_ready(self) -> dict:
        items = _list_state_issues("ready")
        items.sort(key=lambda i: sum(
            1 for l in i.get("labels", []) if l.startswith("p")
        ))
        return {"ready_items": items, "count": len(items)}

    def _do_pull_top(self) -> dict:
        items = _list_state_issues("ready")
        if not items:
            return {"error": "no ready items available"}
        top = items[0]
        number = top["number"]
        labels = _current_labels(number)
        new_labels = [l for l in labels if not l.startswith(LABEL_STATE_PREFIX)]
        new_labels.append(f"{LABEL_STATE_PREFIX}in_progress")
        result = _gh_replace_labels(number, new_labels)
        if isinstance(result, dict) and "error" in result:
            return result
        return {
            "pulled": _normalise_issue(result),
            "action": "story pulled from READY, now IN_PROGRESS",
        }

    def _do_update_status(self, number: int, state: str) -> dict:
        if not number:
            return {"error": "issue number is required"}
        return _set_state(number, state)

    def _do_add_comment(self, number: int, body: str) -> dict:
        if not number or not body.strip():
            return {"error": "issue number and body are required"}
        return _gh_post_comment(number, body)

    def _do_list_labels(self) -> dict:
        raw = _gh_get(f"/repos/{_repo()}/labels", params={"per_page": 100})
        if isinstance(raw, dict) and "error" in raw:
            return raw
        return {"labels": [l["name"] for l in raw]}
