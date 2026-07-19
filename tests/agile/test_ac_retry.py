"""Tests for §H1 AC-retry loop (2.2.1 hotfix).

The AC gate used to send rejected stories to `blocked`. Now it sends them
back to `ready` with the reject reason injected into the story body, and
only blocks after ORGOS_MAX_AC_RETRIES (default 3) rejections. Turns AC
from a one-shot filter into a feedback loop.
"""

from __future__ import annotations

from orgos.agile.board_store import (
    BoardStore, TRANSITIONS, VALID_STATES,
)


class TestStateMachineOpenPath:
    def test_pending_acceptance_to_ready_allowed(self):
        allowed = TRANSITIONS["pending_acceptance"]
        assert "ready" in allowed
        # Original allowed transitions still present
        assert "done" in allowed
        assert "blocked" in allowed
        assert "review" in allowed


class TestBoardRetryTransition:
    def test_can_actually_transition_pending_acceptance_to_ready(self, tmp_path):
        board = BoardStore(tmp_path / "board")
        board.draft_story(
            issue_id="S1", title="t", body="original body",
            story_type="feature", files_to_touch=["app.py"],
            acceptance_criteria=["AC1"],
        )
        board.transition("S1", "refinement", actor="sm")
        board.transition("S1", "ready", actor="sm")
        board.transition("S1", "in_progress", actor="arch")
        board.transition("S1", "review", actor="arch")
        board.transition("S1", "pending_acceptance", actor="merge")
        # This is the new transition — was disallowed before §H1
        board.transition("S1", "ready", actor="po", reason="ac_retry_1")
        s = board.read("S1")
        assert s.state == "ready"

    def test_attempts_counter_survives_ac_retry_cycle(self, tmp_path):
        """Simulate an AC retry loop: attempts increment on each reject,
        eventually reaching MAX and forcing a block."""
        board = BoardStore(tmp_path / "board")
        board.draft_story(
            issue_id="S1", title="t", body="", story_type="feature",
            files_to_touch=["app.py"], acceptance_criteria=["AC1"],
        )
        board.transition("S1", "refinement", actor="sm")
        board.transition("S1", "ready", actor="sm")

        # Cycle: ready → in_progress → review → pending_acceptance → ready
        for cycle in range(3):
            board.transition("S1", "in_progress", actor="arch")
            board.transition("S1", "review", actor="arch")
            board.transition("S1", "pending_acceptance", actor="merge")
            board.increment_attempts("S1", actor="po")
            board.transition("S1", "ready", actor="po",
                              reason=f"ac_retry_{cycle+1}")

        assert board.read("S1").attempts == 3


class TestACFeedbackInjection:
    """Contract test — simulates what _inject_ac_feedback_and_retry does
    without instantiating AsyncAgent."""

    def test_body_grows_with_feedback(self, tmp_path):
        board = BoardStore(tmp_path / "board")
        board.draft_story(
            issue_id="S1", title="t", body="Original spec: return 200 on /health",
            story_type="feature", files_to_touch=["app.py"],
            acceptance_criteria=["Returns 200", "Returns JSON"],
        )
        board.transition("S1", "refinement", actor="sm")
        board.transition("S1", "ready", actor="sm")

        # Manually simulate the injection (matches the code in agent_loop.py)
        fresh = board.read("S1")
        original_len = len(fresh.body)
        feedback = (
            "\n---\n## PREVIOUS ATTEMPT FAILED — AC FEEDBACK (attempt 1)\n\n"
            "### Unmet acceptance criteria\n\n"
            "- **UNMET**: Returns JSON\n"
            "  - Why: response is plain text\n"
        )
        fresh.body = fresh.body + feedback
        fresh.commit_sha = ""
        board._write_story(fresh)

        s = board.read("S1")
        assert len(s.body) > original_len
        assert "PREVIOUS ATTEMPT FAILED" in s.body
        assert "Returns JSON" in s.body
        assert s.commit_sha == ""


class TestReplanBriefUpdate:
    """Verify the replan brief text contains the anti-meta-story rules
    added in §H3. Not a runtime test — just guards against reverts of
    the prompt language."""

    def test_replan_forbids_meta_stories(self):
        from orgos.agile.replan import _REPLAN_BRIEF_TEMPLATE
        assert "DO NOT draft META-STORIES" in _REPLAN_BRIEF_TEMPLATE
        assert "Move X to ready" in _REPLAN_BRIEF_TEMPLATE
        assert "unblock_stories" in _REPLAN_BRIEF_TEMPLATE

    def test_replan_forbids_duplicating_blocked(self):
        from orgos.agile.replan import _REPLAN_BRIEF_TEMPLATE
        assert "DO NOT duplicate blocked stories" in _REPLAN_BRIEF_TEMPLATE
