import subprocess
from pathlib import Path
from unittest.mock import patch

from orgos.tools.github_repo_tool import GitWorktreePushTool


def test_push_tool_category_sandbox():
    assert GitWorktreePushTool().tool_category == "sandbox"


@patch("subprocess.run")
def test_push_tool_invokes_git_push(mock_run, tmp_path):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="ok", stderr=""
    )
    out = GitWorktreePushTool()._run(branch="agile/abc", worktree_path=str(tmp_path))
    assert "pushed" in out.lower()
    args = mock_run.call_args[0][0]
    assert args[:3] == ["git", "push", "origin"]


@patch("subprocess.run")
def test_push_tool_reports_failure(mock_run, tmp_path):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr="boom",
    )
    out = GitWorktreePushTool()._run(branch="agile/abc", worktree_path=str(tmp_path))
    assert "fail" in out.lower() or "boom" in out
