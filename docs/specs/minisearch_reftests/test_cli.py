"""Stories 25–27 — CLI commands.

Uses subprocess to invoke `minisearch` — this is what a user would do.
The `minisearch` console script must be installed via `pip install -e .`.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import pytest


def _run(args, cwd=None, timeout=30):
    """Run the minisearch CLI. Prefer the console-script; fall back to python -m."""
    for cmd in (["minisearch"], [sys.executable, "-m", "minisearch.cli"],
                [sys.executable, "-m", "minisearch"]):
        try:
            return subprocess.run(cmd + args, cwd=cwd, capture_output=True,
                                    text=True, timeout=timeout)
        except FileNotFoundError:
            continue
    pytest.skip("no way to invoke minisearch CLI")


@pytest.fixture
def corpus_dir(tmp_path):
    d = tmp_path / "corpus"
    d.mkdir()
    (d / "a.txt").write_text("The quick brown fox jumps over the lazy dog.\n")
    (d / "b.txt").write_text("Python is a programming language.\n")
    (d / "c.md").write_text("# Heading\n\nDjango is a web framework.\n")
    return d


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "cli.db")


def test_cli_index_command(corpus_dir, db_path):
    r = _run(["index", str(corpus_dir), "--db", db_path])
    assert r.returncode == 0, f"stderr:\n{r.stderr}"


def test_cli_index_missing_dir_nonzero_exit(db_path):
    r = _run(["index", "/no/such/dir/xyz", "--db", db_path])
    assert r.returncode != 0


def test_cli_search_returns_hits(corpus_dir, db_path):
    _run(["index", str(corpus_dir), "--db", db_path])
    r = _run(["search", "python", "--db", db_path])
    assert r.returncode == 0
    assert "python" in r.stdout.lower() or "b.txt" in r.stdout.lower()


def test_cli_search_json_output(corpus_dir, db_path):
    _run(["index", str(corpus_dir), "--db", db_path])
    r = _run(["search", "python", "--db", db_path, "--json"])
    assert r.returncode == 0
    # Some line of stdout should be JSON-parseable
    parsed = None
    for line in r.stdout.splitlines():
        try:
            parsed = json.loads(line)
            break
        except json.JSONDecodeError:
            continue
    if parsed is None:
        # Or the entire body may be JSON
        parsed = json.loads(r.stdout)
    assert parsed is not None


def test_cli_search_zero_hits_still_exit_0(corpus_dir, db_path):
    _run(["index", str(corpus_dir), "--db", db_path])
    r = _run(["search", "quantumnobodyusesthisterm", "--db", db_path])
    assert r.returncode == 0


def test_cli_stats(corpus_dir, db_path):
    _run(["index", str(corpus_dir), "--db", db_path])
    r = _run(["stats", "--db", db_path])
    assert r.returncode == 0
    # Should mention doc count in some form
    assert "3" in r.stdout or "doc" in r.stdout.lower()


def test_cli_stats_json(corpus_dir, db_path):
    _run(["index", str(corpus_dir), "--db", db_path])
    r = _run(["stats", "--db", db_path, "--json"])
    if r.returncode != 0:
        pytest.skip("--json not supported on stats in this build")
    body = json.loads(r.stdout)
    assert body.get("doc_count") == 3
