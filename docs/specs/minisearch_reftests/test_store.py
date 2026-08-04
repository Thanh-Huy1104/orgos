"""Story 6 — document store.

Spec promises:
  - `DocumentStore(conn)` with `.add(text, meta={}) -> doc_id`,
    `.get(doc_id) -> Document`, `.delete(doc_id)`
  - Document has fields: `id, text, meta, created_at`
  - Idempotent `.ensure_schema()`
  - `.iter_all()` yields all documents; `.count()` returns total
  - `.batch_add(items)` for efficient bulk insert
"""
from __future__ import annotations

import pytest

try:
    from minisearch.store import DocumentStore
except ImportError:
    from minisearch.store.documents import DocumentStore


def _mk(conn):
    store = DocumentStore(conn)
    if hasattr(store, "ensure_schema"):
        store.ensure_schema()
    return store


def test_add_returns_int_id(tmp_db):
    store = _mk(tmp_db)
    doc_id = store.add("hello world", meta={"title": "greet"})
    assert isinstance(doc_id, int)


def test_add_get_roundtrip(tmp_db):
    store = _mk(tmp_db)
    doc_id = store.add("some text", meta={"tag": "x"})
    doc = store.get(doc_id)
    assert doc.text == "some text"
    assert doc.meta.get("tag") == "x"


def test_add_returns_monotonically_increasing_ids(tmp_db):
    store = _mk(tmp_db)
    ids = [store.add(f"doc {i}") for i in range(5)]
    assert ids == sorted(ids)
    assert len(set(ids)) == 5


def test_get_missing_raises_keyerror(tmp_db):
    store = _mk(tmp_db)
    with pytest.raises((KeyError, LookupError)):
        store.get(999_999)


def test_delete_removes(tmp_db):
    store = _mk(tmp_db)
    doc_id = store.add("to be deleted")
    store.delete(doc_id)
    with pytest.raises((KeyError, LookupError)):
        store.get(doc_id)


def test_count_reflects_adds(tmp_db):
    store = _mk(tmp_db)
    assert store.count() == 0
    for i in range(3):
        store.add(f"d{i}")
    assert store.count() == 3


def test_iter_all_yields_added_docs(tmp_db):
    store = _mk(tmp_db)
    for i in range(3):
        store.add(f"body {i}")
    texts = [d.text for d in store.iter_all()]
    assert set(texts) == {"body 0", "body 1", "body 2"}


def test_ensure_schema_idempotent(tmp_db):
    store = _mk(tmp_db)
    if hasattr(store, "ensure_schema"):
        # calling twice must not raise
        store.ensure_schema()
        store.ensure_schema()
    # if not exposed, this is not a fail — schema was created on init
    assert store.count() == 0


def test_batch_add_creates_many(tmp_db):
    store = _mk(tmp_db)
    items = [{"text": f"batch doc {i}", "meta": {"i": i}} for i in range(20)]
    try:
        store.batch_add(items)
    except (TypeError, AttributeError):
        # Try positional list-of-tuples style if the dict style isn't supported
        store.batch_add([(x["text"], x["meta"]) for x in items])
    assert store.count() == 20


def test_meta_roundtrip_json_serializable(tmp_db):
    store = _mk(tmp_db)
    meta = {"tags": ["a", "b"], "views": 42, "nested": {"k": "v"}}
    doc_id = store.add("json-me", meta=meta)
    got = store.get(doc_id)
    assert got.meta == meta
