# orgos demo — a self-organizing agile team

This demo shows orgos running a five-role engineering team on its own repo,
overnight. The morning artifact is a graded sprint, a DORA scoreboard update,
and (every 5 sprints) a proposed role-topology mutation awaiting your
approval.

## What you'll see

1. **`/`** — the team scoreboard: DORA grade, 14-sprint streak, active heuristics.
2. **`/sprints`** — last night's sprint detail: the seven envelope chain
   (Intake → Brief → Engineer chain → QA → Release → Retro → DORA).
3. **`/team`** — live role topology graph; click into the ADR feed to approve a
   pending mutation.
4. **`/lab`** — re-run sprint N with the PM's second-choice issue. Side-by-side
   outcomes, rubric-score deltas highlighted.
5. **`/dora`** — DORA time-series and the candidate-heuristic queue.

## Running the demo

```bash
# Seed the demo by running 5 sprints in sequence
python -m orgos.agile.demo seed --sprints 5

# Open the dashboard
python -m orgos.api &
cd dashboard && npm run dev
```

The seed run uses a curated set of `agent-eligible` GitHub issues. Expected
cost: ~$25-40 on Sonnet 4.6.
