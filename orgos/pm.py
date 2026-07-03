"""Project management — task tracking, test running, git operations.

PMStore is a SQLite-backed store for project tasks, test runs, and git
history.  Used by the PM MCP server (pm_mcp.py) to give agents
project-management capabilities.

Usage:
    from orgos.pm import PMStore
    pm = PMStore("./_orgos_memory/pm.db")
    pm.create_task("Vet the AEE/NI linkage thesis", department="research")
    pm.record_test_run("task-1", "pytest", 0, "15 passed", passed=True)
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


@dataclass
class Task:
    id: str
    title: str
    description: str
    department: str | None
    status: str  # todo, in_progress, review, done, blocked
    priority: str  # low, medium, high, critical
    assigned_to: str | None
    created_at: str
    updated_at: str


@dataclass
class TestRun:
    id: str
    task_id: str | None
    command: str
    exit_code: int
    output: str
    passed: bool
    created_at: str


@dataclass
class GitOp:
    id: str
    task_id: str | None
    operation: str  # status, branch, commit, push
    details: str
    pushed: bool
    created_at: str


@dataclass
class Project:
    id: str
    name: str
    goal: str
    owner: str
    status: str  # active, completed, blocked, archived
    task_ids: str  # JSON list of task IDs
    departments: str  # JSON list of department names
    final_report: str
    created_at: str
    updated_at: str


class PMStore:
    """SQLite store for project management data."""

    def __init__(self, db_path: str | Path = "./_orgos_memory/pm.db"):
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
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                department TEXT,
                status TEXT NOT NULL DEFAULT 'todo',
                priority TEXT NOT NULL DEFAULT 'medium',
                assigned_to TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS test_runs (
                id TEXT PRIMARY KEY,
                task_id TEXT,
                command TEXT NOT NULL,
                exit_code INTEGER NOT NULL DEFAULT 0,
                output TEXT DEFAULT '',
                passed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS git_ops (
                id TEXT PRIMARY KEY,
                task_id TEXT,
                operation TEXT NOT NULL,
                details TEXT DEFAULT '',
                pushed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
            CREATE INDEX IF NOT EXISTS idx_tasks_dept ON tasks(department);

            CREATE TABLE IF NOT EXISTS research_reports (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                query TEXT NOT NULL,
                department TEXT DEFAULT 'research',
                summary TEXT DEFAULT '',
                content TEXT DEFAULT '',
                sources_count INTEGER DEFAULT 0,
                tags TEXT DEFAULT '[]',
                tokens_used INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                goal TEXT DEFAULT '',
                owner TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                task_ids TEXT DEFAULT '[]',
                departments TEXT DEFAULT '[]',
                final_report TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sprints (
                id TEXT PRIMARY KEY,
                branch TEXT NOT NULL,
                picked_issue TEXT NOT NULL DEFAULT '{}',
                envelopes_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'in_progress',
                started_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sprints_status ON sprints(status);
            CREATE INDEX IF NOT EXISTS idx_sprints_started_at ON sprints(started_at DESC);

            CREATE TABLE IF NOT EXISTS dora_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                window_days INTEGER NOT NULL,
                deploy_freq REAL NOT NULL,
                lead_time_p50 REAL NOT NULL,
                cfr REAL NOT NULL,
                mttr_p50 REAL NOT NULL,
                tier TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_dora_created ON dora_snapshots(created_at DESC);

            CREATE TABLE IF NOT EXISTS role_attribution (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sprint_id TEXT NOT NULL,
                role_name TEXT NOT NULL,
                score REAL NOT NULL,
                rubric_baseline REAL NOT NULL,
                rubric_ablated REAL NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_attribution_role ON role_attribution(role_name, created_at);

            CREATE TABLE IF NOT EXISTS adrs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sprint_id TEXT,
                kind TEXT NOT NULL,
                before_yaml TEXT NOT NULL DEFAULT '',
                after_yaml TEXT NOT NULL DEFAULT '',
                rationale TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_adrs_status ON adrs(status, created_at DESC);
        """)

    # ── Projects ───────────────────────────────────────────────────────────

    def create_project(
        self, name: str, goal: str = "", owner: str = "owner",
    ) -> Project:
        pid = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO projects (id, name, goal, owner, status, task_ids, departments, final_report, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'active', '[]', '[]', '', ?, ?)""",
            (pid, name, goal, owner, now, now),
        )
        self.conn.commit()
        return self._row_to_project(
            self.conn.execute("SELECT * FROM projects WHERE id = ?", (pid,)).fetchone()
        )

    def get_project(self, project_id: str) -> Project | None:
        row = self.conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return self._row_to_project(row) if row else None

    def list_projects(self, status: str | None = None, limit: int = 20) -> list[Project]:
        if status:
            rows = self.conn.execute(
                "SELECT * FROM projects WHERE status = ? ORDER BY updated_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM projects ORDER BY updated_at DESC LIMIT ?", (limit,),
            ).fetchall()
        return [self._row_to_project(r) for r in rows]

    def update_project_status(self, project_id: str, status: str) -> Project | None:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "UPDATE projects SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, project_id),
        )
        self.conn.commit()
        return self.get_project(project_id)

    def link_tasks_to_project(self, project_id: str, task_ids: list[str]) -> None:
        project = self.get_project(project_id)
        if project is None:
            return
        existing = json.loads(project.task_ids)
        all_ids = list(dict.fromkeys(existing + task_ids))  # deduped, order preserved
        self.conn.execute(
            "UPDATE projects SET task_ids = ?, updated_at = ? WHERE id = ?",
            (json.dumps(all_ids), datetime.now(timezone.utc).isoformat(), project_id),
        )
        self.conn.commit()

    def set_project_report(self, project_id: str, report: str) -> None:
        self.conn.execute(
            "UPDATE projects SET final_report = ?, updated_at = ? WHERE id = ?",
            (report, datetime.now(timezone.utc).isoformat(), project_id),
        )
        self.conn.commit()

    # ── Research reports ────────────────────────────────────────────────────

    def save_research_report(
        self, title: str, query: str, summary: str, content: str,
        sources_count: int = 0, tags: list[str] | None = None, tokens_used: int = 0,
    ) -> str:
        rid = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO research_reports (id, title, query, summary, content, sources_count, tags, tokens_used, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (rid, title, query, summary, content[:50000], sources_count,
             json.dumps(tags or []), tokens_used, now),
        )
        self.conn.commit()
        return rid

    def list_research_reports(self, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, title, query, summary, sources_count, tags, tokens_used, created_at FROM research_reports ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [{
            "id": r["id"], "title": r["title"], "query": r["query"][:200],
            "summary": r["summary"][:300], "sources_count": r["sources_count"],
            "tags": json.loads(r["tags"]), "tokens_used": r["tokens_used"],
            "created_at": r["created_at"],
        } for r in rows]

    def get_research_report(self, report_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM research_reports WHERE id = ?", (report_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"], "title": row["title"], "query": row["query"],
            "summary": row["summary"], "content": row["content"],
            "sources_count": row["sources_count"],
            "tags": json.loads(row["tags"]), "tokens_used": row["tokens_used"],
            "created_at": row["created_at"],
        }

    # ── Sprints ────────────────────────────────────────────────────────────

    def create_sprint(
        self, sprint_id: str, branch: str, picked_issue: dict,
        status: str = "in_progress",
        started_at: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        started = started_at or now
        self.conn.execute(
            "INSERT INTO sprints (id, branch, picked_issue, envelopes_json, "
            "status, started_at, updated_at) VALUES (?, ?, ?, '{}', ?, ?, ?)",
            (sprint_id, branch, json.dumps(picked_issue), status, started, now),
        )
        self.conn.commit()

    def record_sprint_envelope(
        self, sprint_id: str, phase: str, envelope_json: str,
    ) -> None:
        row = self.conn.execute(
            "SELECT envelopes_json FROM sprints WHERE id = ?", (sprint_id,)
        ).fetchone()
        if row is None:
            return
        envs = json.loads(row["envelopes_json"] or "{}")
        envs[phase] = json.loads(envelope_json) if envelope_json else None
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "UPDATE sprints SET envelopes_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(envs), now, sprint_id),
        )
        self.conn.commit()

    def update_sprint_status(self, sprint_id: str, status: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "UPDATE sprints SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, sprint_id),
        )
        self.conn.commit()

    def get_sprint(self, sprint_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM sprints WHERE id = ?", (sprint_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_sprints(self, limit: int = 50) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM sprints ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ── DORA snapshots ─────────────────────────────────────────────────────

    def record_dora_snapshot(self, snapshot: dict) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "INSERT INTO dora_snapshots (window_days, deploy_freq, "
            "lead_time_p50, cfr, mttr_p50, tier, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (snapshot["window_days"], snapshot["deploy_freq"],
             snapshot["lead_time_p50"], snapshot["cfr"],
             snapshot["mttr_p50"], snapshot["tier"], now),
        )
        self.conn.commit()

    def list_dora_snapshots(self, limit: int = 90) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM dora_snapshots ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def latest_dora_snapshot(self) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM dora_snapshots ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def get_project_progress(self, project_id: str) -> dict[str, Any]:
        project = self.get_project(project_id)
        if project is None:
            return {"error": "Project not found"}
        task_ids = json.loads(project.task_ids)
        tasks = []
        for tid in task_ids:
            t = self.get_task(tid)
            if t:
                tasks.append({
                    "id": t.id, "title": t.title, "status": t.status,
                    "priority": t.priority, "department": t.department,
                    "description": t.description, "updated_at": t.updated_at,
                })
        done = sum(1 for t in tasks if t["status"] == "done")
        total = len(tasks)
        return {
            "project_id": project_id,
            "project_name": project.name,
            "project_status": project.status,
            "goal": project.goal,
            "tasks_total": total,
            "tasks_done": done,
            "tasks_in_progress": sum(1 for t in tasks if t["status"] == "in_progress"),
            "tasks_todo": sum(1 for t in tasks if t["status"] == "todo"),
            "tasks_blocked": sum(1 for t in tasks if t["status"] == "blocked"),
            "progress_pct": round(done / max(total, 1) * 100, 1),
            "final_report": project.final_report,
            "tasks": tasks,
        }

    def create_task(
        self, title: str, description: str = "",
        department: str | None = None, priority: str = "medium",
        assigned_to: str | None = None,
    ) -> Task:
        tid = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO tasks (id, title, description, department, status, priority, assigned_to, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'todo', ?, ?, ?, ?)""",
            (tid, title, description, department, priority, assigned_to, now, now),
        )
        self.conn.commit()
        return Task(tid, title, description, department, "todo", priority, assigned_to, now, now)

    def list_tasks(
        self, department: str | None = None, status: str | None = None, limit: int = 20,
    ) -> list[Task]:
        clauses = ["1=1"]
        params: list[Any] = []
        if department:
            clauses.append("department = ?")
            params.append(department)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = " AND ".join(clauses)
        rows = self.conn.execute(
            f"SELECT * FROM tasks WHERE {where} ORDER BY created_at DESC LIMIT ?",
            params + [limit],
        ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def update_task(self, task_id: str, status: str | None = None, notes: str = "") -> Task | None:
        now = datetime.now(timezone.utc).isoformat()
        if status:
            self.conn.execute(
                "UPDATE tasks SET status = ?, updated_at = ?, description = description || ? WHERE id = ?",
                (status, now, f"\n[{now}] {notes}" if notes else "", task_id),
            )
        self.conn.commit()
        row = self.conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return self._row_to_task(row) if row else None

    def get_task(self, task_id: str) -> Task | None:
        row = self.conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return self._row_to_task(row) if row else None

    # ── Test runs ──────────────────────────────────────────────────────────

    def record_test_run(
        self, command: str, exit_code: int, output: str, passed: bool,
        task_id: str | None = None,
    ) -> TestRun:
        rid = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO test_runs (id, task_id, command, exit_code, output, passed, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (rid, task_id, command, exit_code, output[:5000], 1 if passed else 0, now),
        )
        self.conn.commit()
        return TestRun(rid, task_id, command, exit_code, output, passed, now)

    def recent_test_runs(self, limit: int = 10) -> list[TestRun]:
        rows = self.conn.execute(
            "SELECT * FROM test_runs ORDER BY created_at DESC LIMIT ?", (limit,),
        ).fetchall()
        return [self._row_to_test(r) for r in rows]

    # ── Git operations ─────────────────────────────────────────────────────

    def record_git_op(
        self, operation: str, details: str = "", pushed: bool = False,
        task_id: str | None = None,
    ) -> GitOp:
        rid = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO git_ops (id, task_id, operation, details, pushed, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (rid, task_id, operation, details, 1 if pushed else 0, now),
        )
        self.conn.commit()
        return GitOp(rid, task_id, operation, details, pushed, now)

    def recent_git_ops(self, limit: int = 10) -> list[GitOp]:
        rows = self.conn.execute(
            "SELECT * FROM git_ops ORDER BY created_at DESC LIMIT ?", (limit,),
        ).fetchall()
        return [self._row_to_git(r) for r in rows]

    # ── Run tests (subprocess) ─────────────────────────────────────────────

    def run_tests(
        self, command: str, working_dir: str = ".", timeout_sec: int = 120,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute a test command and record the result."""
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True,
                cwd=working_dir, timeout=timeout_sec,
            )
            output = result.stdout
            if result.stderr:
                output += f"\n[stderr]\n{result.stderr}"
            passed = result.returncode == 0
            self.record_test_run(command, result.returncode, output, passed, task_id=task_id)
            return {
                "passed": passed,
                "exit_code": result.returncode,
                "output": output[:3000],
            }
        except subprocess.TimeoutExpired:
            self.record_test_run(command, -1, f"Timed out after {timeout_sec}s", False, task_id=task_id)
            return {"passed": False, "exit_code": -1, "output": f"Timed out after {timeout_sec}s"}

    # ── Git helpers ────────────────────────────────────────────────────────

    def git_status(self, repo_path: str = ".") -> dict[str, Any]:
        """Get git status for a repo."""
        try:
            r = subprocess.run(
                "git status --short", shell=True, capture_output=True, text=True,
                cwd=repo_path, timeout=15,
            )
            branch = subprocess.run(
                "git branch --show-current", shell=True, capture_output=True, text=True,
                cwd=repo_path, timeout=10,
            )
            self.record_git_op("status", f"branch={branch.stdout.strip()}")
            return {
                "branch": branch.stdout.strip(),
                "changes": r.stdout.strip() or "(clean)",
                "error": r.stderr.strip() if r.stderr else None,
            }
        except Exception as e:
            return {"error": str(e)}

    def git_create_branch(self, repo_path: str, branch_name: str) -> dict[str, Any]:
        """Create a new git branch. Safe — local only, no push."""
        try:
            r = subprocess.run(
                f"git checkout -b {branch_name}", shell=True, capture_output=True, text=True,
                cwd=repo_path, timeout=15,
            )
            self.record_git_op("branch", f"created {branch_name}")
            return {
                "created": r.returncode == 0,
                "branch": branch_name,
                "output": r.stdout.strip() or r.stderr.strip(),
            }
        except Exception as e:
            return {"error": str(e)}

    # ── Role attribution ───────────────────────────────────────────────────────

    def record_role_attribution(
        self, sprint_id: str, role_name: str, score: float,
        rubric_baseline: float, rubric_ablated: float,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "INSERT INTO role_attribution (sprint_id, role_name, score, "
            "rubric_baseline, rubric_ablated, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (sprint_id, role_name, score, rubric_baseline, rubric_ablated, now),
        )
        self.conn.commit()

    def list_role_attribution(
        self, role_name: str, since_days: int = 30,
    ) -> list[dict]:
        since = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()
        rows = self.conn.execute(
            "SELECT * FROM role_attribution WHERE role_name = ? AND created_at >= ? "
            "ORDER BY created_at DESC",
            (role_name, since),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── ADRs ───────────────────────────────────────────────────────────────

    def create_adr(
        self, sprint_id: str | None, kind: str,
        before_yaml: str, after_yaml: str, rationale: str,
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.execute(
            "INSERT INTO adrs (sprint_id, kind, before_yaml, after_yaml, "
            "rationale, status, created_at, updated_at) VALUES "
            "(?, ?, ?, ?, ?, 'pending', ?, ?)",
            (sprint_id, kind, before_yaml, after_yaml, rationale, now, now),
        )
        self.conn.commit()
        return int(cur.lastrowid or 0)

    def list_adrs(self, status: str | None = None) -> list[dict]:
        if status:
            rows = self.conn.execute(
                "SELECT * FROM adrs WHERE status = ? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM adrs ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def set_adr_status(self, adr_id: int, status: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "UPDATE adrs SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, adr_id),
        )
        self.conn.commit()

    def list_qa_failure_tags(self, since_sprints: int = 5) -> list[tuple[str, int]]:
        """Return (tag, count) tuples from QA failure_mode tags in recent sprints."""
        sprints = self.list_sprints(limit=since_sprints)
        counter: dict[str, int] = {}
        for s in sprints:
            envs = json.loads(s.get("envelopes_json") or "{}")
            grade = envs.get("grade") or {}
            for c in json.loads(grade.get("payload", "{}")).get("criteria", []):
                if not c.get("passed"):
                    tag = c.get("name") or "unknown"
                    counter[tag] = counter.get(tag, 0) + 1
        return sorted(counter.items(), key=lambda x: -x[1])

    def list_blocker_tags(self, since_sprints: int = 5) -> list[tuple[str, int]]:
        """Return (tag, count) tuples from blocked task descriptions."""
        rows = self.conn.execute(
            "SELECT description FROM tasks WHERE status = 'blocked' "
            "ORDER BY created_at DESC LIMIT ?", (since_sprints * 5,)
        ).fetchall()
        counter: dict[str, int] = {}
        for r in rows:
            desc = (r["description"] or "").lower()
            for tag in ("db-migration", "auth", "flaky-test", "network"):
                if tag in desc:
                    counter[tag] = counter.get(tag, 0) + 1
        return sorted(counter.items(), key=lambda x: -x[1])

    # ── Row converters ─────────────────────────────────────────────────────

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> Task:
        return Task(**{k: row[k] for k in row.keys()})

    @staticmethod
    def _row_to_test(row: sqlite3.Row) -> TestRun:
        return TestRun(**{k: row[k] for k in row.keys()})

    @staticmethod
    def _row_to_git(row: sqlite3.Row) -> GitOp:
        return GitOp(**{k: row[k] for k in row.keys()})

    @staticmethod
    def _row_to_project(row: sqlite3.Row) -> Project:
        return Project(**{k: row[k] for k in row.keys()})

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None


# ── MCP factory ──────────────────────────────────────────────────────────────


def create_pm_mcp(db_path: str = "./_orgos_memory/pm.db") -> Any:
    """Create an MCPServerStdio config for the PM MCP server."""
    from crewai.mcp.config import MCPServerStdio
    import sys
    return MCPServerStdio(
        command=sys.executable,
        args=["-m", "orgos.mcps.pm_mcp", "--db", db_path],
    )
