---
version: 1.0.0
layer: specific
agent_name: SM_Agent
---

# Scrum Master Agent — HEARTBEAT

## Every 5 minutes
Check the board for stories in `draft` or `refinement`. Run planning poker
on any: architect / test / devsecops each vote, discuss if divergent,
converge on story points. Move refined stories to `ready`.

## Every 3 minutes
Run auto-elevation pass on the board: for any ready story older than 30
minutes bump its priority, and for any in_progress story where the
executor started but never committed (>15 minutes with no advance),
reclaim it back to ready so another agent can pick it up. Prevents the
tail-stall pattern where a stuck agent holds a story indefinitely.

## Every 20 minutes
Sprint boundary: close the current sprint and open the next one. This runs
sprint planning — pick up to velocity_target ready stories and commit them
to the new sprint's backlog. Then write a retrospective entry to
wiki/RETRO.md capturing what went well, what went wrong, one action item.

(Runtime override: pass `--sprint-duration-seconds N` to `orgos start` to
rewrite this cadence at boot — useful for demo cadences and 4h benchmark
runs where the chapter's model uses 4h boundaries.)
