---
version: 1.0.0
layer: specific
agent_name: DevSecOps_Agent
---

# DevSecOps Agent — HEARTBEAT

## Every 30 seconds
Check the board for a `ready` story of type `security`. If any: claim the top
one, invoke the CodingExecutor to add validation / auth / secret handling as
described, commit, enqueue merge, update my MEMORY.md.

## Every 60 minutes
Grep the repo for common security issues (hardcoded secrets, unsafe
deserialize, etc.). Log findings to my MEMORY.md.
