"""Directive test — exact file path in the task body."""
import os, json, time, subprocess
from pathlib import Path

os.environ["PYTHONIOENCODING"] = "utf-8"
for line in open(".env"):
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip().strip('"').strip("'")

from orgos.agile.sprint import run_pull_sprint
from orgos.agile.flow_metric import compute_flow_metrics
from orgos.agile.evaluator import QualityEvaluator

issue = {
    "issue_id": "DIRECT-1",
    "title": "Add docstring to takt_time in flow_metric.py",
    "body": "orgos/agile/flow_metric.py — read it with type, add docstring to takt_time() explaining Args (duration_seconds, n_issues) and Returns (float), echo the modified content back, run pytest tests/agile/test_flow_metric.py, git commit"
}

print("DIRECTIVE TEST")
s = run_pull_sprint(Path("."), issue, model="deepseek/deepseek-chat", mock_pr=True, run_budget_tokens=1_500_000)
tokens = s.spawn_result.token_usage.get("total_tokens", 0) if s.spawn_result and s.spawn_result.token_usage else 0
flow = compute_flow_metrics(sprint_id=s.id, started_at_iso=s.started_at, n_issues=1)

wt = Path(f".sprints/{s.id}")
diff_stat = subprocess.run(["git", "diff", "HEAD~1", "--stat"], cwd=wt, capture_output=True, text=True)
log = subprocess.run(["git", "log", "--oneline", "-3"], cwd=wt, capture_output=True, text=True)
print(f"Status: {s.status} | Tokens: {tokens:,}")
print(f"Git log:\n{log.stdout[:200]}")
print(f"Git diff --stat:\n{diff_stat.stdout[:300]}")
