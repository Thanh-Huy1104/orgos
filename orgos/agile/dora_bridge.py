"""Translate DORA snapshots into candidate Reflector heuristics.

Candidates are proposed to Reflector's existing scoring/use_count machinery;
they are NOT auto-promoted into active heuristics.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from orgos.reflect import Heuristic


def _mk(rule: str, why: str, tags: list[str], run_id: str | None = None) -> Heuristic:
    return Heuristic(
        id=f"dora-{uuid.uuid4().hex[:8]}",
        domain="agile",
        tags=tags,
        rule=rule,
        why=why,
        source_run_id=run_id,
        score=0.5,
        use_count=0,
        created_at=datetime.now(timezone.utc).isoformat(),
        source="dora",
    )


def dora_to_heuristic_candidates(
    pm: object | None,
    snapshot: dict,
    prior: list[dict] | None = None,
) -> list[Heuristic]:
    out: list[Heuristic] = []
    # CFR rising 3 snapshots in a row -> canary + rollback
    hist = list(prior or [])
    if (
        len(hist) >= 2
        and snapshot.get("cfr", 0.0) > 0.15
        and snapshot.get("cfr", 0.0) > hist[-1]["cfr"]
        and all(
            hist[i]["cfr"] < hist[i + 1]["cfr"] if i + 1 < len(hist) else True
            for i in range(len(hist))
        )
    ):
        out.append(_mk(
            "DoD must include canary + rollback step",
            f"CFR rising ({[h['cfr'] for h in hist]} -> {snapshot['cfr']:.2f})",
            ["dora", "cfr", "canary"],
        ))
    # Lead Time > 7d median
    if snapshot.get("lead_time_p50", 0.0) > 7 * 86400.0:
        out.append(_mk(
            "PM should split any task > 1 day estimate",
            f"Lead time p50 = {snapshot['lead_time_p50'] / 86400.0:.1f}d exceeds 7d",
            ["pm", "lead_time"],
        ))
    # Deploy Freq < 1/week (~0.14/day)
    if snapshot.get("deploy_freq", 0.0) < 0.14:
        out.append(_mk(
            "Engineer must commit within 2h of starting the task",
            f"Deploy freq = {snapshot['deploy_freq']:.2f}/day (< 1/week)",
            ["engineer", "deploy_freq"],
        ))
    # MTTR > 4h
    if snapshot.get("mttr_p50", 0.0) > 4 * 3600.0:
        out.append(_mk(
            "Add hotfix-ready acceptance test in QA brief",
            f"MTTR p50 = {snapshot['mttr_p50'] / 3600.0:.1f}h exceeds 4h",
            ["qa", "mttr"],
        ))
    return out
