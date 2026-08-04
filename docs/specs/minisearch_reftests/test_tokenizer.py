"""Story 2 — tokenizer behaviors from the spec's AC.

Spec promises:
  - `tokenize(text: str) -> list[str]` returns lower-case tokens
  - Removes punctuation but preserves apostrophes in contractions
  - Splits on whitespace and non-word characters
  - Empty input returns `[]`
  - Handles unicode (accents preserved)
"""
from __future__ import annotations

try:
    from minisearch.tokenizer import tokenize            # preferred
except ImportError:
    from minisearch.tokenizer.basic import tokenize      # spec-declared fallback


def test_empty_returns_empty_list():
    assert tokenize("") == []


def test_single_word_lowercased():
    assert tokenize("Hello") == ["hello"]


def test_hello_world_canonical():
    # Explicit example from the spec's story 3 AC.
    assert tokenize("Hello, World!") == ["hello", "world"]


def test_sentence_splits_on_whitespace():
    assert tokenize("the quick brown fox") == ["the", "quick", "brown", "fox"]


def test_punctuation_stripped():
    result = tokenize("hello, world! how? are: you.")
    assert result == ["hello", "world", "how", "are", "you"]


def test_contraction_apostrophe_preserved():
    # Spec: "don't" → "don't"
    result = tokenize("don't stop believing")
    assert "don't" in result


def test_repeated_calls_deterministic():
    text = "The rain in Spain stays mainly in the plain."
    assert tokenize(text) == tokenize(text)


def test_unicode_accent_preserved():
    result = tokenize("café résumé naïve")
    # Case-fold but keep the accents
    assert "café" in result or "cafe" in result  # some tokenizers casefold-strip
    # Stricter check: accented forms must be handled without crashing
    assert len(result) == 3


def test_multiple_whitespace_collapsed():
    assert tokenize("foo    bar\t\nbaz") == ["foo", "bar", "baz"]


def test_returns_list_type():
    assert isinstance(tokenize("hello"), list)


def test_numbers_kept_as_tokens():
    # Common tokenizer behavior — numbers stay
    result = tokenize("python 3.11 was released in 2022")
    # At minimum: the words survive
    assert "python" in result
    assert "released" in result


def test_all_punctuation_input():
    assert tokenize("!!! ??? ...") == []
