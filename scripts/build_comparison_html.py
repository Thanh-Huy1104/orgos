#!/usr/bin/env python3
"""Build a self-contained HTML comparison report for two orgos teams.

Reads two team workspaces (typically waterfall vs scrum) and emits a single
HTML file with:
  - Run config (repo, goal, model, executor)
  - Side-by-side metrics table
  - Per-story tables with commit + tokens + status
  - Scrum event histogram
  - Test outcome on each integration branch
  - Cost estimate at DeepSeek chat rates (in/out per 1M tokens)

Usage:
  python3 scripts/build_comparison_html.py \
    --repo /tmp/flask-target \
    --waterfall-team cmp-waterfall \
    --scrum-team     cmp-scrum \
    --goal "Add /notes-count endpoint" \
    --out /tmp/orgos-comparison.html

Idempotent; overwrites --out if it exists.
"""

from __future__ import annotations

import argparse
import html
import json
import pathlib
import subprocess
import sys
from collections import Counter


# DeepSeek Chat pricing (Nov 2025): $0.27 / 1M input, $1.10 / 1M output.
# Override with --input-cost / --output-cost for other models.
DEFAULT_INPUT_COST_PER_M  = 0.27
DEFAULT_OUTPUT_COST_PER_M = 1.10


def load_json(p: pathlib.Path) -> dict:
    return json.loads(p.read_text()) if p.exists() else {}


def story_states(root: pathlib.Path) -> Counter:
    d = root / "board" / "stories"
    if not d.exists():
        return Counter()
    return Counter(
        json.loads(f.read_text()).get("state", "?")
        for f in d.glob("*.json")
    )


def stories_details(root: pathlib.Path) -> list[dict]:
    d = root / "board" / "stories"
    if not d.exists():
        return []
    out = []
    for f in sorted(d.glob("*.json")):
        s = json.loads(f.read_text())
        out.append({
            "id":     s.get("issue_id", ""),
            "title":  s.get("title", ""),
            "type":   s.get("type", ""),
            "points": s.get("points", ""),
            "state":  s.get("state", ""),
            "sha":    (s.get("commit_sha", "") or "")[:7],
            "files_to_touch": s.get("files_to_touch", []) or [],
        })
    return out


def event_counts(root: pathlib.Path) -> Counter:
    p = root / "live.jsonl"
    if not p.exists():
        return Counter()
    return Counter(
        json.loads(l).get("action", "?")
        for l in p.read_text().splitlines() if l.strip()
    )


def run_tests(worktree: pathlib.Path) -> tuple[int | None, str]:
    if not worktree.exists():
        return None, "(no worktree)"
    try:
        r = subprocess.run(
            ["pytest", "-q", "--no-header"],
            cwd=str(worktree), capture_output=True, text=True, timeout=120,
        )
        tail = (r.stdout.strip().splitlines() or [""])[-1]
        return r.returncode, tail
    except Exception as e:
        return None, f"(pytest error: {e})"


def collect_team(root: pathlib.Path) -> dict:
    if not root.exists():
        return {"missing": True}

    campaign = load_json(root / "campaign_result.json")
    states = story_states(root)
    events = event_counts(root)
    per_story = campaign.get("per_story_results", [])

    tokens_in  = campaign.get("total_tokens_input", 0) or 0
    tokens_out = campaign.get("total_tokens_output", 0) or 0

    integ_wt = root / ("worktree" if (root / "worktree").exists() else "integration")
    test_rc, test_tail = run_tests(integ_wt)

    # Sprint history (scrum only — waterfall doesn't have sprints)
    sprints = campaign.get("sprints", []) or []
    # Fallback: read sprints/*.json directly if campaign_result didn't inline them
    if not sprints:
        sprints_dir = root / "sprints"
        if sprints_dir.exists():
            for f in sorted(sprints_dir.glob("*.json")):
                try:
                    sprints.append(json.loads(f.read_text()))
                except json.JSONDecodeError:
                    continue
    # Compute mean SPE across closed sprints (only sprints that actually closed
    # have a duration and thus a meaningful SPE).
    closed = [s for s in sprints if s.get("ended_at")]
    mean_spe = (
        round(sum(s.get("spe", 0.0) for s in closed) / len(closed), 4)
        if closed else 0.0
    )
    total_final_commit = sum(s.get("final_commit", 0) for s in closed)

    return {
        "missing":         False,
        "team_id":         campaign.get("team_id", root.name),
        "topology":        campaign.get("topology", "waterfall" if (root / "campaign_result.json").exists() and not events else "scrum"),
        "started_at":      campaign.get("started_at", ""),
        "ended_at":        campaign.get("ended_at", ""),
        "reason_stopped":  campaign.get("reason_stopped", ""),
        "sprints":         sprints,
        "closed_sprints":  len(closed),
        "mean_spe":        mean_spe,
        "total_final_commit_pts": total_final_commit,
        "stories_created": campaign.get("stories_created", sum(states.values())),
        "stories_done":    campaign.get("stories_done", states.get("done", 0)),
        "stories_blocked": campaign.get("stories_blocked", states.get("blocked", 0)),
        "state_counts":    dict(states),
        "tokens_in":       tokens_in,
        "tokens_out":      tokens_out,
        "per_story_run":   per_story,
        "stories":         stories_details(root),
        "event_counts":    dict(events),
        "test_rc":         test_rc,
        "test_tail":       test_tail,
    }


# ── HTML rendering ─────────────────────────────────────────────────────────

_CSS = """
* { box-sizing: border-box; }
body { font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
       color: #1a1a1a; background: #f7f7f5; margin: 0; padding: 24px; }
h1, h2, h3 { color: #0b0b0b; margin-top: 32px; margin-bottom: 12px; }
h1 { margin-top: 0; font-size: 22px; }
h2 { font-size: 17px; border-bottom: 1px solid #d0d0d0; padding-bottom: 4px; }
h3 { font-size: 14px; color: #444; }
.wrap { max-width: 1160px; margin: 0 auto; }
.meta { color: #666; font-size: 12.5px; margin-bottom: 20px; }
.meta code { background: #ececec; padding: 1px 6px; border-radius: 3px; }
table { border-collapse: collapse; width: 100%; margin: 8px 0; background: #fff;
        border-radius: 4px; overflow: hidden; box-shadow: 0 1px 2px rgba(0,0,0,0.04); }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid #e5e5e5;
         font-size: 13px; }
th { background: #f0f0ee; color: #333; font-weight: 600; font-size: 12px;
     text-transform: uppercase; letter-spacing: 0.03em; }
tr:last-child td { border-bottom: 0; }
tr:hover td { background: #fafaf8; }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.winner { background: #e8f5e9 !important; font-weight: 600; }
.loser  { color: #888; }
.tag    { display: inline-block; padding: 1px 8px; border-radius: 10px;
          font-size: 11px; font-weight: 600; }
.tag.done      { background: #dcedc8; color: #33691e; }
.tag.blocked   { background: #ffcdd2; color: #b71c1c; }
.tag.ready     { background: #b3e5fc; color: #01579b; }
.tag.refinement{ background: #fff9c4; color: #827717; }
.tag.draft     { background: #eeeeee; color: #444; }
.tag.in_progress{background: #ffe0b2; color: #e65100; }
.tag.review    { background: #d1c4e9; color: #4527a0; }
.mono { font-family: "SF Mono", Menlo, Consolas, monospace; font-size: 12px; }
.sub { color: #666; font-size: 12px; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin: 12px 0; }
.card { background: #fff; padding: 14px 18px; border-radius: 4px;
        box-shadow: 0 1px 2px rgba(0,0,0,0.05); }
.card h3 { margin-top: 0; }
.pass { color: #2e7d32; font-weight: 600; }
.fail { color: #c62828; font-weight: 600; }
"""


def _tag(state: str) -> str:
    return f'<span class="tag {state}">{state}</span>'


def _fmt_num(x, dash="—"):
    if x is None or x == "":
        return dash
    if isinstance(x, (int, float)):
        return f"{x:,}"
    return str(x)


def _cost(tokens_in: int, tokens_out: int, in_cost: float, out_cost: float) -> float:
    return round(
        (tokens_in / 1_000_000) * in_cost + (tokens_out / 1_000_000) * out_cost, 4,
    )


def _test_verdict(rc, tail):
    if rc == 0:
        return f'<span class="pass">✓ {html.escape(tail)}</span>'
    if rc is None:
        return f'<span class="sub">{html.escape(tail)}</span>'
    return f'<span class="fail">✗ rc={rc} — {html.escape(tail)}</span>'


def render(
    *,
    repo: str, goal: str, model: str, executor: str,
    waterfall: dict, scrum: dict,
    input_cost: float, output_cost: float,
) -> str:
    # Winner cells: lower is better for cost + tokens; higher for done.
    def winner_cell(w_val, s_val, higher_is_better: bool):
        if w_val is None or s_val is None:
            return "", ""
        if w_val == s_val:
            return "", ""
        w_wins = (w_val > s_val) if higher_is_better else (w_val < s_val)
        return ("winner", "loser") if w_wins else ("loser", "winner")

    w_cost = _cost(waterfall.get("tokens_in", 0), waterfall.get("tokens_out", 0), input_cost, output_cost)
    s_cost = _cost(scrum.get("tokens_in", 0),     scrum.get("tokens_out", 0),     input_cost, output_cost)

    metrics = [
        # (label, w_val, s_val, higher_is_better)
        ("stories drafted",   waterfall.get("stories_created", 0), scrum.get("stories_created", 0), True),
        ("stories done",      waterfall.get("stories_done", 0),    scrum.get("stories_done", 0),    True),
        ("stories blocked",   waterfall.get("stories_blocked", 0), scrum.get("stories_blocked", 0), False),
        ("tokens (in)",       waterfall.get("tokens_in", 0),       scrum.get("tokens_in", 0),       False),
        ("tokens (out)",      waterfall.get("tokens_out", 0),      scrum.get("tokens_out", 0),      False),
        ("est. cost (USD)",   w_cost,                              s_cost,                          False),
    ]

    def metric_row(label, w_val, s_val, hib):
        w_cls, s_cls = winner_cell(w_val, s_val, hib)
        return (f"<tr><td>{html.escape(label)}</td>"
                f'<td class="num {w_cls}">{_fmt_num(w_val)}</td>'
                f'<td class="num {s_cls}">{_fmt_num(s_val)}</td></tr>')

    metrics_rows = "\n".join(metric_row(*m) for m in metrics)

    # SPE (mean over closed sprints) — scrum-only. Waterfall has no sprint concept.
    spe_row = ""
    if scrum.get("closed_sprints", 0) > 0:
        s_spe = scrum.get("mean_spe", 0.0)
        try:
            from orgos.agile.spe import spe_band
            band = spe_band(s_spe)
        except Exception:
            band = ""
        s_spe_str = f"{s_spe:.3f}" + (f' ({band})' if band else '')
        spe_row = (
            f'<tr><td>mean SPE (per sprint)</td>'
            f'<td class="num sub">— (no sprints)</td>'
            f'<td class="num">{html.escape(s_spe_str)}</td></tr>'
            f'<tr><td>closed sprints</td>'
            f'<td class="num sub">—</td>'
            f'<td class="num">{scrum["closed_sprints"]}</td></tr>'
            f'<tr><td>total committed pts</td>'
            f'<td class="num sub">—</td>'
            f'<td class="num">{scrum.get("total_final_commit_pts", 0)}</td></tr>'
        )

    # Test verdict row (separate — not a "winner" style)
    tests_row = (
        f'<tr><td>integration tests</td>'
        f'<td>{_test_verdict(waterfall.get("test_rc"), waterfall.get("test_tail", ""))}</td>'
        f'<td>{_test_verdict(scrum.get("test_rc"), scrum.get("test_tail", ""))}</td></tr>'
    )

    def stories_table(rows):
        if not rows:
            return '<div class="sub">(no stories)</div>'
        body = "\n".join(
            f"<tr>"
            f"<td class=\"mono\">{html.escape(s['id'])}</td>"
            f"<td>{html.escape(s['title'][:70])}</td>"
            f"<td>{html.escape(s['type'])}</td>"
            f"<td class=\"num\">{_fmt_num(s['points'])}</td>"
            f"<td>{_tag(s['state'])}</td>"
            f"<td class=\"mono\">{html.escape(s['sha'])}</td>"
            f"</tr>"
            for s in rows
        )
        return (
            "<table><thead><tr><th>id</th><th>title</th><th>type</th>"
            "<th>pts</th><th>state</th><th>sha</th></tr></thead>"
            f"<tbody>{body}</tbody></table>"
        )

    def sprint_history_table(sprints_list):
        if not sprints_list:
            return '<div class="sub">(no sprints — waterfall run, or scrum never closed a sprint)</div>'
        try:
            from orgos.agile.spe import spe_band
        except Exception:
            spe_band = lambda _v: ""  # noqa: E731
        rows = []
        for s in sprints_list:
            n = s.get("number", "?")
            duration = s.get("duration_hours", 0.0)
            fc = s.get("final_commit", 0)
            done = len(s.get("stories_done") or [])
            committed = len(s.get("committed_backlog") or [])
            pts = s.get("points_completed", 0)
            spe = s.get("spe", 0.0)
            band = spe_band(spe) if s.get("ended_at") else "(open)"
            status = "open" if not s.get("ended_at") else s.get("reason_closed", "closed")
            rows.append(
                f"<tr>"
                f"<td class='num'>{n}</td>"
                f"<td>{done}/{committed}</td>"
                f"<td class='num'>{pts}</td>"
                f"<td class='num'>{fc}</td>"
                f"<td class='num'>{duration:.2f}h</td>"
                f"<td class='num'>{spe:.3f}</td>"
                f"<td>{html.escape(band)}</td>"
                f"<td>{html.escape(status)}</td>"
                f"</tr>"
            )
        return (
            "<table><thead><tr>"
            "<th>sprint</th><th>done/committed</th><th>pts done</th>"
            "<th>final_commit (pts)</th><th>duration</th><th>SPE</th>"
            "<th>band</th><th>status</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
        )

    def event_histogram(counts):
        if not counts:
            return '<div class="sub">(no events)</div>'
        items = sorted(counts.items(), key=lambda x: -x[1])
        body = "\n".join(
            f"<tr><td class='mono'>{html.escape(k)}</td><td class='num'>{v}</td></tr>"
            for k, v in items
        )
        return (
            "<table><thead><tr><th>event</th><th>count</th></tr></thead>"
            f"<tbody>{body}</tbody></table>"
        )

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>orgos comparison</title>
<style>{_CSS}</style></head>
<body><div class="wrap">
<h1>orgos: waterfall vs scrum</h1>
<div class="meta">
  repo <code>{html.escape(repo)}</code> &middot;
  model <code>{html.escape(model)}</code> &middot;
  executor <code>{html.escape(executor)}</code>
  <br>goal: {html.escape(goal)}
</div>

<h2>Head-to-head</h2>
<table>
<thead><tr><th>metric</th><th class="num">waterfall</th><th class="num">scrum</th></tr></thead>
<tbody>
{metrics_rows}
{spe_row}
{tests_row}
</tbody>
</table>
<div class="sub">
  Cost estimate uses input=${input_cost:.4f}/1M output=${output_cost:.4f}/1M
  (DeepSeek Chat defaults). Green cell = winner on that metric.
  For "blocked / tokens / cost", lower is better; for "drafted / done / SPE", higher.
  Test outcomes are informational, not scored. SPE = per-sprint
  process efficiency (ideal fair-share hours / actual hours), point-weighted;
  &gt; 1.0 = finished faster than fair share, &lt; 1.0 = ran over, 0 = didn't
  land.
</div>

<div class="grid2">
  <div class="card">
    <h3>Waterfall run</h3>
    <div class="sub">
      team_id: <code>{html.escape(waterfall.get('team_id', ''))}</code><br>
      started: {html.escape(waterfall.get('started_at', '—'))}<br>
      ended:   {html.escape(waterfall.get('ended_at', '—'))}<br>
      reason:  {html.escape(waterfall.get('reason_stopped', '—'))}
    </div>
  </div>
  <div class="card">
    <h3>Scrum run</h3>
    <div class="sub">
      team_id: <code>{html.escape(scrum.get('team_id', ''))}</code><br>
      started: {html.escape(scrum.get('started_at', '—'))}<br>
      ended:   {html.escape(scrum.get('ended_at', '—'))}<br>
      reason:  {html.escape(scrum.get('reason_stopped', '—'))}
    </div>
  </div>
</div>

<h2>Stories — waterfall ({waterfall.get('stories_created', 0)})</h2>
{stories_table(waterfall.get('stories', []))}

<h2>Stories — scrum ({scrum.get('stories_created', 0)})</h2>
{stories_table(scrum.get('stories', []))}

<h2>Scrum sprint history</h2>
{sprint_history_table(scrum.get('sprints', []))}

<h2>Scrum event histogram</h2>
{event_histogram(scrum.get('event_counts', {}))}

</div></body></html>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--waterfall-team", required=True)
    ap.add_argument("--scrum-team",     required=True)
    ap.add_argument("--goal", default="")
    ap.add_argument("--model", default="")
    ap.add_argument("--executor", default="")
    ap.add_argument("--out", default="/tmp/orgos-comparison.html")
    ap.add_argument("--input-cost",  type=float, default=DEFAULT_INPUT_COST_PER_M)
    ap.add_argument("--output-cost", type=float, default=DEFAULT_OUTPUT_COST_PER_M)
    args = ap.parse_args()

    repo = pathlib.Path(args.repo).resolve()
    w = collect_team(repo / ".orgos_teams" / args.waterfall_team)
    s = collect_team(repo / ".orgos_teams" / args.scrum_team)

    if w.get("missing") or s.get("missing"):
        print(f"ERROR: one or both team workspaces missing "
              f"(waterfall_missing={w.get('missing')} scrum_missing={s.get('missing')})",
              file=sys.stderr)
        return 2

    html_text = render(
        repo=str(repo), goal=args.goal, model=args.model, executor=args.executor,
        waterfall=w, scrum=s,
        input_cost=args.input_cost, output_cost=args.output_cost,
    )
    out = pathlib.Path(args.out)
    out.write_text(html_text, encoding="utf-8")
    print(f"[html] wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
