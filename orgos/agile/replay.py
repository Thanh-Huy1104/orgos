"""Counterfactual sprint replay.

Load a past sprint's snapshot, apply a BriefMutation, and run a new sprint
whose PR-opening tool is always mocked (publish-category tools are refused
in replay mode by the existing tier system).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from orgos.pm import PMStore

from .mutations import BriefMutation, SwapTopology, apply_mutation
from .sprint import (
    Sprint, _new_sprint_id, read_snapshot, run_sprint, run_scrum_sprint,
)


def replay_sprint(
    parent_sprint_id: str,
    mutation,
    *,
    base_dir: Path | None = None,
    model: str | None = None,
    _offline: bool = False,
) -> Sprint:
    base = base_dir or Path(".")
    snapshot = read_snapshot(parent_sprint_id, base_dir=base)
    mutated = apply_mutation(snapshot, mutation)

    if _offline:
        # Fast path for tests: skip the actual spawn, produce a stub Sprint.
        replay_id = _new_sprint_id()
        wt = base / ".sprints" / replay_id
        wt.mkdir(parents=True, exist_ok=True)
        replayed = Sprint(
            id=replay_id,
            started_at=datetime.now(timezone.utc).isoformat(),
            repo_path=base,
            worktree_path=wt,
            branch=f"agile/{replay_id}",
            picked_issue=mutated["picked_issue"],
            envelopes={},
            status="completed",
        )
    else:
        if isinstance(mutation, SwapTopology):
            replayed = run_scrum_sprint(
                base, mutated["picked_issue"], model=model, mock_pr=True,
            )
        else:
            replayed = run_sprint(
                base, mutated["picked_issue"], model=model, mock_pr=True,
            )
        # run_sprint/run_scrum_sprint already created the sprint row — only attach replay metadata.
        pm = PMStore()  # default path matches run_sprint
        pm.record_sprint_envelope(
            replayed.id, "_replay",
            json.dumps({
                "parent_sprint_id": parent_sprint_id,
                "mutation_kind": getattr(mutation, "kind", "unknown"),
                "mutation": mutation.__dict__,
            }),
        )
        replayed.envelopes["_replay"] = None  # marker
        return replayed

    # Offline branch: run_sprint was skipped so we must persist manually.
    pm = PMStore(base / "_orgos_memory" / "pm.db")
    pm.create_sprint(replayed.id, replayed.branch, replayed.picked_issue,
                     status=replayed.status)
    pm.record_sprint_envelope(
        replayed.id, "_replay",
        json.dumps({
            "parent_sprint_id": parent_sprint_id,
            "mutation_kind": getattr(mutation, "kind", "unknown"),
            "mutation": mutation.__dict__,
        }),
    )
    replayed.envelopes["_replay"] = None  # marker
    return replayed
