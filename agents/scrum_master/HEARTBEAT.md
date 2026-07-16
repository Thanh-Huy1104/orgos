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

## Every 4 hours
Sprint boundary: close the current sprint and open the next one. This runs
sprint planning — pick up to velocity_target ready stories and commit them
to the new sprint's backlog. Then write a retrospective entry to
wiki/RETRO.md capturing what went well, what went wrong, one action item.
