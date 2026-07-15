# Flow Metrics + Benchmarking — Implementation Plan (Plan 5)

> **Status:** Executed 2026-07-13. Retrospective document.

**Goal:** The measurement layer. Every sprint scored by rubric + DORA + flow-metric; `replay.swap_topology(agents_dir)` enables paired-run dual-team benchmarking on the same issue with SHA-pinned replay.

**Architecture:** `flow_metric.py` implements takt-time and velocity-delta with a composite flow_score (weighted: 40% takt, 30% velocity, 30% throughput). `paired_run.py` freezes repo SHA, runs the same issue against two `agents/` directories, collects rubric + DORA + flow scores, and produces a comparison report with winner determination. The `SwapTopology` mutation extends the existing replay system. API endpoints expose paired-run reports and per-sprint flow metrics.

## File map

| Path | Action | Purpose |
|------|--------|---------|
| `orgos/agile/flow_metric.py` | Created | `takt_time()`, `velocity_delta()`, `compute_flow_metrics()`, `FlowMetricResult` |
| `orgos/agile/paired_run.py` | Created | `run_paired_benchmark()`, `PairedRunReport`, `_compare_teams()` |
| `orgos/agile/mutations.py` | Modified | Added `SwapTopology(agents_dir: str, kind="swap_topology")` |
| `orgos/agile/replay.py` | Modified | Dispatches `SwapTopology` → `run_scrum_sprint()` |
| `orgos/api.py` | Modified | `POST /api/lab/paired-run`, `GET /api/lab/flow-metrics/{sprint_id}` |

## Key interfaces

```python
# Flow metrics
takt_time(duration_seconds, n_issues) -> float
velocity_delta(expected_finish_iso, actual_finish_iso) -> float
compute_flow_metrics(*, sprint_id, started_at_iso, completed_at_iso=None, n_issues=0, expected_finish_iso=None) -> FlowMetricResult

FlowMetricResult(sprint_id, duration_seconds, n_issues, takt_time, velocity_delta, flow_score, warnings)

# Paired benchmarking
run_paired_benchmark(repo_path, issue, agents_dir_a, agents_dir_b, *, model=None, _offline=False) -> PairedRunReport

PairedRunReport(issue_id, repo_sha, created_at, team_a: TeamRunResult, team_b: TeamRunResult, winner, score_delta, flow_delta, summary)
```

## Known open items

- **Flow-metric formula** is a working reconstruction (takt-time / velocity-delta lineage). The exact aggregation (40/30/30 weights) needs external verification before publishing results.
- **Attribution refactor** (per-artifact instead of per-role) is needed before dual-team comparisons can attribute wins to specific topology choices.
- **Cost governance** — dual runs double spend. A budget cap and "sample N% of issues" policy is needed in production.

## Verification

- 14 flow_metric tests pass (takt, velocity, aggregate scoring, warnings)
- 7 paired_run tests pass (team comparison, offline mode, report generation)
- 3 swap_topology tests pass (mutation creation, apply, immutability)
