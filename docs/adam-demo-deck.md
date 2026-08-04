# orgos — Agent Scrum Team Platform
### Progress update · internship demo

Presenter: Thanh-Huy Nguyen
Audience: Adam (+ Emma for funding path)
Deck length target: ~20 min + Q&A

---

## Slide 1 — Hook

> **LLMs, when asked to "build an agentic dev team," produce waterfall.**
> Waterfall on real specs collapses. Scrum ships 24× more, at 4× lower $/story.
> Numbers below are from real DeepSeek runs on a 28-story spec, this week, on my machine.

**Speaker note:** open with the finding, not the architecture. Adam is engineering-literate; he wants the empirical result first.

---

## Slide 2 — What orgos is

Two topologies, same runtime, same target repo, same LLM.

- **Scrum (`orgos start`)** — flat set of specialist agents (Architect, Test, DevSecOps, PO, Scrum Master) each in their own git worktree, pulling stories off a shared board, merging through a FIFO queue with rebase-before-merge.
- **Waterfall (`orgos run --waterfall`)** — the intuitive PO → Architect → Test → DevSecOps pipeline, one story at a time. This is what an LLM writes when you ask it for "an agentic team." Ships as the baseline to beat.

Both use the same executor (spawn+CrewAI+LiteLLM), same personas, same target repo. **The variable is topology.**

---

## Slide 3 — How I measured

| | value |
|---|---|
| Spec | `docs/specs/minisearch.md` — 28-story text search engine (tokenizer, BM25, inverted index, FastAPI, CLI) |
| Target repo | fresh empty git repo per run |
| Model | `deepseek/deepseek-chat` (chosen for cost; ~$0.27/M in, $1.10/M out) |
| Wall budget | 45 min (waterfall); 75 min (scrum: 45 initial + 30 resume) |
| Scrum team | 3 architects + 2 testers + 1 devsecops + PO + SM |
| Waterfall workers | sequential (1 story at a time through 3 roles) |
| Hardware | my laptop |

---

## Slide 4 — Headline numbers

| Metric | Waterfall (`wf1`) | Scrum (`ms1`) |
|---|---:|---:|
| Stories drafted | 10 | 28 |
| **Stories done** | **1** | **24** |
| Stories blocked | 9 | 3 |
| Commits landed | 3 | 30 |
| Tests passing | 0 | **256 / 264** |
| Tokens (in / out) | 2.1M / 56k | 12.4M / 223k |
| **Est. cost (USD)** | **$0.64** | **$3.60** |
| **$/done-story** | **$0.63** | **$0.15** |
| Mean SPE | n/a (no sprints) | 0.121 |

**Delivered artifact from scrum run:** 10-package Python codebase, ~2k LOC, FastAPI app + Typer CLI + BM25 engine + 264 pytest tests, on branch `team/ms1/integration`. Built for **$3.54.**

**Speaker note:** the second-order number Adam will ask about is **stories/dollar**. Lead with `$0.15 vs $0.63` — same LLM, same spec.

---

## Slide 5 — Why scrum wins structurally

1. **Parallel specialization.** 5 agents pulling from one board. An idle tester grabs a test story while an architect is on code. Waterfall's 3 roles are serial per story.
2. **Mid-run replan.** Scrum's PO reads the retro after each sprint, drafts fixup stories, adapts velocity. Waterfall drafts once and dies.
3. **Board self-organization.** No central scheduler — agents pull work. Scales linearly with team size.
4. **Merge queue with rebase-before-merge.** Two architects can commit concurrently and the queue serializes into integration cleanly.
5. **Shared wiki (`wiki/DECISIONS.md`)** — every agent reads prior architectural decisions, so story N doesn't re-invent story 1's choices.

None of these can be added to waterfall without turning it into scrum.

---

## Slide 6 — Honest caveat: is my waterfall unfairly weak?

Fair question. I audited [orgos/agile/waterfall_runner.py](../orgos/agile/waterfall_runner.py). Real biases I found:

| Bias | Fix status |
|---|---|
| Waterfall didn't pass `--spec-file` to PO → only decomposed 10 of 28 stories | **Fixed** in patch |
| No retry on architect `no_commit` | **Fixed** — 1 retry with feedback |
| Wiki/MCP tools zeroed out for arch/test/sec | **Fixed** — restored |
| Test/DevSecOps envelopes are informational, not gating (this actually *favors* waterfall — bad code doesn't get rejected) | left as-is |
| Waterfall is single-sprint (no PO replan) | left — that's definitional |

Rerunning waterfall now with the fair-baseline patches (`wf2`). Expectation: waterfall closes ~4–6 done stories (not 1), $/story drops to ~$0.20 (not $0.63). **The parallelism gap remains** — it's structural, not implementation.

**Speaker note:** own this slide first. Adam or Emma will ask "did you compare apples to apples?" — having the answer prepared with a rerun is the credible move.

---

## Slide 7 — What's built today

- Two topology runners, both wired to the same executor + persona set
- Board store (JSON on disk, atomic writes, git worktree per agent)
- Merge queue with rebase-before-merge + `rerere` for conflict memory
- PO/Scrum Master adaptation loop (velocity + sprint duration retune per retro)
- AC gate + acceptance ceremony (PO signs off before `done`)
- Spec parser (`## Story:` blocks → prewritten backlog, deterministic)
- Live event stream + report HTML per team
- **SPE benchmark now wired into the comparison HTML** (per-sprint + mean, banded)
- ~475 pytest tests covering the runtime (I patched one Windows-only atomic-write race this week)

---

## Slide 8 — The 2-week goal: self-maintaining scrum team

Adam's ask: by end of internship, the scrum team maintains and deploys its own output.

**Concrete deliverables:**

1. **Post-merge CI hook** — every integration merge triggers `pytest` in the worktree. If a story breaks earlier tests, the team auto-drafts a fixup story next sprint. (Building on the merge queue.)
2. **Deploy story type** — new story type `deploy` picked up by a specialised agent. First target: `docker build` + `docker run` on the integration branch, exposing the FastAPI app on a port.
3. **Bug intake** — a REST endpoint on the team's own report server accepts bug reports; PO drafts them as `bugfix` stories automatically.
4. **Multi-day run** — the team keeps running across days on the same team-id, drafting maintenance stories from CI failures.

None of these require new topology work — they extend the board taxonomy and the DevSecOps role.

---

## Slide 9 — The infra question (echo of Teams thread)

**Why this is on the table:** every number on Slide 4 is bought with a DeepSeek API key + laptop. That's the cheapest path *right now*, but not the strategic path for Accenture.

Three routes:

| Route | Cost | Latency | Data | Notes |
|---|---|---|---|---|
| **Cloud API (current)** | ~$3.50 per 28-story build @ DeepSeek. GPT-4o-mini ~$0.15/M in ≈ $2–4/build. Sonnet-4.5 ≈ 10× that. | Fast | Leaves company | Fine for demo; not for client code |
| **Bedrock** (needs client sponsor) | Client-billed | Fast | Stays in-tenant | Adam's preferred long-run; deadend without a client cost centre |
| **Local SLM** (Qwen3.6, quantized) | Hardware only | ~10× slower per sprint | On-prem | Mac M-series Pro/Max/Ultra, ≥48GB unified RAM (128GB for cloud-parity speed), or 2×24GB GPU PC + 128GB RAM. ~5% quality gap vs Sonnet. Model drift risk. |

**Ask:**
- Copilot or Claude Code license for me → cuts my orchestration coding time significantly
- Emma's help identifying a client-funded Bedrock pilot so scrum runs land against paid AWS credits
- If neither: I run local SLM on my personal M-series (48GB) for internal-only benchmarking, no data leaves

---

## Slide 10 — Answers to likely questions

**Q: How do you know it wasn't just DeepSeek being smart?**
A: Same model, same executor, both sides. Only variable is topology. Waterfall got 1 done, scrum got 24. Model quality applies equally to both.

**Q: Why is scrum's SPE only 0.121 (Needs Improvement)?**
A: PO over-committed early sprints. The adaptation loop then dropped `velocity_target` 8 → 6 → 5 → 4 → 3. Sprint 4 hit 0.440 ("Good"), so the loop works — it just took 3 sprints of over-commitment to calibrate. Next iteration: seed initial velocity from spec-file story-point sum, not the default of 8.

**Q: What breaks in the delivered code?**
A: 5 test failures + 19 errors, all in `tests/store/test_documents.py` — a `DocumentStore` API mismatch between what the architect implemented and what the tester wrote. Classic parallel-agent integration seam. This is exactly the kind of bug the CI-hook in Slide 8 would auto-drift into a fixup story.

**Q: What's the token cost split?**
A: 87% of scrum's tokens are *input* (context) not output. That means CrewAI/persona prompts + wiki + prior commits. Cache-friendly. If I turned on DeepSeek's prompt cache, cost drops another ~50%.

**Q: How many stories per hour on scrum?**
A: 24 stories in 75 min ≈ 19 stories/hour with 5 workers. Waterfall: 1 story per ~45 min ≈ 1.3/hour. **~15× throughput.**

**Q: Does this scale to a bigger team (20 agents)?**
A: Board reads/writes are file-based and O(N stories). Bottleneck is the merge queue (serial). Empirical work needed at 8+ agents. That's a candidate for the last two weeks if maintenance isn't the priority.

**Q: What's the failure mode I'm most worried about?**
A: Story-decomposition quality. When PO drafts vague stories, everything downstream is noise. The `spec_parser` path (deterministic story blocks) sidesteps this — that's what the 28-story minisearch run used.

---

## Slide 11 — Next-2-weeks plan

| Week | Deliverable |
|---|---|
| 1 | CI hook + bug intake + `deploy` story type |
| 1 → 2 | 24-hour continuous run on a target repo — team maintains + patches its own output |
| 2 | Comparison HTML regenerated with fair-baseline waterfall (`wf2`+) so the numbers survive scrutiny |
| 2 | Final demo: a real spec goes in → deployed FastAPI service comes out → intentionally-injected bug → team patches → CI green |

---

## Slide 12 — Artifacts to show live

- [docs/comparison-minisearch.html](comparison-minisearch.html) — the 17.4 KB self-contained HTML with the head-to-head, SPE table, per-story tables, cost estimate
- `C:\temp\minisearch-target\.orgos_teams\ms1\report.html` — the scrum team's per-sprint report
- Live: `orgos start --executor mock --team-id demo` — 60-second smoke that shows the board, worktrees, merges live (no LLM cost, works in front of any audience)
- Repo tour: [orgos/agile/waterfall_runner.py](../orgos/agile/waterfall_runner.py) side-by-side with [orgos/agile/agent_loop.py](../orgos/agile/agent_loop.py) to show the topology difference in ~200 LOC

---

## Appendix A — Cost math, receipts

```
DeepSeek chat (Nov 2025 rates): input $0.27/M, output $1.10/M

wf1 (waterfall):
    2,129,038 in  × 0.27 / 1e6  = $0.575
       55,779 out × 1.10 / 1e6  = $0.061
    total = $0.636

ms1 (scrum, both runs combined):
   12,413,210 in  × 0.27 / 1e6  = $3.352
      223,443 out × 1.10 / 1e6  = $0.246
    total = $3.598

$/done-story:
    waterfall: 0.636 / 1  = $0.636
    scrum:     3.598 / 24 = $0.150     (4.2× cheaper)
```

## Appendix B — Repo pointer

- Runtime & personas: `orgos/agile/`
- Governance engine (vendored): `orgos/spawn/`
- Comparison generator: [scripts/build_comparison_html.py](../scripts/build_comparison_html.py)
- SPE math: [orgos/agile/spe.py](../orgos/agile/spe.py)
- Spec that produced Slide-4 numbers: [docs/specs/minisearch.md](specs/minisearch.md)
