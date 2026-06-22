"""Memory layer — persistent storage for runs, decisions, and owner context.

Three concerns:
  1. OrgMemory — SQLite-backed store replacing flat JSONL audit logs.
     Records every spawn() run with structured fields for querying.
  2. OwnerProfile — persistent owner preferences and feedback. Stored in
     the org constitution and injected into agent context.
  3. Context injection — assembling relevant history for agents before a run.

Design: SQLite (zero-dependency, single-file) with JSON payload columns for
flexibility.  Semantic memory (vector search) is Phase 2 — same store,
additional embedding index.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

# ── Owner profile ─────────────────────────────────────────────────────────────


class NotificationThresholds(BaseModel):
    """When the owner wants to be alerted."""

    token_spend_daily: int | None = None
    budget_exceeded_pct: int = 80  # alert at 80% of budget
    consecutive_failures: int = 3


class CommunicationPreferences(BaseModel):
    """How the owner wants to interact."""

    style: str = "concise"  # "concise", "detailed", "technical"
    channels: list[str] = Field(default_factory=lambda: ["terminal"])
    # Future: "slack", "email", "webhook"


class ApprovalRule(BaseModel):
    """A standing rule for when explicit owner approval is required."""

    pattern: str  # fnmatch pattern on action/tool name
    require_approval: bool = True
    note: str = ""


class OwnerProfile(BaseModel):
    """Persistent owner identity — injected into agent context."""

    name: str = "Owner"
    preferences: str = (
        "Conservative risk tolerance. Prefer explicit reasoning. "
        "Flag anything uncertain rather than guessing."
    )
    notification_thresholds: NotificationThresholds = Field(
        default_factory=NotificationThresholds
    )
    communication: CommunicationPreferences = Field(
        default_factory=CommunicationPreferences
    )
    approval_rules: list[ApprovalRule] = Field(default_factory=list)
    feedback: list[str] = Field(default_factory=list)

    def to_context_block(self) -> str:
        """Render as a markdown block for injection into briefs / system prompts."""
        parts = [f"## Owner: {self.name}\n"]
        parts.append(f"**Preferences**: {self.preferences}\n")
        if self.feedback:
            parts.append("**Recent feedback**:")
            for f in self.feedback[-5:]:  # last 5 only
                parts.append(f"- {f}")
        return "\n".join(parts)


# ── Org memory ────────────────────────────────────────────────────────────────


@dataclass
class RunRecord:
    """A single spawn() invocation, stored in the runs table."""

    id: str
    org: str
    department: str | None
    role: str
    status: str
    objective: str
    summary: str
    payload: str
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    success_criteria_met: bool
    requires_human_approval: bool
    created_at: str


@dataclass
class DecisionRecord:
    """An approval, denial, or escalation recorded by the owner or a gate."""

    id: str
    run_id: str | None
    type: str  # "approval", "denial", "escalation", "override"
    role: str
    tool: str | None
    summary: str
    owner_response: str | None
    created_at: str


class OrgMemory:
    """SQLite-backed memory for the org.

    Usage::

        memory = OrgMemory("./_orgos_memory/memory.db")
        memory.record_run("finance", "pair-scanner", envelope, brief, tokens)
        last = memory.last_run("finance", "daily_pair_scan")
        spend = memory.department_spend("finance", days=30)
    """

    def __init__(self, db_path: str | Path = "./_orgos_memory/memory.db"):
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
            CREATE TABLE IF NOT EXISTS runs (
                id              TEXT PRIMARY KEY,
                org             TEXT NOT NULL,
                department      TEXT,
                role            TEXT NOT NULL,
                status          TEXT NOT NULL,
                objective       TEXT NOT NULL,
                summary         TEXT NOT NULL DEFAULT '',
                payload         TEXT NOT NULL DEFAULT '{}',
                total_tokens    INTEGER NOT NULL DEFAULT 0,
                prompt_tokens   INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                success_criteria_met INTEGER NOT NULL DEFAULT 0,
                requires_human_approval INTEGER NOT NULL DEFAULT 0,
                created_at      TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS decisions (
                id              TEXT PRIMARY KEY,
                run_id          TEXT,
                type            TEXT NOT NULL,
                role            TEXT NOT NULL,
                tool            TEXT,
                summary         TEXT NOT NULL DEFAULT '',
                owner_response  TEXT,
                created_at      TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs(id)
            );

            CREATE TABLE IF NOT EXISTS preferences (
                key             TEXT PRIMARY KEY,
                value           TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS heuristics (
                id              TEXT PRIMARY KEY,
                domain          TEXT NOT NULL,
                tags            TEXT NOT NULL DEFAULT '[]',
                rule            TEXT NOT NULL,
                why             TEXT NOT NULL DEFAULT '',
                source_run_id   TEXT,
                score           REAL NOT NULL DEFAULT 0.0,
                use_count       INTEGER NOT NULL DEFAULT 0,
                created_at      TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_runs_dept      ON runs(department, created_at);
            CREATE INDEX IF NOT EXISTS idx_runs_status     ON runs(status, created_at);
            CREATE INDEX IF NOT EXISTS idx_runs_created    ON runs(created_at);
            CREATE INDEX IF NOT EXISTS idx_decisions_run   ON decisions(run_id);
            CREATE INDEX IF NOT EXISTS idx_decisions_type  ON decisions(type, created_at);
            CREATE INDEX IF NOT EXISTS idx_heuristics_domain ON heuristics(domain, score DESC);
        """)

    # ── Write ──────────────────────────────────────────────────────────────

    def record_run(
        self,
        department: str | None,
        role: str,
        envelope: Any,
        brief: Any,
        token_usage: dict[str, int] | None,
        *,
        org: str = "default",
        run_id: str | None = None,
    ) -> str:
        """Record a completed spawn() run. Returns the run_id."""
        import uuid

        rid = run_id or uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()

        self.conn.execute(
            """INSERT OR REPLACE INTO runs
               (id, org, department, role, status, objective, summary, payload,
                total_tokens, prompt_tokens, completion_tokens,
                success_criteria_met, requires_human_approval, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rid,
                org,
                department,
                role,
                getattr(envelope, "status", "unknown"),
                getattr(brief, "objective", str(brief))[:2000],
                getattr(envelope, "summary", "")[:5000],
                str(getattr(envelope, "payload", "{}"))[:10000],
                (token_usage or {}).get("total_tokens", 0),
                (token_usage or {}).get("prompt_tokens", 0),
                (token_usage or {}).get("completion_tokens", 0),
                1 if getattr(envelope, "success_criteria_met", False) else 0,
                1 if getattr(envelope, "requires_human_approval", False) else 0,
                now,
            ),
        )
        self.conn.commit()
        return rid

    def record_decision(
        self,
        *,
        role: str,
        decision_type: str,
        summary: str,
        run_id: str | None = None,
        tool: str | None = None,
        owner_response: str | None = None,
    ) -> str:
        """Record an approval, denial, or escalation."""
        import uuid

        rid = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()

        self.conn.execute(
            """INSERT INTO decisions (id, run_id, type, role, tool, summary, owner_response, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (rid, run_id, decision_type, role, tool, summary, owner_response, now),
        )
        self.conn.commit()
        return rid

    def set_preference(self, key: str, value: Any) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "INSERT OR REPLACE INTO preferences (key, value, updated_at) VALUES (?, ?, ?)",
            (key, json.dumps(value), now),
        )
        self.conn.commit()

    def get_preference(self, key: str, default: Any = None) -> Any:
        row = self.conn.execute(
            "SELECT value FROM preferences WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return default
        return json.loads(row["value"])

    # ── Query ──────────────────────────────────────────────────────────────

    def last_run(self, department: str | None = None, role: str | None = None) -> RunRecord | None:
        """Most recent run, optionally filtered by department or role."""
        clauses = ["1=1"]
        params: list[Any] = []
        if department:
            clauses.append("department = ?")
            params.append(department)
        if role:
            clauses.append("role = ?")
            params.append(role)
        where = " AND ".join(clauses)
        row = self.conn.execute(
            f"SELECT * FROM runs WHERE {where} ORDER BY created_at DESC LIMIT 1",
            params,
        ).fetchone()
        return self._row_to_run(row) if row else None

    def recent_runs(
        self,
        department: str | None = None,
        limit: int = 10,
        days: int | None = 30,
    ) -> list[RunRecord]:
        """Recent runs, newest first."""
        clauses = ["1=1"]
        params: list[Any] = []
        if department:
            clauses.append("department = ?")
            params.append(department)
        if days is not None:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            clauses.append("created_at >= ?")
            params.append(cutoff)
        where = " AND ".join(clauses)
        rows = self.conn.execute(
            f"SELECT * FROM runs WHERE {where} ORDER BY created_at DESC LIMIT ?",
            params + [limit],
        ).fetchall()
        return [self._row_to_run(r) for r in rows]

    def department_spend(self, department: str, days: int = 30) -> dict[str, int]:
        """Total token usage for a department over N days."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        row = self.conn.execute(
            """SELECT COALESCE(SUM(total_tokens), 0) AS total,
                      COALESCE(SUM(prompt_tokens), 0) AS prompt,
                      COALESCE(SUM(completion_tokens), 0) AS completion,
                      COUNT(*) AS runs
               FROM runs
               WHERE department = ? AND created_at >= ?""",
            (department, cutoff),
        ).fetchone()
        return {
            "total_tokens": row["total"],
            "prompt_tokens": row["prompt"],
            "completion_tokens": row["completion"],
            "runs": row["runs"],
        }

    def recent_approvals(self, days: int = 7) -> list[DecisionRecord]:
        """Approvals and denials from the last N days."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = self.conn.execute(
            "SELECT * FROM decisions WHERE created_at >= ? ORDER BY created_at DESC",
            (cutoff,),
        ).fetchall()
        return [self._row_to_decision(r) for r in rows]

    def search_runs(self, query: str, limit: int = 5) -> list[RunRecord]:
        """Simple text search over objectives and summaries."""
        pattern = f"%{query}%"
        rows = self.conn.execute(
            """SELECT * FROM runs
               WHERE objective LIKE ? OR summary LIKE ?
               ORDER BY created_at DESC LIMIT ?""",
            (pattern, pattern, limit),
        ).fetchall()
        return [self._row_to_run(r) for r in rows]

    # ── Context injection ──────────────────────────────────────────────────

    def context_for(
        self,
        department: str | None = None,
        role: str | None = None,
        owner: OwnerProfile | None = None,
    ) -> str:
        """Assemble a context block for injection into an agent's brief.

        Includes: owner preferences, recent department runs, last run summary,
        and token spend.  Designed to be appended to a TaskBrief objective.
        """
        parts: list[str] = []

        if owner:
            parts.append(owner.to_context_block())

        recent = self.recent_runs(department=department, limit=3)
        if recent:
            parts.append("\n## Recent activity\n")
            for r in recent:
                status_icon = "✓" if r.status == "completed" else "✗"
                parts.append(
                    f"- {status_icon} **{r.role}** ({r.created_at[:10]}): "
                    f"{r.summary[:150]}"
                )

        if department:
            spend = self.department_spend(department, days=7)
            parts.append(
                f"\n## Token usage (7-day)\n"
                f"- {spend['total_tokens']:,} total tokens across {spend['runs']} runs"
            )

        last = self.last_run(department=department, role=role)
        if last and last.status != "completed":
            parts.append(
                f"\n⚠️ **Last run was not completed** (status={last.status}). "
                f"Summary: {last.summary[:200]}"
            )

        return "\n".join(parts)

    # ── Internals ──────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_run(row: sqlite3.Row) -> RunRecord:
        return RunRecord(
            id=row["id"],
            org=row["org"],
            department=row["department"],
            role=row["role"],
            status=row["status"],
            objective=row["objective"],
            summary=row["summary"],
            payload=row["payload"],
            total_tokens=row["total_tokens"],
            prompt_tokens=row["prompt_tokens"],
            completion_tokens=row["completion_tokens"],
            success_criteria_met=bool(row["success_criteria_met"]),
            requires_human_approval=bool(row["requires_human_approval"]),
            created_at=row["created_at"],
        )

    @staticmethod
    def _row_to_decision(row: sqlite3.Row) -> DecisionRecord:
        return DecisionRecord(
            id=row["id"],
            run_id=row["run_id"],
            type=row["type"],
            role=row["role"],
            tool=row["tool"],
            summary=row["summary"],
            owner_response=row["owner_response"],
            created_at=row["created_at"],
        )

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None


# ── Memory MCP factory ─────────────────────────────────────────────────────


def create_memory_mcp(db_path: str = "./_orgos_memory/memory.db") -> Any:
    """Create an MCPServerStdio config pointing at the memory MCP server.

    Usage::

        from orgos.memory import create_memory_mcp
        dept.shared_mcps.append(create_memory_mcp("./_orgos_memory/memory.db"))
    """
    from crewai.mcp.config import MCPServerStdio

    import sys
    return MCPServerStdio(
        command=sys.executable,
        args=["-m", "orgos.mcps.memory_mcp", "--db", db_path],
    )
