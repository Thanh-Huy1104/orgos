# minisearch — text search engine with inverted index + BM25

Version: 1.0.0
Author: orgos
Status: ready-to-build

## Overview

A lightweight but fully-featured text search engine. Users index a
directory of text documents (or push documents via API), then run
boolean/phrase/wildcard queries with BM25 relevance scoring, and get
back snippets with query terms highlighted.

Stack: Python 3.11, FastAPI, SQLite (stdlib only), typer/argparse, no
heavy dependencies. Zero external services — the index is a SQLite
database in one file. Deterministic tokenization + scoring so tests
can pin exact expected results.

## Architecture

Ten disjoint packages. Each owns one responsibility. Inter-package
calls go through stable dataclass interfaces so agents can work in
parallel without collision.

```
minisearch/
    tokenizer/     — Text → tokens (case fold, punctuation strip, stemming)
    analyzer/     — Filter pipeline (stopwords, ngrams, synonyms)
    store/        — Document CRUD (SQLite-backed, ID → text + metadata)
    index/        — Inverted index (term → posting list) with SQLite
    query/        — Query parser (boolean AND/OR/NOT, phrase, wildcard)
    scorer/       — BM25 relevance scoring
    highlighter/  — Snippet extraction with query-term highlighting
    ranker/       — Post-scoring reranking (recency, popularity boost)
    api/          — FastAPI: /index, /search, /suggest, /stats
    cli/          — minisearch index <dir> / search "..." / stats
```

Data flow at search time:

```
query string → query.parse → query AST
document store → index.lookup(terms) → posting list per term
scorer.bm25(postings, docstats) → ranked doc IDs + scores
ranker.rerank(ranked, boost_rules) → final order
store.get(id) → doc text → highlighter.snippet(text, query) → SearchHit
→ api response OR cli print
```

## Definition of done

- `pip install -e .` installs `minisearch` package
- `pytest -q` shows ≥120 tests passing with ≥70% coverage on non-CLI modules
- `minisearch index /path/to/docs` builds an index of all .txt/.md files
- `minisearch search "python AND regex"` returns ranked hits with snippets
- `uvicorn minisearch.api:app` serves; `curl localhost:8000/search?q=hello` returns JSON
- Zero external HTTP calls in any test (all-offline)

---

## Story: Set up project scaffolding + baseline test harness
Files: pyproject.toml, minisearch/__init__.py, tests/__init__.py, conftest.py, README.md
Type: architecture
Priority: 100
AC:
  - `pip install -e .` succeeds on Python 3.11+
  - `pytest -q` runs cleanly (may report 0 tests initially)
  - `minisearch` package is importable; `from minisearch import __version__` returns "0.1.0"
  - conftest.py exposes a `tmp_db` pytest fixture returning a fresh sqlite3.Connection
  - README.md has a one-paragraph description + install + test commands

## Story: Tokenizer — text to tokens with case-fold + punctuation strip
Files: minisearch/tokenizer/__init__.py, minisearch/tokenizer/basic.py
Type: architecture
Priority: 95
Component: tokenizer
AC:
  - `tokenize(text: str) -> list[str]` returns lower-case tokens
  - Removes punctuation but preserves apostrophes in contractions ("don't" → "don't")
  - Splits on whitespace and non-word characters
  - Empty input returns `[]`
  - Handles unicode (accents preserved)

## Story: Add tests for tokenizer
Files: tests/tokenizer/__init__.py, tests/tokenizer/test_basic.py
Type: test
Priority: 94
Depends: 2
AC:
  - 12+ tests: empty, single word, sentence, contractions, punctuation, unicode
  - Test that repeated tokenization is deterministic
  - Test that "Hello, World!" tokenizes to ["hello", "world"]

## Story: Analyzer — stopword filter + ngram generator
Files: minisearch/analyzer/__init__.py, minisearch/analyzer/filters.py
Type: feature
Priority: 90
Component: analyzer
Depends: 2
AC:
  - `remove_stopwords(tokens, lang="en")` drops standard English stopwords ({the, a, is, of, ...})
  - `bigrams(tokens)` returns list of "word1_word2" for adjacent pairs
  - Stopword list is loaded from an embedded module (no external files)
  - `apply_pipeline(tokens, filters=[...])` composes filters left-to-right

## Story: Add tests for analyzer
Files: tests/analyzer/__init__.py, tests/analyzer/test_filters.py
Type: test
Priority: 89
Depends: 4
AC:
  - Test stopword removal preserves "run", "test" (not stopwords)
  - Test stopword removal drops "the", "and", "of"
  - Test bigrams: ["a","b","c"] → ["a_b", "b_c"]
  - Test empty input to bigrams returns []
  - Test pipeline composes correctly

## Story: Document store — SQLite CRUD
Files: minisearch/store/__init__.py, minisearch/store/documents.py, minisearch/store/schema.sql
Type: architecture
Priority: 88
Component: store
AC:
  - `DocumentStore(conn)` provides `.add(text, meta={}) -> doc_id`, `.get(doc_id) -> Document`, `.delete(doc_id)`
  - Document has fields: `id: int, text: str, meta: dict, created_at: datetime`
  - Idempotent `.ensure_schema()`
  - `.iter_all()` yields all documents; `.count()` returns total
  - `.batch_add(items)` for efficient bulk insert

## Story: Add tests for document store
Files: tests/store/__init__.py, tests/store/test_documents.py
Type: test
Priority: 87
Depends: 6
AC:
  - 10+ tests: add, get, delete, batch, iteration, count
  - Test that add returns a monotonically increasing id
  - Test that get on missing id raises KeyError
  - Test batch_add of 100 docs completes in < 100ms
  - Test that meta round-trips correctly (JSON serialization)

## Story: Inverted index — SQLite-backed posting lists
Files: minisearch/index/__init__.py, minisearch/index/inverted.py, minisearch/index/schema.sql
Type: architecture
Priority: 85
Component: index
Depends: 6
AC:
  - `InvertedIndex(conn)` with `.add(doc_id, tokens: list[str])` and `.lookup(term) -> list[Posting]`
  - `Posting(doc_id, term_freq, positions: list[int])`
  - `.doc_count()` and `.term_freq(term)` for stats
  - `.remove(doc_id)` deletes all postings for that doc
  - Positions are token indices in the original document

## Story: Add tests for inverted index
Files: tests/index/__init__.py, tests/index/test_inverted.py
Type: test
Priority: 84
Depends: 8
AC:
  - 10+ tests covering add, lookup, remove, doc_count, term_freq
  - Test that adding two docs with shared terms produces correct posting lists
  - Test that positions are 0-indexed and correct
  - Test that lookup of unknown term returns []
  - Test that remove(doc_id) clears all its postings but leaves others alone

## Story: Query parser — boolean + phrase + wildcard
Files: minisearch/query/__init__.py, minisearch/query/parser.py, minisearch/query/ast.py
Type: architecture
Priority: 80
Component: query
AC:
  - `parse(q: str) -> QueryNode` supports: `foo AND bar`, `foo OR bar`, `NOT foo`, `"exact phrase"`, `wild*`
  - QueryNode is a dataclass tree with And/Or/Not/Term/Phrase/Wildcard variants
  - Precedence: NOT > AND > OR (standard boolean)
  - Parenthesization: `(foo OR bar) AND baz` works
  - Malformed query raises `QueryParseError` with position info

## Story: Add tests for query parser
Files: tests/query/__init__.py, tests/query/test_parser.py
Type: test
Priority: 79
Depends: 10
AC:
  - 15+ tests covering each construct + edge cases
  - Test AND precedence: `a AND b OR c` parses as `(a AND b) OR c`
  - Test parens override precedence
  - Test empty query raises QueryParseError
  - Test unbalanced parens raises QueryParseError
  - Test phrase with special chars: `"foo (bar)"` parses correctly

## Story: BM25 scorer
Files: minisearch/scorer/__init__.py, minisearch/scorer/bm25.py
Type: feature
Priority: 76
Component: scorer
Depends: 8
AC:
  - `bm25(query_terms, postings, doc_length, avg_doc_length, doc_count, k1=1.2, b=0.75)` returns a float score
  - Matches the standard BM25 formula (verifiable against Wikipedia)
  - Handles zero doc_length gracefully (returns 0)
  - Handles term not in any doc (idf becomes negative — clamped to small positive)
  - Deterministic given same inputs

## Story: Add tests for BM25 scorer
Files: tests/scorer/__init__.py, tests/scorer/test_bm25.py
Type: test
Priority: 75
Depends: 12
AC:
  - Test that score of query term matching the whole document is high
  - Test that unmatched query returns 0
  - Test with a hand-computed BM25 value from a small example (2 docs, 3 terms) — must match to 4 decimals
  - Test that longer docs get lower per-term scores (length normalization)
  - Test that k1 and b parameters are respected

## Story: Highlighter — snippet with query-term markers
Files: minisearch/highlighter/__init__.py, minisearch/highlighter/snippet.py
Type: feature
Priority: 72
Component: highlighter
AC:
  - `snippet(text, query_terms, window=8) -> str` returns a snippet of `2*window+1` tokens around the first match
  - Query terms wrapped in `<b>...</b>` (or configurable markers)
  - Multiple matches: combine into one snippet with `...` separator if far apart
  - Text with no match returns first `window` tokens
  - Handles unicode + case-insensitive matching

## Story: Add tests for highlighter
Files: tests/highlighter/__init__.py, tests/highlighter/test_snippet.py
Type: test
Priority: 71
Depends: 14
AC:
  - Test single match: correct window around match with markers
  - Test no match: returns leading tokens without markers
  - Test multiple matches: combined snippet with separator
  - Test case-insensitive matching preserves original case in output
  - Test custom markers respected

## Story: Ranker — reranking with recency + popularity boosts
Files: minisearch/ranker/__init__.py, minisearch/ranker/boost.py
Type: feature
Priority: 68
Component: ranker
AC:
  - `Ranker(recency_weight=0.1, popularity_weight=0.05)` reranks a list of (doc_id, score, doc) tuples
  - Recency boost: newer docs get proportionally higher scores
  - Popularity boost: docs with more meta.views get proportionally higher scores
  - Weights of 0 → no reranking (identity)
  - Result is stable-sorted by final score (descending)

## Story: Add tests for ranker
Files: tests/ranker/__init__.py, tests/ranker/test_boost.py
Type: test
Priority: 67
Depends: 16
AC:
  - Test identity ranker (weights=0) preserves input order
  - Test recency boost promotes newer docs
  - Test popularity boost respects meta.views
  - Test tie-break by doc_id when scores are equal
  - Test empty input returns empty list

## Story: SearchEngine facade — tie tokenizer + index + scorer + highlighter
Files: minisearch/engine.py
Type: architecture
Priority: 65
Depends: 2, 6, 8, 12, 14
AC:
  - `SearchEngine(store, index, tokenizer, scorer, highlighter, ranker=None)` composes the pipeline
  - `.index_document(text, meta={}) -> doc_id` adds to store AND index
  - `.search(query, limit=10) -> list[SearchHit]` returns ranked hits with snippets
  - `SearchHit(doc_id, score, snippet, meta)` dataclass
  - `.remove(doc_id)` removes from both store and index

## Story: Add tests for SearchEngine facade
Files: tests/test_engine.py
Type: test
Priority: 64
Depends: 18
AC:
  - Test end-to-end: index 5 docs, search returns expected top-3 in order
  - Test that removed docs don't appear in results
  - Test limit is respected
  - Test empty index returns []
  - Test integration with the actual InvertedIndex + DocumentStore (no mocks)

## Story: FastAPI app skeleton + /health + CORS
Files: minisearch/api/__init__.py, minisearch/api/app.py
Type: architecture
Priority: 55
Component: api
AC:
  - `from minisearch.api import app` returns a FastAPI instance
  - GET /health returns `{"status": "ok", "version": "0.1.0"}` with 200
  - CORS enabled for all origins in DEBUG mode
  - App startup event opens a SearchEngine from `MINISEARCH_DB_PATH` env var (default `./minisearch.db`)
  - `uvicorn minisearch.api:app` starts without error

## Story: /search endpoint
Files: minisearch/api/search_routes.py
Type: feature
Priority: 54
Component: api
Depends: 18, 21
AC:
  - GET /search?q=<query>&limit=<n> returns `{"hits": [...], "total": N, "took_ms": X}`
  - Each hit: `{"doc_id", "score", "snippet", "meta"}`
  - Invalid query returns 400 with error field
  - Empty query returns 400
  - Default limit=10; max 100

## Story: /index endpoint (add document)
Files: minisearch/api/index_routes.py
Type: feature
Priority: 53
Component: api
Depends: 6, 8, 21
AC:
  - POST /index {"text": "...", "meta": {...}} returns `{"doc_id": N}` with 201
  - Missing text returns 400
  - GET /index/{doc_id} returns the document
  - DELETE /index/{doc_id} removes it, returns 204

## Story: /stats endpoint
Files: minisearch/api/stats_routes.py
Type: feature
Priority: 52
Component: api
Depends: 6, 8, 21
AC:
  - GET /stats returns `{"doc_count": N, "term_count": T, "avg_doc_length": X, "db_size_bytes": Y}`
  - Response includes top 10 most frequent terms with counts
  - Response includes index build timestamp
  - Handles empty index (all zeros, no crash)

## Story: Add tests for the API
Files: tests/api/__init__.py, tests/api/test_api.py
Type: test
Priority: 51
Depends: 22, 23, 24
AC:
  - 10+ tests using FastAPI TestClient (no live uvicorn)
  - Test /health returns expected shape
  - Test full lifecycle: POST /index → GET /search → DELETE /index/{id}
  - Test invalid query returns 400 with descriptive error
  - Test /stats on empty and populated indices

## Story: CLI — minisearch index <dir>
Files: minisearch/cli/__init__.py, minisearch/cli/main.py, minisearch/cli/index_cmd.py
Type: feature
Priority: 45
Component: cli
Depends: 18
AC:
  - `minisearch index /path/to/dir --db X.db` indexes all .txt/.md files recursively
  - Prints per-file "indexed: filename (N tokens)" line
  - Prints summary: total docs, terms, wall time
  - `--force` re-indexes even existing docs
  - Exit code 0 on success, non-zero on directory not found

## Story: CLI — minisearch search "..."
Files: minisearch/cli/search_cmd.py
Type: feature
Priority: 44
Component: cli
Depends: 18
AC:
  - `minisearch search "query" --db X.db --limit 10` prints ranked hits
  - Each hit shows: `[score] doc_id — meta.title (or first line)` + snippet on next line
  - `--json` outputs machine-readable JSON
  - `--limit 0` means unlimited
  - Exit code 0 always (0 hits is not an error)

## Story: CLI — minisearch stats
Files: minisearch/cli/stats_cmd.py
Type: feature
Priority: 43
Component: cli
Depends: 6, 8
AC:
  - `minisearch stats --db X.db` prints a summary table
  - Includes: doc_count, unique_terms, avg_doc_length, DB size, top 10 terms
  - Handles missing DB gracefully with clear error
  - `--json` for machine-readable output

## Story: End-to-end integration test — full stack smoke
Files: tests/e2e/__init__.py, tests/e2e/test_end_to_end.py
Type: test
Priority: 35
Depends: 26, 27, 28
AC:
  - Test that CLI (`minisearch index`) indexes a test corpus, then `minisearch search` returns expected hits
  - Test that API (`POST /index` + `GET /search`) produces the same results as the CLI
  - Test that `minisearch stats` matches what the API reports
  - Runs in < 15 seconds total
  - Zero network I/O; uses `subprocess.run([sys.executable, "-m", "minisearch.cli", ...])` for CLI tests
