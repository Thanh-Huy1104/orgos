# orgos — a company of agents

A general-purpose orchestrator + departments of subagents, built on **CrewAI**.
This document is the north star: the decisions are settled here so the build has one source
of truth. Reference it from `CLAUDE.md` so AI coding agents build to spec rather than improvising.

---

## 1. Vision

One owner (you) runs a small "company" of AI agents organised into departments
(finance, marketing, logistics, legal, admin, …). A dynamic orchestrator decomposes a
goal, routes it to the right department(s), spawns role-scoped agents, and collects
results. Every consequential action passes a validator and, if it touches the outside
world, your recorded approval. The system is observable end-to-end and can propose changes
to its own structure — but only you commit them.

Guiding formula, borrowed and generalised from MetaGPT: **Org = SOP(Agents)**. Quality
comes from well-defined standard operating procedures executed by specialised roles, not
from any single clever agent.

## 2. Settled architectural decisions

These are decided. Don't relitigate them mid-build without a written reason.

**Topology: two-tier supervisor, not swarm.**
Orchestrator → department supervisors → fan-out workers. A peer/swarm topology is rejected
at the org level because it has no single trace and is not auditable — disqualifying for a
system with a finance core and a legal department. Bounded peer loops (sequential CrewAI
chains via `spawn_chain`) are allowed *inside* one department for a single deliverable that
needs tight critique cycles (e.g. implement → review → test), always behind an exit gate.

**Handoff contract: strict envelope, free payload.**
Every department-to-department handoff is a typed `HandoffEnvelope` (status, summary,
artifacts, `success_criteria_met`, `requires_human_approval`, payload). The envelope is
validated at every boundary; invalid output is a failed handoff, not silent garbage. The
`payload` field is free-form so agents keep their expressiveness. CrewAI's `output_pydantic`
on Tasks enforces this schema at the LLM level.

**Capability is separated from authority.**
Agents may generate imperfect output but cannot publish it. Four permission tiers:

| Tier | Can do | Cannot do |
|------|--------|-----------|
| `worker` | compute, call tools, produce artifacts | publish externally, approve own work |
| `validator` | deterministic read-only checks | modify artifacts, run side effects |
| `publisher` | the only tier that touches the outside world | act without recorded human approval |
| `orchestrator` | spawn/route subagents via hierarchical Crew | publish, hold broad compute |

The human gate lives in **our code**, enforced deterministically before a publish tool is
ever made available — never in a model's judgement. Tools that require approval inherit
from `GatedToolBase`; their `_check_gate()` fires *before* execution. Denied = the tool
returns a `DENIED:` string. This is the kill-switch principle, generalised.

**Workflow controls the agents, not the reverse.**
Structured briefs (`TaskBrief`), schema gates (`HandoffEnvelope` via `output_pydantic`),
iteration caps (`max_iter`), and execution-time caps (`max_execution_time`) are the
guardrails. A free-form delegation is a known failure mode.

**Tools are the agents' hands.**
CrewAI agents reason via LLM calls. To interact with the world they use tools — custom
Python functions wrapped with `@tool` or subclasses of `BaseTool`. Gate-requiring tools
(`GatedToolBase`) carry an `approval_fn` that is wired by `spawn()` at runtime. Tools
define their input schema via Pydantic models (`args_schema`); the LLM reads the tool's
`description` and constructs valid calls against the schema.

## 3. Auth & model support (decided early because they ripple)

- **Model-agnostic.** CrewAI uses litellm under the hood. Set any provider's key:
  `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `AZURE_OPENAI_API_KEY`, or
  use local models via Ollama (`model="ollama/llama3"`). See the
  [CrewAI LLM docs](https://docs.crewai.com/how-to/LLM-Connections/) for all providers.
- **Cost: metered per API call.** Every agent carries a `max_iter` cap and an optional
  `max_execution_time` limit. Multi-agent runs multiply cost — use a single agent unless
  specialisation, parallelism, or critique genuinely earns the multi-agent cost.
- **CrewAI Telemetry.** CrewAI collects anonymous usage data by default. Set
  `OTEL_SDK_DISABLED=true` to disable. No prompts or agent outputs are collected unless
  `share_crew=True` is explicitly set.

## 4. Primary requirement domains

1. **Org model ("constitution")** — version-controlled declarative `RoleSpec`s + department
   definitions + SOPs + decision rights. The orchestrator and spawn library compile from it.
2. **Spawn library** — the factory that turns a `RoleSpec` + `TaskBrief` into a configured
   CrewAI Crew and returns a validated `HandoffEnvelope`. **(This phase's focus.)**
3. **Tool system** — `GatedToolBase` for approval-gated actions, `@tool` decorator for
   stateless tools, `args_schema` Pydantic models for typed tool inputs.
4. **Orchestration engine** — `spawn()` (hierarchical) and `spawn_chain()` (sequential)
   compose CrewAI Crews. Routes goals to departments; runs the shared blackboard.
5. **Governance / HITL** — `GatedToolBase.approval_fn` is the programmatic kill-switch.
   `cli_approval()` provides terminal prompts; the interface is pluggable for Slack/email.
6. **Scheduler** — the "production calendar": recurring jobs and event triggers.
7. **Observability** — `make_audit_callback()` logs every agent step to `_audit_logs/<run_id>.jsonl`
   via CrewAI's `step_callback`. Append-only, machine-readable.
8. **Owner interface** — notifications + a decision inbox (approve / reject / redirect).
9. **Infra / safety** — Proxmox host, per-agent sandboxing, secrets, global kill-switch.

## 5. Build roadmap (crawl → walk → run)

- **Phase 0 (now): foundations.** `RoleSpec` + `HandoffEnvelope` contracts, the spawn
  library, `GatedToolBase` + `BashTool`, the audit callback. Prove it on a single worker
  in a single department.
- **Phase 1: one real job end-to-end.** Orchestrator + human-approval gate doing one task —
  maintaining the quant model, since that domain is already understood and gradeable.
- **Phase 2: multi-department.** Second/third department, shared blackboard, scheduler, the
  legal/compliance validator with veto power.
- **Phase 3: evolutive + deployed.** The org proposes changes to its own constitution (you
  approve every commit); Proxmox deployment with per-agent sandboxing.

Each phase ships something you actually run. Never debug a cathedral.

## 6. Where the spawn library fits

The spawn library is the keystone primitive everything else composes from. The orchestrator
is just a `RoleSpec` of tier `orchestrator` whose subordinates are other `RoleSpec`s; a
department is a supervisor `RoleSpec` plus worker/validator/publisher `RoleSpec`s. Build the
primitive correctly and the org is configuration on top of it.

Two orchestration patterns:
- **`spawn(role, brief, subordinates=[...])`** — hierarchical Crew. The orchestrator agent
  becomes the CrewAI manager; subordinates are the worker pool it delegates to.
- **`spawn_chain([(role1, brief1), (role2, brief2)])`** — sequential Crew. Each agent's
  output feeds into the next via task `context` chaining. Good for implement → review → test.

### File map

| Concern | File |
|---------|------|
| Typed contracts (RoleSpec, TaskBrief, HandoffEnvelope, tiers) | `contracts.py` |
| Spawn factory (spawn, spawn_chain, SpawnResult) | `spawn.py` |
| Tools (GatedToolBase, BashTool) | `tools.py` |
| Audit + human gate (make_audit_callback, cli_approval) | `audit.py` |
| Concrete example (quant pair scanning) | `examples/quant_pair_scanner.py` |
