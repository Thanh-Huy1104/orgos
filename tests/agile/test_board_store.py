"""Tests for BoardStore — CRUD, transitions, filtering, dependencies."""

from __future__ import annotations

from pathlib import Path

import pytest

from orgos.agile.board_store import (
    BoardError, BoardStore, InvalidTransition, VALID_TYPES,
)


@pytest.fixture
def board(tmp_path: Path) -> BoardStore:
    return BoardStore(tmp_path)


class TestDraft:
    def test_creates_story_in_draft_state(self, board):
        s = board.draft_story(issue_id="A", title="Add x", body="do x",
                               story_type="feature", priority=10)
        assert s.state == "draft"
        assert s.type == "feature"
        assert s.priority == 10

    def test_rejects_invalid_type(self, board):
        with pytest.raises(BoardError):
            board.draft_story(issue_id="A", title="t", body="b",
                               story_type="not-a-type")

    def test_rejects_duplicate_issue_id(self, board):
        board.draft_story(issue_id="A", title="t", body="b",
                          story_type="feature")
        with pytest.raises(BoardError):
            board.draft_story(issue_id="A", title="t2", body="b",
                               story_type="feature")


class TestTransitions:
    def test_full_happy_path(self, board):
        board.draft_story(issue_id="A", title="t", body="b",
                          story_type="feature")
        board.transition("A", "refinement", actor="sm")
        board.transition("A", "ready", actor="sm")
        board.transition("A", "in_progress", actor="w")
        board.transition("A", "review", actor="w")
        board.transition("A", "done", actor="r")
        assert board.read("A").state == "done"

    def test_illegal_transition_rejected(self, board):
        board.draft_story(issue_id="A", title="t", body="b",
                          story_type="feature")
        with pytest.raises(InvalidTransition):
            board.transition("A", "done", actor="w")

    def test_done_is_terminal(self, board):
        board.draft_story(issue_id="A", title="t", body="b",
                          story_type="feature")
        for s in ("refinement", "ready", "in_progress", "review", "done"):
            board.transition("A", s, actor="sm")
        with pytest.raises(InvalidTransition):
            board.transition("A", "in_progress", actor="w")

    def test_blocked_can_recover(self, board):
        board.draft_story(issue_id="A", title="t", body="b",
                          story_type="feature")
        board.transition("A", "refinement", actor="sm")
        board.transition("A", "blocked", actor="sm")
        board.transition("A", "refinement", actor="sm")
        assert board.read("A").state == "refinement"


class TestTypeFilter:
    def test_architect_pulls_architecture_and_feature(self, board):
        board.draft_story(issue_id="A", title="arch", body="b",
                          story_type="architecture")
        board.draft_story(issue_id="B", title="feat", body="b",
                          story_type="feature")
        board.draft_story(issue_id="C", title="test", body="b",
                          story_type="test")
        for iid in ("A", "B", "C"):
            board.transition(iid, "refinement", actor="sm")
            board.transition(iid, "ready", actor="sm")
        ready = {s.issue_id for s in board.list_ready_for_type("architect")}
        assert ready == {"A", "B"}

    def test_test_worker_only_pulls_test(self, board):
        board.draft_story(issue_id="A", title="arch", body="b",
                          story_type="architecture")
        board.draft_story(issue_id="B", title="test", body="b",
                          story_type="test")
        for iid in ("A", "B"):
            board.transition(iid, "refinement", actor="sm")
            board.transition(iid, "ready", actor="sm")
        ready = [s.issue_id for s in board.list_ready_for_type("test")]
        assert ready == ["B"]

    def test_priority_ordering(self, board):
        board.draft_story(issue_id="LOW", title="t", body="b",
                          story_type="feature", priority=1)
        board.draft_story(issue_id="HIGH", title="t", body="b",
                          story_type="feature", priority=99)
        for iid in ("LOW", "HIGH"):
            board.transition(iid, "refinement", actor="sm")
            board.transition(iid, "ready", actor="sm")
        ready = [s.issue_id for s in board.list_ready_for_type("architect")]
        assert ready[0] == "HIGH"


class TestDependencies:
    def test_dep_not_done_hides_story(self, board):
        board.draft_story(issue_id="DEP", title="dep", body="b",
                          story_type="feature")
        b_story = board.draft_story(issue_id="B", title="child", body="b",
                                     story_type="feature")
        b_story.depends_on = ["DEP"]
        board._write_story(b_story)
        board.transition("DEP", "refinement", actor="sm")
        board.transition("DEP", "ready", actor="sm")
        board.transition("B", "refinement", actor="sm")
        board.transition("B", "ready", actor="sm")
        ready = {s.issue_id for s in board.list_ready_for_type("architect")}
        # DEP is ready and available; B waits for DEP to be done
        assert "DEP" in ready
        assert "B" not in ready

    def test_dep_done_unblocks_story(self, board):
        board.draft_story(issue_id="DEP", title="dep", body="b",
                          story_type="feature")
        b_story = board.draft_story(issue_id="B", title="child", body="b",
                                     story_type="feature")
        b_story.depends_on = ["DEP"]
        board._write_story(b_story)
        # Move DEP through the full lifecycle to done
        for s in ("refinement", "ready", "in_progress", "review", "done"):
            board.transition("DEP", s, actor="a")
        board.transition("B", "refinement", actor="sm")
        board.transition("B", "ready", actor="sm")
        ready = {s.issue_id for s in board.list_ready_for_type("architect")}
        assert "B" in ready

    def test_missing_dep_reference_blocks_story(self, board):
        b_story = board.draft_story(issue_id="B", title="child", body="b",
                                     story_type="feature")
        b_story.depends_on = ["NEVER-EXISTED"]
        board._write_story(b_story)
        board.transition("B", "refinement", actor="sm")
        board.transition("B", "ready", actor="sm")
        ready = {s.issue_id for s in board.list_ready_for_type("architect")}
        assert "B" not in ready


class TestAuditTrail:
    def test_actions_recorded(self, board):
        board.draft_story(issue_id="A", title="t", body="b",
                          story_type="feature")
        board.transition("A", "refinement", actor="sm")
        board.add_poker_vote("A", voter="architect", points=3,
                              justification="looks small")
        board.add_signoff("A", role="architect", actor="architect")
        board.transition("A", "ready", actor="sm")
        trail = board.audit_trail("A")
        actions = [e["action"] for e in trail]
        assert "draft_story" in actions
        assert "transition" in actions
        assert "poker_vote" in actions
        assert "signoff" in actions

    def test_second_vote_by_same_voter_overwrites(self, board):
        board.draft_story(issue_id="A", title="t", body="b",
                          story_type="feature")
        board.add_poker_vote("A", voter="arch", points=3, justification="j1")
        board.add_poker_vote("A", voter="arch", points=8, justification="j2")
        story = board.read("A")
        # Only one vote per voter
        arch_votes = [v for v in story.votes if v["voter"] == "arch"]
        assert len(arch_votes) == 1
        assert arch_votes[0]["points"] == 8


class TestCounters:
    def test_counts_by_state_reflects_transitions(self, board):
        board.draft_story(issue_id="A", title="t", body="b", story_type="feature")
        board.draft_story(issue_id="B", title="t", body="b", story_type="feature")
        board.transition("A", "refinement", actor="sm")
        board.transition("A", "ready", actor="sm")
        counts = board.counts_by_state()
        assert counts["draft"] == 1
        assert counts["ready"] == 1
        assert counts["done"] == 0
