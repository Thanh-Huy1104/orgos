import json
from unittest.mock import patch

import pytest

from orgos.spawn.toolbase import GatedToolBase
from orgos.tools.github_pr_tool import GitHubOpenPRTool


def test_pr_tool_is_publish_and_gated():
    t = GitHubOpenPRTool()
    assert t.tool_category == "publish"
    assert isinstance(t, GatedToolBase)


def test_pr_tool_returns_denied_without_approval():
    t = GitHubOpenPRTool()
    t.approval_fn = lambda role, name, args: False
    t._gate_required = True
    out = t._run(branch="x", base="main", title="t", body="b")
    assert out.startswith("DENIED:")


@patch("orgos.tools.github_pr_tool._gh_post")
def test_pr_tool_calls_api_when_approved(mock_post):
    mock_post.return_value = {"html_url": "https://github.com/o/r/pull/1"}
    t = GitHubOpenPRTool()
    t.approval_fn = lambda role, name, args: True
    t._gate_required = True
    out = t._run(branch="x", base="main", title="t", body="b")
    assert out == "https://github.com/o/r/pull/1"


def test_pr_tool_passes_role_and_name_to_approval_fn():
    t = GitHubOpenPRTool()
    t._agent_role = "release-manager"
    t._gate_required = True
    captured = {}

    def approve(role, name, args):
        captured["role"] = role
        captured["name"] = name
        captured["args"] = args
        return False

    t.approval_fn = approve
    t._run(branch="agile/x", base="main", title="t", body="b")
    assert captured["role"] == "release-manager"
    assert captured["name"] == "github_open_pr"
    assert captured["args"]["branch"] == "agile/x"
