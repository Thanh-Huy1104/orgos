  check: Read back DECISIONS.md to confirm append worked

- 2026-07-15 sprint L10-05-wait-time-follows-unit: Add wait_time metric — must match established time_unit — Added wait_time(ready_ts, start_ts) returning Metric with unit='seconds' (matching cycle_time convention), plus 3 tests verifying value, name, and unit consistency with cycle_time.
