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

## Every 20 minutes
Sprint boundary: close the current sprint and open the next one. This runs
sprint planning — pick up to velocity_target ready stories and commit them
to the new sprint's backlog. Then write a retrospective entry to
wiki/RETRO.md capturing what went well, what went wrong, one action item.

(Runtime override: pass `--sprint-duration-seconds N` to `orgos start` to
rewrite this cadence at boot — useful for demo cadences and 4h benchmark
runs where the chapter's model uses 4h boundaries.)
