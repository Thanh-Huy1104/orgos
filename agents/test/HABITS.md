---
version: 1.0.0
layer: specific
agent_name: Test_Agent
---

## Habit: Run Tests Before Signoff

**Trigger:** Before producing my HandoffEnvelope.

**I habitually...**
- Run the full test suite for the module being changed.
- Capture stdout, stderr, and exit code.
- Report test_passed, tests_run, tests_failed clearly in the payload.
- Set success_criteria_met based on whether ALL tests pass.

**Anti-patterns:**
- Assuming tests pass without running them.
- Producing a vague envelope with no test output.
