"""PM MCP server — project management tools for agents.

Exposes task tracking, test running, and git operations as MCP tools.

Usage as CrewAI MCP:
    from orgos.pm import create_pm_mcp
    dept.shared_mcps = [create_pm_mcp("./_orgos_memory/pm.db")]

Run standalone for testing:
    python -m orgos.mcps.pm_mcp --db ./_orgos_memory/pm.db

Tools:
  - create_task(title, description?, department?, priority?)
  - list_tasks(department?, status?, limit?)
  - update_task(task_id, status, notes?)
  - run_tests(command, working_dir?, timeout_sec?)
  - git_status(repo_path?)
  - git_create_branch(repo_path, branch_name)
  - get_project_status(department?)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

_here = Path(__file__).resolve().parent.parent.parent  # repo root (mcps/ is one level deeper)
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))


async def serve(db_path: str) -> None:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent

    from orgos.pm import PMStore

    pm = PMStore(db_path)

    server = Server(
        "orgos-pm",
        version="1.0.0",
        instructions="Project management: create tasks, run tests, manage git.",
    )

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        def _tool(name, desc, props):
            return Tool(
                name=name, description=desc,
                inputSchema={
                    "type": "object",
                    "properties": props,
                    "required": list(props.keys()),
                },
            )

        return [
            _tool("list_tasks", "List project tasks.",
                {"department": {"type": "string", "description": "Department name or empty string for all."},
                 "status": {"type": "string", "description": "Status filter: todo, in_progress, review, done, blocked, or empty string for all."},
                 "limit": {"type": "integer", "description": "Max results, e.g. 20."}}),
            _tool("create_task", "Create a task.",
                {"task_title": {"type": "string", "description": "Task title."},
                 "description": {"type": "string", "description": "Description."},
                 "department": {"type": "string", "description": "Department name."},
                 "priority": {"type": "string", "description": "low, medium, high, critical."}}),
            _tool("update_task", "Update task status.",
                {"task_id": {"type": "string", "description": "Task ID."},
                 "status": {"type": "string", "description": "New status: todo, in_progress, review, done, blocked."},
                 "notes": {"type": "string", "description": "Progress notes."}}),
            _tool("run_tests", "Run a test command and return results.",
                {"command": {"type": "string", "description": "Shell command, e.g. pytest tests/ -q."},
                 "working_dir": {"type": "string", "description": "Working directory, e.g. '.'."},
                 "timeout_sec": {"type": "integer", "description": "Timeout seconds, e.g. 120."},
                 "task_id": {"type": "string", "description": "Optional task ID, or empty string."}}),
            _tool("git_status", "Check git status.",
                {"repo_path": {"type": "string", "description": "Repo path, e.g. '.'."}}),
            _tool("git_create_branch", "Create a local git branch.",
                {"repo_path": {"type": "string", "description": "Repo path."},
                 "branch_name": {"type": "string", "description": "Branch name."}}),
            _tool("get_project_status", "Overall project status.",
                {"department": {"type": "string", "description": "Department name or empty string for all."}}),

            # Project management tools
            _tool("create_project", "Create a new project.",
                {"project_name": {"type": "string", "description": "Project name, e.g. quant-model-v2."},
                 "goal": {"type": "string", "description": "Project goal description."},
                 "owner": {"type": "string", "description": "Owner name."}}),
            _tool("list_projects", "List all projects.",
                {"status": {"type": "string", "description": "Filter: active, completed, blocked, or empty for all."},
                 "limit": {"type": "integer", "description": "Max results."}}),
            _tool("get_project_progress", "Get detailed progress for a project.",
                {"project_id": {"type": "string", "description": "Project ID."}}),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        try:
            if name == "create_task":
                if "task_title" not in arguments:
                    return [TextContent(type="text", text=json.dumps({"error": "task_title is required"}))]
                task = pm.create_task(
                    title=arguments["task_title"],
                    description=arguments.get("description", ""),
                    department=arguments.get("department"),
                    priority=arguments.get("priority", "medium"),
                )
                return [TextContent(type="text", text=json.dumps({
                    "id": task.id, "title": task.title, "status": task.status,
                    "priority": task.priority, "department": task.department,
                    "created_at": task.created_at,
                }, indent=2))]

            elif name == "list_tasks":
                tasks = pm.list_tasks(
                    department=arguments.get("department"),
                    status=arguments.get("status"),
                    limit=arguments.get("limit", 20),
                )
                result = [{
                    "id": t.id, "title": t.title, "status": t.status,
                    "priority": t.priority, "department": t.department,
                    "assigned_to": t.assigned_to, "updated_at": t.updated_at,
                } for t in tasks]
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "update_task":
                if "task_id" not in arguments or "status" not in arguments:
                    return [TextContent(type="text", text=json.dumps({"error": "task_id and status are required"}))]
                task = pm.update_task(
                    task_id=arguments["task_id"],
                    status=arguments["status"],
                    notes=arguments.get("notes", ""),
                )
                if task is None:
                    return [TextContent(type="text", text=json.dumps({"error": "Task not found"}))]
                return [TextContent(type="text", text=json.dumps({
                    "id": task.id, "title": task.title, "status": task.status,
                    "updated_at": task.updated_at,
                }, indent=2))]

            elif name == "run_tests":
                result = pm.run_tests(
                    command=arguments["command"],
                    working_dir=arguments.get("working_dir", "."),
                    timeout_sec=arguments.get("timeout_sec", 120),
                    task_id=arguments.get("task_id"),
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "git_status":
                result = pm.git_status(repo_path=arguments.get("repo_path", "."))
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "git_create_branch":
                result = pm.git_create_branch(
                    repo_path=arguments["repo_path"],
                    branch_name=arguments["branch_name"],
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "get_project_status":
                dept = arguments.get("department")
                tasks = pm.list_tasks(department=dept, limit=50)
                tests = pm.recent_test_runs(limit=5)
                git_ops = pm.recent_git_ops(limit=5)

                status_counts = {"todo": 0, "in_progress": 0, "review": 0, "done": 0, "blocked": 0}
                for t in tasks:
                    if t.status in status_counts:
                        status_counts[t.status] += 1

                return [TextContent(type="text", text=json.dumps({
                    "tasks_by_status": status_counts,
                    "total_tasks": len(tasks),
                    "recent_test_runs": [
                        {"command": t.command, "passed": t.passed, "created_at": t.created_at}
                        for t in tests
                    ],
                    "recent_git_ops": [
                        {"operation": g.operation, "details": g.details, "pushed": g.pushed}
                        for g in git_ops
                    ],
                }, indent=2))]

            elif name == "create_project":
                project = pm.create_project(
                    name=arguments["project_name"],
                    goal=arguments.get("goal", ""),
                    owner=arguments.get("owner", "owner"),
                )
                return [TextContent(type="text", text=json.dumps({
                    "id": project.id, "name": project.name, "goal": project.goal,
                    "status": project.status, "owner": project.owner,
                    "created_at": project.created_at,
                }, indent=2))]

            elif name == "list_projects":
                projects = pm.list_projects(
                    status=arguments.get("status"),
                    limit=arguments.get("limit", 20),
                )
                return [TextContent(type="text", text=json.dumps([{
                    "id": p.id, "name": p.name, "status": p.status,
                    "goal": p.goal[:200], "owner": p.owner, "updated_at": p.updated_at,
                } for p in projects], indent=2))]

            elif name == "get_project_progress":
                progress = pm.get_project_progress(arguments["project_id"])
                return [TextContent(type="text", text=json.dumps(progress, indent=2))]

            else:
                return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

        except Exception as exc:
            return [TextContent(type="text", text=json.dumps({"error": str(exc)}))]

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main():
    parser = argparse.ArgumentParser(description="orgos PM MCP Server")
    parser.add_argument("--db", default="./_orgos_memory/pm.db", help="Path to PMStore database")
    args = parser.parse_args()
    asyncio.run(serve(args.db))


if __name__ == "__main__":
    main()
