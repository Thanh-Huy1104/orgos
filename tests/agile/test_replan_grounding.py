"""Replan grounding fixes from the 2026-07-22 TS acceptance run.

Observed drift: sprints 3-5 delivered almost nothing — the PO drafted 5
duplicates of already-merged stories (it only ever saw done COUNTS, never
what was done) and unblocked 0 stories (blocked stories carried no reason).
"""

from __future__ import annotations

import json

from orgos.agile.board_store import BoardStore
from orgos.agile.replan import _REPLAN_BRIEF_TEMPLATE, _fmt_backlog, _fmt_done


def _board_with(tmp_path):
    return BoardStore(tmp_path / "board")


def _draft(board, iid, title="t"):
    board.draft_story(
        issue_id=iid, title=title, body="b", story_type="feature",
        files_to_touch=["f"], acceptance_criteria=["ac"],
    )


class TestBlockedReasonPersistence:
    def test_reason_persisted_on_block(self, tmp_path):
        board = _board_with(tmp_path)
        _draft(board, "S1")
        board.transition("S1", "blocked", actor="po", reason="AC failed 3x: no snippet output")
        assert board.read("S1").blocked_reason == "AC failed 3x: no snippet output"

    def test_reason_cleared_on_unblock(self, tmp_path):
        board = _board_with(tmp_path)
        _draft(board, "S1")
        board.transition("S1", "blocked", actor="po", reason="stuck")
        board.transition("S1", "draft", actor="po", reason="unblocked_by_po_replan")
        assert board.read("S1").blocked_reason == ""

    def test_old_story_files_without_field_still_read(self, tmp_path):
        board = _board_with(tmp_path)
        _draft(board, "S1")
        p = board._story_path("S1")
        data = json.loads(p.read_text())
        data.pop("blocked_reason", None)  # simulate pre-upgrade story file
        p.write_text(json.dumps(data))
        assert board.read("S1").blocked_reason == ""


class TestReplanPromptGrounding:
    def test_backlog_shows_blocked_reason(self, tmp_path):
        board = _board_with(tmp_path)
        _draft(board, "S1", title="highlighter")
        board.transition("S1", "blocked", actor="po", reason="merge_conflict on formatter")
        out = _fmt_backlog(board)
        assert "blocked because: merge_conflict on formatter" in out

    def test_backlog_flags_missing_reason(self, tmp_path):
        board = _board_with(tmp_path)
        _draft(board, "S1")
        board.transition("S1", "blocked", actor="po", reason="")
        assert "(no reason recorded)" in _fmt_backlog(board)

    def test_done_list_names_shipped_stories(self, tmp_path):
        board = _board_with(tmp_path)
        _draft(board, "S1", title="Primitive schema builders")
        for st in ("refinement", "ready", "in_progress", "review", "done"):
            board.transition("S1", st, actor="x")
        out = _fmt_done(board)
        assert "Primitive schema builders" in out
        assert "S1" in out

    def test_done_list_includes_pending_acceptance(self, tmp_path):
        board = _board_with(tmp_path)
        _draft(board, "S2", title="Composite schemas")
        for st in ("refinement", "ready", "in_progress", "review", "pending_acceptance"):
            board.transition("S2", st, actor="x")
        assert "Composite schemas" in _fmt_done(board)

    def test_done_list_empty_board(self, tmp_path):
        assert "(nothing done yet)" in _fmt_done(_board_with(tmp_path))

    def test_template_has_done_block_and_blocked_first_guidance(self):
        assert "{done_block}" in _REPLAN_BRIEF_TEMPLATE
        assert "ALREADY SHIPPED" in _REPLAN_BRIEF_TEMPLATE
        assert "BLOCKED stories FIRST" in _REPLAN_BRIEF_TEMPLATE
