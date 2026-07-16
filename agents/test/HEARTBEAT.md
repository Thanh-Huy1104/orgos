---
version: 1.0.0
layer: specific
agent_name: Test_Agent
---

# Test Agent — HEARTBEAT

## Every 30 seconds
Check the board for a `ready` story of type `test`. If any: claim the top one,
invoke the CodingExecutor to add or update tests, commit, enqueue merge,
update my MEMORY.md.

## Every 30 minutes
Skim wiki/DECISIONS.md for any new testing conventions.
