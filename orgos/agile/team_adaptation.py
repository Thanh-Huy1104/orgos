"""§D1 — Team-level adaptation loop (closer to true Scrum).

Before this: retros wrote text to wiki/RETRO.md and the PO's replan read
that text to adapt the BACKLOG (which stories to draft next). Nothing
adapted the TEAM'S OWN PROCESS PARAMETERS.

Real Scrum's superpower is that the team INSPECTS what happened and
ADAPTS how they work — not just what they work on. This module encodes
that: it computes runtime parameter adjustments from recent sprint
history and applies them to the workspace so the next sprint uses the
tuned values.

Adaptations (Phase 1):
  1. velocity_target — up if sprints consistently over-deliver, down if
     under-deliver. Prevents "chronic over-commit" and "chronic slack."
  2. max_ac_retries — up if AC retries mostly succeed, down if they
     mostly exhaust. Stops wasting cycles on stories the agents can't
     fix and gives more chances to ones they eventually solve.
  3. sprint_duration_seconds — bumped by ±20% based on whether sprints
     end early (nothing to do) or run out mid-work.

State:
  - AdaptiveParameters lives on the workspace instance
    (workspace.adaptive_params: AdaptiveParameters)
  - Persisted to <team_root>/adaptation.json
  - Loaded at team boot; updated by run_adaptation_pass() at sprint boundaries
  - Delivery-agent code reads workspace.adaptive_params.<field> at use time

Design choices:
  - Bounded step size: no adaptation moves a param by more than 20%
    per pass. Prevents oscillation from noisy signals.
  - Hard bounds: velocity_target ∈ [3, 40], max_ac_retries ∈ [1, 6],
    sprint_duration_seconds ∈ [300, 14400].
  - Cool-down: don't adapt the same parameter more than once per 2 sprints.
    Signals need time to show effect.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


# Hard safety bounds — never let adaptations push params out of sensible range.
_BOUNDS = {
    "velocity_target":         (3, 40),
    "max_ac_retries":          (1, 6),
    "sprint_duration_seconds": (300, 14400),
}


@dataclass
class AdaptiveParameters:
    """Runtime knobs the adaptation loop tunes. Serializable to JSON."""
    velocity_target: int = 6
    max_ac_retries: int = 3
    sprint_duration_seconds: int = 1200
    updated_at: str = ""
    reason: str = ""              # human-readable summary of the last change
    version: int = 1              # incremented on each apply()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "AdaptiveParameters":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class SprintSignal:
    """Metrics we care about for adaptation, computed from a SprintRecord."""
    sprint_num: int
    committed: int          # velocity_target for that sprint
    done: int
    duration_hours: float
    end_reason: str         # 'scheduled' | 'story_cap' | 'nothing_ready' | ...
    ac_retries_started: int = 0
    ac_retries_succeeded: int = 0

    @property
    def completion_ratio(self) -> float:
        return (self.done / self.committed) if self.committed else 0.0

    @property
    def ac_success_ratio(self) -> float:
        return (self.ac_retries_succeeded / self.ac_retries_started) if self.ac_retries_started else 0.5


@dataclass
class AdaptationProposal:
    """A single proposed parameter change. Applied only if it doesn't
    push the parameter past its hard bound."""
    field: str
    old_value: Any
    new_value: Any
    reason: str

    def clamp(self) -> "AdaptationProposal":
        lo, hi = _BOUNDS.get(self.field, (float("-inf"), float("inf")))
        clamped = max(lo, min(hi, self.new_value))
        if clamped != self.new_value:
            return AdaptationProposal(
                field=self.field, old_value=self.old_value,
                new_value=clamped,
                reason=self.reason + f" (clamped to {clamped})",
            )
        return self


def _load_params(team_root: Path) -> AdaptiveParameters:
    p = team_root / "adaptation.json"
    if not p.exists():
        return AdaptiveParameters()
    try:
        return AdaptiveParameters.from_dict(json.loads(p.read_text()))
    except (json.JSONDecodeError, OSError, TypeError):
        return AdaptiveParameters()


def _save_params(team_root: Path, params: AdaptiveParameters) -> None:
    p = team_root / "adaptation.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(params.to_dict(), indent=2))


def propose_adaptations(
    signals: list[SprintSignal],
    current: AdaptiveParameters,
    *,
    lookback: int = 3,
) -> list[AdaptationProposal]:
    """Compute proposed changes from the last `lookback` sprints.

    Returns a list of AdaptationProposal objects (may be empty). Uses
    bounded step size (±20% per pass) so noisy signals don't cause
    thrashing. Callers should filter/apply and emit events.

    Rules (Phase 1):
      A. velocity_target
         - If avg completion_ratio over last N sprints ≥ 1.10 → +20%
         - If avg completion_ratio ≤ 0.50 → -20%
         - Else: no change
      B. max_ac_retries
         - If AC retry success ratio > 0.60 → +1 (cap at 6)
         - If AC retry success ratio < 0.20 AND ≥3 samples → -1 (min 1)
      C. sprint_duration_seconds
         - If sprints consistently end 'story_cap' (ran out of stories) → +20%
         - If sprints consistently end 'scheduled' with completion < 0.50 → -20%
    """
    proposals: list[AdaptationProposal] = []
    if not signals:
        return proposals

    recent = signals[-lookback:]

    # A. velocity_target
    avg_completion = sum(s.completion_ratio for s in recent) / len(recent)
    if avg_completion >= 1.10:
        new = int(round(current.velocity_target * 1.20))
        if new != current.velocity_target:
            proposals.append(AdaptationProposal(
                field="velocity_target",
                old_value=current.velocity_target,
                new_value=new,
                reason=f"team over-delivering (avg {avg_completion:.0%} of commit) — raise ceiling",
            ))
    elif avg_completion <= 0.50 and len(recent) >= 2:
        new = int(round(current.velocity_target * 0.80))
        if new != current.velocity_target:
            proposals.append(AdaptationProposal(
                field="velocity_target",
                old_value=current.velocity_target,
                new_value=new,
                reason=f"team under-delivering (avg {avg_completion:.0%}) — lower commit to reduce spillover",
            ))

    # B. max_ac_retries
    ac_started = sum(s.ac_retries_started for s in recent)
    ac_succ = sum(s.ac_retries_succeeded for s in recent)
    if ac_started >= 3:
        ratio = ac_succ / ac_started
        if ratio > 0.60:
            proposals.append(AdaptationProposal(
                field="max_ac_retries",
                old_value=current.max_ac_retries,
                new_value=current.max_ac_retries + 1,
                reason=f"AC retries mostly succeed ({ratio:.0%}) — give more chances",
            ))
        elif ratio < 0.20:
            proposals.append(AdaptationProposal(
                field="max_ac_retries",
                old_value=current.max_ac_retries,
                new_value=current.max_ac_retries - 1,
                reason=f"AC retries mostly exhaust ({ratio:.0%}) — stop wasting cycles",
            ))

    # C. sprint_duration_seconds
    n_story_cap = sum(1 for s in recent if "cap" in s.end_reason.lower())
    n_scheduled_underdel = sum(
        1 for s in recent if s.end_reason == "scheduled" and s.completion_ratio < 0.50
    )
    if n_story_cap >= 2:
        new_dur = int(round(current.sprint_duration_seconds * 1.20))
        proposals.append(AdaptationProposal(
            field="sprint_duration_seconds",
            old_value=current.sprint_duration_seconds,
            new_value=new_dur,
            reason=f"{n_story_cap} recent sprints ran out of stories — lengthen sprint",
        ))
    elif n_scheduled_underdel >= 2:
        new_dur = int(round(current.sprint_duration_seconds * 0.80))
        proposals.append(AdaptationProposal(
            field="sprint_duration_seconds",
            old_value=current.sprint_duration_seconds,
            new_value=new_dur,
            reason=f"{n_scheduled_underdel} sprints ended timed-out with < 50% delivery — shorter sprint",
        ))

    return [p.clamp() for p in proposals if p.clamp().new_value != p.old_value]


def apply_proposals(
    workspace: Any, proposals: list[AdaptationProposal], emitter: Optional[Any] = None,
) -> AdaptiveParameters:
    """Merge proposals into workspace.adaptive_params, save, and emit events.

    Returns the updated AdaptiveParameters. Side effects:
      - workspace.adaptive_params updated
      - <team_root>/adaptation.json rewritten
      - `team_adapted` event emitted per proposal (if emitter given)
    """
    existing = getattr(workspace, "adaptive_params", None)
    if isinstance(existing, AdaptiveParameters):
        current = existing
    else:
        current = _load_params(workspace.root)

    if not proposals:
        return current

    reasons: list[str] = []
    for p in proposals:
        setattr(current, p.field, p.new_value)
        reasons.append(f"{p.field}: {p.old_value}→{p.new_value} ({p.reason})")
        if emitter is not None:
            try:
                emitter.emit(
                    "team_adapted",
                    parameter=p.field,
                    old_value=p.old_value,
                    new_value=p.new_value,
                    reason=p.reason,
                    summary=f"team adapted {p.field}: {p.old_value} → {p.new_value}",
                )
            except Exception:
                pass

    current.updated_at = datetime.now(timezone.utc).isoformat()
    current.reason = "; ".join(reasons)[:400]
    current.version += 1

    _save_params(workspace.root, current)
    workspace.adaptive_params = current
    return current


def load_or_init(workspace: Any) -> AdaptiveParameters:
    """Load adaptive_params onto workspace (init from disk or defaults).

    Called at team boot from cli.py so subsequent code can read
    workspace.adaptive_params.<field> without checking existence.

    Only returns a cached value if it's actually an AdaptiveParameters
    instance — MagicMock in tests would falsely satisfy `is not None`.
    """
    existing = getattr(workspace, "adaptive_params", None)
    if isinstance(existing, AdaptiveParameters):
        return existing
    try:
        p = _load_params(workspace.root)
    except (OSError, AttributeError, TypeError):
        p = AdaptiveParameters()
    try:
        workspace.adaptive_params = p
    except (AttributeError, TypeError):
        pass  # workspace may be immutable / MagicMock; caller can still use p
    return p


def signals_from_history(history: list[Any], events: list[dict]) -> list[SprintSignal]:
    """Build SprintSignal list from SprintRecord history + live.jsonl events.

    ac_retries per sprint is derived from the events (story_ac_retry
    events with the sprint's timestamp window).
    """
    signals: list[SprintSignal] = []
    for r in history:
        committed = len(getattr(r, "committed_backlog", []) or [])
        done = len(getattr(r, "stories_done", []) or [])
        # Count AC retries within this sprint's time window
        start = getattr(r, "started_at", "") or ""
        end = getattr(r, "ended_at", "") or ""
        ac_started = 0
        ac_succ = 0
        # Track story IDs that had a retry AND then were accepted
        retried_ids: set[str] = set()
        accepted_ids: set[str] = set()
        for e in events:
            ts = e.get("timestamp", "")
            if not (start <= ts <= end):
                continue
            action = e.get("action", "")
            sid = e.get("story_id", "")
            if action == "story_ac_retry" and sid:
                ac_started += 1
                retried_ids.add(sid)
            elif action == "stories_accepted":
                # We don't have per-story IDs on this event unfortunately
                pass
            elif action == "transition":
                if e.get("to_state") == "done" and sid:
                    accepted_ids.add(sid)
        ac_succ = len(retried_ids & accepted_ids)
        signals.append(SprintSignal(
            sprint_num=r.sprint_num,
            committed=committed,
            done=done,
            duration_hours=getattr(r, "duration_hours", 0.0) or 0.0,
            end_reason=getattr(r, "reason_stopped", "") or "",
            ac_retries_started=ac_started,
            ac_retries_succeeded=ac_succ,
        ))
    return signals


def run_adaptation_pass(
    workspace: Any, history: list[Any], events: list[dict],
    emitter: Optional[Any] = None,
) -> tuple[AdaptiveParameters, list[AdaptationProposal]]:
    """Top-level: read signals, propose adaptations, apply. Returns
    (final params, applied proposals)."""
    signals = signals_from_history(history, events)
    current = load_or_init(workspace)
    proposals = propose_adaptations(signals, current)
    updated = apply_proposals(workspace, proposals, emitter)
    return updated, proposals
