"""Long-form experiment: run N sprints, collect metrics across iterations.

Usage: py -3.12 long_run.py --sprints 10 --model deepseek/deepseek-chat
"""

import os, json, time, sys, argparse
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

os.environ["PYTHONIOENCODING"] = "utf-8"
for line in open(".env"):
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip().strip('"').strip("'")

from orgos.agile.sprint import run_pull_sprint, Sprint
from orgos.agile.flow_metric import compute_flow_metrics, FlowMetricResult
from orgos.agile.compaction import CompactionRunner
from orgos.pm import PMStore


def make_issue(n: int) -> dict:
    tasks = [
        {"title": "Add docstring to takt_time in flow_metric.py",
         "body": "Add a docstring to takt_time() in orgos/agile/flow_metric.py explaining it returns average calendar time per issue. Run pytest to verify."},
        {"title": "Add type hints to board.py check_ready_gate",
         "body": "Add Python type annotations to check_ready_gate() in orgos/agile/board.py. All parameters are Keyword-only. Run pytest tests/agile/test_board.py."},
        {"title": "Add logging to conductor boot method",
         "body": "Add a log.info() call to Conductor.boot() in orgos/agile/conductor.py that logs agent_name and next_action length. Run pytest tests/agile/test_conductor.py."},
        {"title": "Add error message to scope_drift_check",
         "body": "Improve the error message in _scope_drift_check in orgos/agile/rubric.py to include the file count of drift files. Run pytest tests/agile/test_rubric.py."},
        {"title": "Add __repr__ to CompactionResult",
         "body": "Add a __repr__ method to CompactionResult in orgos/agile/compaction.py that returns sprint_id and audit count. Run pytest tests/agile/test_compaction.py."},
    ]
    t = tasks[n % len(tasks)]
    return {"issue_id": str(500 + n), "title": t["title"], "body": t["body"]}


def run_experiment(num_sprints: int = 10, model: str = "deepseek/deepseek-chat",
                   budget: int = 300_000):
    repo = Path(".")
    compaction = CompactionRunner(Path("wiki"), Path("agents"))
    pm = PMStore()
    results: list[dict] = []

    print(f"LONG-FORM EXPERIMENT: {num_sprints} pull-based sprints")
    print(f"Model: {model}  Budget: {budget:,}/sprint  Total: ~{budget*num_sprints:,}")
    print("=" * 60)

    for i in range(num_sprints):
        issue = make_issue(i)
        t0 = time.time()

        try:
            sprint = run_pull_sprint(repo, issue, model=model, mock_pr=True,
                                     run_budget_tokens=budget)
        except Exception as e:
            print(f"[{i+1}/{num_sprints}] CRASH: {e}")
            results.append({"sprint_id": f"crash-{i}", "status": "crashed",
                           "tokens": 0, "elapsed_s": 0, "error": str(e)})
            continue

        elapsed = time.time() - t0
        tokens = (sprint.spawn_result.token_usage.get("total_tokens", 0)
                  if sprint.spawn_result and sprint.spawn_result.token_usage else 0)
        flow = compute_flow_metrics(sprint_id=sprint.id,
                                    started_at_iso=sprint.started_at,
                                    n_issues=1)
        cmp = compaction.run(sprint, agent_names=["architect", "test", "devsecops"])

        r = {
            "sprint_id": sprint.id,
            "issue": issue["title"][:50],
            "status": sprint.status,
            "tokens": tokens,
            "elapsed_s": round(elapsed, 1),
            "envelopes": len(sprint.envelopes),
            "flow_score": flow.flow_score,
            "wiki_delta": len(cmp.wiki_delta),
        }
        results.append(r)

        print(f"[{i+1}/{num_sprints}] {sprint.status:16} {tokens:>8,} tokens  "
              f"{elapsed:>5.0f}s  flow={flow.flow_score:.2f}  "
              f"env={len(sprint.envelopes)}  wiki={len(cmp.wiki_delta)}  "
              f"'{issue['title'][:40]}'")

        if i < num_sprints - 1:
            time.sleep(2)  # brief cooldown between sprints

    # Summary
    completed = [r for r in results if r["status"] == "completed"]
    crashed = [r for r in results if r["status"] == "crashed"]
    total_tokens = sum(r["tokens"] for r in results)
    total_time = sum(r["elapsed_s"] for r in results)

    print(f"\n{'='*60}")
    print(f"EXPERIMENT SUMMARY: {num_sprints} sprints")
    print(f"  Completed: {len(completed)}/{num_sprints} ({len(completed)/num_sprints*100:.0f}%)")
    print(f"  Crashed:   {len(crashed)}/{num_sprints}")
    print(f"  Total tokens: {total_tokens:,}")
    print(f"  Avg tokens/sprint: {total_tokens/num_sprints:,.0f}")
    print(f"  Total time: {total_time:.0f}s ({total_time/60:.1f}min)")
    if completed:
        avg_flow = sum(r["flow_score"] for r in completed) / len(completed)
        print(f"  Avg flow score: {avg_flow:.3f}")

    # Save results
    out_path = Path(f"experiment_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}.json")
    out_path.write_text(json.dumps({
        "config": {"num_sprints": num_sprints, "model": model, "budget": budget},
        "results": results,
        "summary": {
            "completed": len(completed), "crashed": len(crashed),
            "total_tokens": total_tokens,
            "avg_tokens": total_tokens // max(num_sprints, 1),
            "total_time_s": round(total_time, 1),
        },
    }, indent=2))
    print(f"\nResults saved to {out_path}")
    return results

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--sprints", type=int, default=5)
    p.add_argument("--model", default="deepseek/deepseek-chat")
    p.add_argument("--budget", type=int, default=300_000)
    args = p.parse_args()
    run_experiment(args.sprints, args.model, args.budget)
