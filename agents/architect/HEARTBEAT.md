---
version: 1.0.0
layer: specific
agent_name: Architect_Agent
---

# Architect Agent — HEARTBEAT

## Every 30 seconds
Check the board for a `ready` story of type `architecture` or `feature`. If any:
claim the top one, invoke the CodingExecutor in my worktree, commit, enqueue
the merge, update my MEMORY.md with what I learned. If none: sleep.

## Every 30 minutes
Read wiki/DECISIONS.md to catch up on any new architectural decisions from
other agents.
