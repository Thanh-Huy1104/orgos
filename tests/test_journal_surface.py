"""The journal/trail surface the dashboard reads: enriched journal fields,
schema migration of old DBs, and recent_trails listing."""

import sqlite3
from pathlib import Path

from orgos.quant import journal as J
from orgos.spawn import recent_trails
from orgos.spawn import audit


class TestJournalFields:
    def test_record_and_recent_carry_rubric_fields(self, tmp_path):
        db = str(tmp_path / "j.db")
        J.record("find utilities pairs", "found AEE/NI", status="completed",
                 tokens=1234, run_id="chain-abc", score=0.9998, attempts=2,
                 attempt_run_ids=["chain-aaa", "chain-abc"], db_path=db)
        [e] = J.recent(5, db_path=db)
        assert e["run_id"] == "chain-abc"
        assert e["score"] == 0.9998
        assert e["attempts"] == 2
        assert e["tokens"] == 1234
        assert e["status"] == "completed"
        assert e["attempt_run_ids"] == ["chain-aaa", "chain-abc"]

    def test_migrates_legacy_db_without_new_columns(self, tmp_path):
        db = str(tmp_path / "old.db")
        # simulate a pre-rubric DB: original 5-column schema, one row
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE research_journal (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "ts TEXT NOT NULL, objective TEXT NOT NULL, status TEXT, "
                    "summary TEXT NOT NULL, tokens INTEGER)")
        con.execute("INSERT INTO research_journal (ts, objective, status, summary, tokens) "
                    "VALUES ('2026-01-01', 'old hunt', 'completed', 'old finding', 99)")
        con.commit(); con.close()

        # recent() triggers _ensure() → ALTER TABLE adds the missing columns
        [e] = J.recent(5, db_path=db)
        assert e["objective"] == "old hunt"
        assert e["run_id"] is None and e["score"] is None and e["attempts"] is None
        # and a new enriched row coexists
        J.record("new hunt", "new finding", run_id="r2", score=0.5, attempts=1, db_path=db)
        assert J.recent(5, db_path=db)[0]["run_id"] == "r2"


class TestRecentTrails:
    def test_lists_recent_runs_newest_first(self, tmp_path, monkeypatch):
        d = tmp_path / "_audit_logs"
        d.mkdir()
        # two runs: one with 2 tool calls (1 ok), one with none
        (d / "chain-old.jsonl").write_text(
            '{"type":"tool_call","tool":"scan","ok":true}\n'
            '{"type":"tool_call","tool":"news","ok":false}\n')
        (d / "chain-new.jsonl").write_text('{"type":"task"}\n')
        # make chain-new newer
        import os, time
        os.utime(d / "chain-old.jsonl", (time.time() - 100, time.time() - 100))

        monkeypatch.setattr(audit, "AUDIT_DIR", d)
        runs = recent_trails(10)
        assert [r["run_id"] for r in runs] == ["chain-new", "chain-old"]  # newest first
        old = next(r for r in runs if r["run_id"] == "chain-old")
        assert old["tool_calls"] == 2 and old["ok"] == 1
