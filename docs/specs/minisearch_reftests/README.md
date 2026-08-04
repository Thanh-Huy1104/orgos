# minisearch — held-out reference test suite

These tests are the **independent evaluation** for any implementation of
`docs/specs/minisearch.md`. They were written from the spec alone,
without reading any agent's code.

**How to use**

    # Copy this directory into the target repo:
    Copy-Item -Recurse minisearch_reftests <target>/tests/_reftests
    cd <target>
    pip install -e .
    pytest tests/_reftests --tb=no -q

The pass count out of the total is the arm's **reference-suite pass rate**.
This is the metric to report for a fair comparison — it is not
self-graded by the arm's own test agent.

**Design principles**

- Only test behavior the spec explicitly promises in AC / DoD.
- Do not test internal shape (class names, module layouts, private helpers).
- Import from documented paths only. If an implementation exposes the API
  differently, that's the implementation's problem — the spec was clear.
- Each test is a single behavioral assertion.
- Skip tests never inflate the pass count. Fail-hard on missing modules.

**Files**

    conftest.py            — shared fixtures (corpus, tmp DB)
    test_tokenizer.py      — Story 2 behaviors
    test_analyzer.py       — Story 4 behaviors
    test_store.py          — Story 6 behaviors
    test_index.py          — Story 8 behaviors
    test_query.py          — Story 10 behaviors
    test_scorer.py         — Story 12 behaviors (BM25 with a hand-computed value)
    test_highlighter.py    — Story 14 behaviors
    test_ranker.py         — Story 16 behaviors
    test_engine.py         — Story 18 end-to-end
    test_api.py            — Stories 20–24 HTTP behaviors
    test_cli.py            — Stories 25–27 CLI behaviors
    test_e2e.py            — Story 28 full-stack smoke
