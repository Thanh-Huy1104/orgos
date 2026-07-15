# WIP: architect brief change — record substantive decisions, not just log lines

**Status:** ready to apply when the current pilot (`pilot-10`) completes.
Do NOT edit `orgos/agile/sprint.py` while pilot is running — the second half
of the pilot would see different code than the first half.

## Motivation

The current architect brief (in `sprint.py`, `_ARCHITECT_BRIEF`) tells the
agent to append a one-line changelog entry to `wiki/DECISIONS.md`. That
records what happened but not *why*, so later sprints get no useful signal
from it. The linked-corpus benchmark
(`orgos/agile/issue_generator_linked.py`) depends on later architects
reading substantive prior decisions — which the current brief doesn't
produce.

## The swap

In `orgos/agile/sprint.py`, find step 5 in `_ARCHITECT_BRIEF`:

```python
5. WIKI LOG (one call): use the `wiki_write` tool with mode="append" to append
   one line to `DECISIONS.md`:
     path="DECISIONS.md"
     content="- <today ISO date> sprint {issue_id}: {title} — <one-line summary of what you wrote>"
     mode="append"
```

Replace with:

```python
5. WIKI DECISION (one call): use the `wiki_write` tool with mode="append" on
   `DECISIONS.md`. If your work established a convention that a future teammate
   would need to know to stay consistent — naming style, unit, field order,
   error-handling policy, API shape — record it as a full block:

     ## <topic> — sprint {issue_id}
     - <decision>: <the exact choice, as it appears in the code>
     - Rationale: <why this over the alternative>
     - Applies to: <what future code should follow this>

   If your work established no new convention (e.g. it just added a
   docstring or fixed a typo), append a one-line entry instead:

     - <today ISO date> sprint {issue_id}: {title} — <one-line summary>

   Do NOT skip this step. Reading and writing DECISIONS.md is how the team
   stays coherent across sprints.
```

## When to apply

1. Wait for `pilot-10` to finish (background bash task `bp4imlrr9`).
2. Read pilot report at `benchmark_reports/pilot-10/report.html`.
3. If the story is compelling as-is (team wins on independent issues), we
   may or may not need this change. Discuss.
4. If we're going ahead with the linked-corpus pilot, apply this swap
   FIRST, then run:

     ```
     python3 scripts/run_benchmark.py --n 10 --seed 42 \
         --run-id linked-pilot-10 --backlog linked
     ```

   (Note: `--backlog linked` will require a small harness change to load
   from `issue_generator_linked.generate_linked_corpus` instead of the
   default generator. That change is trivial — one branch in
   `scripts/run_benchmark.py`.)

## Small harness change needed too

In `scripts/run_benchmark.py`, replace:

```python
from orgos.agile.issue_generator import generate_corpus
...
corpus = generate_corpus(n=args.n, seed=args.seed)
```

with:

```python
from orgos.agile.issue_generator import generate_corpus
from orgos.agile.issue_generator_linked import generate_linked_corpus
...
if getattr(args, "backlog", "independent") == "linked":
    corpus = generate_linked_corpus(n=args.n)
else:
    corpus = generate_corpus(n=args.n, seed=args.seed)
```

And add the CLI flag:

```python
parser.add_argument("--backlog", type=str, default="independent",
                    choices=["independent", "linked"],
                    help="which corpus to run")
```

## Expected linked-pilot outcome

- L1-L3: both sides pass (basic tests, no cross-issue dependency).
- L4 onwards: team should read wiki/DECISIONS.md and follow conventions
  → tests pass. Solo has no wiki access → picks conventions randomly
  → tests fail on convention checks (name style, unit consistency,
  return-None-on-invalid).
- Team's rolling avg quality stays ~5. Solo's drops from ~5 to ~2-3
  over the sequence.

That chart — team flat-high vs solo drifting down — is the
offshore-team demo. Not "team is better per issue" but
"team retains context; solo can't".
