"""Backfill attribution for existing sprints, then fire the topology proposer.

The topology check normally runs inside run_nightly_sprint every 5 sprints.
Since our existing sprints were run via run_sprint directly (which skips the
attribution + topology hooks), the role_attribution table is empty. This
script:

  1. Reads each completed sprint's envelopes back from PMStore.
  2. Reconstructs a lightweight Sprint object so compute_attribution can
     score each role.
  3. Writes role_attribution rows for each (sprint, role) pair.
  4. Invokes propose_topology_mutations against the real data.
  5. Writes any proposals as ADR rows so the /team dashboard shows them.
"""
from __future__ import annotations

import json
from pathlib import Path

from orgos.pm import PMStore
from orgos.agile.attribution import compute_attribution
from orgos.agile.envelopes import (
    BacklogEnvelope, BriefEnvelope, DoraEnvelope, EngineeringEnvelope,
    GradeEnvelope, ReleaseEnvelope, RetroEnvelope,
)
from orgos.agile.topology import propose_topology_mutations
from orgos.agile.sprint import Sprint
from orgos.spawn.contracts import HandoffEnvelope

PHASE_TO_ENVELOPE = {
    "backlog": BacklogEnvelope,
    "brief": BriefEnvelope,
    "engineering": EngineeringEnvelope,
    "grade": GradeEnvelope,
    "release": ReleaseEnvelope,
    "dora": DoraEnvelope,
    "retro": RetroEnvelope,
}


def _rebuild_envelope(phase: str, data: dict):
    """Try to reconstruct the phase-specific envelope subclass; fall back to
    the base HandoffEnvelope on any schema mismatch."""
    cls = PHASE_TO_ENVELOPE.get(phase)
    if cls is None:
        return HandoffEnvelope.model_validate(data)
    try:
        return cls.model_validate(data)
    except Exception:
        return HandoffEnvelope.model_validate(data)


def _rebuild_sprint(row: dict) -> Sprint:
    envs = json.loads(row.get("envelopes_json") or "{}")
    envelopes = {}
    for phase, data in envs.items():
        if not isinstance(data, dict):
            continue
        try:
            envelopes[phase] = _rebuild_envelope(phase, data)
        except Exception:
            continue
    return Sprint(
        id=row["id"],
        started_at=row["started_at"],
        repo_path=Path("."),
        worktree_path=Path("."),
        branch=row["branch"],
        picked_issue=json.loads(row.get("picked_issue") or "{}"),
        envelopes=envelopes,
        status=row["status"],
    )


def main() -> None:
    pm = PMStore()

    sprints = pm.list_sprints(limit=50)
    print(f"Backfilling attribution for {len(sprints)} sprint(s)...")
    for row in sprints:
        sprint = _rebuild_sprint(row)
        scores = compute_attribution(sprint)
        grade = sprint.envelopes.get("grade")
        baseline = grade.parsed_payload().get("rubric_score", 0.0) if grade else 0.5

        # Skip if we already have attribution for this sprint (rerun-safe).
        existing = pm.conn.execute(
            "SELECT COUNT(*) FROM role_attribution WHERE sprint_id = ?",
            (sprint.id,),
        ).fetchone()[0]
        if existing > 0:
            print(f"  {sprint.id}: already has {existing} attribution rows, skipping")
            continue

        # Also record roles that exist in config but aren't in the attribution
        # dict (currently retro-agent — it's a configured member but nothing
        # actually invokes it during a sprint, so its true contribution is 0).
        # Without this row the topology's REMOVE_ROLE rule can't detect the
        # dead role, which is exactly what we'd want it to flag.
        configured_but_unused = {"retro-agent"} - set(scores.keys())
        for role in configured_but_unused:
            scores[role] = 0.0

        for role, score in scores.items():
            pm.record_role_attribution(
                sprint_id=sprint.id, role_name=role, score=score,
                rubric_baseline=baseline,
                rubric_ablated=max(baseline - score, 0.0),
            )
        print(f"  {sprint.id} ({sprint.status}): wrote {len(scores)} rows  "
              f"[baseline={baseline:.2f}, scores={ {r: round(s,2) for r,s in scores.items()} }]")

    print()
    print("Invoking propose_topology_mutations...")
    proposals = propose_topology_mutations(
        pm, Path("config/org.yaml"), window_sprints=5,
    )
    print(f"  {len(proposals)} proposal(s) returned")

    for i, p in enumerate(proposals, 1):
        adr_id = pm.create_adr(
            sprint_id=sprints[0]["id"] if sprints else "topology-check",
            kind=p.kind,
            before_yaml=p.before_yaml,
            after_yaml=p.after_yaml,
            rationale=p.rationale,
        )
        print()
        print(f"  ADR-{adr_id:03d}  {p.kind}")
        print(f"    rationale: {p.rationale}")

    print()
    if not proposals:
        print("No proposals fired.  This is a legitimate outcome — the")
        print("trigger rules are:")
        print("  - REMOVE_ROLE:  role contribution < 0.05 for 5 consecutive sprints")
        print("  - SPLIT_ROLE:   QA failure tag count >= 3 in the window")
        print("  - ADD_ROLE:     blocker tag count >= 3 with no owning role")
        print("None of these were met by the current attribution + sprint history.")
    else:
        print("Refresh http://localhost:3000/team — pending ADRs are at the top of the feed.")


if __name__ == "__main__":
    main()
