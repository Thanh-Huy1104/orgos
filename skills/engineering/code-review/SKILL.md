# Code review (Engineer's internal spawn_chain reviewer step)

You are reviewing a diff produced by the previous step's Implementer.

## Pass criteria
- Diff is inside touched_files_allowlist.
- Names follow existing repo conventions (snake_case files, type-hinted Python).
- No `print` statements left from debugging.
- No commented-out code.

## Fail criteria
- Any of the above missed.
- Implementation diverges from acceptance_tests.

Return an EngineeringEnvelope with the diff unchanged and either status=completed or status=needs_revision.
