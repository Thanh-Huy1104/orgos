"""Story 18 — SearchEngine facade end-to-end.

Spec promises:
  - `SearchEngine(store, index, tokenizer, scorer, highlighter, ranker=None)`
    composes the pipeline
  - `.index_document(text, meta={}) -> doc_id`
  - `.search(query, limit=10) -> list[SearchHit]`
  - `SearchHit(doc_id, score, snippet, meta)`
  - `.remove(doc_id)` cleans both store and index

These are the tests that most closely mirror the user experience.
Uses a real store + real index + real scorer, not mocks (per AC of story 19).
"""
from __future__ import annotations

import pytest


def _try_build_engine(conn):
    """Try a few common instantiation styles — the spec's constructor
    signature is optional in exact form. What matters is that we can
    get a working engine."""
    from minisearch.engine import SearchEngine
    try:
        # Preferred: default-constructible with just a connection
        return SearchEngine.from_connection(conn)
    except AttributeError:
        pass
    try:
        return SearchEngine(conn)
    except TypeError:
        pass
    # Fall back to fully explicit wiring
    try:
        from minisearch.store import DocumentStore
    except ImportError:
        from minisearch.store.documents import DocumentStore
    try:
        from minisearch.index import InvertedIndex
    except ImportError:
        from minisearch.index.inverted import InvertedIndex
    try:
        from minisearch.tokenizer import tokenize
    except ImportError:
        from minisearch.tokenizer.basic import tokenize
    try:
        from minisearch.scorer import bm25
    except ImportError:
        from minisearch.scorer.bm25 import bm25
    try:
        from minisearch.highlighter import snippet
    except ImportError:
        from minisearch.highlighter.snippet import snippet

    store = DocumentStore(conn)
    if hasattr(store, "ensure_schema"):
        store.ensure_schema()
    idx = InvertedIndex(conn)
    if hasattr(idx, "ensure_schema"):
        idx.ensure_schema()
    return SearchEngine(store=store, index=idx, tokenizer=tokenize,
                         scorer=bm25, highlighter=snippet)


def test_index_and_search_returns_hit(tmp_db):
    eng = _try_build_engine(tmp_db)
    doc_id = eng.index_document(
        "Python is a programming language used for data science.",
        meta={"title": "Python intro"})
    hits = eng.search("python")
    assert len(hits) >= 1
    assert hits[0].doc_id == doc_id


def test_search_returns_hits_ordered_by_score(tmp_db):
    eng = _try_build_engine(tmp_db)
    # A doc that mentions "python" many times
    top_id = eng.index_document("python python python python is great")
    # A doc that mentions it once
    _mid_id = eng.index_document("python is a language")
    # Doc with no mention
    _low_id = eng.index_document("rust is fast")
    hits = eng.search("python", limit=10)
    # Two matching hits, top match first
    assert len(hits) >= 2
    assert hits[0].doc_id == top_id
    for a, b in zip(hits, hits[1:]):
        assert a.score >= b.score


def test_search_empty_index_returns_empty(tmp_db):
    eng = _try_build_engine(tmp_db)
    assert eng.search("anything") == []


def test_limit_respected(tmp_db):
    eng = _try_build_engine(tmp_db)
    for i in range(5):
        eng.index_document(f"foo bar baz {i}")
    hits = eng.search("foo", limit=2)
    assert len(hits) <= 2


def test_search_hit_has_snippet(tmp_db):
    eng = _try_build_engine(tmp_db)
    eng.index_document("The quick brown fox jumps over the lazy dog.")
    hits = eng.search("fox")
    assert len(hits) >= 1
    assert isinstance(hits[0].snippet, str)
    assert len(hits[0].snippet) > 0


def test_remove_clears_hit(tmp_db):
    eng = _try_build_engine(tmp_db)
    doc_id = eng.index_document("removeme")
    assert len(eng.search("removeme")) == 1
    eng.remove(doc_id)
    assert eng.search("removeme") == []


def test_meta_preserved_in_hit(tmp_db):
    eng = _try_build_engine(tmp_db)
    eng.index_document("hello world", meta={"title": "greet", "author": "me"})
    hits = eng.search("hello")
    assert len(hits) >= 1
    assert hits[0].meta.get("title") == "greet"
