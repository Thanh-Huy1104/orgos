# Handoff — orgos three-arm benchmark, Windows → Mac

**Written:** 2026-08-04, from a Windows workstation, for a Mac session with more
compute. Read this in full before doing anything.

---

## 1. What this project is (60-second version)

`orgos` is a multi-agent scrum-team runtime. Two topologies share one executor
stack:

- `orgos start` — **scrum**: flat specialists (architect / test / devsecops
  / PO / SM), shared board, git worktree per agent, merge queue.
- `orgos run --waterfall` — **waterfall**: sequential PO → arch → test →
  devsecops pipeline, one story at a time.

The interesting comparison is **scrum vs waterfall vs a solo-agent baseline**
(Copilot CLI, sequential one prompt per story). All three arms work on the
same 28-story spec: `docs/specs/minisearch.md` (a text-search engine with
tokenizer, BM25, inverted index, FastAPI, CLI).

## 2. The finding so far (do not lose this)

At n=2 per arm, measured against a **held-out reference test suite** at
`docs/specs/minisearch_reftests/` (110 tests written from the spec alone,
without reading any agent's code):

| Arm            | run 1  | run 2  | mean     | range         |
|----------------|--------|--------|----------|---------------|
| Solo Copilot   | 79.1%  | 71.8%  | **75.5%** | [71.8, 79.1] |
| Waterfall      | 33.6%  | 12.7%  | **23.2%** | [12.7, 33.6] |
| Scrum          | 19.1%  | 12.7%  | **15.9%** | [12.7, 19.1] |

**Solo Copilot dominates on spec conformance.** Both multi-agent topologies
lose badly. The failure mode is **spec drift** — each agent implements only
one story out of the whole spec, so they collectively drift on interface
names, dataclass shapes, function-vs-class choices. Solo Copilot reads the
whole spec each cycle and stays conformant.

Concrete example (both waterfall and scrum do this):
- Spec says `remove_stopwords(tokens, lang="en")` and `bigrams(tokens)` —
  module-level functions.
- Both team topologies build `class StopwordFilter` and `class NgramGenerator`
  instead. Their own tests pass. The spec's tests fail.

**This is the presentation story.** Not "scrum wins," not "scrum loses" —
it's *"multi-agent coordination without a spec-conformance gate is worse
than a single strong agent."* The proposed fix (roadmap item) is a
spec-conformance gate: reference tests generated from the AC block become
a hard merge gate, and a shared type-stub file is auto-generated from the
spec so drift becomes an import error not a silent test-pass.

## 3. What we need from the Mac session

**n ≥ 5 per arm** (ideally n=10) so the ranges above become tight confidence
bounds. The Windows machine can only sustain sequential runs (subscription
throttling on Copilot; one batch is ~6.75 hrs at n=3). Mac with more compute
+ parallelism budget could do:

- **n=10 per arm with arms in parallel** — solo Copilot serially, waterfall
  serially (deepseek API rate-limited), scrum in parallel with waterfall
  (both hit deepseek but scrum has more workers). ~7.5 hrs wall.
- Or **n=5 per arm, all arms concurrent, second target spec** to check
  cross-spec generalization.

The bare-minimum ask: **n=5 per arm on the minisearch spec**, sequential,
which is ~11 hrs wall on a Windows-equivalent box (probably faster on Mac).

## 4. What's committed to the branch

Branch `vendored-spawn` on `origin` — the last 7 commits are:

```
752274b  docs: Adam-demo deck + pilot comparison HTML
3387eea  PowerShell launchers used during pilot experiments
6419607  bench: n=3 batch harness for the three-arm comparison
7eb4c82  Held-out reference test suite + scoring harness
c424331  build_comparison_html: use sys.executable for pytest on Windows
1b42231  Windows resilience + fair-baseline waterfall patches
49ff75a  gitignore: exclude experiment logs, dist archives, auto-generated egg-info
```

Key artifacts:
- `docs/specs/minisearch.md` — the 28-story spec (input)
- `docs/specs/minisearch_reftests/` — 110 held-out tests (evaluation)
- `scripts/score_reftests.py` — scoring harness (Python, cross-platform)
- `bench/*.ps1` — batch driver (**PowerShell — Windows-shaped, port required**)
- `docs/adam-demo-deck.html` — the presentation deck (numbers on slide 5
  need to be refreshed after new runs)

## 5. Mac-specific setup

### 5.1 Python + orgos
```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 5.2 Environment
```bash
cat > .env <<'EOF'
DEEPSEEK_API_KEY=sk-...        # user has this
OPENAI_API_KEY=...             # not needed unless retargeting model
EOF
export PYTHONIOENCODING=utf-8   # not strictly needed on macOS but harmless
export OTEL_SDK_DISABLED=true
```

### 5.3 Copilot CLI (only if running the solo arm)
```bash
npm install -g @github/copilot
copilot           # then /login (interactive) — one-time
copilot -p "hello"  # verify auth
```

## 6. What to run

**Option A (recommended first pass) — port the driver to bash.**
The `bench/*.ps1` scripts encode the arm invocations. They're readable
PowerShell but the loop structure needs porting. The core is:

For each iteration i in 1..N, for each arm in (wf, co, ms):
1. Fresh target dir at `$HOME/tmp/bench/targets/<arm>-<i>`
2. `git init` + `git commit -m init`
3. Run the arm:
   - **wf**: `orgos run --waterfall --repo <target> --team-id <label>
     --spec-file docs/specs/minisearch.md --model deepseek/deepseek-chat
     --n-workers 1 --sprint-story-cap 28 --sprint-duration 2700 --fresh`
   - **co**: parse spec via `orgos.agile.spec_parser.parse_spec_text`,
     for each story call `copilot -p "$FLAT_PROMPT" --allow-all-tools
     --allow-all-paths --add-dir <target>`. See §7 for the argv gotcha —
     it applies to PS5 only, bash handles multiline args fine.
   - **ms**: `orgos start --repo <target> --team-id <label> --spec-file
     docs/specs/minisearch.md --executor spawn --model deepseek/deepseek-chat
     --architects 3 --testers 2 --devsecops 1 --timeout-seconds 2700
     --sprint-duration-seconds 300 --fresh`
4. Score: `python scripts/score_reftests.py --target <delivery-branch-path>
   --label <arm>-<i> --out ~/tmp/bench/scores/<label>.json`

The delivery-branch path per arm:
- **wf**: `<target>/.orgos_teams/<label>/integration`
- **co**: `<target>` (Copilot commits straight to master)
- **ms**: `<target>/.orgos_teams/<label>/integration`

**Option B — install PowerShell 7 on Mac and run the existing scripts.**
```bash
brew install powershell
pwsh ./bench/run_n3.ps1
```
Then patch:
- `.\\.venv\\Scripts\\orgos.exe` → `./.venv/bin/orgos` in the three arm
  scripts
- `.\\.venv\\Scripts\\python.exe` → `./.venv/bin/python` in `run_n3.ps1`
  and `copilot_arm.ps1`
- Target root `C:\temp\bench` → `$HOME/tmp/bench` throughout
- The `Set-Location` calls will just work
- Backslashes in string arguments generally survive because `orgos` never
  parses them as path separators when they're passed via argv

Option A (bash port) will be cleaner. Option B (pwsh 7) is faster to get
running for a first test.

## 7. Load-bearing quirks — do not "improve" these

1. **Solo Copilot arm on Windows required prompt flattening.** PowerShell 5
   splits multiline strings passed as EXE argv into multiple words → copilot
   sees `error: Invalid command format`. See `bench/copilot_arm.ps1` — it
   flattens `\r\n` → ` | ` and swaps `"` for `'`. **On Mac/bash this is not
   needed** — bash quoting handles multiline fine. But do the flatten anyway
   if using pwsh 7 to keep behavior identical to Windows numbers.

2. **Waterfall has huge variance.** Pilot run scored 33.6%, next run scored
   12.7%. Same spec, same budget. This isn't a bug — it's the topology.
   Report **ranges**, not just means, until n≥5. The n=1 pilot said
   "waterfall does 1 story" (which was a floor) — that was misleading.

3. **Scrum's spec-drift IS the finding.** Do not try to fix it by tweaking
   the persona prompts, wiki, or PO. The 15.9% pass rate at n=2 is what
   makes the presentation. If you make it disappear by hacking the prompts,
   you lose the story. Only reference-suite-passing fix is the proposed
   spec-conformance gate (see roadmap in slide 7 of the deck) — but that's
   a multi-week build, not a same-session change.

4. **Copilot arm on `wf-2` and beyond in the Windows batch was still
   running when this handoff was written.** The Windows box's batch is
   detached (`Start-Process -WindowStyle Hidden`, PID 30512, log at
   `C:\temp\bench\batch-20260804-083119.log`). If it completes before the
   Mac batch, we'll have n=3 Windows data by ~1 PM today. Mac numbers
   should be scored the same way and merged.

5. **The scorer's `-q` flag was removed.** Pytest with `-q` suppresses the
   summary line when there are many failures + collection errors, which
   silently returns 0/0 counts. `scripts/score_reftests.py` runs without
   `-q` — do not add it back.

6. **`test_e2e.py::test_full_index_search_delete_via_api`** in the reftests
   uses FastAPI TestClient with lifespan events. On some builds this fails
   spuriously on the first run and passes on retry. If you see one flaky
   fail here across runs, it's the test not the arm.

## 8. What to bring back

Only two things:

```
~/tmp/bench/scores/*.json           # ~9-30 files depending on N
~/tmp/bench/scores/_summary.json    # aggregated summary
```

Optional (only if the reference tests get revised and we want to re-score
old runs):
```
~/tmp/bench/targets/**/.orgos_teams/**/integration/   # delivery branches
```

To zip: `cd ~/tmp/bench && tar czf scores.tgz scores/`. Drop the tarball
anywhere — the next Windows session can rebuild slide 5 from the JSONs
alone. Total size should be < 1 MB.

## 9. Interpreting the JSON

Each score file looks like:
```json
{
  "label": "wf-3",
  "target": "/path/to/target",
  "install_ok": true,
  "pytest_exit_code": 1,
  "counts": {
    "passed": 14, "failed": 41, "errors": 17, "skipped": 1,
    "total": 73, "pct_pass": 19.2
  },
  "wall_seconds": 48.9
}
```

- `counts.passed / 110` is the **reference-suite pass rate**. Prefer this
  over `pct_pass` (which divides by `passed+failed+errors+skipped` and
  can hide missing modules).
- `counts.errors` = tests that couldn't be *collected* because a module
  wasn't built or the import name didn't match the spec. This is the
  spec-drift signal.
- `install_ok=false` means `pip install -e .` failed — the arm didn't
  produce a valid Python package. All tests then count as failures.

## 10. The presentation deck

`docs/adam-demo-deck.html` — 9-slide reveal.js deck. Slide 5 has the
n=2 table. When new numbers land, update:

- Slide 5's `<tbody>` — add columns for run 3, 4, 5, and update mean/range
- Slide 2's blockquote if the top-line ordering changes (unlikely — the
  ordering is very stable, only magnitudes will tighten)

Slide 6 ("What the drift looks like") shows literal code from the scrum
arm's `filters.py`. If new scrum runs produce different drift patterns,
consider swapping the example. Otherwise leave it — the pattern is
representative.

## 11. Trust but verify — read this if numbers look weird

If any arm scores dramatically differently from n=2:

- **Reftest bug**: the reference tests are fallible. Run
  `pytest docs/specs/minisearch_reftests/ --collect-only` in a target
  repo to see collection errors; a genuine drift bug will manifest as
  ImportError on module init.
- **Model change**: if `deepseek/deepseek-chat` was silently upgraded on
  the API side, everything's off. Check `.env` and current pricing at
  the API vendor.
- **Copilot CLI version**: the shim checks minimum version 0.0.394. If
  Copilot updates and requires interactive confirmation, non-interactive
  runs will fail silently.

Sanity check anytime with:
```
python scripts/score_reftests.py --target docs/specs/minisearch_reftests/dummy-passing
```
(no such target exists yet; if you need a smoke test, hand-code a tiny
minisearch stub in a scratch dir and score against that — should show
tokenizer tests passing, everything else erroring.)

## 12. If the Adam meeting happens before Mac runs finish

Present what we have. The n=2 numbers are already defensible with the
"pilot-tier, formal n=5 in progress" caveat. Slide 5 already says n=2 and
explains the direction is stable. The core narrative — **spec drift is
the coordination-vs-context problem** — does not depend on n=10 numbers.

The Mac numbers upgrade the deck from "here's what we saw" to "here's
what we can back with variance data." Both are valid; the second is just
harder to attack.

---

**Sanity check on receipt of this file:**
- `git log --oneline -8` should show the 7 commits listed in §4
- `ls docs/specs/minisearch_reftests/*.py | wc -l` should be 12
- `python -c "import orgos; print(orgos.__file__)"` should succeed
- `orgos --help` should list `start`, `run`, `stop`, `status`, `logs`,
  `report`, `ls`, `reset`, `serve`, `verify`, `ship`, `deliver`

If any of these fail, you're on the wrong branch or the venv isn't
activated.

— end handoff —
