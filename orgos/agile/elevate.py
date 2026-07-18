"""Auto-priority elevation for stuck stories (Fix §B7).

Two failure modes we've measured (visible right now in quant-desk-v1's
tail stall):
  1. Ready stories no agent pulls (deps satisfied, but priority is low or
     agents are working on other things) sit forever.
  2. In-progress stories where the executor started but never committed
     (LLM stuck in a tool-use loop, iteration cap not enforced tightly)
     hold the story indefinitely.

Both waste wall clock. This module runs on SM's heartbeat and:
  - Bumps priority of ready stories older than `ready_stale_seconds`.
  - Reclaims in-progress stories older than `in_progress_stale_seconds`
    by transitioning them back to ready with attempts++ and priority bump.

Emits `story_elevated` (priority bump) and `story_reclaimed` (in_progress
→ ready) events so the report shows the intervention.

Kept in its own module so the logic is easy to unit-test without spinning
up the whole async runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from orgos.agile.board_store import BoardStore


@dataclass
class ElevationConfig:
    ready_stale_seconds: int = 1800       # 30 min → bump priority
    ready_bump_amount: int = 15           # each elevation
    in_progress_stale_seconds: int = 900  # 15 min → reclaim
    max_bumps_per_story: int = 3          # cap so a truly stuck story eventually blocks
    now_fn: Any = None                    # overridable for tests

    def now(self) -> datetime:
        return self.now_fn() if self.now_fn else datetime.now(timezone.utc)


def _parse_iso(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    try:
        # accepts both '...+00:00' and '...Z'
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _seconds_since(ts: str, now: datetime) -> Optional[float]:
    dt = _parse_iso(ts)
    if dt is None:
        return None
    try:
        return (now - dt).total_seconds()
    except (TypeError, ValueError):
        return None


def _bump_count(board: BoardStore, issue_id: str) -> int:
    """Count prior elevate_priority audit entries for this story."""
    trail = board.audit_trail(issue_id)
    return sum(1 for e in trail if e.get("action") == "elevate_priority")


def run_elevation_pass(
    board: BoardStore, emitter: Any,
    config: Optional[ElevationConfig] = None,
) -> dict:
    """Scan the board and apply elevations. Idempotent per tick.

    Returns a dict of counters: elevated_ready, reclaimed_in_progress,
    skipped_max_bumps.
    """
    cfg = config or ElevationConfig()
    now = cfg.now()
    counts = {"elevated_ready": 0, "reclaimed_in_progress": 0, "skipped_max_bumps": 0}

    # 1. Ready stories older than threshold — bump priority
    for story in board.list_state("ready"):
        age = _seconds_since(story.updated_at, now)
        if age is None or age < cfg.ready_stale_seconds:
            continue
        if _bump_count(board, story.issue_id) >= cfg.max_bumps_per_story:
            counts["skipped_max_bumps"] += 1
            continue
        old_priority = story.priority
        story.priority = story.priority + cfg.ready_bump_amount
        board._write_story(story)
        board._audit(
            story.issue_id, "sm", "elevate_priority",
            old_priority=old_priority, new_priority=story.priority,
            age_seconds=int(age),
        )
        try:
            emitter.emit(
                "story_elevated", story_id=story.issue_id,
                old_priority=old_priority, new_priority=story.priority,
                age_seconds=int(age),
                summary=(
                    f"{story.issue_id} priority {old_priority} → {story.priority} "
                    f"after {int(age/60)}min in ready"
                ),
            )
        except Exception:
            pass
        counts["elevated_ready"] += 1

    # 2. In-progress stories where activated_at is stale — reclaim
    for story in board.list_state("in_progress"):
        age = _seconds_since(story.activated_at, now)
        if age is None or age < cfg.in_progress_stale_seconds:
            continue
        try:
            board.increment_attempts(story.issue_id, actor="sm")
            board.transition(
                story.issue_id, "ready", actor="sm",
                reason=f"reclaimed: stuck in_progress for {int(age/60)}min",
            )
            # Bump priority so it gets picked up soon on re-enter
            fresh = board.read(story.issue_id)
            fresh.priority = fresh.priority + cfg.ready_bump_amount
            board._write_story(fresh)
            try:
                emitter.emit(
                    "story_reclaimed", story_id=story.issue_id,
                    age_seconds=int(age), previous_assignee=story.assignee,
                    summary=(
                        f"{story.issue_id} reclaimed after {int(age/60)}min in "
                        f"in_progress (was assigned to {story.assignee or '?'})"
                    ),
                )
            except Exception:
                pass
            counts["reclaimed_in_progress"] += 1
        except Exception:
            # If the transition or write fails, just skip and try next tick
            continue
    return counts
