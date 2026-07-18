"""Delivery reconciliation (Fix §A3) — spec-in vs delivered-out.

After a run, the human wants one question answered: "You asked for 37
stories. What did we ship?"

This module compares a spec-file to the team's board and writes a
delivery-receipt.md that names, per declared story:
  - Was it delivered?
  - Was its commit accepted (all AC bullets MET)?
  - If not delivered: which state is it in and why?

Also emits an overall summary: cost trace, tokens, wall time, test
coverage delta (if pytest was run on the built code), and a plain-English
verdict ("shipped 25 of 37 declared stories in 4h 6min at $3.14 cost").
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from orgos.agile.board_store import BoardStore
from orgos.agile.live_events import read_events
from orgos.agile.pricing import cost_usd
from orgos.agile.spec_parser import parse_spec_text
from orgos.agile.team_report import collect_blocked_reasons


@dataclass
class DeclaredMatch:
    """One row of the delivery table."""
    declared_index: int          # 0-based index in the spec
    declared_title: str
    matched_story_id: Optional[str] = None
    matched_title: str = ""
    state: str = "not_matched"    # done | blocked | in_progress | ... | not_matched
    commit_sha: str = ""
    ac_declared: int = 0
    ac_met: int = 0
    ac_unmet: int = 0
    block_reason: str = ""


@dataclass
class DeliveryReport:
    team_id: str
    spec_path: str
    started_at: str
    ended_at: str
    duration: str
    declared_count: int
    delivered_count: int
    blocked_count: int
    in_flight_count: int
    not_matched_count: int
    matches: list[DeclaredMatch] = field(default_factory=list)
    total_tokens_input: int = 0
    total_tokens_output: int = 0
    estimated_cost_usd: float = 0.0
    model_default: str = ""
    integration_commits: int = 0
    per_state: dict = field(default_factory=dict)
    blocked_reasons: dict = field(default_factory=dict)


def _normalize_title(t: str) -> str:
    """Lowercase, strip non-alphanumerics down to just word chars."""
    import re
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def _match_declared_to_board(
    declared: list, board_stories: list,
) -> list[DeclaredMatch]:
    """Fuzzy-match spec-declared stories to board stories by normalized title.

    A declared story may match 0 or 1 board stories. We DON'T do many-to-one:
    each declared story gets its best board candidate, and each board story
    is claimed by at most one declared story.
    """
    board_by_norm: dict[str, list] = {}
    for s in board_stories:
        key = _normalize_title(s.title)
        board_by_norm.setdefault(key, []).append(s)

    def _field(obj: Any, name: str, default=""):
        """Accept either dataclass (SpecStory) or dict (in tests)."""
        v = getattr(obj, name, None)
        if v is not None:
            return v
        try:
            return obj.get(name, default)
        except (AttributeError, TypeError):
            return default

    claimed_ids: set[str] = set()
    matches: list[DeclaredMatch] = []
    for i, d in enumerate(declared):
        declared_title = _field(d, "title", "")
        norm = _normalize_title(declared_title)
        match_story = None
        # 1. Exact normalized-title match
        for s in board_by_norm.get(norm, []):
            if s.issue_id not in claimed_ids:
                match_story = s
                break
        # 2. Substring fallback — cheap and works for most PO paraphrases
        if match_story is None:
            for s in board_stories:
                if s.issue_id in claimed_ids:
                    continue
                if not norm:
                    continue
                s_norm = _normalize_title(s.title)
                if norm in s_norm or s_norm in norm:
                    match_story = s
                    break
        row = DeclaredMatch(
            declared_index=i,
            declared_title=declared_title,
            ac_declared=len(_field(d, "acceptance_criteria", []) or []),
        )
        if match_story is not None:
            claimed_ids.add(match_story.issue_id)
            row.matched_story_id = match_story.issue_id
            row.matched_title = match_story.title
            row.state = match_story.state
            row.commit_sha = match_story.commit_sha
            # AC counts come from the board story's own acceptance_criteria
            # (which may differ from the spec if PO rewrote them).
            declared_ac = getattr(match_story, "acceptance_criteria", None) or []
            row.ac_declared = max(row.ac_declared, len(declared_ac))
        matches.append(row)
    return matches


def _enrich_ac_verdicts(
    matches: list[DeclaredMatch], workspace_root: Path,
) -> None:
    """Read live.jsonl for story_ac_check events and fill met/unmet counts
    on matched rows. Mutates rows in place.
    """
    try:
        events = read_events(workspace_root)
    except Exception:
        return
    latest_verdict_by_story: dict[str, dict] = {}
    for e in events:
        if e.get("action") != "story_ac_check":
            continue
        sid = e.get("story_id")
        if sid:
            latest_verdict_by_story[sid] = e  # last-write-wins → keeps final
    for row in matches:
        if not row.matched_story_id:
            continue
        v = latest_verdict_by_story.get(row.matched_story_id)
        if not v:
            continue
        row.ac_met = int(v.get("met", 0) or 0)
        row.ac_unmet = int(v.get("unmet", 0) or 0)


def build_report(
    *,
    workspace: Any,
    board: BoardStore,
    spec_text: str,
    spec_path: Path,
) -> DeliveryReport:
    """Assemble a DeliveryReport for the given workspace + spec."""
    declared = parse_spec_text(spec_text)
    board_stories = board.all_stories()
    matches = _match_declared_to_board(declared, board_stories)
    _enrich_ac_verdicts(matches, workspace.root)

    # Overall counts
    delivered = sum(1 for m in matches if m.state == "done")
    blocked = sum(1 for m in matches if m.state == "blocked")
    in_flight = sum(
        1 for m in matches
        if m.state in ("in_progress", "review", "pending_acceptance", "ready", "refinement", "draft")
    )
    not_matched = sum(1 for m in matches if m.state == "not_matched")

    # Tokens + cost — scan commit_landed events (delivery agents) + spawn
    # results in ceremonies (we conservatively include what's tracked).
    events = []
    try:
        events = read_events(workspace.root)
    except Exception:
        pass
    tokens_in = sum(
        int(e.get("tokens_in", 0) or 0) for e in events
        if e.get("action") in ("commit_landed", "story_no_commit")
    )
    tokens_out = sum(
        int(e.get("tokens_out", 0) or 0) for e in events
        if e.get("action") in ("commit_landed", "story_no_commit")
    )

    # Model + cost
    try:
        m = workspace.manifest()
        model_default = m.model
        started_at = m.created_at
    except Exception:
        model_default = "deepseek/deepseek-chat"
        started_at = ""
    cost = cost_usd(model_default, tokens_in, tokens_out)

    # Integration commit count
    integ_commits = 0
    try:
        import subprocess as _sp
        r = _sp.run(
            ["git", "log", "--oneline"],
            cwd=str(workspace.integration_worktree),
            capture_output=True, text=True, timeout=10,
        )
        integ_commits = len([ln for ln in (r.stdout or "").splitlines() if ln.strip()])
    except Exception:
        pass

    # State histogram + blocked reasons
    per_state = board.counts_by_state()
    blocked_reasons = collect_blocked_reasons(workspace).get("totals", {})

    # Duration
    ended_at = datetime.now(timezone.utc).isoformat()
    duration = ""
    try:
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        end = datetime.fromisoformat(ended_at)
        delta = end - start
        h, rem = divmod(int(delta.total_seconds()), 3600)
        mm, _ = divmod(rem, 60)
        duration = f"{h}h {mm}m"
    except Exception:
        pass

    team_id = ""
    try:
        team_id = workspace.manifest().team_id
    except Exception:
        pass

    return DeliveryReport(
        team_id=team_id,
        spec_path=str(spec_path),
        started_at=started_at,
        ended_at=ended_at,
        duration=duration,
        declared_count=len(declared),
        delivered_count=delivered,
        blocked_count=blocked,
        in_flight_count=in_flight,
        not_matched_count=not_matched,
        matches=matches,
        total_tokens_input=tokens_in,
        total_tokens_output=tokens_out,
        estimated_cost_usd=cost,
        model_default=model_default,
        integration_commits=integ_commits,
        per_state=per_state,
        blocked_reasons=blocked_reasons,
    )


def format_receipt(report: DeliveryReport) -> str:
    """Render the DeliveryReport as a markdown document."""
    lines: list[str] = []
    lines.append(f"# {report.team_id} — delivery receipt")
    lines.append("")
    lines.append(f"- **Spec:** `{report.spec_path}`")
    lines.append(f"- **Started:** {report.started_at}")
    lines.append(f"- **Ended:**   {report.ended_at}")
    lines.append(f"- **Duration:** {report.duration}")
    lines.append(f"- **Model:** {report.model_default}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    delivered_pct = (
        100.0 * report.delivered_count / report.declared_count
        if report.declared_count else 0.0
    )
    lines.append(
        f"**Delivered {report.delivered_count} of {report.declared_count} "
        f"declared stories ({delivered_pct:.0f}%)** in {report.duration}."
    )
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Declared | {report.declared_count} |")
    lines.append(f"| Delivered | {report.delivered_count} |")
    lines.append(f"| Blocked | {report.blocked_count} |")
    lines.append(f"| In flight | {report.in_flight_count} |")
    lines.append(f"| Not matched | {report.not_matched_count} |")
    lines.append(f"| Integration commits | {report.integration_commits} |")
    lines.append(f"| Tokens (in / out) | {report.total_tokens_input:,} / {report.total_tokens_output:,} |")
    lines.append(f"| Estimated cost | ${report.estimated_cost_usd:.3f} |")
    lines.append("")

    if report.blocked_reasons:
        lines.append("### Blocked stories by reason")
        lines.append("")
        for k, v in report.blocked_reasons.items():
            if v:
                lines.append(f"- **{k}**: {v}")
        lines.append("")

    # Delivered table
    delivered_rows = [m for m in report.matches if m.state == "done"]
    if delivered_rows:
        lines.append(f"## Delivered ({len(delivered_rows)})")
        lines.append("")
        lines.append("| # | Declared title | Commit | AC met |")
        lines.append("|---|---|---|---|")
        for m in delivered_rows:
            ac = f"{m.ac_met}/{m.ac_met + m.ac_unmet}" if (m.ac_met + m.ac_unmet) else "—"
            lines.append(
                f"| {m.declared_index} | {m.declared_title[:70]} | `{m.commit_sha[:8]}` | {ac} |"
            )
        lines.append("")

    # Not-yet-delivered (blocked + in flight + not matched)
    other = [m for m in report.matches if m.state != "done"]
    if other:
        lines.append(f"## Not delivered ({len(other)})")
        lines.append("")
        lines.append("| # | Declared title | State | Notes |")
        lines.append("|---|---|---|---|")
        for m in other:
            state_label = m.state if m.matched_story_id else "not on board"
            note = ""
            if m.state == "blocked":
                note = "check `agents/<role>/failures/<id>.log`"
            elif m.state == "not_matched":
                note = "PO didn't draft this — check replan events"
            lines.append(
                f"| {m.declared_index} | {m.declared_title[:70]} | {state_label} | {note} |"
            )
        lines.append("")

    lines.append("## Verdict")
    lines.append("")
    if delivered_pct >= 80:
        lines.append(
            "✅ **The spec is materially delivered.** Recommend running the "
            "e2e test suite in the integration worktree to confirm quality."
        )
    elif delivered_pct >= 50:
        lines.append(
            "⚠️  **Partial delivery.** Substantial work landed, but the spec "
            "isn't complete. Read the 'Not delivered' table above for gaps."
        )
    else:
        lines.append(
            "❌ **Low delivery rate.** Only a fraction of the spec landed. "
            "Consider: (a) running longer, (b) simpler decomposition, "
            "(c) `--po-model` upgrade, (d) checking `orgos logs` for a "
            "structural failure early in the run."
        )
    lines.append("")
    return "\n".join(lines)


def write_receipt(
    *,
    workspace: Any,
    board: BoardStore,
    spec_path: Path,
) -> Path:
    """Convenience: build report, write to workspace.root/delivery-receipt.md."""
    try:
        spec_text = spec_path.read_text(encoding="utf-8")
    except OSError:
        spec_text = ""
    report = build_report(
        workspace=workspace, board=board,
        spec_text=spec_text, spec_path=spec_path,
    )
    out = workspace.root / "delivery-receipt.md"
    out.write_text(format_receipt(report), encoding="utf-8")
    return out
