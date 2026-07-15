"""Linked benchmark corpus — tests the compounding-memory thesis.

Unlike issue_generator.py (independent issues), these 10 issues BUILD ON
EACH OTHER. Later issues reference conventions established (and recorded
in wiki/DECISIONS.md) by earlier issues.

The thesis:
  - Team's architect reads wiki/DECISIONS.md via MCP → knows prior conventions
  - Solo has NO wiki access (no MCP, worktree's wiki is frozen at baseline)
    → cannot see prior conventions, must guess

Expected outcome:
  - L1-L3: both sides pass. Team establishes conventions.
  - L4 onwards: team follows recorded conventions (tests pass). Solo drifts:
    picks wrong name style, wrong return type, wrong error policy → tests fail.
  - Team's rolling avg quality stays high; solo's drops over the sequence.

This is the "offshore team knows the codebase" thesis:
  Every solo spawn = fresh contractor. Team = colleagues since sprint 1.

Corpus target: a small metrics_v2 sub-package built up across 10 sprints.
"""

from __future__ import annotations

from orgos.agile.issue_generator import BenchmarkIssue


_ISSUES: list[BenchmarkIssue] = [
    # ── L1: establish base + THREE conventions in DECISIONS.md ──────────────
    BenchmarkIssue(
        issue_id="L10-01-metrics-base",
        title="Establish metrics_v2 base + record 3 conventions",
        difficulty="medium",
        template="establish_conventions",
        body=(
            "Create the base for a new metrics sub-package.\n\n"
            "1. Create orgos/agile/metrics_v2/__init__.py (empty is fine, or "
            "   re-export Metric).\n"
            "2. Create orgos/agile/metrics_v2/base.py with:\n\n"
            "     from __future__ import annotations\n"
            "     from dataclasses import dataclass\n\n"
            "     @dataclass(frozen=True)\n"
            "     class Metric:\n"
            "         name: str\n"
            "         value: float\n"
            "         unit: str\n\n"
            "3. Create tests/agile/test_metrics_v2_base.py with 2 tests:\n"
            "   - test_metric_construction: builds Metric('mean_takt', 3.5, 's')\n"
            "   - test_metric_is_frozen: assert dataclasses.fields(Metric) length 3\n"
            "     AND that mutating raises (pytest.raises(dataclasses.FrozenInstanceError))\n\n"
            "4. IMPORTANT — RECORD CONVENTIONS. Use wiki_write (mode='append') "
            "   to append the following EXACT block to DECISIONS.md:\n\n"
            "     ## metrics_v2 conventions (established sprint L10-01)\n"
            "     - Metric dataclass fields, in order: (name, value, unit). "
            "frozen=True.\n"
            "     - Metric.name style: snake_case only (e.g. 'mean_takt', "
            "not 'MeanTakt' or 'mean-takt').\n"
            "     - Invalid-input policy for metric functions: RETURN None, "
            "do NOT raise. This applies to every metrics_v2/*.py function.\n"
            "     - Every new metric function goes in its own module under "
            "orgos/agile/metrics_v2/.\n\n"
            "Verify: pytest tests/agile/test_metrics_v2_base.py -v (2/2)."
        ),
    ),

    # ── L2: first metric using the conventions ──────────────────────────────
    BenchmarkIssue(
        issue_id="L10-02-mean-takt",
        title="Add mean_takt metric following metrics_v2 conventions",
        difficulty="medium",
        template="apply_convention",
        body=(
            "Add a mean_takt metric to the metrics_v2 sub-package.\n\n"
            "Follow the metrics_v2 conventions established in prior sprints and "
            "documented in wiki/DECISIONS.md. Read that section BEFORE writing.\n\n"
            "1. Create orgos/agile/metrics_v2/mean_takt.py exposing:\n"
            "     def mean_takt(takts: list[float]) -> Metric | None:\n"
            "   which returns a Metric containing the arithmetic mean.\n\n"
            "2. Create tests/agile/test_metrics_v2_mean_takt.py with 4 tests:\n"
            "   - test_basic: mean_takt([1.0, 2.0, 3.0]) returns a Metric "
            "     with value == 2.0.\n"
            "   - test_name_convention: the returned Metric has .name == 'mean_takt' "
            "     (this asserts the snake_case naming convention).\n"
            "   - test_unit_present: the returned Metric has non-empty .unit "
            "     (any string is fine).\n"
            "   - test_invalid_input_returns_none: mean_takt([]) returns None "
            "     (this asserts the return-None-on-invalid convention, NOT raise).\n\n"
            "Verify: pytest tests/agile/test_metrics_v2_mean_takt.py -v (4/4)."
        ),
    ),

    # ── L3: second metric — same conventions ────────────────────────────────
    BenchmarkIssue(
        issue_id="L10-03-median-takt",
        title="Add median_takt metric following metrics_v2 conventions",
        difficulty="medium",
        template="apply_convention",
        body=(
            "Add a median_takt metric to the metrics_v2 sub-package. "
            "Same conventions as mean_takt — read wiki/DECISIONS.md.\n\n"
            "1. Create orgos/agile/metrics_v2/median_takt.py exposing:\n"
            "     def median_takt(takts: list[float]) -> Metric | None:\n"
            "   Returns the median (average of two middle values for even-length).\n\n"
            "2. Create tests/agile/test_metrics_v2_median_takt.py with 4 tests:\n"
            "   - test_odd: median_takt([1.0, 3.0, 2.0]) returns Metric with value == 2.0.\n"
            "   - test_even: median_takt([1.0, 2.0, 3.0, 4.0]) returns Metric with "
            "     value == 2.5.\n"
            "   - test_name_convention: returned Metric has .name == 'median_takt' "
            "     (snake_case).\n"
            "   - test_invalid_input_returns_none: median_takt([]) returns None.\n\n"
            "Verify: pytest tests/agile/test_metrics_v2_median_takt.py -v (4/4)."
        ),
    ),

    # ── L4: introduces a NEW convention (time_unit) ─────────────────────────
    BenchmarkIssue(
        issue_id="L10-04-cycle-time-establishes-unit",
        title="Add cycle_time metric — establish time_unit convention",
        difficulty="medium",
        template="establish_extension",
        body=(
            "Add cycle_time to the metrics_v2 sub-package.\n\n"
            "This is the FIRST metric with time semantics — you must establish a "
            "time_unit convention that all future timing metrics will follow.\n\n"
            "1. Create orgos/agile/metrics_v2/cycle_time.py exposing:\n"
            "     def cycle_time(start_ts: float, end_ts: float) -> Metric | None:\n"
            "   Returns end - start, wrapped in a Metric. Follow the base conventions "
            "   (name='cycle_time', invalid -> None if end < start).\n\n"
            "2. Choose a time unit (SECONDS or MILLISECONDS) for the Metric.unit "
            "   field. Record your choice in wiki/DECISIONS.md via wiki_write "
            "   (mode='append') as:\n\n"
            "     ## metrics_v2 time_unit convention (established sprint L10-04)\n"
            "     - time_unit: <'s' or 'ms'>\n"
            "     - Applies to: every metrics_v2 function that returns a duration "
            "or a time interval.\n\n"
            "3. Create tests/agile/test_metrics_v2_cycle_time.py with 3 tests:\n"
            "   - test_positive_span: cycle_time(100.0, 250.0) returns Metric with "
            "     value == 150.0.\n"
            "   - test_name: .name == 'cycle_time'.\n"
            "   - test_end_before_start_returns_none: cycle_time(200.0, 100.0) returns None.\n\n"
            "Verify: pytest tests/agile/test_metrics_v2_cycle_time.py -v (3/3)."
        ),
    ),

    # ── L5: another time metric — MUST match L4's time_unit ─────────────────
    BenchmarkIssue(
        issue_id="L10-05-wait-time-follows-unit",
        title="Add wait_time metric — must match established time_unit",
        difficulty="medium",
        template="apply_extended_convention",
        body=(
            "Add wait_time to the metrics_v2 sub-package.\n\n"
            "Read wiki/DECISIONS.md for the metrics_v2 conventions. Pay close "
            "attention to the time_unit convention established in a prior sprint — "
            "your Metric.unit MUST match it exactly.\n\n"
            "1. Create orgos/agile/metrics_v2/wait_time.py exposing:\n"
            "     def wait_time(ready_ts: float, start_ts: float) -> Metric | None:\n"
            "   Returns start - ready, wrapped in a Metric.\n\n"
            "2. Create tests/agile/test_metrics_v2_wait_time.py with 3 tests:\n"
            "   - test_positive_wait: wait_time(10.0, 30.0) returns Metric with "
            "     value == 20.0.\n"
            "   - test_name: .name == 'wait_time'.\n"
            "   - test_unit_matches_cycle_time: the .unit field of a wait_time "
            "     result MUST equal the .unit field of a cycle_time result. Import "
            "     cycle_time from orgos.agile.metrics_v2.cycle_time and assert.\n\n"
            "This last test is the load-bearing check: consistency with earlier work.\n\n"
            "Verify: pytest tests/agile/test_metrics_v2_wait_time.py -v (3/3)."
        ),
    ),

    # ── L6: another sample metric — extends error-handling coverage ─────────
    BenchmarkIssue(
        issue_id="L10-06-p95-takt",
        title="Add p95_takt metric — nth-percentile with base conventions",
        difficulty="medium",
        template="apply_convention",
        body=(
            "Add p95_takt to the metrics_v2 sub-package. Follow the base "
            "conventions in wiki/DECISIONS.md.\n\n"
            "1. Create orgos/agile/metrics_v2/p95_takt.py exposing:\n"
            "     def p95_takt(takts: list[float]) -> Metric | None:\n"
            "   For empty list, follow the invalid-input policy. For non-empty, "
            "   compute the 95th percentile (use the ceiling-index method: "
            "   sorted(takts)[min(len-1, int(ceil(0.95 * len)) - 1)]).\n\n"
            "2. Create tests/agile/test_metrics_v2_p95_takt.py with 3 tests:\n"
            "   - test_20_values: p95_takt(list(range(1, 21))) returns Metric with "
            "     value == 19.0 (the 95th percentile of 1..20).\n"
            "   - test_name: .name == 'p95_takt'.\n"
            "   - test_invalid_input_returns_none: p95_takt([]) returns None.\n\n"
            "Verify: pytest tests/agile/test_metrics_v2_p95_takt.py -v (3/3)."
        ),
    ),

    # ── L7: bundle helper that DEPENDS on prior metrics AND conventions ─────
    BenchmarkIssue(
        issue_id="L10-07-summary-bundle",
        title="Add summarize() that bundles prior metrics — reads conventions",
        difficulty="hard",
        template="cross_module_bundle",
        body=(
            "Add a summarize() helper that aggregates prior metrics into a bundle.\n\n"
            "Read wiki/DECISIONS.md for all metrics_v2 conventions.\n\n"
            "1. Create orgos/agile/metrics_v2/summary.py exposing:\n"
            "     def summarize(takts: list[float]) -> list[Metric]:\n"
            "   which returns a list containing the results of calling mean_takt, "
            "   median_takt, and p95_takt on the input, EXCLUDING any None entries.\n\n"
            "   Import from orgos.agile.metrics_v2.mean_takt, .median_takt, .p95_takt.\n\n"
            "2. Create tests/agile/test_metrics_v2_summary.py with 3 tests:\n"
            "   - test_non_empty: summarize([1.0, 2.0, 3.0, 4.0, 5.0]) returns a "
            "     list of length 3, all entries are Metric instances.\n"
            "   - test_empty_returns_empty_list: summarize([]) returns [] "
            "     (empty list — because each metric returns None which we filter).\n"
            "   - test_all_names_snake_case: for each Metric in a non-empty result, "
            "     assert r.name matches r'^[a-z_][a-z0-9_]*$' (snake_case regex).\n\n"
            "Verify: pytest tests/agile/test_metrics_v2_summary.py -v (3/3)."
        ),
    ),

    # ── L8: introduce a new metric that must use time_unit + return-none ────
    BenchmarkIssue(
        issue_id="L10-08-lead-time",
        title="Add lead_time metric — must follow every established convention",
        difficulty="hard",
        template="apply_all_conventions",
        body=(
            "Add lead_time to the metrics_v2 sub-package. Read wiki/DECISIONS.md "
            "for all conventions — this metric touches BOTH the base conventions "
            "AND the time_unit convention.\n\n"
            "1. Create orgos/agile/metrics_v2/lead_time.py exposing:\n"
            "     def lead_time(created_ts: float, closed_ts: float) -> Metric | None:\n"
            "   Returns closed - created, wrapped in a Metric.\n\n"
            "2. Create tests/agile/test_metrics_v2_lead_time.py with 4 tests:\n"
            "   - test_positive: lead_time(0.0, 100.0) returns Metric with value == 100.0.\n"
            "   - test_name_snake_case: .name == 'lead_time'.\n"
            "   - test_closed_before_created_returns_none: lead_time(200.0, 100.0) "
            "     returns None (NOT raise).\n"
            "   - test_unit_matches_cycle_time: from orgos.agile.metrics_v2.cycle_time "
            "     import cycle_time; assert lead_time(0,100).unit == cycle_time(0,100).unit.\n\n"
            "Verify: pytest tests/agile/test_metrics_v2_lead_time.py -v (4/4)."
        ),
    ),

    # ── L9: convention-audit function ───────────────────────────────────────
    BenchmarkIssue(
        issue_id="L10-09-audit-conventions",
        title="Add audit_conventions() to validate the sub-package",
        difficulty="hard",
        template="convention_meta",
        body=(
            "Add an audit helper that checks metrics_v2 conventions are held. "
            "Read wiki/DECISIONS.md for the conventions this must enforce.\n\n"
            "1. Create orgos/agile/metrics_v2/audit.py exposing:\n"
            "     def audit_conventions() -> list[str]:\n"
            "   which returns a list of convention violations found in metrics_v2. "
            "   Empty list means all conventions are met.\n\n"
            "   Implementation: for each metric function in the sub-package "
            "   (mean_takt, median_takt, p95_takt, cycle_time, wait_time, lead_time), "
            "   check:\n"
            "   - Calling with invalid input ([] for list-based, or a broken time "
            "     interval for time-based) returns None (not raise).\n"
            "   - The returned Metric's .name is snake_case (matches r'^[a-z_][a-z0-9_]*$').\n"
            "   Append a violation string like f'{fn_name}: invalid input raised' "
            "   or f'{fn_name}: name is not snake_case' for each failure.\n\n"
            "2. Create tests/agile/test_metrics_v2_audit.py with 2 tests:\n"
            "   - test_audit_returns_list: audit_conventions() returns a list.\n"
            "   - test_audit_currently_clean: audit_conventions() == []  "
            "     (all prior metrics_v2 metrics conform).\n\n"
            "Verify: pytest tests/agile/test_metrics_v2_audit.py -v (2/2)."
        ),
    ),

    # ── L10: dashboard-style rollup — uses everything ───────────────────────
    BenchmarkIssue(
        issue_id="L10-10-dashboard-rollup",
        title="Add dashboard() rollup that combines summary + lead_time + audit",
        difficulty="hard",
        template="full_integration",
        body=(
            "Add a top-level dashboard() helper. Read wiki/DECISIONS.md.\n\n"
            "1. Create orgos/agile/metrics_v2/dashboard.py exposing:\n"
            "     def dashboard(takts: list[float], "
            "created_ts: float, closed_ts: float) -> dict:\n"
            "   Returns a dict shaped as:\n"
            "     {\n"
            "       'summary': [Metric, ...],      # from summarize(takts)\n"
            "       'lead_time': Metric | None,    # from lead_time(created, closed)\n"
            "       'audit_violations': [str, ...] # from audit_conventions()\n"
            "     }\n"
            "   Uses summarize, lead_time, audit_conventions.\n\n"
            "2. Create tests/agile/test_metrics_v2_dashboard.py with 3 tests:\n"
            "   - test_shape: dashboard([1,2,3,4,5], 0.0, 100.0) returns a dict "
            "     with keys 'summary', 'lead_time', 'audit_violations' (exact set).\n"
            "   - test_summary_is_list_of_metrics: each element in result['summary'] "
            "     is a Metric.\n"
            "   - test_lead_time_unit_matches_summary_time_unit: the unit of "
            "     result['lead_time'] should equal cycle_time(0,100).unit (proves the "
            "     time_unit convention held throughout).\n\n"
            "Verify: pytest tests/agile/test_metrics_v2_dashboard.py -v (3/3)."
        ),
    ),
]


def generate_linked_corpus(n: int = 10) -> list[BenchmarkIssue]:
    """Return the linked benchmark corpus in fixed order.

    Do NOT shuffle. Order is load-bearing — L4 must run after L3, etc.
    """
    return _ISSUES[:n]
