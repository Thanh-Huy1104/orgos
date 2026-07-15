"""Tests for the HEARTBEAT conductor (Plan 4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from orgos.agile.conductor import (
    Conductor,
    BootResult,
    _extract_section,
    _extract_next_action,
    _estimate_scope,
)
from orgos.spawn.contracts import TaskBrief


@pytest.fixture
def agents_dir(tmp_path: Path) -> Path:
    root = tmp_path / "agents"
    root.mkdir()
    agent = root / "architect"
    agent.mkdir(parents=True)
    agent.joinpath("heartbeat.md").write_text(
        "---\nversion: 1.0.0\nlayer: specific\nagent_name: Architect_Agent\n---\n\n"
        "# HEARTBEAT - Architect\n\n"
        "## Current Task\n\n"
        "Refactor the authentication module to use JWT instead of session tokens.\n\n"
        "## Next Actions\n\n"
        "1. Write JWT validation middleware in auth/jwt.py\n"
        "2. Update tests/test_auth.py with JWT fixtures\n"
        "3. Remove session-token code paths\n\n"
        "## Recent Session Summary\n\n"
        "Last session: reviewed PR #42, approved architecture for the payment module.\n"
    )
    return root


@pytest.fixture
def agents_dir_vague(tmp_path: Path) -> Path:
    root = tmp_path / "agents"
    root.mkdir()
    agent = root / "po"
    agent.mkdir(parents=True)
    agent.joinpath("heartbeat.md").write_text(
        "---\nversion: 1.0.0\nlayer: specific\nagent_name: PO_Agent\n---\n\n"
        "ok"
    )
    return root


class TestExtractSection:
    def test_extracts_named_section(self):
        body = "## Next Actions\nDo the thing.\n\n## Other\nSkip this."
        result = _extract_section(body, "Next Actions")
        assert result == "Do the thing."

    def test_returns_none_for_missing_section(self):
        body = "## Status\nAll good."
        assert _extract_section(body, "Next Actions") is None

    def test_extracts_multi_line_section(self):
        body = "## Current Task\nLine 1\nLine 2\n\nLine 3\n\n## Next\nOther."
        result = _extract_section(body, "Current Task")
        assert "Line 1" in result
        assert "Line 3" in result
        assert "Other" not in result

    def test_extracts_last_section(self):
        body = "## First\nA\n\n## Last\nB"
        result = _extract_section(body, "Last")
        assert result == "B"


class TestExtractNextAction:
    def test_prefers_next_actions(self):
        body = "## Next Actions\nPriority action.\n\n## Current Task\nLess important."
        result = _extract_next_action(body)
        assert result == "Priority action."

    def test_falls_back_to_current_task(self):
        body = "## Current Task\nDo this now."
        result = _extract_next_action(body)
        assert result == "Do this now."

    def test_falls_back_to_current_phase(self):
        body = "## Current Phase\nImplementing auth."
        result = _extract_next_action(body)
        assert result == "Implementing auth."

    def test_falls_back_to_full_body(self):
        body = "No standard sections here. Just do the work."
        result = _extract_next_action(body)
        assert result == body


class TestEstimateScope:
    def test_detects_file_paths(self):
        text = "Write tests/test_auth.py and src/auth/jwt.py"
        files, loc = _estimate_scope(text)
        assert files >= 2

    def test_no_files_returns_zero(self):
        text = "Refactor the login flow."
        files, loc = _estimate_scope(text)
        assert files == 0


class TestConductorBoot:
    def test_boots_agent_from_heartbeat(self, agents_dir):
        c = Conductor(agents_dir)
        result = c.boot("architect")
        assert isinstance(result, BootResult)
        assert result.agent_name == "architect"
        assert isinstance(result.brief, TaskBrief)
        assert "Write JWT" in result.next_action

    def test_boot_extracts_next_action_section(self, agents_dir):
        c = Conductor(agents_dir)
        result = c.boot("architect")
        assert "1. Write JWT" in result.next_action
        assert "Refactor" not in result.next_action  # prefers Next Actions over Current Task

    def test_boot_produces_valid_brief(self, agents_dir):
        c = Conductor(agents_dir)
        result = c.boot("architect")
        brief = result.brief
        assert brief.objective
        assert len(brief.objective.split()) >= 4
        assert brief.underspecified() is None

    def test_boot_with_vague_heartbeat_warns(self, agents_dir_vague):
        c = Conductor(agents_dir_vague)
        result = c.boot("po")
        assert not result.scope_ok
        assert len(result.warnings) > 0

    def test_boot_rejects_underscore_name(self, agents_dir):
        c = Conductor(agents_dir)
        with pytest.raises(ValueError, match="start with"):
            c.boot("_principles")

    def test_boot_missing_agent_raises(self, agents_dir):
        c = Conductor(agents_dir)
        with pytest.raises(Exception):
            c.boot("nonexistent")

    def test_boot_result_has_timestamp(self, agents_dir):
        c = Conductor(agents_dir)
        result = c.boot("architect")
        assert result.boots_at
        assert "T" in result.boots_at  # ISO 8601

    def test_boot_with_scope_check_raises_on_bad_scope(self, agents_dir_vague):
        c = Conductor(agents_dir_vague)
        with pytest.raises(ValueError, match="boot failed"):
            c.boot_with_scope_check("po")

    def test_boot_with_scope_check_passes_on_good_scope(self, agents_dir):
        c = Conductor(agents_dir)
        result = c.boot_with_scope_check("architect")
        assert result.scope_ok
