"""Tests for the AC acceptance gate (Fix §A1)."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from orgos.agile.ac_gate import (
    ACVerdict, AcceptanceVerdict, _parse_grade_json,
    grade_acceptance_criteria,
)


@dataclass
class _Story:
    issue_id: str
    title: str
    body: str
    type: str = "feature"
    commit_sha: str = ""
    acceptance_criteria: list = field(default_factory=list)


@pytest.fixture
def repo_with_commit(tmp_path):
    """Init a git repo, make a commit, return the path + commit sha."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "app.py").write_text("def health(): return {'status': 'ok'}\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "add health"], cwd=tmp_path, check=True)
    r = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path,
        capture_output=True, text=True, check=True,
    )
    return tmp_path, r.stdout.strip()


class TestNoACIsAccept:
    def test_empty_ac_returns_accept_trivially(self):
        story = _Story("S1", "t", "b", "feature", "abc123", [])
        verdict = grade_acceptance_criteria(
            story=story, integration_worktree=Path("/tmp"),
            model="mock",
        )
        assert verdict.accept is True
        assert verdict.per_bullet == []
        assert verdict.degraded is False


class TestSpawnerContract:
    def test_all_met_returns_accept(self, repo_with_commit):
        wt, sha = repo_with_commit
        story = _Story(
            "S1", "add /health", "should return ok", "feature", sha,
            ["Returns 200 on GET /health", "Response body is JSON"],
        )

        def fake_spawner(*, prompt, model):
            result = MagicMock()
            result.tasks_output = [
                MagicMock(raw='{"verdicts":['
                              '{"ac":"Returns 200","verdict":"MET","reason":"code returns status ok"},'
                              '{"ac":"Response body is JSON","verdict":"MET","reason":"dict return"}'
                              '], "accept": true, "reason_if_reject": ""}')
            ]
            result.total_tokens_input = 500
            result.total_tokens_output = 80
            return result

        verdict = grade_acceptance_criteria(
            story=story, integration_worktree=wt, model="mock",
            spawner=fake_spawner,
        )
        assert verdict.accept is True
        assert verdict.met_count == 2
        assert verdict.unmet_count == 0
        assert verdict.tokens_input == 500

    def test_any_unmet_forces_reject(self, repo_with_commit):
        wt, sha = repo_with_commit
        story = _Story(
            "S2", "add /health", "should return ok", "feature", sha,
            ["Returns 200", "Rate-limited to 10/min"],
        )

        def fake_spawner(*, prompt, model):
            result = MagicMock()
            result.tasks_output = [
                MagicMock(raw='{"verdicts":['
                              '{"ac":"Returns 200","verdict":"MET","reason":""},'
                              '{"ac":"Rate-limited to 10/min","verdict":"UNMET",'
                              '"reason":"no rate limiter in diff"}'
                              '], "accept": true, "reason_if_reject": ""}')
            ]
            return result

        verdict = grade_acceptance_criteria(
            story=story, integration_worktree=wt, model="mock",
            spawner=fake_spawner,
        )
        # Model said accept=true, but we override to False because there's
        # an UNMET (defense in depth per the gate's contract).
        assert verdict.accept is False
        assert verdict.unmet_count == 1
        assert "Rate-limited" in verdict.reason

    def test_uncertain_still_accepts(self, repo_with_commit):
        wt, sha = repo_with_commit
        story = _Story(
            "S3", "backtest engine", "vectorized replay", "architecture", sha,
            ["Completes 10k bars in < 500ms"],
        )

        def fake_spawner(*, prompt, model):
            result = MagicMock()
            result.tasks_output = [
                MagicMock(raw='{"verdicts":['
                              '{"ac":"perf","verdict":"UNCERTAIN","reason":"needs runtime measurement"}'
                              '], "accept": true, "reason_if_reject": ""}')
            ]
            return result

        verdict = grade_acceptance_criteria(
            story=story, integration_worktree=wt, model="mock",
            spawner=fake_spawner,
        )
        # UNCERTAIN doesn't reject — only UNMET does
        assert verdict.accept is True
        assert verdict.unmet_count == 0


class TestFailOpen:
    def test_spawner_exception_returns_degraded_accept(self, repo_with_commit):
        wt, sha = repo_with_commit
        story = _Story("S1", "t", "b", "feature", sha, ["ac1"])

        def broken_spawner(*, prompt, model):
            raise RuntimeError("provider unreachable")

        verdict = grade_acceptance_criteria(
            story=story, integration_worktree=wt, model="mock",
            spawner=broken_spawner,
        )
        # Fail OPEN — don't strand the story on a transient hiccup
        assert verdict.accept is True
        assert verdict.degraded is True
        assert "unreachable" in verdict.reason

    def test_garbage_json_returns_degraded_accept(self, repo_with_commit):
        wt, sha = repo_with_commit
        story = _Story("S1", "t", "b", "feature", sha, ["ac1"])

        def garbage_spawner(*, prompt, model):
            result = MagicMock()
            result.tasks_output = [MagicMock(raw="not JSON at all lol")]
            return result

        verdict = grade_acceptance_criteria(
            story=story, integration_worktree=wt, model="mock",
            spawner=garbage_spawner,
        )
        assert verdict.accept is True
        assert verdict.degraded is True


class TestJSONParsing:
    def test_bare_object(self):
        raw = '{"verdicts": [], "accept": true}'
        parsed = _parse_grade_json(raw)
        assert parsed == {"verdicts": [], "accept": True}

    def test_object_in_envelope(self):
        raw = '{"role":"po","status":"completed","payload":{"verdicts":[],"accept":false,"reason_if_reject":"x"}}'
        parsed = _parse_grade_json(raw)
        assert parsed["accept"] is False
        assert parsed["reason_if_reject"] == "x"

    def test_object_embedded_in_prose(self):
        raw = 'Here is my grade:\n\n{"verdicts": [], "accept": true}\n\nThanks.'
        parsed = _parse_grade_json(raw)
        assert parsed == {"verdicts": [], "accept": True}

    def test_first_valid_wins_when_multiple(self):
        raw = '{"noise": 1} {"verdicts": [], "accept": true}'
        parsed = _parse_grade_json(raw)
        # Only the second object is grade-shaped
        assert parsed == {"verdicts": [], "accept": True}
