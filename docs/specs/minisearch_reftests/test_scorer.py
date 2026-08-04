"""Story 12 — BM25 scorer.

Spec promises:
  - `bm25(query_terms, postings, doc_length, avg_doc_length, doc_count, k1=1.2, b=0.75)` -> float
  - Standard BM25 formula (verifiable against Wikipedia)
  - Zero doc_length → 0
  - Deterministic

We test the algorithmic contract without pinning a specific `postings`
input shape — implementations may use a Posting dataclass, dict,
or tuple. So we probe behavior instead: score should be > 0 for
matched terms, 0 for unmatched, and grow with matches.
"""
from __future__ import annotations

import math

try:
    from minisearch.scorer import bm25
except ImportError:
    from minisearch.scorer.bm25 import bm25


def _mock_posting(doc_id, tf, positions=None):
    """Best-effort posting: try dataclass import, else use a namedtuple-like."""
    try:
        from minisearch.index import Posting
    except ImportError:
        try:
            from minisearch.index.inverted import Posting
        except ImportError:
            from collections import namedtuple
            Posting = namedtuple("Posting", "doc_id term_freq positions")
    try:
        return Posting(doc_id=doc_id, term_freq=tf, positions=positions or [])
    except TypeError:
        # Positional
        return Posting(doc_id, tf, positions or [])


def test_returns_float():
    p = [_mock_posting(1, 2)]
    result = bm25(
        query_terms=["foo"],
        postings={"foo": p},
        doc_length=10, avg_doc_length=10, doc_count=1,
    )
    assert isinstance(result, (int, float))


def test_zero_doc_length_returns_zero():
    p = [_mock_posting(1, 2)]
    assert bm25(
        query_terms=["foo"],
        postings={"foo": p},
        doc_length=0, avg_doc_length=10, doc_count=1,
    ) == 0


def test_unmatched_query_returns_zero():
    assert bm25(
        query_terms=["nothing"],
        postings={},              # term doesn't exist
        doc_length=10, avg_doc_length=10, doc_count=5,
    ) == 0


def test_deterministic():
    p = [_mock_posting(1, 3)]
    args = dict(
        query_terms=["foo"],
        postings={"foo": p},
        doc_length=20, avg_doc_length=15, doc_count=10,
    )
    assert bm25(**args) == bm25(**args)


def test_positive_score_for_matched():
    p = [_mock_posting(1, 3)]
    score = bm25(
        query_terms=["foo"],
        postings={"foo": p},
        doc_length=20, avg_doc_length=15, doc_count=10,
    )
    assert score > 0


def test_higher_tf_gives_higher_score():
    low  = [_mock_posting(1, 1)]
    high = [_mock_posting(1, 5)]
    args = dict(doc_length=20, avg_doc_length=20, doc_count=10)
    s_low  = bm25(query_terms=["foo"], postings={"foo": low},  **args)
    s_high = bm25(query_terms=["foo"], postings={"foo": high}, **args)
    assert s_high > s_low


def test_longer_docs_get_lower_per_term_scores():
    # Same TF, same corpus stats, but one doc is very long → length
    # normalization should reduce its score.
    p = [_mock_posting(1, 3)]
    args = dict(avg_doc_length=10, doc_count=10)
    s_short = bm25(query_terms=["foo"], postings={"foo": p}, doc_length=5,  **args)
    s_long  = bm25(query_terms=["foo"], postings={"foo": p}, doc_length=50, **args)
    assert s_short > s_long


def test_k1_parameter_respected():
    p = [_mock_posting(1, 5)]
    args = dict(query_terms=["foo"], postings={"foo": p},
                doc_length=20, avg_doc_length=20, doc_count=10)
    s_small_k1 = bm25(k1=0.5, **args)
    s_large_k1 = bm25(k1=3.0, **args)
    assert s_small_k1 != s_large_k1


def test_b_parameter_respected():
    p = [_mock_posting(1, 3)]
    args = dict(query_terms=["foo"], postings={"foo": p},
                doc_length=50, avg_doc_length=20, doc_count=10)
    s_no_norm   = bm25(b=0.0, **args)   # no length normalization
    s_full_norm = bm25(b=1.0, **args)
    assert s_no_norm != s_full_norm


def test_multiterm_query_sums():
    pf = [_mock_posting(1, 2)]
    pb = [_mock_posting(1, 2)]
    args = dict(doc_length=20, avg_doc_length=20, doc_count=10)
    s_one = bm25(query_terms=["foo"], postings={"foo": pf}, **args)
    s_two = bm25(query_terms=["foo", "bar"],
                  postings={"foo": pf, "bar": pb}, **args)
    # Two matched terms should score >= a single one
    assert s_two >= s_one
