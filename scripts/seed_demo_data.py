"""Seed the dashboard with fake sprints so a first-time reviewer has
something to look at. No LLM calls, no cost — pure PMStore + Reflector
writes.

Usage:
    python scripts/seed_demo_data.py            # additive: leave existing rows
    python scripts/seed_demo_data.py --reset    # wipe + reseed

The seed produces:
  * 8 sprints spanning ~10 days (mix of completed / needs_revision / failed)
  * Each sprint has a full envelope chain (backlog -> brief -> engineering
    -> grade -> release -> dora -> retro), plus one sprint carries a
    counterfactual _replay envelope so the /lab UI has a replay to show.
  * Per-role attribution rows so /team shows real weight edges.
  * 6 DORA snapshots showing a Medium -> Elite progression.
  * 3 active Reflector heuristics + 2 candidate heuristics.
  * 2 ADR proposals (1 pending, 1 applied).

The idea is that after running this you can click every page in the
dashboard and see meaningful content.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Point PMStore + Reflector at the same DBs the running API uses.
os.environ.setdefault("ORGOS_PM_DB", "./_orgos_memory/pm.db")
os.environ.setdefault("ORGOS_MEMORY_DB", "./_orgos_memory/memory.db")

from orgos.pm import PMStore  # noqa: E402
from orgos.reflect import Heuristic, Reflector  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[1]
PM_DB = REPO_ROOT / "_orgos_memory" / "pm.db"
MEM_DB = REPO_ROOT / "_orgos_memory" / "memory.db"
SPRINTS_DIR = REPO_ROOT / ".sprints"


def _iso(dt: datetime) -> str:
    return dt.replace(tzinfo=timezone.utc).isoformat() if dt.tzinfo is None else dt.isoformat()


ISSUES = [
    ("42", "Add farewell() to src.py", ["agent-eligible"]),
    ("43", "Type-hint the intake module", ["agent-eligible"]),
    ("44", "Extract return strings to constants", ["agent-eligible", "docs"]),
    ("45", "Add doctest for greet()", ["agent-eligible"]),
    ("46", "Rename greet -> welcome with shim", ["agent-eligible"]),
    ("47", "Fix flaky test_dora seeding", ["agent-eligible", "flaky-test"]),
    ("48", "Add canary check to release DoD", ["agent-eligible"]),
    ("49", "Document run_nightly_sprint entrypoint", ["agent-eligible", "docs"]),
]


ROLE_WEIGHTS_COMPLETED = {
    "sprint-lead": 0.08,
    "product-manager": 0.28,
    "engineer": 0.42,
    "qa-validator": 0.14,
    "release-manager": 0.08,
}
ROLE_WEIGHTS_NEEDS_REVISION = {
    "sprint-lead": 0.10,
    "product-manager": 0.22,
    "engineer": 0.22,
    "qa-validator": 0.28,
    "release-manager": 0.18,
}
ROLE_WEIGHTS_UNIFORM = {r: 0.20 for r in
    ("sprint-lead", "product-manager", "engineer", "qa-validator", "release-manager")}


def make_envelopes(
    sprint_id: str,
    issue_id: str,
    issue_title: str,
    labels: list[str],
    status: str,
    rubric_score: float,
) -> dict:
    """Build a plausible seven-envelope chain for one sprint."""
    backlog_candidates = [
        {"issue_id": iid, "title": t, "size_estimate": "S", "risk_estimate": "low",
         "labels": lbl, "rank_reason": "size=S,risk=low"}
        for iid, t, lbl in ISSUES[:5]
    ]
    brief = {
        "role": "product-manager", "status": "completed",
        "summary": f"Brief for issue #{issue_id}", "success_criteria_met": True,
        "requires_human_approval": False,
        "payload": {
            "picked_issue_id": issue_id,
            "task_brief_json": json.dumps({"objective": issue_title}),
            "touched_files_allowlist": ["src.py", "test_src.py"],
            "acceptance_tests": ["pytest test_src.py"],
        },
    }
    engineering = {
        "role": "engineer", "status": "completed",
        "summary": f"Implemented #{issue_id}", "success_criteria_met": True,
        "requires_human_approval": False,
        "payload": {
            "diff": f"+++ b/src.py\n+def new_fn():\n+    return 'ok'  # for issue {issue_id}\n",
            "commit_sha": uuid.uuid4().hex[:12],
            "files_touched": ["src.py", "test_src.py"],
            "test_command": "pytest test_src.py",
            "test_output": "1 passed" if status == "completed" else "1 failed",
            "test_passed": status == "completed",
        },
    }
    criteria = [
        {"name": "tests_pass", "passed": status == "completed", "reason": ""},
        {"name": "files_in_allowlist", "passed": True, "reason": ""},
        {"name": "diff_size_ok", "passed": True, "reason": "diff_lines=8"},
        {"name": "commit_recorded", "passed": True, "reason": ""},
        {"name": "test_command_matches", "passed": True, "reason": ""},
    ]
    grade = {
        "role": "qa-validator", "status": status,
        "summary": f"rubric_score={rubric_score:.2f}",
        "success_criteria_met": rubric_score >= 0.99,
        "requires_human_approval": False,
        "payload": {"criteria": criteria, "rubric_score": rubric_score},
    }
    release = {
        "role": "release-manager", "status": "completed" if status == "completed" else "blocked",
        "summary": "PR opened" if status == "completed" else "no PR (QA failed)",
        "success_criteria_met": status == "completed",
        "requires_human_approval": True,
        "payload": {
            "pr_url": f"https://github.com/Thanh-Huy1104/orgos/pull/{100 + int(issue_id)}"
                      if status == "completed" else None,
            "branch": f"agile/{sprint_id}",
            "mock_mode": False,
        },
    }
    weights = (
        ROLE_WEIGHTS_COMPLETED if status == "completed"
        else ROLE_WEIGHTS_NEEDS_REVISION if status == "needs_revision"
        else ROLE_WEIGHTS_UNIFORM
    )
    retro = {
        "role": "retro-agent", "status": "completed",
        "summary": f"score={rubric_score:.2f}", "success_criteria_met": True,
        "requires_human_approval": False,
        "payload": {
            "retro_markdown": (
                f"# Sprint {sprint_id} retro\n\n"
                f"- **Issue:** #{issue_id} — {issue_title}\n"
                f"- **Rubric score:** {rubric_score:.2f}\n"
                f"- **Status:** {status}\n"
            ),
            "candidate_heuristics": (
                [{"rule": "Add canary + rollback to DoD",
                  "why": "tests_pass criterion regressed", "tags": ["canary"]}]
                if status != "completed" else []
            ),
            "role_attribution": weights,
        },
    }
    dora = {
        "role": "dora", "status": "completed",
        "summary": "tier=High",
        "success_criteria_met": True,
        "requires_human_approval": False,
        "payload": {
            "window_days": 14,
            "deploy_freq": round(random.uniform(0.4, 1.6), 3),
            "lead_time_p50": random.randint(3600, 60000),
            "cfr": round(random.uniform(0.02, 0.18), 3),
            "mttr_p50": random.randint(1800, 12000),
            "tier": random.choice(["High", "Elite", "Medium"]),
        },
    }
    return {
        "backlog": {"role": "intake", "status": "completed",
                    "summary": f"ranked {len(backlog_candidates)} candidates",
                    "success_criteria_met": True, "requires_human_approval": False,
                    "payload": {"candidates": backlog_candidates}},
        "brief": brief,
        "engineering": engineering,
        "grade": grade,
        "release": release,
        "dora": dora,
        "retro": retro,
    }, weights


def seed_sprints(pm: PMStore, base_time: datetime) -> list[str]:
    """Create the seven-envelope chains + attribution + snapshots."""
    sprint_ids: list[str] = []
    plan = [
        ("completed", 1.00), ("completed", 1.00), ("needs_revision", 0.75),
        ("completed", 1.00), ("failed", 0.55),   ("completed", 1.00),
        ("completed", 1.00), ("needs_revision", 0.80),
    ]

    for i, ((status, score), issue) in enumerate(zip(plan, ISSUES)):
        started_at = base_time + timedelta(days=i, hours=2)
        sprint_id = f"{started_at.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"
        sprint_ids.append(sprint_id)

        picked_issue = {"issue_id": issue[0], "title": issue[1], "labels": issue[2],
                        "body": f"Body for issue {issue[0]}", "url": f"https://x/{issue[0]}"}

        pm.create_sprint(sprint_id, f"agile/{sprint_id}", picked_issue,
                         status=status, started_at=_iso(started_at))

        envs, weights = make_envelopes(sprint_id, issue[0], issue[1], issue[2], status, score)
        for phase, env in envs.items():
            pm.record_sprint_envelope(sprint_id, phase, json.dumps(env))
        pm.update_sprint_status(sprint_id, status)

        for role, w in weights.items():
            pm.record_role_attribution(
                sprint_id, role, score=w,
                rubric_baseline=score, rubric_ablated=max(score - w, 0.0),
            )

        SPRINTS_DIR.mkdir(exist_ok=True)
        wt = SPRINTS_DIR / sprint_id
        wt.mkdir(exist_ok=True)
        (wt / "snapshot.json").write_text(json.dumps({
            "sprint_id": sprint_id,
            "started_at": _iso(started_at),
            "branch": f"agile/{sprint_id}",
            "picked_issue": picked_issue,
            "backlog": envs["backlog"]["payload"]["candidates"],
            "heuristics": [],
        }, indent=2))

    parent = sprint_ids[3]
    replay_id = f"replay-{uuid.uuid4().hex[:6]}"
    replay_picked = {"issue_id": "45", "title": "Add doctest for greet() — replayed",
                     "labels": ["agent-eligible"], "url": "https://x/45"}
    pm.create_sprint(replay_id, f"agile/{replay_id}", replay_picked,
                     status="completed",
                     started_at=_iso(base_time + timedelta(days=4, hours=6)))
    pm.record_sprint_envelope(replay_id, "_replay", json.dumps({
        "parent_sprint_id": parent,
        "mutation_kind": "inject_heuristic",
        "mutation": {"rule": "DoD must include canary + rollback step",
                     "why": "counterfactual: what if this heuristic already existed?",
                     "tags": ["dora", "canary"]},
    }))
    return sprint_ids


def seed_dora(pm: PMStore, base_time: datetime) -> None:
    trend = [
        ("Medium", 0.10, 4 * 86400, 0.13, 5 * 3600),
        ("Medium", 0.14, 3 * 86400, 0.11, 4 * 3600),
        ("High", 0.20, 2 * 86400, 0.08, 3 * 3600),
        ("High", 0.35, 1.5 * 86400, 0.06, 2 * 3600),
        ("Elite", 0.80, 1.0 * 86400, 0.04, 1.2 * 3600),
        ("Elite", 1.20, 0.6 * 86400, 0.02, 0.8 * 3600),
    ]
    for i, (tier, freq, lead, cfr, mttr) in enumerate(trend):
        pm.conn.execute(
            "INSERT INTO dora_snapshots (window_days, deploy_freq, lead_time_p50, "
            "cfr, mttr_p50, tier, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (14, freq, lead, cfr, mttr, tier,
             _iso(base_time + timedelta(days=i * 2))),
        )
    pm.conn.commit()


def seed_heuristics(pm: PMStore) -> None:
    reflector = Reflector(domain="agile", db_path=str(MEM_DB))
    now = datetime.now(timezone.utc)

    active = [
        Heuristic(id="h-active-1", domain="agile", tags=["engineer", "commit"],
                  rule="Engineer must commit within 2h of starting task",
                  why="Deploy Freq was <1/wk in early sprints",
                  source_run_id=None, score=0.86, use_count=4,
                  created_at=_iso(now - timedelta(days=5)), source="dora"),
        Heuristic(id="h-active-2", domain="agile", tags=["qa", "canary"],
                  rule="DoD must include canary + rollback step",
                  why="CFR clustered above 15% for 3 snapshots",
                  source_run_id=None, score=0.91, use_count=3,
                  created_at=_iso(now - timedelta(days=3)), source="dora"),
        Heuristic(id="h-active-3", domain="agile", tags=["pm", "split"],
                  rule="PM should split any task > 1 day estimate",
                  why="Lead time p50 exceeded 7d in week 2",
                  source_run_id=None, score=0.72, use_count=2,
                  created_at=_iso(now - timedelta(days=2)), source="dora"),
    ]
    candidates = [
        Heuristic(id="h-cand-1", domain="agile", tags=["qa", "mttr"],
                  rule="Add hotfix-ready acceptance test in QA brief",
                  why="MTTR p50 = 4.2h exceeds 4h threshold",
                  source_run_id=None, score=0.5, use_count=0,
                  created_at=_iso(now - timedelta(hours=6)), source="dora"),
        Heuristic(id="h-cand-2", domain="agile", tags=["engineer", "review"],
                  rule="Reviewer must run tests before approving",
                  why="Two consecutive sprints slipped on review depth",
                  source_run_id=None, score=0.5, use_count=0,
                  created_at=_iso(now - timedelta(hours=2)), source="rubric"),
    ]
    for h in active + candidates:
        reflector.store_candidate(h)


def seed_adrs(pm: PMStore) -> None:
    pending = pm.create_adr(
        sprint_id="dora-run-5", kind="SPLIT_ROLE",
        before_yaml=(
            "org:\n  departments:\n    - name: engineering\n"
            "      members:\n        - name: engineer\n          tier: worker\n"
        ),
        after_yaml=(
            "org:\n  departments:\n    - name: engineering\n"
            "      members:\n        - name: engineer\n          tier: worker\n"
            "        - name: engineer-release-eng\n          tier: worker\n"
        ),
        rationale=(
            "QA failures cluster on 'no-canary' (4 out of last 5 sprints). "
            "Proposal: split Engineer -> engineer + engineer-release-eng with "
            "the release-eng owning canary acceptance tests."
        ),
    )
    print(f"  ADR #{pending} (pending): SPLIT_ROLE engineer")

    applied = pm.create_adr(
        sprint_id="dora-run-3", kind="ADD_ROLE",
        before_yaml="org:\n  departments:\n    - name: engineering\n      members: []\n",
        after_yaml=(
            "org:\n  departments:\n    - name: engineering\n"
            "      members:\n        - name: flaky-test-specialist\n"
            "          tier: worker\n          expire_at: '2026-08-01T00:00:00+00:00'\n"
        ),
        rationale=(
            "Blocker tag 'flaky-test' appeared 3 times with no owner. "
            "Adding a 30-day temporary specialist to unblock the intake queue."
        ),
    )
    pm.set_adr_status(applied, "applied")
    print(f"  ADR #{applied} (applied): ADD_ROLE flaky-test-specialist (30d)")


def wipe(pm: PMStore) -> None:
    for tbl in ("sprints", "role_attribution", "adrs", "dora_snapshots"):
        pm.conn.execute(f"DELETE FROM {tbl}")
    pm.conn.commit()
    print("  wiped PMStore tables")
    try:
        import sqlite3
        conn = sqlite3.connect(str(MEM_DB))
        conn.execute("DELETE FROM heuristics")
        conn.commit()
        conn.close()
        print("  wiped Reflector heuristics")
    except Exception as e:
        print(f"  reflector wipe skipped: {e}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="Wipe existing rows before seeding")
    args = ap.parse_args()

    random.seed(42)
    pm = PMStore(str(PM_DB))
    if args.reset:
        wipe(pm)

    base = datetime.now(timezone.utc) - timedelta(days=10)
    print("Seeding sprints…")
    ids = seed_sprints(pm, base)
    print(f"  {len(ids)} sprints created")

    print("Seeding DORA snapshots…")
    seed_dora(pm, base)
    print("  6 DORA snapshots (Medium -> Elite progression)")

    print("Seeding Reflector heuristics…")
    seed_heuristics(pm)
    print("  3 active + 2 candidate heuristics")

    print("Seeding ADR proposals…")
    seed_adrs(pm)

    print("\nDone. Refresh http://localhost:3000 to see the seeded UI.")


if __name__ == "__main__":
    main()
