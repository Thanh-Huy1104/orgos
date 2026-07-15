"""Team-vs-solo benchmark harness.

Usage:
    python scripts/run_benchmark.py --n 5 --seed 42
    python scripts/run_benchmark.py --n 20 --seed 7 --run-id my-demo

Writes benchmark_reports/<run_id>/{team,solo}/<issue_id>.json and a summary.json.
Also writes benchmark_reports/<run_id>/report.html — the shareable artifact.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

# Make the repo root importable when run directly.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Load repo-local .env so DEEPSEEK_API_KEY etc. reach litellm/crewai.
_env_path = _REPO_ROOT / ".env"
if _env_path.exists():
    import os
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v

from orgos.agile.benchmark import BenchmarkRun, run_team
from orgos.agile.issue_generator import BenchmarkIssue, generate_corpus
from orgos.agile.issue_generator_linked import generate_linked_corpus
from orgos.agile.report import render_report
from orgos.agile.scrum_team_runner import run_scrum
from orgos.agile.solo_baseline import run_solo


def _new_run_id() -> str:
    return "bench-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")


def _write_run(base: Path, approach: str, run: BenchmarkRun) -> Path:
    d = base / approach
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{run.issue_id}.json"
    p.write_text(run.to_json())
    return p


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=5, help="number of issues in corpus")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--model", type=str, default="deepseek/deepseek-chat")
    parser.add_argument("--run-id", type=str, default=None)
    parser.add_argument("--approaches", type=str, default="team,scrum,solo",
                        help="comma list of approaches to run (team=waterfall,scrum=self-organizing,solo=1-agent)")
    parser.add_argument("--budget", type=int, default=2_000_000,
                        help="per-issue token budget")
    parser.add_argument("--backlog", type=str, default="independent",
                        choices=["independent", "linked"],
                        help="which corpus to run")
    args = parser.parse_args()

    run_id = args.run_id or _new_run_id()
    base = _REPO_ROOT / "benchmark_reports" / run_id
    base.mkdir(parents=True, exist_ok=True)

    if args.backlog == "linked":
        corpus = generate_linked_corpus(n=args.n)
    else:
        corpus = generate_corpus(n=args.n, seed=args.seed)
    approaches = [a.strip() for a in args.approaches.split(",") if a.strip()]

    # Persist the corpus for reproducibility.
    (base / "corpus.json").write_text(json.dumps([asdict(c) for c in corpus], indent=2))

    manifest = {
        "run_id": run_id,
        "model": args.model,
        "n": args.n,
        "seed": args.seed,
        "approaches": approaches,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    (base / "manifest.json").write_text(json.dumps(manifest, indent=2))

    runs: dict[str, list[BenchmarkRun]] = {a: [] for a in approaches}

    # Per-side wall-clock guard so a hung API call (wifi drop, provider stall)
    # can't eat the whole run. Runs the side in a thread; if it doesn't return
    # within the guard window, we abandon that side for this issue and move on.
    import threading
    _PHASE_TIMEOUT = 600  # 10 min per side per issue

    def _run_with_timeout(fn, label):
        result_holder = {}
        def _target():
            try:
                result_holder["ok"] = fn()
            except Exception as e:
                result_holder["err"] = e
        t = threading.Thread(target=_target, daemon=True)
        t.start()
        t.join(_PHASE_TIMEOUT)
        if t.is_alive():
            raise TimeoutError(f"{label} exceeded {_PHASE_TIMEOUT}s guard — abandoning this side for this issue")
        if "err" in result_holder:
            raise result_holder["err"]
        return result_holder["ok"]

    for idx, issue in enumerate(corpus, start=1):
        print(f"\n=== [{idx}/{len(corpus)}] {issue.issue_id}  ({issue.template})", flush=True)
        d = {"issue_id": issue.issue_id, "title": issue.title, "body": issue.body}

        if "team" in approaches:
            print(f"  → team (waterfall)...", flush=True, end="")
            try:
                _, run = _run_with_timeout(
                    lambda: run_team(_REPO_ROOT, d, model=args.model, run_budget_tokens=args.budget),
                    "team")
            except Exception as e:
                print(f" ERROR: {e}")
                continue
            _write_run(base, "team", run)
            runs["team"].append(run)
            print(f" done "
                  f"tokens={run.tokens_total} cost=${run.cost_usd:.4f} "
                  f"q={run.quality_ac}/{run.quality_code}/{run.quality_tests} "
                  f"commit={run.commit_produced}", flush=True)

        if "scrum" in approaches:
            print(f"  → scrum...", flush=True, end="")
            try:
                _, run = _run_with_timeout(
                    lambda: run_scrum(_REPO_ROOT, d, model=args.model,
                                      n_workers=1, run_budget_tokens=args.budget),
                    "scrum")
            except Exception as e:
                print(f" ERROR: {e}")
                continue
            _write_run(base, "scrum", run)
            runs["scrum"].append(run)
            print(f" done "
                  f"tokens={run.tokens_total} cost=${run.cost_usd:.4f} "
                  f"q={run.quality_ac}/{run.quality_code}/{run.quality_tests} "
                  f"commit={run.commit_produced}", flush=True)

        if "solo" in approaches:
            print(f"  → solo...", flush=True, end="")
            try:
                _, run = _run_with_timeout(
                    lambda: run_solo(_REPO_ROOT, d, model=args.model, run_budget_tokens=args.budget),
                    "solo")
            except Exception as e:
                print(f" ERROR: {e}")
                continue
            _write_run(base, "solo", run)
            runs["solo"].append(run)
            print(f" done "
                  f"tokens={run.tokens_total} cost=${run.cost_usd:.4f} "
                  f"q={run.quality_ac}/{run.quality_code}/{run.quality_tests} "
                  f"commit={run.commit_produced}", flush=True)

    # Summary
    def _tot(rs: list[BenchmarkRun], key: str) -> float:
        return sum((getattr(r, key) or 0) for r in rs)

    def _avg(rs: list[BenchmarkRun], key: str) -> float:
        vals = [getattr(r, key) for r in rs if getattr(r, key) is not None]
        return sum(vals) / len(vals) if vals else 0

    summary = {
        "run_id": run_id,
        "n_issues": len(corpus),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    for approach in approaches:
        rs = runs[approach]
        summary[approach] = {
            "n_runs": len(rs),
            "tokens_total": int(_tot(rs, "tokens_total")),
            "cost_usd_total": round(_tot(rs, "cost_usd"), 4),
            "wall_seconds_total": round(_tot(rs, "wall_seconds"), 1),
            "commits_produced": sum(1 for r in rs if r.commit_produced),
            "avg_quality_ac": round(_avg(rs, "quality_ac"), 2),
            "avg_quality_code": round(_avg(rs, "quality_code"), 2),
            "avg_quality_tests": round(_avg(rs, "quality_tests"), 2),
        }
    (base / "summary.json").write_text(json.dumps(summary, indent=2))
    print("\n=== SUMMARY ===")
    print(json.dumps(summary, indent=2))

    # HTML report
    report_path = base / "report.html"
    render_report(base, report_path)
    print(f"\nReport: {report_path}")
    print(f"Open with: open {report_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
