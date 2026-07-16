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
Run the sprint retrospective. Write a retro entry to wiki/RETRO.md capturing:
what went well, what went wrong, one action item for next sprint. Then trigger
PO's replan.
