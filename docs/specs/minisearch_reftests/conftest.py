"""Shared fixtures for the held-out reference test suite.

Fixtures here are documented in the spec (`tmp_db` is explicitly named).
Others are additional test scaffolding that any reasonable implementation
of the spec should be able to satisfy.
"""
from __future__ import annotations

import sqlite3
import pytest


@pytest.fixture
def tmp_db(tmp_path):
    """Fresh SQLite connection — spec says conftest exposes this fixture."""
    p = tmp_path / "ms.db"
    conn = sqlite3.connect(str(p))
    yield conn
    conn.close()


@pytest.fixture
def corpus():
    """Small fixed corpus for search behavior tests."""
    return [
        # (text, meta)
        ("Python is a programming language used for data science and web development.",
         {"title": "Python intro", "views": 100}),
        ("Regular expressions in Python allow flexible string matching.",
         {"title": "Regex guide", "views": 50}),
        ("Machine learning models require careful data preprocessing.",
         {"title": "ML basics", "views": 200}),
        ("The Django web framework is written in Python.",
         {"title": "Django overview", "views": 75}),
        ("Rust is a systems programming language with memory safety guarantees.",
         {"title": "Rust intro", "views": 30}),
    ]
