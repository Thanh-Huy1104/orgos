# orgos — demo runbook

**The pitch (say this first):**
> "Anyone can wire up an LLM agent. The hard part — what enterprises actually need —
> is agents that are **reliable, governed, and auditable**: they can't exceed their
> permissions, every action is logged, outputs are **graded, not trusted**, and a
> human approves anything consequential. orgos is a working reference implementation
> of exactly that. Let me show you."

This is a **governance + reliability** story, not an "AI that predicts markets" story.
The quant desk is just the worked example that proves the framework.

---

## Pre-demo checklist (do this 10 min before)

```bash
cd /home/th/orgos
git checkout demo                      # the demo branch
python demo/seed_journal.py            # populate the Journal with real hunts
```

**Launch — pick ONE:**

*A) systemd (least typing, needs sudo):* the units run from this repo dir, so they
pick up the demo branch automatically.
```bash
sudo systemctl restart orgos-api orgos-dashboard
# open the dashboard URL (LAN/Tailscale/localhost:3000)
```

*B) fully local (max control, no surprises):*
```bash
sudo systemctl stop orgos-api orgos-dashboard      # free the ports (optional)
python -m uvicorn orgos.api:app --host 0.0.0.0 --port 8420   # terminal 1
cd dashboard && npm run dev                                   # terminal 2 -> :3000
```

**Smoke test before they're watching:**
```bash
curl -s localhost:8420/api/quant/journal | python3 -c "import sys,json;print(len(json.load(sys.stdin)['entries']),'journal entries')"
# expect: 6 journal entries
```

---

## The demo flow (~12 min)

### Act 1 — The org & the governance model  *(Org page, ~3 min)*
- Open **Org**: a "company of agents" — departments (research, quant, compliance),
  each role tagged with a **permission tier**: `worker / validator / publisher / orchestrator`.
- **Point:** *capability is separated from authority.* A worker can produce output but
  **cannot publish or act externally** — that needs a validator, then a **human gate
  enforced in code, not in the model's judgment.** Show `orgos/spawn/contracts.py`
  (the tiers) and `GatedToolBase` if the audience is technical.

### Act 2 — It shows its work  *(Logs page, ~3 min)*
- Open **Logs**: every run leaves a **tool-by-tool research trail** — exactly what each
  agent read, searched, and computed, with **inputs and outputs**. Expand one run.
- **Point:** full observability, append-only. For regulated or high-stakes work,
  *"the agent said so"* isn't acceptable — here you can **audit every step.**

### Act 3 — Outputs are graded, not trusted  *(Journal page, ~4 min — the money shot)*
- Open **Journal**: real research the desk produced. Each hunt shows status, a **rubric
  "strength" score**, **attempts**, the findings, and the approach/sources.
- Show a **success** (the cross-sector hunt → AEE/NI, strength 0.9998) **and an honest
  failure** (US regional banks → `needs_revision`, *0 durable pairs*).
- **Point — the differentiator:** the system **grades its own output against a rubric
  and fails closed.** It told us *"this doesn't work"* instead of fabricating a
  confident answer. Note the **2 attempts** — it re-aimed when the first failed. *This*
  is reliability: it won't hand a stakeholder confident garbage.
- Click **"approach & sources"** → the real trail loads from the audit log.

### Act 4 — The architecture  *(for technical buyers, ~2 min)*
- **Spawn library:** `RoleSpec` + `TaskBrief` → a configured agent under tiers, token/
  loop budgets, approval gates, and an audit callback (`orgos/spawn/`).
- **Rubric loop:** run → grade → re-aim → **fail closed** (`spawn/rubric.py`); the same
  primitive that graded the hunts.
- **Evolve:** the org analyses its own performance and **proposes changes to its own
  structure — you approve every commit** (`orgos/evolve.py`, `/proposals`).
- "It's CrewAI under the hood — the value-add is the **governance layer**: tiers, gates,
  audit, rubric self-test, human-in-the-loop. The things that make agents safe to ship."

### Close
> "This is the pattern I bring to client work: agents that are **auditable, gated,
> graded, and human-approved** — reliable enough to put in front of real stakeholders."

---

## Risk control — what NOT to do live
- **Do not run a live Strategist hunt during the demo** — it takes 3–7 minutes, needs
  the LLM, and can fail. The seeded **Journal is your safe showcase.** If you want a
  "live" moment, kick a hunt off *at the very start* (it runs in the background and
  lands in the Journal) and reveal it at the end as a bonus — but never block on it.
- **The Desk page needs the live Icarus engine.** If it shows "engine offline," skip it
  or frame it: *"this bridges to a live trading engine, offline for this demo."*
- Re-run `python demo/seed_journal.py` if the Journal ever looks empty.

## One-line capability summary (for your own notes)
permission tiers · gated tools w/ human approval · append-only audit + research trail ·
rubric-graded, fail-closed outputs · self-improvement proposals (human-approved) ·
deterministic domain tools + out-of-sample backtests · live dashboard.
