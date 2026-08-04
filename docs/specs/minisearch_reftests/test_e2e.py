"""Story 28 — end-to-end integration smoke.

Combines CLI + API and checks they produce consistent results.
This is the "does the whole thing hang together" test.
"""
from __future__ import annotations

import subprocess
import sys
import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


def _cli(args, cwd=None, timeout=45):
    for cmd in (["minisearch"], [sys.executable, "-m", "minisearch.cli"],
                [sys.executable, "-m", "minisearch"]):
        try:
            return subprocess.run(cmd + args, cwd=cwd, capture_output=True,
                                    text=True, timeout=timeout)
        except FileNotFoundError:
            continue
    pytest.skip("no way to invoke minisearch CLI")


def test_cli_and_api_agree_on_doc_count(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "1.txt").write_text("python is great")
    (corpus / "2.txt").write_text("rust is fast")
    (corpus / "3.txt").write_text("go is simple")
    db = tmp_path / "e2e.db"

    r = _cli(["index", str(corpus), "--db", str(db)])
    assert r.returncode == 0

    monkeypatch.setenv("MINISEARCH_DB_PATH", str(db))
    from minisearch.api import app
    with TestClient(app) as c:
        stats = c.get("/stats").json()
    assert stats.get("doc_count") == 3


def test_full_index_search_delete_via_api(tmp_path, monkeypatch):
    monkeypatch.setenv("MINISEARCH_DB_PATH", str(tmp_path / "flow.db"))
    from minisearch.api import app
    with TestClient(app) as c:
        # Add
        r = c.post("/index", json={"text": "python is a great language"})
        assert r.status_code == 201
        doc_id = r.json()["doc_id"]
        # Search
        r = c.get("/search", params={"q": "python"})
        assert r.status_code == 200
        hits = r.json()["hits"]
        assert any(h["doc_id"] == doc_id for h in hits)
        # Delete
        r = c.delete(f"/index/{doc_id}")
        assert r.status_code == 204
        # Search again — gone
        r = c.get("/search", params={"q": "python"})
        assert not any(h["doc_id"] == doc_id for h in r.json()["hits"])
