import json
from unittest.mock import patch, MagicMock

import pytest

from orgos.tools.github_issue_tool import (
    GitHubListIssuesTool, GitHubGetIssueTool,
)


def _mock_issue(num=1, labels=("agent-eligible",)):
    return {
        "number": num, "title": f"t{num}", "body": "b",
        "labels": [{"name": l} for l in labels],
        "html_url": f"https://github.com/o/r/issues/{num}",
    }


def test_list_issues_category_read():
    assert GitHubListIssuesTool().tool_category == "read"


@patch("orgos.tools.github_issue_tool._gh_get")
@patch("orgos.tools.github_issue_tool._repo")
def test_list_issues_returns_normalised_dicts(mock_repo, mock_get):
    mock_repo.return_value = "owner/repo"
    mock_get.return_value = [_mock_issue(1), _mock_issue(2, labels=("bug",))]
    out = GitHubListIssuesTool()._run(labels=None, state="open", limit=10)
    data = json.loads(out)
    assert len(data) == 2
    assert data[0]["issue_id"] == "1"
    assert "agent-eligible" in data[0]["labels"]


@patch("orgos.tools.github_issue_tool._gh_get")
@patch("orgos.tools.github_issue_tool._repo")
def test_list_issues_filters_by_label(mock_repo, mock_get):
    mock_repo.return_value = "owner/repo"
    mock_get.return_value = [_mock_issue(1, labels=("agent-eligible",)),
                              _mock_issue(2, labels=("docs",))]
    out = GitHubListIssuesTool()._run(labels=["agent-eligible"], state="open", limit=10)
    data = json.loads(out)
    assert [d["issue_id"] for d in data] == ["1"]


@patch("orgos.tools.github_issue_tool._gh_get")
@patch("orgos.tools.github_issue_tool._repo")
def test_get_issue_returns_one(mock_repo, mock_get):
    mock_repo.return_value = "owner/repo"
    mock_get.return_value = _mock_issue(42)
    out = GitHubGetIssueTool()._run(number=42)
    assert json.loads(out)["issue_id"] == "42"
