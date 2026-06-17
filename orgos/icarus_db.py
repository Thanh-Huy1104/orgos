"""Connection plumbing for Icarus's TimescaleDB.

Two cursor types, deliberately separated:
  - ro_cursor():  read-only session (engine state, P&L). orgos OBSERVES Icarus.
  - rw_cursor():  read-write, used ONLY for orgos-namespaced tables (the
    `orgos_*` bars cache). It must never touch Icarus's engine tables — that's
    enforced by convention + the `orgos_` table prefix, not by the DB.

The URI comes from ICARUS_PG_URI, else Icarus's own .env (PG_URI).
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

ICARUS_PATH = Path(os.environ.get("ICARUS_PATH", "/home/th/quant-engine"))


def pg_uri() -> str:
    uri = os.environ.get("ICARUS_PG_URI")
    if uri:
        return uri
    env = ICARUS_PATH / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line.startswith("PG_URI="):
                return line.split("=", 1)[1].strip()
    raise RuntimeError(
        f"No Icarus DB URI: set ICARUS_PG_URI or ensure {ICARUS_PATH}/.env has PG_URI"
    )


@contextmanager
def ro_cursor():
    """Read-only autocommit cursor — the session refuses writes at the DB level."""
    import psycopg2

    conn = psycopg2.connect(pg_uri())
    conn.set_session(readonly=True, autocommit=True)
    try:
        yield conn.cursor()
    finally:
        conn.close()


@contextmanager
def rw_cursor():
    """Read-write cursor for orgos-namespaced tables ONLY (e.g. the bars cache).

    Commits on clean exit, rolls back on error. Callers must restrict writes to
    `orgos_*` tables — this connection is not a license to touch engine state.
    """
    import psycopg2

    conn = psycopg2.connect(pg_uri())
    try:
        yield conn.cursor()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def rows(cur) -> list[dict]:
    """Materialise a cursor's result as a list of dicts."""
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


# ── Live-state reads (all read-only) ──────────────────────────────────────────

def account_snapshot() -> dict | None:
    """Latest equity / available funds / open-position count."""
    with ro_cursor() as cur:
        cur.execute(
            "SELECT timestamp, total_equity, available_funds, open_positions_count "
            "FROM account_history ORDER BY timestamp DESC LIMIT 1"
        )
        r = rows(cur)
    if not r:
        return None
    a = r[0]
    return {"as_of": a["timestamp"].isoformat(),
            "total_equity": float(a["total_equity"]),
            "available_funds": float(a["available_funds"]),
            "open_positions": int(a["open_positions_count"])}


def active_pairs() -> list[dict]:
    """The pairs Icarus is actually configured to trade (is_active)."""
    with ro_cursor() as cur:
        cur.execute(
            "SELECT pair_id, asset_y, asset_x FROM trading_pairs "
            "WHERE is_active = true ORDER BY pair_id"
        )
        return [{"pair_id": r["pair_id"], "pair": f"{r['asset_y']}/{r['asset_x']}",
                 "y": r["asset_y"], "x": r["asset_x"]} for r in rows(cur)]


def live_pair_state() -> list[dict]:
    """Latest engine state per pair: its OWN z-score, hedge ratio, OU params.

    Reads pair_state_log (the reliable signal — market_ticks.z_score is
    badly-scaled), joined to trading_pairs for human-readable symbols.
    """
    with ro_cursor() as cur:
        cur.execute(
            "SELECT DISTINCT ON (s.pair_id) s.pair_id, t.asset_y, t.asset_x, "
            "  s.time, s.z_score, s.hedge_ratio, s.hurst_exponent "
            "FROM pair_state_log s JOIN trading_pairs t USING (pair_id) "
            "ORDER BY s.pair_id, s.time DESC"
        )
        out = []
        for r in rows(cur):
            out.append({
                "pair_id": r["pair_id"], "pair": f"{r['asset_y']}/{r['asset_x']}",
                "as_of": r["time"].isoformat(),
                "z_score": round(float(r["z_score"]), 3) if r["z_score"] is not None else None,
                "hedge_ratio": round(float(r["hedge_ratio"]), 4) if r["hedge_ratio"] is not None else None,
                "hurst": round(float(r["hurst_exponent"]), 3) if r["hurst_exponent"] is not None else None,
            })
        return out


def performance_summary() -> dict:
    """Aggregate realized P&L across closed trades."""
    with ro_cursor() as cur:
        cur.execute(
            "SELECT count(*) n, count(*) FILTER (WHERE realized_pnl > 0) wins, "
            "  coalesce(sum(realized_pnl),0) total_pnl, "
            "  coalesce(avg(realized_pnl),0) avg_pnl "
            "FROM stat_arb_executions WHERE realized_pnl IS NOT NULL"
        )
        r = rows(cur)[0]
    n = int(r["n"])
    return {"closed_trades": n, "wins": int(r["wins"]),
            "win_rate": round(int(r["wins"]) / n, 3) if n else None,
            "total_realized_pnl": round(float(r["total_pnl"]), 2),
            "avg_pnl_per_trade": round(float(r["avg_pnl"]), 2)}
