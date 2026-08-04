"""Story 8 — inverted index behaviors.

Spec promises:
  - `InvertedIndex(conn)` with `.add(doc_id, tokens)` and `.lookup(term)`
  - `Posting(doc_id, term_freq, positions)` — positions are 0-indexed token indices
  - `.doc_count()`, `.term_freq(term)`
  - `.remove(doc_id)` clears all its postings
"""
from __future__ import annotations

try:
    from minisearch.index import InvertedIndex
except ImportError:
    from minisearch.index.inverted import InvertedIndex


def _mk(conn):
    idx = InvertedIndex(conn)
    if hasattr(idx, "ensure_schema"):
        idx.ensure_schema()
    return idx


def _tf(posting):
    """Cross-tolerant read of term_freq off a Posting or dict-like."""
    return getattr(posting, "term_freq", None) or getattr(posting, "tf", None) or posting["term_freq"]


def _doc_id(posting):
    return getattr(posting, "doc_id", None) or posting["doc_id"]


def _positions(posting):
    return getattr(posting, "positions", None) or posting["positions"]


def test_lookup_unknown_returns_empty(tmp_db):
    idx = _mk(tmp_db)
    assert list(idx.lookup("no_such_term")) == []


def test_add_and_lookup_single_doc(tmp_db):
    idx = _mk(tmp_db)
    idx.add(1, ["foo", "bar", "foo"])
    postings = list(idx.lookup("foo"))
    assert len(postings) == 1
    assert _doc_id(postings[0]) == 1


def test_positions_are_zero_indexed(tmp_db):
    idx = _mk(tmp_db)
    idx.add(1, ["a", "b", "c", "a", "d"])
    postings = list(idx.lookup("a"))
    assert _positions(postings[0]) == [0, 3]


def test_term_freq_counted(tmp_db):
    idx = _mk(tmp_db)
    idx.add(1, ["x", "x", "y", "x"])
    postings = list(idx.lookup("x"))
    assert _tf(postings[0]) == 3


def test_two_docs_shared_term(tmp_db):
    idx = _mk(tmp_db)
    idx.add(1, ["shared", "unique1"])
    idx.add(2, ["shared", "unique2"])
    postings = list(idx.lookup("shared"))
    doc_ids = sorted(_doc_id(p) for p in postings)
    assert doc_ids == [1, 2]


def test_doc_count_reflects_adds(tmp_db):
    idx = _mk(tmp_db)
    assert idx.doc_count() == 0
    idx.add(1, ["a"])
    idx.add(2, ["b"])
    assert idx.doc_count() == 2


def test_term_freq_aggregated_across_docs(tmp_db):
    idx = _mk(tmp_db)
    idx.add(1, ["k", "k"])
    idx.add(2, ["k", "other"])
    # total occurrences of "k" = 3
    assert idx.term_freq("k") == 3


def test_remove_clears_its_postings(tmp_db):
    idx = _mk(tmp_db)
    idx.add(1, ["gone"])
    idx.add(2, ["kept"])
    idx.remove(1)
    assert list(idx.lookup("gone")) == []
    kept = list(idx.lookup("kept"))
    assert len(kept) == 1
    assert _doc_id(kept[0]) == 2


def test_remove_leaves_others_alone(tmp_db):
    idx = _mk(tmp_db)
    idx.add(1, ["shared"])
    idx.add(2, ["shared"])
    idx.remove(1)
    postings = list(idx.lookup("shared"))
    assert len(postings) == 1
    assert _doc_id(postings[0]) == 2


def test_add_empty_tokens_ok(tmp_db):
    idx = _mk(tmp_db)
    # Adding a doc with no tokens shouldn't crash; lookup finds nothing
    idx.add(1, [])
    assert list(idx.lookup("anything")) == []
