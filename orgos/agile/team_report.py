"""Team-level HTML report — self-contained, one file per team run.

Reads .orgos_teams/<team_id>/{manifest.json,campaign_result.json,board/}
and produces .orgos_teams/<team_id>/report.html with:
  - header: team_id, goal, model, timing
  - totals: stories done/blocked, cost, tokens, wall time
  - board timeline: state transitions per story
  - per-story drilldown: envelopes, diff, wiki decisions
"""

from __future__ import annotations

import html
import json
import subprocess
from dataclasses import asdict
from pathlib import Path

from orgos.agile.board_store import BoardStore
from orgos.agile.pricing import cost_usd
from orgos.agile.team_workspace import TeamWorkspace


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _wiki_decisions_tail(wiki_root: Path, n: int = 20) -> str:
    p = wiki_root / "DECISIONS.md"
    if not p.exists():
        return "(no DECISIONS.md yet)"
    try:
        text = p.read_text()
    except OSError:
        return "(cannot read)"
    lines = text.splitlines()
    return "\n".join(lines[-n * 5:])  # give some room per entry


def _diff_full(ws: TeamWorkspace, baseline_sha: str) -> str:
    return subprocess.run(
        ["git", "diff", f"{baseline_sha}..HEAD"],
        cwd=str(ws.worktree), capture_output=True, text=True, timeout=30,
    ).stdout


_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>orgos team — __TEAM_ID__</title>
<style>
  :root {
    --bg: #0d1117; --panel: #161b22; --border: #30363d;
    --fg: #e6edf3; --muted: #7d8590; --accent: #58a6ff;
    --scrum: #4ade80; --team: #fb923c; --wiki: #fbbf24;
    --good: #4ade80; --bad: #f87171;
    --add: #033a16; --rem: #67060c; --add-fg: #7ee787; --rem-fg: #ffa198;
    --state-draft: #7d8590; --state-refinement: #fbbf24;
    --state-ready: #58a6ff; --state-in_progress: #a78bfa;
    --state-review: #f472b6; --state-done: #4ade80;
    --state-blocked: #f87171;
  }
  * { box-sizing: border-box; }
  html, body { margin:0; padding:0; background:var(--bg); color:var(--fg);
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size:14px; line-height:1.5; }
  header { padding:24px 32px; border-bottom:1px solid var(--border); }
  header h1 { margin:0 0 6px 0; font-size:20px; }
  header .goal { color:var(--fg); font-size:13px; margin-top:4px; max-width:900px; }
  header .meta { color:var(--muted); font-size:12px; margin-top:6px; }
  main { padding:24px 32px; max-width:1600px; margin:0 auto; }
  section { margin-bottom:32px; }
  section h2 { font-size:15px; margin:0 0 12px 0; padding-bottom:6px;
    border-bottom:1px solid var(--border); color:var(--muted); font-weight:500;
    text-transform:uppercase; letter-spacing:0.5px; }
  .cards { display:grid; gap:12px; grid-template-columns:repeat(auto-fit, minmax(200px,1fr)); }
  .card { background:var(--panel); border:1px solid var(--border); border-radius:6px; padding:14px; }
  .card .l { color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:0.5px; }
  .card .v { font-size:22px; font-weight:500; margin-top:4px; font-variant-numeric:tabular-nums; }
  .card .sub { color:var(--muted); font-size:11px; margin-top:2px; }

  .stories { background:var(--panel); border:1px solid var(--border); border-radius:6px; }
  .story-row { padding:12px 14px; border-bottom:1px solid var(--border); cursor:pointer;
    display:grid; grid-template-columns:100px 80px 60px 1fr 80px; gap:12px; align-items:center; }
  .story-row:last-child { border-bottom:none; }
  .story-row:hover { background:#21262d; }
  .story-row.active { background:#1f6feb33; border-left:3px solid var(--accent); }
  .story-row .id { color:var(--muted); font-family:"SF Mono",monospace; font-size:11px; }
  .story-row .state {
    padding:2px 8px; border-radius:3px; font-size:10px; text-align:center;
    text-transform:uppercase; font-weight:600; letter-spacing:0.5px;
  }
  .state.state-draft { background:#21262d; color:var(--state-draft); }
  .state.state-refinement { background:#3d310b; color:var(--state-refinement); }
  .state.state-ready { background:#0d2d5f; color:var(--state-ready); }
  .state.state-in_progress { background:#3f2b6b; color:var(--state-in_progress); }
  .state.state-review { background:#4b1e40; color:var(--state-review); }
  .state.state-done { background:#0d3d1c; color:var(--state-done); }
  .state.state-blocked { background:#4a0e11; color:var(--state-blocked); }
  .story-row .type {
    padding:2px 8px; border-radius:3px; font-size:10px; text-align:center;
    background:#21262d; color:var(--muted);
  }
  .story-row .title { font-size:13px; }
  .story-row .points { color:var(--muted); font-size:11px; text-align:right; }

  .detail { background:var(--panel); border:1px solid var(--border); border-radius:6px;
    padding:16px; margin-top:16px; }
  .detail h3 { margin:0 0 8px 0; font-size:14px; }
  .detail .body { color:var(--muted); font-size:12.5px; margin-bottom:12px; white-space:pre-wrap; }
  .detail details { margin-top:8px; }
  .detail details summary { cursor:pointer; padding:4px 0; color:var(--muted); font-size:12px; }
  .detail details summary:hover { color:var(--fg); }
  .detail pre { background:#0b0f14; border:1px solid var(--border); border-radius:4px;
    padding:10px; overflow-x:auto; max-height:400px; overflow-y:auto;
    font-family:"SF Mono",Menlo,Consolas,monospace; font-size:11.5px;
    white-space:pre; margin:6px 0 0 0; }
  .diff .line-add { background:var(--add); color:var(--add-fg); display:block; }
  .diff .line-rem { background:var(--rem); color:var(--rem-fg); display:block; }
  .diff .line-hunk { color:var(--accent); display:block; }
  .diff .line-file { color:var(--muted); font-weight:500; display:block; }

  .audit { font-family:"SF Mono",monospace; font-size:11px; color:var(--muted); }
  .audit .row { padding:2px 0; }
  .audit .action { color:var(--accent); font-weight:500; }

  .wiki-block {
    background:#1a1305; border:1px dashed var(--wiki); border-radius:6px;
    padding:12px 14px; margin-top:8px;
    font-family:"SF Mono",monospace; font-size:11.5px; white-space:pre-wrap;
    max-height:400px; overflow-y:auto;
  }
</style>
</head>
<body>
<header>
  <h1>orgos team — <span id="team-id"></span></h1>
  <div class="goal" id="goal"></div>
  <div class="meta" id="meta"></div>
</header>
<main>

<section>
  <h2>Totals</h2>
  <div class="cards" id="cards"></div>
</section>

<section>
  <h2>Wiki decisions (tail)</h2>
  <div class="wiki-block" id="wiki"></div>
</section>

<section>
  <h2>Stories</h2>
  <div class="stories" id="stories"></div>
  <div class="detail" id="detail" style="display:none;">
    <h3 id="d-title"></h3>
    <div class="body" id="d-body"></div>
    <details open><summary>Audit trail</summary><div class="audit" id="d-audit"></div></details>
    <details><summary>Poker votes</summary><pre id="d-votes"></pre></details>
    <details><summary>Envelope</summary><pre id="d-envelope"></pre></details>
    <details><summary>Diff (this story)</summary><pre class="diff" id="d-diff"></pre></details>
  </div>
</section>

</main>

<script>
const MANIFEST = __MANIFEST__;
const RESULT = __RESULT__;
const STORIES = __STORIES__;   // {issue_id: story dict}
const AUDIT = __AUDIT__;       // {issue_id: [audit entries]}
const WIKI = __WIKI_TAIL__;
const FULL_DIFF = __FULL_DIFF__;
const RESULTS_BY_STORY = __RESULTS_BY_STORY__;   // {issue_id: work result}

function esc(s) { return String(s || "").replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c])); }
function fmt(n, dp=0) { if (n==null) return "—"; if (typeof n !== "number") return n;
  return n.toLocaleString(undefined, {maximumFractionDigits: dp}); }

document.getElementById("team-id").textContent = MANIFEST.team_id || "(no team)";
document.getElementById("goal").textContent = MANIFEST.goal || "";
document.getElementById("meta").textContent =
  "model: " + (MANIFEST.model || "?") +
  " · created: " + (MANIFEST.created_at || "").slice(0,19).replace("T"," ") +
  " · branch: " + (MANIFEST.branch || "");

const totals = [
  {l:"stories created", v: RESULT.stories_created ?? Object.keys(STORIES).length},
  {l:"stories done", v: RESULT.stories_done ?? 0},
  {l:"stories blocked", v: RESULT.stories_blocked ?? 0},
  {l:"tokens (in+out)", v: fmt((RESULT.total_tokens_input||0) + (RESULT.total_tokens_output||0), 0)},
  {l:"cost (USD)", v: "$" + fmt(__COST_USD__, 4)},
  {l:"stopped because", v: RESULT.reason_stopped || "—", sub:""},
];
const cardsEl = document.getElementById("cards");
for (const t of totals) {
  const d = document.createElement("div");
  d.className = "card";
  d.innerHTML = '<div class="l">'+esc(t.l)+'</div><div class="v">'+esc(t.v)+'</div>';
  cardsEl.appendChild(d);
}

document.getElementById("wiki").textContent = WIKI || "(no wiki entries yet)";

// Stories in priority order (state first, then priority desc)
const stateOrder = {done:0, review:1, in_progress:2, ready:3, refinement:4, draft:5, blocked:6};
const ids = Object.keys(STORIES).sort((a,b) => {
  const sa = stateOrder[STORIES[a].state] ?? 9;
  const sb = stateOrder[STORIES[b].state] ?? 9;
  if (sa !== sb) return sa - sb;
  return (STORIES[b].priority||0) - (STORIES[a].priority||0);
});
const storiesEl = document.getElementById("stories");
for (const id of ids) {
  const s = STORIES[id];
  const row = document.createElement("div");
  row.className = "story-row";
  row.dataset.id = id;
  row.innerHTML =
    '<div class="id">'+esc(id.slice(0,20))+'</div>' +
    '<div class="state state-'+s.state+'">'+esc(s.state)+'</div>' +
    '<div class="type">'+esc(s.type)+'</div>' +
    '<div class="title">'+esc(s.title)+'</div>' +
    '<div class="points">'+(s.points != null ? s.points + " pts" : "—")+'</div>';
  row.addEventListener("click", () => showDetail(id));
  storiesEl.appendChild(row);
}

function renderDiff(text) {
  if (!text) return "(no diff)";
  return text.split("\n").map(line => {
    const e = esc(line);
    if (line.startsWith("+++") || line.startsWith("---") || line.startsWith("diff --git")) return '<span class="line-file">'+e+'</span>';
    if (line.startsWith("@@")) return '<span class="line-hunk">'+e+'</span>';
    if (line.startsWith("+")) return '<span class="line-add">'+e+'</span>';
    if (line.startsWith("-")) return '<span class="line-rem">'+e+'</span>';
    return e;
  }).join("\n");
}

function showDetail(id) {
  document.querySelectorAll(".story-row").forEach(r =>
    r.classList.toggle("active", r.dataset.id === id));
  document.getElementById("detail").style.display = "block";
  const s = STORIES[id];
  document.getElementById("d-title").textContent = "[" + s.type + "] " + s.title + "  (" + s.state + ")";
  document.getElementById("d-body").textContent = s.body || "(no body)";
  const trail = AUDIT[id] || [];
  document.getElementById("d-audit").innerHTML = trail.map(e =>
    '<div class="row"><span>'+esc(e.timestamp?.slice(11,19)||"")+'</span> ' +
    '<span class="action">'+esc(e.action)+'</span> ' +
    '<span>by '+esc(e.actor||"?")+'</span> ' +
    (e.to_state ? '<span>→ '+esc(e.to_state)+'</span>' : '') +
    (e.reason ? '<span> ('+esc(e.reason)+')</span>' : '') +
    '</div>'
  ).join("");
  document.getElementById("d-votes").textContent = JSON.stringify(s.votes || [], null, 2);
  const r = RESULTS_BY_STORY[id] || {};
  document.getElementById("d-envelope").textContent = JSON.stringify(r.envelope || {}, null, 2);
  document.getElementById("d-diff").innerHTML = renderDiff(r.diff_summary || "(no diff for this story)");
}
</script>
</body>
</html>
"""


def render_team_report(workspace: TeamWorkspace) -> Path:
    """Render <workspace.root>/report.html. Returns the path."""
    manifest = _load(workspace.manifest_path)
    result = _load(workspace.root / "campaign_result.json")

    board = BoardStore(workspace.board_dir)
    stories = {s.issue_id: asdict(s) for s in board.all_stories()}
    audit = {iid: board.audit_trail(iid) for iid in stories}

    # Wiki tail — prefer the team's local wiki dir if it has DECISIONS.md,
    # else fall back to the source_repo's wiki dir.
    wiki_tail = _wiki_decisions_tail(workspace.wiki_dir)
    if wiki_tail == "(no DECISIONS.md yet)":
        wiki_tail = _wiki_decisions_tail(workspace.source_repo / "wiki")

    full_diff = ""
    try:
        full_diff = _diff_full(workspace, manifest.get("baseline_sha", ""))
    except Exception:
        pass

    # Per-story work results (from campaign_result)
    results_by_story: dict = {}
    for r in result.get("per_story_results", []):
        results_by_story[r.get("story_id", "")] = r

    # Cost
    model = manifest.get("model", "unknown")
    tin = result.get("total_tokens_input", 0)
    tout = result.get("total_tokens_output", 0)
    cost = round(cost_usd(model, tin, tout), 6)

    html_content = _HTML
    replacements = {
        "__TEAM_ID__": html.escape(manifest.get("team_id", "")),
        "__MANIFEST__": json.dumps(manifest),
        "__RESULT__": json.dumps(result),
        "__STORIES__": json.dumps(stories),
        "__AUDIT__": json.dumps(audit),
        "__WIKI_TAIL__": json.dumps(wiki_tail),
        "__FULL_DIFF__": json.dumps(full_diff),
        "__RESULTS_BY_STORY__": json.dumps(results_by_story),
        "__COST_USD__": json.dumps(cost),
    }
    for k, v in replacements.items():
        html_content = html_content.replace(k, v)

    out_path = workspace.root / "report.html"
    out_path.write_text(html_content, encoding="utf-8")
    return out_path
