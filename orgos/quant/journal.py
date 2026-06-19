"""Research journal — the strategist's memory, so the desk compounds.

A real analyst doesn't start cold every morning: they remember which hypotheses
paid off, which were dead ends, and what they learned. This is that memory — a
small persistent store of past strategist runs (objective + findings) that gets
injected into the next run's brief and written back at the end.

The loop: read recent findings → don't re-test known-dead hypotheses, build on
known-live pairs → run → record what happened. Free-text summaries (not brittle
structured parsing) — the next run reads them like an analyst reads their notes.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = "./_orgos_memory/quant_journal.db"


@contextmanager
def _conn(db_path: str = DB_PATH):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    try:
        yield con
        con.commit()
    finally:
        con.close()


def _ensure(db_path: str = DB_PATH) -> None:
    with _conn(db_path) as con:
        con.execute(
            "CREATE TABLE IF NOT EXISTS research_journal ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, "
            "objective TEXT NOT NULL, status TEXT, summary TEXT NOT NULL, "
            "tokens INTEGER)"
        )
        # Migrate older DBs in place: the rubric loop added run_id (links to the
        # research trail), score (the optimise strength), and attempts.
        have = {r[1] for r in con.execute("PRAGMA table_info(research_journal)")}
        for col, typ in (("run_id", "TEXT"), ("score", "REAL"), ("attempts", "INTEGER"),
                         ("attempt_run_ids", "TEXT")):
            if col not in have:
                con.execute(f"ALTER TABLE research_journal ADD COLUMN {col} {typ}")


def record(objective: str, summary: str, *, status: str = "", tokens: int | None = None,
           run_id: str | None = None, score: float | None = None,
           attempts: int | None = None, attempt_run_ids: list[str] | None = None,
           db_path: str = DB_PATH) -> int:
    """Append one research run to the journal. Returns the row id."""
    import json
    _ensure(db_path)
    with _conn(db_path) as con:
        cur = con.execute(
            "INSERT INTO research_journal "
            "(ts, objective, status, summary, tokens, run_id, score, attempts, attempt_run_ids) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (dt.datetime.now(dt.timezone.utc).isoformat(), objective, status,
             summary or "", tokens, run_id, score, attempts,
             json.dumps(attempt_run_ids or [])),
        )
        return cur.lastrowid


def recent(n: int = 5, db_path: str = DB_PATH) -> list[dict]:
    """The n most recent journal entries, newest first."""
    import json
    _ensure(db_path)
    with _conn(db_path) as con:
        rows = con.execute(
            "SELECT ts, objective, status, summary, tokens, run_id, score, attempts, attempt_run_ids "
            "FROM research_journal ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
    return [{"ts": r[0], "objective": r[1], "status": r[2], "summary": r[3],
             "tokens": r[4], "run_id": r[5], "score": r[6], "attempts": r[7],
             "attempt_run_ids": json.loads(r[8]) if r[8] else []}
            for r in rows]


def prior_research_block(n: int = 5, *, max_chars: int = 1400, db_path: str = DB_PATH) -> str:
    """Format recent findings for injection into a strategist brief.

    Empty string if the journal is empty (first run). Each entry is trimmed so a
    long history doesn't blow the prompt.
    """
    entries = recent(n, db_path)
    if not entries:
        return ""
    lines = ["## Prior research notes (your own past runs — build on these, "
             "don't re-test known dead ends)"]
    for e in entries:
        when = e["ts"][:10]
        summ = (e["summary"] or "").strip().replace("\n", " ")[:max_chars]
        lines.append(f"- [{when}] objective: {e['objective'][:120]}\n  finding: {summ}")
    return "\n".join(lines)
