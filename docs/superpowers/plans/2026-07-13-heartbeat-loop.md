# HEARTBEAT Loop + Compaction — Implementation Plan (Plan 4)

> **Status:** Executed 2026-07-13. Retrospective document.

**Goal:** Enable real autonomy. Agents author their own next task in HEARTBEAT.md; the conductor reads it on boot and produces a validated TaskBrief; at sprint end compaction runs (wiki delta, MEMORY delta, audit pruning). A scope brake prevents runaway HEARTBEAT scope.

**Architecture:** `Conductor` reads `agents/<name>/heartbeat.md`, extracts the next-action section via regex, and produces a `TaskBrief` that passes the same `underspecified()` validation gate as PM-authored briefs. `CompactionRunner` runs at sprint boundaries: detects wiki files modified during the sprint window, snapshots per-agent MEMORY deltas, moves audit logs older than 7 days into `_compacted/`, and extracts retro candidates from the existing retro pipeline. The scheduler gains `register_scrum_sprint_jobs()` for 4h-interval scheduling. Rubric adds `story_completed_matches_story_booted` for scope-drift detection.

## File map

| Path | Action | Purpose |
|------|--------|---------|
| `orgos/agile/conductor.py` | Created | Reads HEARTBEAT.md, extracts next-action, produces TaskBrief, validates scope caps |
| `orgos/agile/compaction.py` | Created | Sprint-end pipeline: wiki delta, MEMORY deltas, audit pruning |
| `orgos/scheduler.py` | Modified | Added `register_scrum_sprint_jobs()` with conductor + compaction |
| `orgos/agile/rubric.py` | Modified | Added `story_completed_matches_story_booted` criterion |

## Key interfaces

```python
# Conductor
class Conductor:
    def __init__(self, agents_root: Path): ...
    def boot(agent_name, *, estimated_files=0, estimated_loc=0) -> BootResult: ...
    def boot_with_scope_check(agent_name, ...) -> BootResult:  # raises on bad scope

BootResult(agent_name, boots_at, next_action, brief: TaskBrief, scope_ok, scope_reason, warnings)

# Compaction
class CompactionRunner:
    def __init__(self, wiki_root=None, agents_root=None): ...
    def run(sprint, *, agent_names=None, window_days=7) -> CompactionResult: ...

CompactionResult(sprint_id, compacted_at, wiki_delta, memory_deltas, audit_files_compacted, retro_candidates, errors)

# Scheduler
register_scrum_sprint_jobs(scheduler)  # 4h interval with conductor + compaction
```

## Verification

- 19 conductor tests pass (section extraction, boot, scope validation, underspecified detection)
- 14 compaction tests pass (wiki delta, MEMORY deltas, audit pruning, sprint start parsing)
