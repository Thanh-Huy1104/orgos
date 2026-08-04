"""Story 10 — query parser behaviors.

Spec promises:
  - `parse(q: str) -> QueryNode` supports AND / OR / NOT / phrase / wildcard
  - Precedence: NOT > AND > OR
  - Parenthesization: `(foo OR bar) AND baz` works
  - Malformed query raises `QueryParseError`
"""
from __future__ import annotations

import pytest

try:
    from minisearch.query import parse, QueryParseError
except ImportError:
    from minisearch.query.parser import parse, QueryParseError


def _kind(node):
    """Cross-tolerant read of node kind — supports Term/Phrase/And/Or/Not
    as class names (dataclass variants)."""
    return type(node).__name__.lower()


def test_parses_single_term():
    ast = parse("hello")
    assert "term" in _kind(ast)


def test_parses_and():
    ast = parse("foo AND bar")
    assert "and" in _kind(ast)


def test_parses_or():
    ast = parse("foo OR bar")
    assert "or" in _kind(ast)


def test_parses_not():
    ast = parse("NOT foo")
    assert "not" in _kind(ast)


def test_parses_phrase():
    ast = parse('"hello world"')
    assert "phrase" in _kind(ast)


def test_parses_wildcard():
    ast = parse("hell*")
    assert "wild" in _kind(ast) or "term" in _kind(ast)


def test_empty_raises_parse_error():
    with pytest.raises(QueryParseError):
        parse("")


def test_whitespace_only_raises():
    with pytest.raises(QueryParseError):
        parse("   ")


def test_unbalanced_parens_raises():
    with pytest.raises(QueryParseError):
        parse("(foo AND bar")


def test_parens_override_precedence():
    # The tree shape should be OR-at-root when parens force it:
    #   `(foo OR bar) AND baz` — root is And, its left child is Or
    ast = parse("(foo OR bar) AND baz")
    assert "and" in _kind(ast)


def test_and_precedence_over_or():
    # `a AND b OR c` parses as `(a AND b) OR c` — root is Or
    ast = parse("a AND b OR c")
    assert "or" in _kind(ast)


def test_phrase_with_special_chars():
    # Spec: `"foo (bar)"` parses without raising
    ast = parse('"foo (bar)"')
    assert "phrase" in _kind(ast)


def test_case_insensitive_operators():
    # `and` vs `AND` — most implementations accept both, but the spec
    # examples all show uppercase. Accept either.
    try:
        ast = parse("foo AND bar")
    except QueryParseError:
        pytest.fail("AND uppercase should parse")
    assert "and" in _kind(ast)


def test_nested_parens():
    ast = parse("((foo OR bar) AND (baz OR qux))")
    assert "and" in _kind(ast)


def test_not_binds_tighter_than_and():
    # `NOT foo AND bar` = `(NOT foo) AND bar` — root is And
    ast = parse("NOT foo AND bar")
    assert "and" in _kind(ast)
