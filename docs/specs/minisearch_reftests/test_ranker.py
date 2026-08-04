"""Story 16 — ranker with recency + popularity boosts.

Spec promises:
  - `Ranker(recency_weight=0.1, popularity_weight=0.05)` reranks (doc_id, score, doc) tuples
  - Weights of 0 → identity
  - Result stable-sorted by final score
"""
from __future__ import annotations

import datetime as dt

try:
    from minisearch.ranker import Ranker
except ImportError:
    from minisearch.ranker.boost import Ranker


def _mk_doc(doc_id, created_at=None, views=0):
    """Minimal duck-typed doc — many implementations will expect a real
    Document, so we produce a lightweight namespace-like."""
    class _D:
        pass
    d = _D()
    d.id = doc_id
    d.meta = {"views": views}
    d.created_at = created_at or dt.datetime(2020, 1, 1)
    return d


def test_identity_preserves_input_order():
    r = Ranker(recency_weight=0, popularity_weight=0)
    docs = [(1, 3.0, _mk_doc(1)), (2, 2.0, _mk_doc(2)), (3, 1.0, _mk_doc(3))]
    result = list(r.rerank(docs))
    doc_ids = [item[0] for item in result]
    assert doc_ids == [1, 2, 3]


def test_empty_input_returns_empty():
    r = Ranker()
    assert list(r.rerank([])) == []


def test_popularity_boost_promotes_high_views():
    r = Ranker(recency_weight=0, popularity_weight=1.0)
    # Same base score; doc 2 has more views
    a = _mk_doc(1, views=10)
    b = _mk_doc(2, views=1000)
    docs = [(1, 1.0, a), (2, 1.0, b)]
    result = list(r.rerank(docs))
    assert result[0][0] == 2  # doc 2 promoted


def test_recency_boost_promotes_newer():
    r = Ranker(recency_weight=1.0, popularity_weight=0)
    old = _mk_doc(1, created_at=dt.datetime(2000, 1, 1))
    new = _mk_doc(2, created_at=dt.datetime.utcnow())
    docs = [(1, 1.0, old), (2, 1.0, new)]
    result = list(r.rerank(docs))
    assert result[0][0] == 2  # newer promoted


def test_tie_break_by_doc_id():
    r = Ranker(recency_weight=0, popularity_weight=0)
    # Same base score, same recency, same popularity → order by doc_id
    docs = [(2, 1.0, _mk_doc(2)), (1, 1.0, _mk_doc(1))]
    result = list(r.rerank(docs))
    doc_ids = [item[0] for item in result]
    assert doc_ids == [1, 2]  # or a stable order — spec says "stable-sorted"


def test_result_sorted_descending_by_score():
    r = Ranker(recency_weight=0.1, popularity_weight=0.05)
    docs = [(1, 0.5, _mk_doc(1, views=10)),
            (2, 2.0, _mk_doc(2, views=10)),
            (3, 1.0, _mk_doc(3, views=10))]
    result = list(r.rerank(docs))
    scores = [item[1] for item in result]
    assert scores == sorted(scores, reverse=True)
