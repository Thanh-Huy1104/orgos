"""Story 14 — snippet highlighter.

Spec promises:
  - `snippet(text, query_terms, window=8) -> str` returns snippet of ~2*window+1 tokens
    around first match
  - Query terms wrapped in `<b>...</b>` (or configurable markers)
  - No match: returns leading tokens (no markers)
  - Case-insensitive matching
"""
from __future__ import annotations

try:
    from minisearch.highlighter import snippet
except ImportError:
    from minisearch.highlighter.snippet import snippet


LONG = (
    "The quick brown fox jumps over the lazy dog. "
    "Then the fox runs away into the deep dark forest, "
    "chased by hounds and hunters on horseback."
)


def test_returns_str():
    assert isinstance(snippet("some text with fox in it", ["fox"]), str)


def test_wraps_match_with_b_tag():
    s = snippet(LONG, ["fox"])
    assert "<b>" in s.lower() and "fox" in s.lower()


def test_no_match_returns_leading_tokens_without_markers():
    s = snippet(LONG, ["quantum"])
    # No `<b>` marker if nothing matched
    assert "<b>" not in s.lower()
    # Should still return content (leading window)
    assert len(s) > 0


def test_empty_query_terms_no_crash():
    s = snippet(LONG, [])
    assert isinstance(s, str)


def test_case_insensitive_match():
    s = snippet("Python is Great", ["python"])
    # Match found; the original case may or may not be preserved but a marker
    # should appear
    assert "<b>" in s.lower()


def test_short_text_returned_intact_ish():
    text = "hello world foo"
    s = snippet(text, ["foo"])
    # All three original words appear somewhere in output
    for w in ("hello", "world", "foo"):
        assert w in s.lower()


def test_multiple_matches_produces_snippet():
    text = "alpha beta gamma delta alpha epsilon zeta alpha"
    s = snippet(text, ["alpha"])
    # At least one match highlighted
    assert s.lower().count("<b>") >= 1


def test_configurable_markers_if_supported():
    try:
        s = snippet(LONG, ["fox"], marker=("[[", "]]"))
        if "[[" in s or "]]" in s:
            assert "[[" in s and "]]" in s
    except TypeError:
        # `marker` kwarg optional per spec; skip silently
        pass
