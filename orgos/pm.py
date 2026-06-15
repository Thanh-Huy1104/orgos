"""Project management — task tracking, test running, git operations.

PMStore is a SQLite-backed store for project tasks, test runs, and git
history.  Used by the PM MCP server (pm_mcp.py) to give agents
project-management capabilities.

Usage:
    from orgos.pm import PMStore
    pm = PMStore("./_orgos_memory/pm.db")
    pm.create_task("Fix the login bug", department="engineering")
    pm.record_test_run("task-1", "pytest", 0, "15 passed", passed=True)
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
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
            self._conn = sqlite3.connect(str(self.db_path))
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

            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                goal TEXT DEFAULT '',
                owner TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                task_ids TEXT DEFAULT '[]',
                departments TEXT DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)

    # ── Projects ───────────────────────────────────────────────────────────

    def create_project(
        self, name: str, goal: str = "", owner: str = "owner",
    ) -> Project:
        pid = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO projects (id, name, goal, owner, status, task_ids, departments, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'active', '[]', '[]', ?, ?)""",
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

    def get_project_progress(self, project_id: str) -> dict[str, Any]:
        project = self.get_project(project_id)
        if project is None:
            return {"error": "Project not found"}
        task_ids = json.loads(project.task_ids)
        tasks = []
        for tid in task_ids:
            t = self.get_task(tid)
            if t:
                tasks.append({"id": t.id, "title": t.title, "status": t.status, "priority": t.priority})
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
    return MCPServerStdio(
        command="python",
        args=["-m", "orgos.pm_mcp", "--db", db_path],
    )
