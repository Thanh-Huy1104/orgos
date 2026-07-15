"""Tests for the GitHub board tool (Plan 3)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from orgos.tools.github_board import (
    REQUIRED_ROLES,
    VALID_STATES,
    GitHubBoardTool,
    _state_label,
    _set_state,
)


def _mock_issue_raw(number=1, title="Test Story", labels=None, body=""):
    return {
        "number": number,
        "title": title,
        "body": body,
        "labels": [{"name": l} for l in (labels or [])],
        "html_url": f"https://github.com/o/r/issues/{number}",
    }


def _mock_issue_normalised(number=1, title="Test Story", labels=None, body=""):
    return {
        "number": number,
        "title": title,
        "body": body,
        "labels": list(labels or []),
        "html_url": f"https://github.com/o/r/issues/{number}",
    }


def _mock_labels(*names):
    return [{"name": n} for n in names]


class TestToolCategory:
    def test_board_tool_is_orchestrate(self):
        t = GitHubBoardTool()
        assert t.tool_category == "orchestrate"

    def test_name_is_github_board(self):
        t = GitHubBoardTool()
        assert t.name == "github_board"


class TestDispatch:
    def test_dispatch_unknown_action(self):
        t = GitHubBoardTool()
        result = t._dispatch("invalid_action", "", "", 0, "", "", "", 0, 0)
        assert "error" in result
        assert "unknown action" in result["error"]


class TestDraftStory:
    @patch("orgos.tools.github_board._repo")
    @patch("orgos.tools.github_board._gh_post")
    def test_draft_creates_issue_with_state_draft_label(self, mock_post, mock_repo):
        mock_repo.return_value = "owner/repo"
        mock_post.return_value = _mock_issue_raw(1, labels=["state:draft"])
        t = GitHubBoardTool()
        result = t._do_draft_story("Fix login", "Users cannot log in")
        data = result
        assert data["number"] == 1
        assert "state:draft" in data["labels"]

    def test_draft_requires_title(self):
        t = GitHubBoardTool()
        result = t._do_draft_story("", "body")
        assert "error" in result


class TestReadStory:
    @patch("orgos.tools.github_board._repo")
    @patch("orgos.tools.github_board._gh_get")
    def test_read_returns_normalised_issue(self, mock_get, mock_repo):
        mock_repo.return_value = "owner/repo"
        mock_get.return_value = _mock_issue_raw(42, "Fix bug", ["state:ready"])
        t = GitHubBoardTool()
        result = t._do_read_story(42)
        assert result["number"] == 42
        assert result["title"] == "Fix bug"

    def test_read_requires_number(self):
        t = GitHubBoardTool()
        result = t._do_read_story(0)
        assert "error" in result


class TestRefineStory:
    @patch("orgos.tools.github_board._gh_post_comment")
    def test_refine_posts_role_comment(self, mock_comment):
        mock_comment.return_value = {"id": 1, "body": "**Refinement — architect**\n\nconcern"}
        t = GitHubBoardTool()
        result = t._do_refine_story(1, "architect", "This might break the API.")
        assert "error" not in result
        assert "architect" in result.get("body", "")

    def test_refine_requires_role_and_concern(self):
        t = GitHubBoardTool()
        assert "error" in t._do_refine_story(1, "", "concern")
        assert "error" in t._do_refine_story(1, "architect", "")


class TestSignoffStory:
    @patch("orgos.tools.github_board._current_labels")
    @patch("orgos.tools.github_board._add_label")
    def test_signoff_adds_refined_label(self, mock_add, mock_labels):
        mock_labels.return_value = ["state:refinement"]
        mock_add.side_effect = lambda n, l: {"labels": mock_labels() + [{"name": l}]}
        t = GitHubBoardTool()
        t._do_signoff_story(1, "architect")
        mock_add.assert_called_once_with(1, "refined:architect")

    def test_signoff_rejects_unknown_role(self):
        t = GitHubBoardTool()
        result = t._do_signoff_story(1, "designer")
        assert "error" in result

    def test_all_required_roles_accepted(self):
        t = GitHubBoardTool()
        with patch("orgos.tools.github_board._current_labels", return_value=[]):
            with patch("orgos.tools.github_board._add_label", return_value={"labels": []}):
                for role in REQUIRED_ROLES:
                    result = t._do_signoff_story(1, role)
                    assert "error" not in result, f"role {role} should be accepted"


class TestMarkReady:
    @patch("orgos.tools.github_board._repo")
    @patch("orgos.tools.github_board._current_labels")
    @patch("orgos.tools.github_board._gh_get")
    @patch("orgos.tools.github_board._gh_replace_labels")
    def test_mark_ready_when_all_signoffs_and_in_caps(self, mock_replace, mock_get, mock_labels, mock_repo):
        mock_repo.return_value = "owner/repo"
        mock_get.return_value = _mock_issue_raw(
            1, "Fix login",
            labels=["state:refinement", "refined:architect", "refined:test",
                    "refined:devsecops"],
            body="Acceptance Criteria:\n- Users can log in",
        )
        mock_labels.return_value = ["state:refinement", "refined:architect",
                                    "refined:test", "refined:devsecops"]
        mock_replace.return_value = {"number": 1, "labels": [
            "state:ready", "refined:architect",
            "refined:test", "refined:devsecops"]}

        t = GitHubBoardTool()
        result = t._do_mark_ready(1, estimated_files=2, estimated_loc=100)
        assert "error" not in result

    @patch("orgos.tools.github_board._repo")
    @patch("orgos.tools.github_board._current_labels")
    @patch("orgos.tools.github_board._gh_get")
    def test_mark_ready_blocks_missing_signoffs(self, mock_get, mock_labels, mock_repo):
        mock_repo.return_value = "owner/repo"
        mock_get.return_value = _mock_issue_raw(
            1, "Fix login",
            labels=["state:refinement"],
            body="Acceptance Criteria:\n- Users can log in",
        )
        mock_labels.return_value = ["state:refinement"]

        t = GitHubBoardTool()
        result = t._do_mark_ready(1, estimated_files=2, estimated_loc=100)
        assert "ready" in result
        assert not result["ready"]


class TestListReady:
    @patch("orgos.tools.github_board._list_state_issues")
    def test_list_ready_returns_items(self, mock_list):
        mock_list.return_value = [
            _mock_issue_normalised(1, "Story A", ["state:ready", "p0"]),
            _mock_issue_normalised(2, "Story B", ["state:ready", "p2"]),
        ]
        t = GitHubBoardTool()
        result = t._do_list_ready()
        assert result["count"] == 2
        assert len(result["ready_items"]) == 2

    @patch("orgos.tools.github_board._list_state_issues")
    def test_list_ready_empty(self, mock_list):
        mock_list.return_value = []
        t = GitHubBoardTool()
        result = t._do_list_ready()
        assert result["count"] == 0


class TestPullTop:
    @patch("orgos.tools.github_board._list_state_issues")
    @patch("orgos.tools.github_board._current_labels")
    @patch("orgos.tools.github_board._gh_replace_labels")
    def test_pull_top_moves_to_in_progress(self, mock_replace, mock_labels, mock_list):
        mock_list.return_value = [_mock_issue_normalised(1, "Story A",
                                                          ["state:ready", "p0"])]
        mock_labels.return_value = ["state:ready", "p0"]
        mock_replace.return_value = _mock_issue_raw(1, "Story A",
                                                     ["state:in_progress", "p0"])

        t = GitHubBoardTool()
        result = t._do_pull_top()
        assert result["pulled"]["number"] == 1
        assert "IN_PROGRESS" in result["action"]

    @patch("orgos.tools.github_board._list_state_issues")
    def test_pull_top_no_ready_items(self, mock_list):
        mock_list.return_value = []
        t = GitHubBoardTool()
        result = t._do_pull_top()
        assert "error" in result


class TestUpdateStatus:
    @patch("orgos.tools.github_board._current_labels")
    @patch("orgos.tools.github_board._gh_replace_labels")
    def test_update_to_valid_state(self, mock_replace, mock_labels):
        mock_labels.return_value = ["state:draft"]
        mock_replace.return_value = {}

        t = GitHubBoardTool()
        result = t._do_update_status(1, "review")
        assert "error" not in result


class TestListLabels:
    @patch("orgos.tools.github_board._repo")
    @patch("orgos.tools.github_board._gh_get")
    def test_list_labels_returns_names(self, mock_get, mock_repo):
        mock_repo.return_value = "owner/repo"
        mock_get.return_value = [
            {"name": "state:draft", "color": "ccc"},
            {"name": "state:ready", "color": "0f0"},
            {"name": "refined:architect", "color": "00f"},
        ]
        t = GitHubBoardTool()
        result = t._do_list_labels()
        assert "labels" in result
        assert "state:draft" in result["labels"]


class TestValidStates:
    def test_all_states_are_recognised(self):
        assert set(VALID_STATES) == {"draft", "refinement", "ready", "in_progress",
                                     "review", "done"}
