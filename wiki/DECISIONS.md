# Decisions

Chronological decision log for the orgos project.

---

## 2026-07-13: Pull-based sprint model adopted

**Decision:** The pull-based self-organizing model is the primary sprint mode. Agents self-assign from READY queue. No orchestrator delegates. PO prioritizes only.

**Rationale:** 6x cheaper per sprint than hierarchical. 100% completion rate vs 0% for hierarchical at similar budget. Validated across multiple experiments.

**Source:** Experiment comparison data.

## 2026-07-13: Anti-waterfall anchors added to persona files

**Decision:** Every persona file now includes immutable anti-waterfall rules at the top. Agents may not add assignment gates, approval steps, or permission checks.

**Rationale:** LLMs default to waterfall. Infrastructure must enforce Scrum, not rely on agent behavior.

**Source:** WI #300-derived analysis.

## 2026-07-13: Flow metric formula confirmed as working reconstruction

**Decision:** The takt-time/velocity-delta aggregation (40/30/30 weights) is used as a working metric. External confirmation pending.

**Rationale:** Produces stable scores across diverse tasks (0.65 for simple coding sprints). Sufficient for relative comparison.

**Source:** Experimental data.
