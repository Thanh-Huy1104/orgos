# orgos — a governed agentic framework with a self-organizing agile product team

orgos is a multi-agent orchestration framework built on CrewAI + litellm. Its
worked example is a **self-organizing engineering team** that runs nightly
sprints on the orgos repo itself, grades itself on DORA metrics, mutates its
own role topology under human approval, and supports counterfactual sprint
replay.

## Why this is interesting

Three demo hooks no public framework currently combines:

- **Self-organizing role topology** — `evolve.py` proposes ADD/REMOVE/SPLIT/MERGE
  role mutations every 5 sprints based on per-role contribution attribution.
  Human approves each as an ADR.
- **Nightly self-sprint + counterfactual replay** — the team works real GitHub
  issues on the orgos repo. The dashboard's Lab page replays past sprints with
  mutated PM briefs (different issue picked, different heuristic injected,
  different model on Engineer) and shows side-by-side outcomes.
- **DORA closed loop** — Deploy Frequency, Lead Time, Change Failure Rate, MTTR
  computed nightly from PMStore. DORA signals produce candidate Reflector
  heuristics that flow through the existing scoring machinery before being
  injected into future PM briefs.

## Architecture

Two-tier supervisor: orchestrator → department supervisors → workers. Strict
typed `HandoffEnvelope` between roles. Four permission tiers
(worker/validator/publisher/orchestrator). Human gate in code on every
publishing tool (`GatedToolBase`). Append-only audit logs. Rubric-graded retry
loops with Reflector heuristic learning. The system can propose changes to its
own org structure (`evolve.py`) but never auto-applies them.

## Quick start

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...  # or OPENAI_API_KEY, GEMINI_API_KEY
python -m orgos.scheduler            # nightly sprint loop
python -m orgos.api                  # dashboard + API on :8000
cd dashboard && npm install && npm run dev   # Next.js on :3000
```

## Design

See `DESIGN.md` for the load-bearing architectural decisions and
`docs/superpowers/specs/2026-06-30-agile-product-team-design.md` for the
current worked-example design.
