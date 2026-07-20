"""Tests for §D2 customer agent review."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest

from orgos.agile.board_store import BoardStore
from orgos.agile.customer_review import (
    CUSTOMER_MAX_REJECTS, CustomerFeedback,
    _count_previous_customer_rejects, _parse_review_jsonl,
    _pick_stories_to_review, run_customer_review,
)


@pytest.fixture
def repo_with_wiki(tmp_path):
    """Repo with wiki/SPEC.md and integration_worktree structure."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "SPEC.md").write_text(
        "# Spec\n\n"
        "## Story: Add /health endpoint\n"
        "Files: app.py\n"
        "AC:\n"
        "  - GET /health returns 200\n"
        "  - Response body is JSON {status: ok}\n"
    )
    (tmp_path / "app.py").write_text("def health():\n    return 'ok'\n")  # plain text, not JSON!
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    return tmp_path


def _make_ws(root):
    ws = MagicMock()
    ws.root = root
    ws.wiki_dir = root / "wiki"
    ws.integration_worktree = root
    ws.source_repo = root
    return ws


def _draft_done_story(board, issue_id, title="test story"):
    board.draft_story(
        issue_id=issue_id, title=title, body="build it",
        story_type="feature", files_to_touch=["app.py"],
        acceptance_criteria=["GET /health returns 200", "JSON body"],
    )
    board.transition(issue_id, "refinement", actor="sm")
    board.transition(issue_id, "ready", actor="sm")
    board.transition(issue_id, "in_progress", actor="arch")
    board.transition(issue_id, "review", actor="arch")
    board.set_commit(issue_id, "abc1234", actor="arch")
    board.transition(issue_id, "pending_acceptance", actor="merge")
    board.transition(issue_id, "done", actor="po")


class TestParseReviewJSONL:
    def test_valid_jsonl_parsed(self):
        raw = (
            '{"story_id": "S1", "verdict": "accept", "reason": "matches spec"}\n'
            '{"story_id": "S2", "verdict": "reject", "reason": "wrong shape", '
            '"spec_quote": "returns JSON body"}\n'
        )
        result = _parse_review_jsonl(raw)
        assert len(result) == 2
        assert result[0].story_id == "S1"
        assert result[0].verdict == "accept"
        assert result[1].verdict == "reject"
        assert result[1].spec_quote == "returns JSON body"

    def test_bad_lines_skipped(self):
        raw = (
            "some prose\n"
            '{"story_id": "S1", "verdict": "accept"}\n'
            "not json at all\n"
            '{"verdict": "no story_id"}\n'
            '{"story_id": "S2", "verdict": "invalid_verdict"}\n'
        )
        result = _parse_review_jsonl(raw)
        assert len(result) == 1
        assert result[0].story_id == "S1"

    def test_empty_input(self):
        assert _parse_review_jsonl("") == []


class TestRejectCounting:
    def test_no_prior_rejects(self, tmp_path):
        board = BoardStore(tmp_path / "board")
        _draft_done_story(board, "S1")
        assert _count_previous_customer_rejects(board.read("S1")) == 0

    def test_counts_customer_reject_comments(self, tmp_path):
        board = BoardStore(tmp_path / "board")
        _draft_done_story(board, "S1")
        board.add_comment("S1", author="customer", body="customer reject #1: bad")
        board.add_comment("S1", author="customer", body="customer reject #2: still bad")
        board.add_comment("S1", author="po", body="unrelated")
        assert _count_previous_customer_rejects(board.read("S1")) == 2


class TestPickStoriesToReview:
    def test_only_done_stories(self, tmp_path):
        board = BoardStore(tmp_path / "board")
        _draft_done_story(board, "S1")
        # A story that's only in ready — should NOT be picked
        board.draft_story(issue_id="S2", title="t", body="b",
                          story_type="feature", files_to_touch=["x.py"])
        board.transition("S2", "refinement", actor="sm")
        board.transition("S2", "ready", actor="sm")
        picked = _pick_stories_to_review(board)
        assert len(picked) == 1
        assert picked[0].issue_id == "S1"

    def test_max_rejects_filter(self, tmp_path):
        board = BoardStore(tmp_path / "board")
        _draft_done_story(board, "S1")
        # Add CUSTOMER_MAX_REJECTS reject comments
        for i in range(CUSTOMER_MAX_REJECTS):
            board.add_comment("S1", author="customer",
                              body=f"customer reject #{i+1}: bad")
        picked = _pick_stories_to_review(board)
        assert picked == []


class TestRunCustomerReview:
    def test_accept_verdict_leaves_story_done(self, repo_with_wiki):
        board = BoardStore(repo_with_wiki / "board")
        _draft_done_story(board, "S1", "Add /health endpoint")
        ws = _make_ws(repo_with_wiki)
        emitter = MagicMock()

        def fake_spawner(*, prompt, model):
            result = MagicMock()
            result.tasks_output = [MagicMock(raw=(
                '{"story_id": "S1", "verdict": "accept", "reason": "matches spec"}'
            ))]
            return result

        review = run_customer_review(
            workspace=ws, board=board, model="mock",
            emitter=emitter, spawner=fake_spawner,
        )
        assert review.accepted == 1
        assert review.rejected == 0
        assert board.read("S1").state == "done"

    def test_reject_verdict_sends_story_to_blocked(self, repo_with_wiki):
        board = BoardStore(repo_with_wiki / "board")
        _draft_done_story(board, "S1", "Add /health endpoint")
        ws = _make_ws(repo_with_wiki)
        emitter = MagicMock()

        def fake_spawner(*, prompt, model):
            result = MagicMock()
            result.tasks_output = [MagicMock(raw=(
                '{"story_id": "S1", "verdict": "reject", '
                '"reason": "returns plain text not JSON", '
                '"spec_quote": "Response body is JSON"}'
            ))]
            return result

        review = run_customer_review(
            workspace=ws, board=board, model="mock",
            emitter=emitter, spawner=fake_spawner,
        )
        assert review.rejected == 1
        assert board.read("S1").state == "blocked"
        # customer_reject event emitted
        actions = [c.args[0] for c in emitter.emit.call_args_list]
        assert "customer_reject" in actions

    def test_no_spec_returns_degraded(self, tmp_path):
        # workspace with NO wiki/SPEC.md
        board = BoardStore(tmp_path / "board")
        _draft_done_story(board, "S1")
        ws = MagicMock()
        ws.root = tmp_path
        ws.wiki_dir = tmp_path / "no-such-wiki"
        ws.integration_worktree = tmp_path
        ws.source_repo = tmp_path
        review = run_customer_review(
            workspace=ws, board=board, model="mock",
            emitter=MagicMock(), spawner=lambda **_: None,
        )
        assert review.degraded is True
        assert "SPEC" in review.reason_degraded

    def test_no_done_stories_no_op(self, repo_with_wiki):
        board = BoardStore(repo_with_wiki / "board")  # empty
        ws = _make_ws(repo_with_wiki)
        review = run_customer_review(
            workspace=ws, board=board, model="mock",
            emitter=MagicMock(), spawner=lambda **_: None,
        )
        assert review.reviewed == 0

    def test_spawner_exception_fails_open(self, repo_with_wiki):
        board = BoardStore(repo_with_wiki / "board")
        _draft_done_story(board, "S1")
        ws = _make_ws(repo_with_wiki)

        def broken_spawner(*, prompt, model):
            raise RuntimeError("provider dead")

        review = run_customer_review(
            workspace=ws, board=board, model="mock",
            emitter=MagicMock(), spawner=broken_spawner,
        )
        assert review.degraded is True
        # Story unchanged
        assert board.read("S1").state == "done"

    def test_max_rejects_prevents_further_review(self, repo_with_wiki):
        board = BoardStore(repo_with_wiki / "board")
        _draft_done_story(board, "S1")
        for i in range(CUSTOMER_MAX_REJECTS):
            board.add_comment("S1", author="customer",
                              body=f"customer reject #{i+1}: bad")
        ws = _make_ws(repo_with_wiki)
        review = run_customer_review(
            workspace=ws, board=board, model="mock",
            emitter=MagicMock(), spawner=lambda **_: None,
        )
        assert review.reviewed == 0  # picked no stories
