---
version: 1.0.0
layer: specific
agent_name: PO_Agent
---

# Product Owner Agent — HEARTBEAT

## Every 1 minutes
Acceptance review: for each story in `pending_acceptance` state, accept it
(transition to done) if it has a commit_sha and the merged code looks
consistent with the story's body. Reject (transition to blocked with a
reason) if the commit is empty or the change doesn't match acceptance
criteria. Additionally, an `architecture` story may only be accepted once it
has recorded its decision in `wiki/DECISIONS.md` with the three mandatory
fields (author, timestamp, source) citing the story's issue_id — an
undocumented or unsourced decision must be rejected. This is the real-Scrum
DoD gate.

## Every 30 minutes
If the board has fewer than 3 stories in `ready`, invoke replan(): read the
SPEC.md and RETRO.md, draft new stories to fill the backlog. Do NOT
re-propose work that already exists in the board.

## Every 60 minutes
Poll the draft PR (if any) for new review comments via pr_feedback.ingest().
Each substantive comment becomes a new story on the board.
