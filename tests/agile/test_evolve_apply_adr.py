import subprocess
from pathlib import Path

import pytest

from orgos.pm import PMStore
from orgos.evolve import apply_adr


@pytest.fixture
def git_repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    cfg = tmp_path / "config" / "org.yaml"
    cfg.parent.mkdir()
    cfg.write_text("departments: []\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
    return tmp_path


def test_apply_adr_writes_file_and_commits(git_repo, monkeypatch):
    monkeypatch.chdir(git_repo)
    pm = PMStore("./pm.db")
    aid = pm.create_adr(
        sprint_id="s1", kind="REMOVE_ROLE",
        before_yaml="departments: []\n",
        after_yaml="departments:\n  - name: new\n",
        rationale="test",
    )
    apply_adr(pm, aid, config_path=Path("config/org.yaml"))
    text = (git_repo / "config" / "org.yaml").read_text()
    assert "new" in text
    rows = pm.list_adrs(status="applied")
    assert any(r["id"] == aid for r in rows)


def test_apply_adr_rejects_non_pending(git_repo, monkeypatch):
    monkeypatch.chdir(git_repo)
    pm = PMStore("./pm.db")
    aid = pm.create_adr("s1", "REMOVE_ROLE", "before", "after", "r")
    pm.set_adr_status(aid, "rejected")
    with pytest.raises(ValueError):
        apply_adr(pm, aid, config_path=Path("config/org.yaml"))
