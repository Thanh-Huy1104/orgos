---
version: 1.0.0
layer: specific
agent_name: PO_Agent
---

# Product Owner Agent — HEARTBEAT

## Every 30 minutes
If the board has fewer than 3 stories in `ready`, invoke replan(): read the
SPEC.md and RETRO.md, draft new stories to fill the backlog. Do NOT
re-propose work that already exists in the board.

## Every 60 minutes
Poll the draft PR (if any) for new review comments via pr_feedback.ingest().
Each substantive comment becomes a new story on the board.
