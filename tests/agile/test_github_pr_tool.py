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
    t.approval_fn = lambda _: False
    t._gate_required = True
    out = t._run(branch="x", base="main", title="t", body="b")
    assert out.startswith("DENIED:")


@patch("orgos.tools.github_pr_tool._gh_post")
def test_pr_tool_calls_api_when_approved(mock_post):
    mock_post.return_value = {"html_url": "https://github.com/o/r/pull/1"}
    t = GitHubOpenPRTool()
    t.approval_fn = lambda _: True
    t._gate_required = True
    out = t._run(branch="x", base="main", title="t", body="b")
    assert out == "https://github.com/o/r/pull/1"
