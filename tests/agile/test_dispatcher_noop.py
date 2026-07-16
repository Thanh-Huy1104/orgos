"""Test the no-op detection logic in Dispatcher._is_noop_completion.

We don't spin up a real spawn — the logic is pure, we just feed
synthetic WorkResults.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from orgos.agile.dispatcher import Dispatcher, WorkResult
from orgos.agile.team_workspace import TeamWorkspace


@pytest.fixture
def dispatcher(tmp_path: Path) -> Dispatcher:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.local"],
                    cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "test"],
                    cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("# test\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    ws = TeamWorkspace.create("t1", tmp_path, goal="g", model="m")
    return Dispatcher(workspace=ws, model="m")


def _result(**envelope_fields) -> WorkResult:
    return WorkResult(
        story_id="X", role="architect", status="no_commit",
        envelope=envelope_fields,
    )


class TestIsNoopCompletion:
    def test_valid_noop(self, dispatcher):
        r = _result(
            status="completed", success_criteria_met=True,
            payload={"files_touched": [], "test_passed": True,
                     "test_command": "pytest -q"},
        )
        assert dispatcher._is_noop_completion(r)

    def test_no_test_run_still_valid(self, dispatcher):
        r = _result(
            status="completed", success_criteria_met=True,
            payload={"files_touched": [], "test_command": ""},
        )
        assert dispatcher._is_noop_completion(r)

    def test_files_touched_rejects(self, dispatcher):
        r = _result(
            status="completed", success_criteria_met=True,
            payload={"files_touched": ["app.py"], "test_passed": True},
        )
        assert not dispatcher._is_noop_completion(r)

    def test_test_failed_rejects(self, dispatcher):
        r = _result(
            status="completed", success_criteria_met=True,
            payload={"files_touched": [], "test_passed": False,
                     "test_command": "pytest -q"},
        )
        assert not dispatcher._is_noop_completion(r)

    def test_status_not_completed_rejects(self, dispatcher):
        r = _result(
            status="failed", success_criteria_met=True,
            payload={"files_touched": []},
        )
        assert not dispatcher._is_noop_completion(r)

    def test_success_criteria_not_met_rejects(self, dispatcher):
        r = _result(
            status="completed", success_criteria_met=False,
            payload={"files_touched": []},
        )
        assert not dispatcher._is_noop_completion(r)

    def test_missing_envelope_rejects(self, dispatcher):
        assert not dispatcher._is_noop_completion(
            WorkResult(story_id="X", role="a", status="no_commit"),
        )

    def test_non_dict_envelope_rejects(self, dispatcher):
        r = WorkResult(story_id="X", role="a", status="no_commit",
                        envelope={"status": "completed"})
        # envelope has status but no payload — should fail through
        assert not dispatcher._is_noop_completion(r)


class TestModelForResolver:
    def test_default_when_no_override(self, tmp_path):
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.email", "t@t.local"],
                        cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.name", "test"],
                        cwd=tmp_path, check=True)
        (tmp_path / "README.md").write_text("")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-qm", "init"],
                        cwd=tmp_path, check=True)
        ws = TeamWorkspace.create("t1", tmp_path, goal="g", model="m")
        d = Dispatcher(workspace=ws, model="default-model")
        assert d._model_for("architect") == "default-model"
        assert d._model_for("po") == "default-model"

    def test_override_takes_precedence(self, tmp_path):
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.email", "t@t.local"],
                        cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.name", "test"],
                        cwd=tmp_path, check=True)
        (tmp_path / "README.md").write_text("")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-qm", "init"],
                        cwd=tmp_path, check=True)
        ws = TeamWorkspace.create("t1", tmp_path, goal="g", model="m")
        d = Dispatcher(
            workspace=ws, model="default-model",
            role_models={"po": "smart-model", "architect": "fast-model"},
        )
        assert d._model_for("po") == "smart-model"
        assert d._model_for("architect") == "fast-model"
        assert d._model_for("test") == "default-model"
