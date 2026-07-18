# orgos — Troubleshooting

Runbook for the failure modes that hit real 4-hour runs. Each entry lists
the symptom, the root cause, and the one command that unblocks you.

---

## Table of contents

- [Nothing at all is happening](#nothing-at-all-is-happening)
- [Backlog is empty after decomposition](#backlog-is-empty-after-decomposition)
- [All agents show idle in `orgos status`](#all-agents-show-idle-in-orgos-status)
- [Merge conflict cascade — every commit blocks](#merge-conflict-cascade--every-commit-blocks)
- [`no_commit` streak — retries not helping](#no_commit-streak--retries-not-helping)
- [PO rejects architecture stories on acceptance](#po-rejects-architecture-stories-on-acceptance)
- [`orgos stop` doesn't stop the team](#orgos-stop-doesnt-stop-the-team)
- [Cost blew past estimate](#cost-blew-past-estimate)
- [Multi-agent throughput is worse than N=1](#multi-agent-throughput-is-worse-than-n1)
- [Run finished but report is empty](#run-finished-but-report-is-empty)

---

## Nothing at all is happening

**Symptom:** you ran `orgos start` and no events flow. `live.jsonl` is empty
or only has the boot lines.

**First:**

```bash
orgos doctor --repo .
```

If any essential row is `✗`, fix that. Common misses:
- No API key in `.env` and `claude`/`copilot` CLIs aren't installed. Pick one.
- Target repo has no commits. `git commit --allow-empty -m init` fixes this.

If doctor passes but agents don't tick, check the heartbeat interval —
scrum_master's sprint boundary is every 20 minutes by default. For a demo,
pass `--sprint-duration-seconds 120` to see boundaries in 2 minutes.

---

## Backlog is empty after decomposition

**Symptom:** `[cli] drafted 0 stories` or `[cli] WARNING: goal decomposition
failed: PO produced no parseable JSON`.

**Root causes and fixes:**

1. **Weak PO model.** The default is `deepseek/deepseek-chat`. If it's
   truncating JSON on complex goals, try:
   ```bash
   orgos start --po-model deepseek/deepseek-reasoner ...
   ```
   Or use Claude Code:
   ```bash
   orgos start --executor claude ...
   ```

2. **Goal too vague.** "Build me a scheduler" is too broad. Write a
   `spec.md` with `## Story:` blocks and pass `--spec-file spec.md` — orgos
   uses them directly, no PO involved.

3. **Prompt cache miss (network hiccup).** Retry once; the second attempt
   pays cache-hit rates and is 100× cheaper.

**Sanity check without spending a token:**

```bash
orgos plan --spec-file spec.md --repo .    # dry-run
```

---

## All agents show idle in `orgos status`

**Symptom:** `orgos status --watch` shows every agent `(idle)` even though
the board has ready stories.

**Diagnosis (in order):**

1. **Component ownership serialization.** If every ready story shares the
   same component (e.g. all touch `app.py`), only ONE can be in flight at
   a time — the others correctly wait. Check:
   ```bash
   jq '.component' .orgos_teams/<id>/board/stories/*.json | sort | uniq -c
   ```
   If everything is `"core"`, the PO left `files_to_touch` empty and
   orgos couldn't derive components. Rerun decomposition with a better
   `--po-model` or use a spec-file with explicit `Files:` fields.

2. **Depends-on chain.** A ready story with unmet `depends_on` won't be
   pulled. Look at any specific story:
   ```bash
   cat .orgos_teams/<id>/board/stories/<story-id>.json | jq '.depends_on'
   ```
   Then check each dep's state — if they're not `done`, that's why.

3. **Sprint number mismatch.** In sprint mode, stories with
   `sprint_number != current_sprint` don't get pulled. The next sprint
   boundary picks them up. Force one with `--sprint-duration-seconds`
   shorter than your wait time.

---

## Merge conflict cascade — every commit blocks

**Symptom:** `merge_conflict` events fire for every commit in a row; the
count in the report is `> 15`.

**Root cause (~95% of the time):** two agents committed to the same file
because `files_to_touch` was empty or misaligned in the decomposition.

**Fix in the running team:** N/A — the fix is already in the code (branch
reset on conflict, from Fix J in RESULTS.md). The cascade won't propagate
forever, just the current story blocks.

**Fix for the next run:**

1. Use `orgos plan --spec-file spec.md` beforehand and look at each story's
   `files:` line. If two stories touch the same file, merge them or add
   `Depends:` between them so they serialize.

2. If you're getting empty `files_to_touch` from the PO, that's a
   decomposition-quality problem — either write a spec-file, or use a
   stronger `--po-model`.

3. Enable rerere:
   ```bash
   git -C .orgos_teams/<id>/integration config rerere.enabled true
   ```
   (orgos does this automatically on team creation; check that it wasn't
   overridden.)

---

## `no_commit` streak — retries not helping

**Symptom:** stories bounce ready → in_progress → ready → in_progress and
eventually block after 3 attempts.

**First:** read the full failure body — the event stream only carries the
first 200 chars, but the full stderr is on disk:

```bash
cat .orgos_teams/<id>/agents/architect/failures/<story-id>.log
cat .orgos_teams/<id>/agents/architect-1/failures/<story-id>.log
```

Common causes:

- **LLM ran out of iterations.** The executor prompt asks for a commit but
  the LLM spent 40 iterations reading files. Bump the retry budget:
  ```bash
  ORGOS_MAX_ATTEMPTS_PER_STORY=5 orgos start ...
  ```

- **`git add` failed** because .gitattributes was corrupted (rare). Reset
  the workspace: `orgos reset --team-id <id>` then re-run.

- **Executor process hangs.** If wall_seconds on the no_commit event is
  suspiciously long (>300s), the underlying CLI is stuck. Consider
  `--executor spawn` (in-process LiteLLM, no external CLI).

---

## PO rejects architecture stories on acceptance

**Symptom:** `story_blocked_dod` events with
`missing a compliant wiki/DECISIONS.md entry`.

**Root cause:** the architect committed code but forgot the wiki entry, OR
wrote the entry in markdown-bold (`**source:** X`) which the DoD-gate regex
rejects. orgos auto-writes a stub if missing, but if the architect wrote
one manually in the wrong format, the check catches it.

**Fix:** if it's an isolated story, transition it back manually:

```python
python -c "
from orgos.agile.board_store import BoardStore
b = BoardStore('.orgos_teams/<id>/board')
b.transition('<story-id>', 'draft', actor='human', reason='wiki_format_fix')
"
```

Then delete or reformat the offending entry in
`.orgos_teams/<id>/integration/wiki/DECISIONS.md` — the required format is:

```
## <decision summary>
author: <who>
timestamp: <ISO-8601>
source: <story-id>

<rationale>
```

---

## `orgos stop` doesn't stop the team

**Symptom:** `orgos stop --team-id X` prints `ERROR: no running team found`.

**Cause:** the team started before `pid.txt` was persisted (very old
workspace) OR the process crashed and the file is stale.

**Fix (Unix):**

```bash
pgrep -f "orgos.cli.*start.*--team-id=X" | xargs kill -INT
```

**Fix (Windows):**

```powershell
Get-Process python* | Where-Object { $_.CommandLine -like '*--team-id X*' } | Stop-Process
```

For future runs, prefer `--timeout-seconds N` — no signal needed.

---

## Cost blew past estimate

Real DeepSeek v4-flash cost with prompt caching is dominated by cache-miss
tokens. If you're seeing 10× estimate, one of:

- **Cache invalidated by prompt changes.** Every persona edit or new tool
  registration invalidates the cache. First run after edits costs full
  price; subsequent runs are cheap.

- **Retry loops.** `no_commit` retries pay for the full prompt each time.
  Read the failures log (above) and fix the root cause instead of
  cranking `MAX_ATTEMPTS_PER_STORY`.

- **Excessive `wiki_read` calls.** If DECISIONS.md is huge, every read
  dumps the whole file into context. Rotate it manually if it exceeds
  ~10 KB.

Check per-story cost:

```bash
jq '.per_story_results | map({id: .story_id, tokens: (.tokens_input + .tokens_output)})' \
    .orgos_teams/<id>/campaign_result.json
```

---

## Multi-agent throughput is worse than N=1

**Symptom:** `--architects 3 --testers 3 --devsecops 3` finishes fewer
stories in 4h than a solo agent.

**This is the Run 5c regression — well-documented.** The cause is
component-lock contention when stories share files (they all serialize
on the same lock).

**Fix:**

1. Ensure `files_to_touch` is populated on every story:
   ```bash
   jq 'map(select(.files_to_touch == [])) | length' \
       .orgos_teams/<id>/board/stories/*.json
   ```
   If > 20%, your PO is under-specifying. Use a stronger `--po-model`,
   or provide a spec-file.

2. Ensure stories span **many** components. A goal with 7 disjoint
   feature areas gives N=3 room to run in parallel. A goal that's all
   one CRUD app on `app.py` gives N=3 nothing to parallelize.

3. Check `orgos status --watch` mid-run. If 2 of 3 architects are always
   idle, the goal doesn't parallelize enough — drop to N=1 for that
   goal.

---

## Run finished but report is empty

**Symptom:** `.orgos_teams/<id>/report.html` opens with `(no team)` or
missing stories.

**Cause:** the report is rendered on demand; if `orgos start` was SIGKILLed
(not SIGINT), the post-run rendering skipped.

**Fix:** re-render explicitly:

```bash
orgos report --team-id <id>
```

Or serve the live report:

```bash
orgos serve --team-id <id>
```
