# Sprint planning

Used by the Product Manager role when building the BriefEnvelope.

## What to include
- `picked_issue_id`
- `task_brief_json` (a serialised TaskBrief: objective, expected_output, success_criteria)
- `touched_files_allowlist` — explicit list of file paths the Engineer may modify
- `acceptance_tests` — at least one pytest invocation that will be run by QA

## Boundaries
- Never authorise > 5 files or > 400 LOC.
- If the issue's body is ambiguous, refuse and ask the Sprint Lead to pick another issue.
