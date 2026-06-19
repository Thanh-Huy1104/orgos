"""The strategist endpoint dispatches a background job and is polled — so a
multi-minute hunt never blocks (or times out) the HTTP request."""

import time

import orgos.subagents.quant_strategist as qs
from orgos.quant.api import StrategistBody, strategist, strategist_job


class _FakeEnv:
    status = "completed"
    success_criteria_met = True
    summary = "found AEE/NI"
    notes = None


class _FakeResult:
    envelope = _FakeEnv()
    token_usage = {"total_tokens": 42}
    run_id = "chain-fake"
    attempts = 2
    grade = None


def _poll_until_done(job_id, timeout=5.0):
    deadline = time.time() + timeout
    job = strategist_job(job_id)
    while job["status"] == "running" and time.time() < deadline:
        time.sleep(0.02)
        job = strategist_job(job_id)
    return job


def test_dispatch_returns_job_then_resolves(monkeypatch):
    monkeypatch.setattr(qs, "run_strategist", lambda *a, **k: _FakeResult())

    out = strategist(StrategistBody(objective="find shared-commodity cross-sector pairs"))
    assert out["status"] == "running" and out["job_id"]

    job = _poll_until_done(out["job_id"])
    assert job["status"] == "done"
    assert job["result"]["run_id"] == "chain-fake"
    assert job["result"]["attempts"] == 2
    assert job["result"]["tokens"] == 42
    assert "elapsed_s" in job


def test_failure_surfaces_as_error_status(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("scanner exploded")
    monkeypatch.setattr(qs, "run_strategist", boom)

    out = strategist(StrategistBody(objective="this run will blow up on purpose"))
    job = _poll_until_done(out["job_id"])
    assert job["status"] == "error"
    assert "scanner exploded" in job["error"]


def test_unknown_job_is_404():
    import pytest
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        strategist_job("nope-not-a-job")
