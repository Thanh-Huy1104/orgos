"""Tests for the Reflector (two-loop learning architecture)."""

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from orgos.reflect import Reflector, Heuristic, _tokenise, _truncate, _extract_tags


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_grade(passed: bool, score: float = 0.0, failures=None, notes=""):
    return SimpleNamespace(
        passed=passed,
        score=score,
        failures=failures or [],
        notes=notes,
    )


def _make_result(grades=None, summary="test run", run_id="abc123"):
    envelope = SimpleNamespace(summary=summary, status="completed")
    r = SimpleNamespace(
        envelope=envelope,
        run_id=run_id,
        attempt_grades=grades or [],
        grade=grades[-1] if grades else None,
    )
    return r


def _tmp_reflector(domain="test"):
    with tempfile.TemporaryDirectory() as td:
        db = str(Path(td) / "test.db")
        yield Reflector(domain=domain, db_path=db)


# ── Unit: helpers ──────────────────────────────────────────────────────────────


def test_tokenise_strips_stop_words():
    tokens = _tokenise("find a pair in the energy sector")
    assert "pair" in tokens
    assert "energy" in tokens
    assert "sector" in tokens
    assert "the" not in tokens
    assert "in" not in tokens
    assert "a" not in tokens


def test_tokenise_min_length():
    tokens = _tokenise("find ab pairs")
    assert "ab" not in tokens  # len < 3
    assert "find" in tokens
    assert "pairs" in tokens


def test_truncate_short():
    assert _truncate("hello", 10) == "hello"


def test_truncate_long():
    result = _truncate("hello world foo bar", 12)
    assert len(result) <= 15  # truncated + ellipsis
    assert result.endswith("…")


def test_extract_tags_caps():
    tags = _extract_tags("energy sector cointegration pairs", max_tags=2)
    assert len(tags) <= 2


# ── Unit: Reflector.reflect ────────────────────────────────────────────────────


def test_reflect_no_grades_returns_empty():
    with tempfile.TemporaryDirectory() as td:
        r = Reflector("test", db_path=str(Path(td) / "db"))
        result = _make_result(grades=[])
        assert r.reflect(result) == []


def test_reflect_single_pass_no_notes_returns_empty():
    with tempfile.TemporaryDirectory() as td:
        r = Reflector("test", db_path=str(Path(td) / "db"))
        result = _make_result(grades=[_make_grade(True, score=0.8, notes="")])
        # No notes → no success heuristic extracted
        extracted = r.reflect(result)
        assert extracted == []


def test_reflect_single_pass_high_score_with_notes():
    with tempfile.TemporaryDirectory() as td:
        r = Reflector("test", db_path=str(Path(td) / "db"))
        result = _make_result(
            grades=[_make_grade(True, score=0.9, notes="iron condor on high IV rank ticker")]
        )
        extracted = r.reflect(result)
        assert len(extracted) == 1
        assert "Works:" in extracted[0].rule


def test_reflect_fail_then_pass_extracts_failure_heuristic():
    with tempfile.TemporaryDirectory() as td:
        r = Reflector("test", db_path=str(Path(td) / "db"))
        grades = [
            _make_grade(False, score=0.2, failures=["IV rank was neutral, no edge signal"]),
            _make_grade(True, score=0.8, notes="found high IV rank on AAPL"),
        ]
        result = _make_result(grades=grades)
        extracted = r.reflect(result)
        # Should extract at least a failure recovery heuristic
        assert len(extracted) >= 1
        rules = [h.rule for h in extracted]
        assert any("Avoid:" in rule for rule in rules)


def test_reflect_persists_to_db():
    with tempfile.TemporaryDirectory() as td:
        db = str(Path(td) / "db")
        r = Reflector("test", db_path=db)
        grades = [
            _make_grade(False, score=0.1, failures=["no pairs survived FDR filter"]),
            _make_grade(True, score=0.75, notes="sector momentum worked"),
        ]
        result = _make_result(grades=grades)
        r.reflect(result)

        # Re-load from same DB
        r2 = Reflector("test", db_path=db)
        loaded = r2._load_domain()
        assert len(loaded) >= 1


# ── Unit: Reflector.retrieve ───────────────────────────────────────────────────


def test_retrieve_empty_db_returns_empty():
    with tempfile.TemporaryDirectory() as td:
        r = Reflector("test", db_path=str(Path(td) / "db"))
        result = r.retrieve("find cointegrated energy pairs", n=3)
        assert result == []


def test_retrieve_keyword_relevance():
    with tempfile.TemporaryDirectory() as td:
        db = str(Path(td) / "db")
        r = Reflector("test", db_path=db)

        h_relevant = Heuristic(
            id="aaa", domain="test",
            tags=["energy", "cointegration", "pairs"],
            rule="Avoid: energy sector pairs have high correlation but weak cointegration",
            why="empirical",
            source_run_id=None, score=0.8,
        )
        h_irrelevant = Heuristic(
            id="bbb", domain="test",
            tags=["crypto", "funding", "carry"],
            rule="Works: crypto funding carry on BTC/ETH",
            why="empirical",
            source_run_id=None, score=0.9,
        )
        r._store(h_relevant)
        r._store(h_irrelevant)

        results = r.retrieve("find cointegrated energy sector pairs", n=3)
        assert len(results) >= 1
        # The relevant heuristic should rank higher
        assert results[0].id == "aaa"


def test_retrieve_bumps_use_count():
    with tempfile.TemporaryDirectory() as td:
        db = str(Path(td) / "db")
        r = Reflector("test", db_path=db)
        h = Heuristic(
            id="ccc", domain="test",
            tags=["energy", "pairs"],
            rule="Avoid: energy sector",
            why="test",
            source_run_id=None, score=0.7,
        )
        r._store(h)
        r.retrieve("find energy pairs", n=3)
        loaded = r._load_domain()
        assert loaded[0].use_count == 1


# ── Unit: Reflector.inject_block ──────────────────────────────────────────────


def test_inject_block_empty():
    with tempfile.TemporaryDirectory() as td:
        r = Reflector("test", db_path=str(Path(td) / "db"))
        assert r.inject_block([]) == ""


def test_inject_block_formats_bullets():
    with tempfile.TemporaryDirectory() as td:
        r = Reflector("test", db_path=str(Path(td) / "db"))
        h = Heuristic(
            id="x", domain="test", tags=[],
            rule="Avoid: bad approach", why="it failed",
            source_run_id=None, score=0.5,
        )
        block = r.inject_block([h])
        assert "Playbook" in block
        assert "Avoid: bad approach" in block
        assert "it failed" in block


# ── Unit: deduplication ────────────────────────────────────────────────────────


def test_deduplication_rejects_similar():
    with tempfile.TemporaryDirectory() as td:
        db = str(Path(td) / "db")
        r = Reflector("test", db_path=db)
        h1 = Heuristic(
            id="d1", domain="test", tags=["energy", "pairs"],
            rule="Avoid: energy sector pairs weak cointegration",
            why="test", source_run_id=None, score=0.7,
        )
        h2 = Heuristic(
            id="d2", domain="test", tags=["energy", "pairs"],
            rule="Avoid: energy pairs weak cointegration sector",
            why="test", source_run_id=None, score=0.7,
        )
        r._store(h1)
        assert r._is_duplicate(h2)


def test_deduplication_allows_different():
    with tempfile.TemporaryDirectory() as td:
        db = str(Path(td) / "db")
        r = Reflector("test", db_path=db)
        h1 = Heuristic(
            id="e1", domain="test", tags=["energy"],
            rule="Avoid: energy sector pairs",
            why="test", source_run_id=None, score=0.7,
        )
        h2 = Heuristic(
            id="e2", domain="test", tags=["crypto"],
            rule="Works: crypto funding carry strategy",
            why="test", source_run_id=None, score=0.8,
        )
        r._store(h1)
        assert not r._is_duplicate(h2)


# ── Integration: full reflect → retrieve → inject cycle ───────────────────────


def test_full_cycle():
    with tempfile.TemporaryDirectory() as td:
        db = str(Path(td) / "db")
        r = Reflector("quant_pairs", db_path=db)

        # Simulate a run that failed once then passed
        grades = [
            _make_grade(False, score=0.1, failures=["FDR filter eliminated all utility pairs"]),
            _make_grade(True, score=0.82, notes="tech sector momentum pairs survived FDR"),
        ]
        result = _make_result(grades=grades, summary="found MSFT/GOOGL pair")
        r.reflect(result)

        # Next run: retrieve relevant heuristics for a similar objective
        heuristics = r.retrieve("find cointegrated tech sector pairs", n=4)
        assert len(heuristics) >= 1

        block = r.inject_block(heuristics)
        assert "Playbook" in block
        # The failure heuristic about FDR/utility should appear
        assert len(block) > 20
