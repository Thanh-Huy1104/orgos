"""API client for the orgos backend (localhost:8420)."""

from __future__ import annotations

import json
from typing import Any

import httpx

BASE = "http://localhost:8420"


def _get(path: str, **params: Any) -> dict | list:
    try:
        r = httpx.get(f"{BASE}{path}", params=params or None, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def _post(path: str, body: dict) -> dict:
    try:
        r = httpx.post(f"{BASE}{path}", json=body, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


# ── Dashboard ──────────────────────────────────────────────────────────

def get_dora():
    return _get("/api/dora")


def get_dashboard():
    return _get("/api/dashboard")


# ── Sprints ────────────────────────────────────────────────────────────

def get_sprints(limit: int = 50) -> list[dict]:
    return _get("/api/sprints", limit=limit)


def get_sprint(sprint_id: str) -> dict:
    return _get(f"/api/sprints/{sprint_id}")


def get_flow_metrics(sprint_id: str) -> dict:
    return _get(f"/api/lab/flow-metrics/{sprint_id}")


# ── Experiments ────────────────────────────────────────────────────────

def get_experiments() -> list[str]:
    return _get("/api/experiments")


def get_experiment(exp_id: str) -> dict:
    return _get(f"/api/experiments/{exp_id}")


def run_experiment(num_sprints: int, model: str, budget: int, mode: str = "pull") -> dict:
    return _post("/api/experiments/run", {
        "num_sprints": num_sprints, "model": model,
        "budget": budget, "mode": mode,
    })


# ── Paired benchmark ───────────────────────────────────────────────────

def run_paired_benchmark(issue_id: str, issue_title: str, agents_dir_b: str) -> dict:
    return _post("/api/lab/paired-run", {
        "issue_id": issue_id, "issue_title": issue_title,
        "agents_dir_b": agents_dir_b,
    })


# ── Personas ───────────────────────────────────────────────────────────

def get_personas() -> list[dict]:
    return _get("/api/personas")


def get_persona_file(agent: str, file: str) -> dict:
    return _get(f"/api/personas/{agent}/{file}")


def update_persona_file(agent: str, file: str, content: str) -> dict:
    return _post(f"/api/personas/{agent}/{file}", {"content": content})


# ── Wiki ───────────────────────────────────────────────────────────────

def get_wiki_files() -> list[dict]:
    return _get("/api/wiki/files")


def get_wiki_file(path: str) -> dict:
    return _get(f"/api/wiki/file?path={path}")


# ── Board ──────────────────────────────────────────────────────────────

def get_board_status() -> dict:
    return _get("/api/board/status")


# ── Cost / Tokens ──────────────────────────────────────────────────────

def get_costs() -> list[dict]:
    return _get("/api/costs")


# ── Heuristics ─────────────────────────────────────────────────────────

def get_heuristics() -> dict:
    return _get("/api/heuristics")
