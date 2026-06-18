# orgos

A company of agents on **CrewAI** — model-agnostic, multi-provider LLM support.

This repo is **Phase 0**: the spawn library — the primitive everything else composes from.
Read [`DESIGN.md`](./DESIGN.md) first; it holds the settled decisions.

## Install

```bash
pip install crewai pydantic          # Python 3.10+

# Set your LLM provider key (any of these work):
export OPENAI_API_KEY=sk-...         # OpenAI
export ANTHROPIC_API_KEY=sk-ant-...  # Anthropic
export GEMINI_API_KEY=...            # Google
export AZURE_OPENAI_API_KEY=...      # Azure
```

CrewAI uses litellm under the hood for most providers. For Anthropic native support:
`pip install crewai[anthropic]`. See [CrewAI LLM docs](https://docs.crewai.com/how-to/LLM-Connections/).

## Run it

```bash
# The full suite (offline, no API keys needed):
python -m pytest -q

# The REST API + dashboard backend (reads config/org.yaml):
python -m uvicorn orgos.api:app --host 0.0.0.0 --port 8420
```

The org constitution lives in `config/org.yaml`; the compliance policy bank in
`config/policy-bank.yaml`.

## The primitive

```python
from orgos import RoleSpec, TaskBrief, PermissionTier, spawn

role = RoleSpec(
    name="researcher",
    description="Use this role to research a topic and write a brief.",
    tier=PermissionTier.WORKER,
    system_prompt="You are a careful research assistant.",
    model="gpt-4o",
    max_iter=15,
)
result = spawn(role, TaskBrief(objective="Summarise X into a one-page brief"))
print(result.envelope.status, result.envelope.summary)
```

### Sequential chain

```python
from orgos import spawn_chain

result = spawn_chain([
    (scanner_role, scan_brief),
    (validator_role, validate_brief),
])
# Each step's output feeds into the next via CrewAI task context.
```

`spawn()` gives you, for free on every run:

- a role-scoped system prompt + a **structured brief** (no free-form delegation)
- **tier-enforced guardrails** — `worker` / `validator` / `publisher` / `orchestrator`
  (capability separated from authority)
- an append-only **audit log** (`_audit_logs/<run_id>.jsonl`) of every agent step
- a deterministic **human gate** on publish-class actions (via CrewAI's `human_input`)
- hard **iteration + execution time caps**
- a **validated `HandoffEnvelope`** out — bad output becomes a `failed` envelope, never
  silent garbage

## How the pieces map to the design

| Decision (DESIGN.md) | Where it lives |
|---|---|
| Two-tier supervisor | `spawn()` with `subordinates=` or `spawn_chain()` |
| Strict envelope, free payload | `HandoffEnvelope` in `contracts.py` |
| Capability vs authority | `PermissionTier` + `TIER_POLICY` in `contracts.py` |
| Human gate in code, not judgement | `human_input=True` on publish Tasks + `cli_approval` in `audit.py` |
| Observability | `make_audit_callback` in `audit.py` → `_audit_logs/` |
| Cost discipline | `max_iter` / `max_execution_time` on every `RoleSpec` |

## Building with AI coding agents

Point your coding agent at this repo and reference `DESIGN.md`. Good next tasks:
write a `cointegration` CrewAI tool, add real publish-tool names to the `publisher`
tier's `requires_approval`, and build the Phase 1 orchestrator that runs the
quant-maintenance job end-to-end.
