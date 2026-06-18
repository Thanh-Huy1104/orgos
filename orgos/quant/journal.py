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


def record(objective: str, summary: str, *, status: str = "", tokens: int | None = None,
           db_path: str = DB_PATH) -> int:
    """Append one research run to the journal. Returns the row id."""
    _ensure(db_path)
    with _conn(db_path) as con:
        cur = con.execute(
            "INSERT INTO research_journal (ts, objective, status, summary, tokens) "
            "VALUES (?,?,?,?,?)",
            (dt.datetime.now(dt.timezone.utc).isoformat(), objective, status,
             summary or "", tokens),
        )
        return cur.lastrowid


def recent(n: int = 5, db_path: str = DB_PATH) -> list[dict]:
    """The n most recent journal entries, newest first."""
    _ensure(db_path)
    with _conn(db_path) as con:
        rows = con.execute(
            "SELECT ts, objective, status, summary FROM research_journal "
            "ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
    return [{"ts": r[0], "objective": r[1], "status": r[2], "summary": r[3]} for r in rows]


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
