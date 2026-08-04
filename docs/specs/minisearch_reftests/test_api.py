"""Stories 20–24 — FastAPI endpoints.

Uses FastAPI's TestClient (no live uvicorn per story 25 AC).

Spec promises:
  - GET /health → {"status": "ok", "version": ...} with 200
  - POST /index {"text": ..., "meta": ...} → {"doc_id": N} with 201
  - GET /index/{id} → the document
  - DELETE /index/{id} → 204
  - GET /search?q=<q>&limit=<n> → {"hits": [...], "total": N, "took_ms": X}
  - Invalid/empty query → 400
  - GET /stats → {doc_count, term_count, avg_doc_length, db_size_bytes, top_terms, indexed_at}
"""
from __future__ import annotations

import os
import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Point the app at a scratch DB
    monkeypatch.setenv("MINISEARCH_DB_PATH", str(tmp_path / "api.db"))
    from minisearch.api import app
    with TestClient(app) as c:
        yield c


def test_health_returns_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") == "ok"
    assert "version" in body


def test_index_post_returns_doc_id(client):
    r = client.post("/index", json={"text": "hello world", "meta": {"tag": "x"}})
    assert r.status_code == 201
    assert isinstance(r.json().get("doc_id"), int)


def test_index_post_missing_text_returns_400(client):
    r = client.post("/index", json={"meta": {}})
    assert r.status_code == 400 or r.status_code == 422


def test_index_get_returns_document(client):
    r = client.post("/index", json={"text": "fetch me back"})
    doc_id = r.json()["doc_id"]
    r2 = client.get(f"/index/{doc_id}")
    assert r2.status_code == 200
    assert "fetch me back" in r2.text or r2.json().get("text") == "fetch me back"


def test_index_delete_returns_204(client):
    r = client.post("/index", json={"text": "deleteme"})
    doc_id = r.json()["doc_id"]
    r2 = client.delete(f"/index/{doc_id}")
    assert r2.status_code == 204


def test_search_returns_hits_shape(client):
    client.post("/index", json={"text": "python is a language"})
    client.post("/index", json={"text": "rust is a language"})
    r = client.get("/search", params={"q": "python"})
    assert r.status_code == 200
    body = r.json()
    assert "hits" in body
    assert isinstance(body["hits"], list)
    assert "total" in body
    assert "took_ms" in body


def test_search_hit_has_expected_fields(client):
    client.post("/index", json={"text": "python programming", "meta": {"t": 1}})
    r = client.get("/search", params={"q": "python"})
    hits = r.json()["hits"]
    assert len(hits) >= 1
    h = hits[0]
    for field in ("doc_id", "score", "snippet"):
        assert field in h


def test_search_empty_query_returns_400(client):
    r = client.get("/search", params={"q": ""})
    assert r.status_code == 400 or r.status_code == 422


def test_search_invalid_query_returns_400(client):
    # `(foo AND` — unbalanced parens
    r = client.get("/search", params={"q": "(foo AND"})
    assert r.status_code == 400 or r.status_code == 422


def test_search_default_limit_10(client):
    for i in range(15):
        client.post("/index", json={"text": f"cat number {i} is a cat"})
    r = client.get("/search", params={"q": "cat"})
    assert len(r.json()["hits"]) <= 10


def test_search_limit_cap_100(client):
    for i in range(10):
        client.post("/index", json={"text": f"cat number {i} is a cat"})
    # Limit=200 should be clamped to 100 (or at least not crash)
    r = client.get("/search", params={"q": "cat", "limit": 200})
    assert r.status_code == 200
    assert len(r.json()["hits"]) <= 100


def test_stats_empty_index(client):
    r = client.get("/stats")
    assert r.status_code == 200
    body = r.json()
    assert body.get("doc_count") == 0


def test_stats_after_indexing(client):
    for i in range(5):
        client.post("/index", json={"text": f"doc number {i}"})
    r = client.get("/stats")
    body = r.json()
    assert body["doc_count"] == 5
    assert "avg_doc_length" in body
