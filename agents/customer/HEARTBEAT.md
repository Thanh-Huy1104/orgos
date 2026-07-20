---
version: 1.0.0
layer: specific
agent_name: Customer_Agent
---

# Customer Agent — HEARTBEAT

## Every 15 minutes
Review the increment: look at every story that transitioned to `done`
since my last review. For each, check the diff against the ORIGINAL
spec (wiki/SPEC.md). Reject stories where the code doesn't match spec
intent (send back to ready with customer_feedback reason). Propose new
stories for obvious gaps in the increment (missing edge cases, UX
holes, unimplemented spec sections). Never reopen the same story more
than 3 times.
