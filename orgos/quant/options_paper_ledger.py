"""Paper-trading ledger for options orders and positions.

A self-contained SQLite store (separate DB file, not the org memory DB) so the
paper-trading record is isolated from everything else. Mirrors the WAL +
``executescript`` migration pattern used by ``orgos/memory.py``.

Two tables:
  options_paper_orders     — every order we submitted (one row per order)
  options_paper_positions  — open/closed positions with realized P&L

This is the data that finally answers the expectancy question: once it holds real
paper fills, you can measure whether the strategist's recommendations made money.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class OptionsPaperLedger:
    def __init__(self, db_path: str | Path = "./_orgos_memory/options_paper.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._migrate()
        return self._conn

    def _migrate(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS options_paper_orders (
                id              TEXT PRIMARY KEY,
                run_id          TEXT,
                ticker          TEXT NOT NULL,
                strategy        TEXT NOT NULL DEFAULT '',
                legs            TEXT NOT NULL DEFAULT '[]',
                limit_price     REAL,
                status          TEXT NOT NULL DEFAULT 'submitted',
                ib_order_ids    TEXT NOT NULL DEFAULT '[]',
                fill_price      REAL,
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS options_paper_positions (
                id              TEXT PRIMARY KEY,
                order_id        TEXT,
                run_id          TEXT,
                ticker          TEXT NOT NULL,
                strategy        TEXT NOT NULL DEFAULT '',
                legs            TEXT NOT NULL DEFAULT '[]',
                status          TEXT NOT NULL DEFAULT 'open',
                open_price      REAL,
                close_price     REAL,
                realized_pnl    REAL,
                opened_at       TEXT NOT NULL,
                closed_at       TEXT,
                FOREIGN KEY (order_id) REFERENCES options_paper_orders(id)
            );

            CREATE INDEX IF NOT EXISTS idx_paper_orders_status
                ON options_paper_orders(status, created_at);
            CREATE INDEX IF NOT EXISTS idx_paper_positions_status
                ON options_paper_positions(status, opened_at);
        """)

    # ── Orders ────────────────────────────────────────────────────────────────

    def record_order(self, *, ticker: str, strategy: str, legs: list[dict],
                     limit_price: float | None, run_id: str | None,
                     ib_order_ids: list[Any] | None = None,
                     status: str = "submitted") -> str:
        oid = f"opx-{uuid.uuid4().hex[:10]}"
        now = _now()
        self.conn.execute(
            "INSERT INTO options_paper_orders "
            "(id, run_id, ticker, strategy, legs, limit_price, status, ib_order_ids, "
            " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (oid, run_id, ticker, strategy, json.dumps(legs), limit_price, status,
             json.dumps(ib_order_ids or []), now, now),
        )
        self.conn.commit()
        return oid

    def update_order(self, order_id: str, *, status: str | None = None,
                     fill_price: float | None = None,
                     ib_order_ids: list[Any] | None = None) -> None:
        sets, vals = [], []
        if status is not None:
            sets.append("status=?"); vals.append(status)
        if fill_price is not None:
            sets.append("fill_price=?"); vals.append(fill_price)
        if ib_order_ids is not None:
            sets.append("ib_order_ids=?"); vals.append(json.dumps(ib_order_ids))
        if not sets:
            return
        sets.append("updated_at=?"); vals.append(_now())
        vals.append(order_id)
        self.conn.execute(
            f"UPDATE options_paper_orders SET {', '.join(sets)} WHERE id=?", vals)
        self.conn.commit()

    def orders_today(self) -> int:
        today = datetime.now(timezone.utc).date().isoformat()
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM options_paper_orders WHERE created_at >= ?",
            (today,)).fetchone()
        return int(row["n"]) if row else 0

    # ── Positions ─────────────────────────────────────────────────────────────

    def open_position(self, *, order_id: str, ticker: str, strategy: str,
                      legs: list[dict], open_price: float | None,
                      run_id: str | None) -> str:
        pid = f"pos-{uuid.uuid4().hex[:10]}"
        self.conn.execute(
            "INSERT INTO options_paper_positions "
            "(id, order_id, run_id, ticker, strategy, legs, status, open_price, opened_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (pid, order_id, run_id, ticker, strategy, json.dumps(legs), "open",
             open_price, _now()),
        )
        self.conn.commit()
        return pid

    def close_position(self, position_id: str, *, close_price: float | None,
                       realized_pnl: float | None) -> None:
        self.conn.execute(
            "UPDATE options_paper_positions "
            "SET status='closed', close_price=?, realized_pnl=?, closed_at=? WHERE id=?",
            (close_price, realized_pnl, _now(), position_id),
        )
        self.conn.commit()

    def open_positions(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM options_paper_positions WHERE status='open' "
            "ORDER BY opened_at DESC").fetchall()
        return [self._row_to_position(r) for r in rows]

    def count_open_positions(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM options_paper_positions WHERE status='open'"
        ).fetchone()
        return int(row["n"]) if row else 0

    def all_positions(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM options_paper_positions ORDER BY opened_at DESC").fetchall()
        return [self._row_to_position(r) for r in rows]

    @staticmethod
    def _row_to_position(r: sqlite3.Row) -> dict:
        d = dict(r)
        d["legs"] = json.loads(d.get("legs") or "[]")
        return d
