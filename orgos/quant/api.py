"""Quant desk API — agentic endpoints only.

Live-book monitoring (Desk) and agent-driven discovery (Strategist). Manual
scanner/signals/crypto shortcuts are gone — the strategist agent owns discovery.
Nothing here trades or writes the trading DB (except /halt for emergency stop).
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/quant", tags=["quant"])


@router.get("/book")
def book() -> dict:
    """Live Icarus state: account, active pairs (with live z-score), performance.

    Reads the trading DB read-only. 503 if the DB is unreachable (engine off /
    network) so the UI can show a clear 'engine offline' state.
    """
    from orgos.subagents.quant_supervisor import live_overview

    try:
        return live_overview()
    except Exception as exc:  # noqa: BLE001 — surface as a clean 503 for the UI
        raise HTTPException(status_code=503, detail=f"Icarus DB unreachable: {exc}")


class StrategistBody(BaseModel):
    objective: str
    asset_class: str = "equity"
    allow_research: bool = False
    max_attempts: int = 2


# A strategist hunt takes minutes — far longer than any HTTP/proxy idle timeout
# will hold a connection open. So the run is dispatched to a background thread and
# the UI polls for the result. The job store is in-process (the API is a single
# worker); a lost job is harmless because run_strategist also records to the
# journal, so the result is never actually lost.
_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()
_JOB_TTL_S = 3600  # forget finished jobs after an hour


def _result_dict(r: Any) -> dict:
    from orgos.spawn import read_trail

    e = r.envelope
    g = getattr(r, "grade", None)
    rubric = None
    if g is not None:
        rubric = {"passed": g.passed, "score": round(g.score, 4),
                  "grader": g.grader, "notes": g.notes}
    return {"status": e.status, "criteria_met": e.success_criteria_met,
            "summary": e.summary, "notes": e.notes,
            "tokens": (r.token_usage or {}).get("total_tokens"),
            "run_id": r.run_id, "trail": read_trail(r.run_id),
            "attempts": getattr(r, "attempts", 1), "rubric": rubric,
            "attempt_run_ids": getattr(r, "attempt_run_ids", [])}


def _prune_jobs() -> None:
    now = time.time()
    for jid, job in list(_JOBS.items()):
        if job.get("status") != "running" and now - job.get("ended_at", now) > _JOB_TTL_S:
            _JOBS.pop(jid, None)


@router.post("/strategist")
def strategist(body: StrategistBody) -> dict:
    """Dispatch an agent-driven discovery hunt. Returns a job id immediately; the
    run continues in the background (minutes). Poll GET /strategist/{job_id}."""
    from orgos.subagents.quant_strategist import run_strategist

    job_id = uuid.uuid4().hex[:12]
    with _JOBS_LOCK:
        _prune_jobs()
        _JOBS[job_id] = {"status": "running", "started_at": time.time()}

    def _run() -> None:
        try:
            r = run_strategist(body.objective, asset_class=body.asset_class,
                               allow_research=body.allow_research,
                               max_attempts=body.max_attempts, verbose=False)
            out = {"status": "done", "result": _result_dict(r)}
        except Exception as exc:  # noqa: BLE001 — surface the error to the UI
            out = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
        out["ended_at"] = time.time()
        with _JOBS_LOCK:
            out["started_at"] = _JOBS.get(job_id, {}).get("started_at", out["ended_at"])
            _JOBS[job_id] = out

    threading.Thread(target=_run, daemon=True).start()
    return {"job_id": job_id, "status": "running"}


@router.get("/strategist/{job_id}")
def strategist_job(job_id: str) -> dict:
    """Poll a dispatched hunt: status running | done | error, with the result when done."""
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "unknown or expired job")
    elapsed = round(time.time() - job.get("started_at", time.time()))
    return {"job_id": job_id, "elapsed_s": elapsed, **job}


@router.get("/journal")
def journal(limit: int = 25) -> dict:
    """The research journal: past hunts with their result, rubric strength, and a
    link (run_id) to the research trail. This is what the desk has found."""
    from orgos.quant import journal as quant_journal

    return {"entries": quant_journal.recent(limit)}


@router.get("/trails")
def trails(limit: int = 25) -> dict:
    """Recent runs that left a research trail, newest first (for the Logs view)."""
    from orgos.spawn import recent_trails

    return {"runs": recent_trails(limit)}


@router.get("/trail/{run_id}")
def trail(run_id: str) -> dict:
    """The full tool-by-tool research trail for one run."""
    from orgos.spawn import read_trail

    return {"run_id": run_id, "trail": read_trail(run_id)}


@router.get("/risk")
def risk() -> dict:
    """Read-only risk assessment of the live book + current kill-switch state."""
    from .kill_switch import assess_active_pairs

    try:
        return assess_active_pairs()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"risk assessment failed: {exc}")


class HaltBody(BaseModel):
    pair_id: int
    reason: str


@router.post("/halt")
def halt(body: HaltBody) -> dict:
    """Publish a HALT to Icarus's Redis kill switch for one pair (set-only).

    This is the one write orgos makes to the live system. It only STOPS a pair
    (the fail-safe direction) — orgos never clears a halt; un-halting is a human
    decision in Icarus/Mimir.
    """
    from .kill_switch import publish_halt

    try:
        return publish_halt(body.pair_id, body.reason)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"halt failed: {exc}")
