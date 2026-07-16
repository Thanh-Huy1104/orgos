"""Sprint Process Efficiency (SPE) — time-proportional delivery metric.

Ported into orgos from the standalone TeamBoard experiment. Answers a
question the token/velocity metrics don't: *did each story finish within its
fair share of the sprint's wall-clock time?*

Definitions
-----------
Process Efficiency (PE) for a single story::

    ideal_hours  = (points / final_commit) * sprint_duration_hours
    actual_hours = closed_at - activated_at   (first in_progress → done)
    PE           = ideal_hours / actual_hours

  - PE = 1.0  → the story used exactly its proportional share of sprint time
  - PE > 1.0  → finished faster than its fair share
  - PE < 1.0  → ran over
  - PE = 0.0  → the story never reached `done` (incomplete work earns nothing)

Sprint Process Efficiency (SPE) is the story-point-weighted mean PE across
all committed, non-dropped stories::

    SPE = Σ(PE_i · points_i) / Σ(points_i)

`final_commit` is the sum of points over the committed, non-dropped stories —
what the team *committed to*, incomplete items included. This is deliberate:
counting only finished work would let a low-throughput team look efficient by
dropping everything it couldn't finish.

A `blocked` story is treated as the orgos analog of TeamBoard's `cancelled`
(dropped from the commitment) and is excluded from both `final_commit` and the
SPE average.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Optional

# Story state that means "dropped from the sprint commitment" — the orgos
# analog of a cancelled item. Excluded from final_commit and the SPE average.
_DROPPED_STATE = "blocked"
_DONE_STATE = "done"


def _parse(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _points(story: Any) -> int:
    try:
        return int(getattr(story, "points", 0) or 0)
    except (TypeError, ValueError):
        return 0


def process_efficiency(
    story: Any, *, duration_hours: float, final_commit: int,
) -> float:
    """PE for one story. Returns 0.0 for any non-`done` or unmeasurable story."""
    if getattr(story, "state", "") != _DONE_STATE:
        return 0.0
    if not final_commit or duration_hours <= 0:
        return 0.0
    activated = _parse(getattr(story, "activated_at", "") or "")
    closed = _parse(getattr(story, "closed_at", "") or "")
    if activated is None or closed is None:
        return 0.0
    actual_hours = (closed - activated).total_seconds() / 3600.0
    if actual_hours <= 0:
        return 0.0
    ideal_hours = (_points(story) / final_commit) * duration_hours
    return ideal_hours / actual_hours


def spe_band(spe: float) -> str:
    """Human-readable interpretation band for an SPE value (0.0–1.0+ scale)."""
    if spe <= 0:
        return "No Delivery"
    if spe < 0.25:
        return "Needs Improvement"
    if spe < 0.50:
        return "Good"
    if spe <= 0.80:
        return "Excellent"
    return "Verify Data"


def sprint_process_efficiency(
    stories: Iterable[Any], *, duration_hours: float,
) -> dict:
    """Compute SPE for a sprint's committed stories.

    `stories` is the collection of Story objects committed to the sprint
    (each needs `points`, `state`, `activated_at`, `closed_at`). Returns a
    dict with the sprint-level number plus a per-story breakdown, safe to
    serialize into the sprint JSON and the HTML report.
    """
    committed = list(stories)
    scored = [s for s in committed if getattr(s, "state", "") != _DROPPED_STATE]
    final_commit = sum(_points(s) for s in scored)

    per_story: list[dict] = []
    weighted_sum = 0.0
    for s in scored:
        pe = process_efficiency(
            s, duration_hours=duration_hours, final_commit=final_commit,
        )
        pts = _points(s)
        weighted_sum += pe * pts
        per_story.append({
            "issue_id": getattr(s, "issue_id", ""),
            "points": pts,
            "state": getattr(s, "state", ""),
            "pe": round(pe, 4),
        })

    spe = (weighted_sum / final_commit) if final_commit > 0 else 0.0
    return {
        "spe": round(spe, 4),
        "band": spe_band(spe),
        "final_commit": final_commit,
        "duration_hours": round(duration_hours, 4),
        "scored_stories": len(scored),
        "dropped_stories": len(committed) - len(scored),
        "per_story": per_story,
    }
