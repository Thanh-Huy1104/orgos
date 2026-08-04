"""Story 4 — analyzer filter pipeline.

Spec promises:
  - `remove_stopwords(tokens, lang="en")` drops standard English stopwords
  - `bigrams(tokens)` returns list of "word1_word2" for adjacent pairs
  - `apply_pipeline(tokens, filters=[...])` composes filters left-to-right
"""
from __future__ import annotations

try:
    from minisearch.analyzer import remove_stopwords, bigrams
except ImportError:
    from minisearch.analyzer.filters import remove_stopwords, bigrams


def test_stopwords_dropped():
    result = remove_stopwords(["the", "quick", "brown", "fox", "and", "the", "lazy", "dog"])
    for sw in ("the", "and"):
        assert sw not in result
    for keep in ("quick", "brown", "fox", "lazy", "dog"):
        assert keep in result


def test_stopwords_preserves_content_words():
    # Explicit AC: "run", "test" must survive
    result = remove_stopwords(["run", "test", "the", "code"])
    assert "run" in result
    assert "test" in result
    assert "code" in result
    assert "the" not in result


def test_stopwords_of_dropped():
    assert "of" not in remove_stopwords(["heart", "of", "gold"])


def test_stopwords_empty_input():
    assert remove_stopwords([]) == []


def test_bigrams_three_tokens():
    # AC: ["a","b","c"] → ["a_b", "b_c"]
    assert bigrams(["a", "b", "c"]) == ["a_b", "b_c"]


def test_bigrams_empty_input_returns_empty():
    assert bigrams([]) == []


def test_bigrams_single_token_returns_empty():
    assert bigrams(["solo"]) == []


def test_bigrams_two_tokens():
    assert bigrams(["hello", "world"]) == ["hello_world"]


def test_bigrams_preserves_order():
    result = bigrams(["one", "two", "three", "four"])
    assert result == ["one_two", "two_three", "three_four"]


def test_apply_pipeline_composes():
    try:
        from minisearch.analyzer import apply_pipeline
    except ImportError:
        from minisearch.analyzer.filters import apply_pipeline
    # remove_stopwords then bigrams
    result = apply_pipeline(["the", "quick", "brown", "fox"],
                             filters=[remove_stopwords, bigrams])
    # Post-stopword tokens: ["quick", "brown", "fox"] → bigrams
    assert result == ["quick_brown", "brown_fox"]
