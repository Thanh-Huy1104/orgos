"""Team-level HTML report — self-contained, one file per team run.

Works in two modes with the SAME file:
  - Static: written once at run end; opens as a plain report of what happened.
  - Live:   served by `orgos serve`; polls /live/state + /live/tail and
            refreshes the kanban board and activity strip every 2s.

The report auto-detects live mode by trying to fetch /live/state. If that
succeeds, it enables polling; if it 404s (or the file was opened directly
without a server), it stays in static mode.

Reads:
  <workspace.root>/manifest.json
  <workspace.root>/campaign_result.json
  <workspace.root>/board/    (via BoardStore)
  <workspace.root>/live.jsonl (via read_events)
"""

from __future__ import annotations

import html
import json
import subprocess
from dataclasses import asdict
from pathlib import Path

from orgos.agile.board_store import BoardStore
from orgos.agile.live_events import read_events
from orgos.agile.pricing import cost_usd
from orgos.agile.sprint_history import read_history
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
    return "\n".join(lines[-n * 5:])


def _diff_full(ws: TeamWorkspace, baseline_sha: str) -> str:
    if not baseline_sha:
        return ""
    try:
        return subprocess.run(
            ["git", "diff", f"{baseline_sha}..HEAD"],
            cwd=str(ws.worktree), capture_output=True, text=True, timeout=30,
        ).stdout
    except Exception:
        return ""


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
  header {
    padding:20px 32px; border-bottom:1px solid var(--border);
    display:flex; align-items:baseline; justify-content:space-between;
    flex-wrap:wrap; gap:16px;
  }
  header h1 { margin:0 0 4px 0; font-size:20px; display:flex; align-items:center; gap:12px; }
  header .goal { color:var(--fg); font-size:13px; margin-top:2px; max-width:900px; }
  header .meta { color:var(--muted); font-size:12px; margin-top:4px; }
  header .right { text-align:right; color:var(--muted); font-size:12px; }

  #live-badge {
    display:inline-flex; align-items:center; gap:6px;
    background:#0d3d1c; color:var(--good);
    padding:3px 10px; border-radius:12px; font-size:11px;
    font-weight:600; text-transform:uppercase; letter-spacing:0.6px;
    opacity:0; transition:opacity 0.3s;
  }
  #live-badge.on { opacity:1; }
  #live-badge .dot {
    width:8px; height:8px; border-radius:50%; background:var(--good);
    animation: pulse 1.5s ease-in-out infinite;
  }
  @keyframes pulse {
    0%,100% { opacity:1; box-shadow:0 0 4px var(--good); }
    50% { opacity:0.4; box-shadow:0 0 0 var(--good); }
  }

  main { padding:20px 32px; max-width:1800px; margin:0 auto; }
  section { margin-bottom:32px; }
  section h2 { font-size:14px; margin:0 0 12px 0; padding-bottom:6px;
    border-bottom:1px solid var(--border); color:var(--muted); font-weight:500;
    text-transform:uppercase; letter-spacing:0.5px;
    display:flex; align-items:center; gap:8px; }
  section h2 .count { color:var(--muted); font-weight:400; font-size:12px; }

  .cards { display:grid; gap:10px; grid-template-columns:repeat(auto-fit, minmax(180px,1fr)); }
  .card { background:var(--panel); border:1px solid var(--border); border-radius:6px; padding:12px; }
  .card .l { color:var(--muted); font-size:10.5px; text-transform:uppercase; letter-spacing:0.5px; }
  .card .v { font-size:20px; font-weight:500; margin-top:2px; font-variant-numeric:tabular-nums; }

  /* Kanban */
  .kanban { display:grid; grid-template-columns:repeat(6, 1fr); gap:10px; }
  @media (max-width:1200px) { .kanban { grid-template-columns:repeat(3, 1fr); } }
  .kan-col {
    background:var(--panel); border:1px solid var(--border); border-radius:6px;
    padding:10px; min-height:120px; display:flex; flex-direction:column;
  }
  .kan-col.state-draft       { border-top:3px solid var(--state-draft); }
  .kan-col.state-refinement  { border-top:3px solid var(--state-refinement); }
  .kan-col.state-ready       { border-top:3px solid var(--state-ready); }
  .kan-col.state-in_progress { border-top:3px solid var(--state-in_progress); }
  .kan-col.state-review      { border-top:3px solid var(--state-review); }
  .kan-col.state-done        { border-top:3px solid var(--state-done); }
  .kan-col.state-blocked     { border-top:3px solid var(--state-blocked); }
  .kan-col h3 {
    margin:0 0 8px 0; font-size:11px; text-transform:uppercase; letter-spacing:0.5px;
    color:var(--muted); font-weight:600; display:flex; justify-content:space-between;
  }
  .kan-col h3 .n { color:var(--fg); font-variant-numeric:tabular-nums; }
  .kan-card {
    background:#0b0f14; border:1px solid var(--border); border-radius:4px;
    padding:6px 8px; margin-bottom:6px; font-size:12px; cursor:pointer;
    transition:background 0.15s, transform 0.15s;
  }
  .kan-card:hover { background:#21262d; }
  .kan-card.fresh {
    animation: fresh-flash 1.6s ease-out;
  }
  @keyframes fresh-flash {
    0% { background:#1f6feb99; transform:scale(1.03); }
    100% { background:#0b0f14; transform:scale(1); }
  }
  .kan-card .title { color:var(--fg); font-size:12px; line-height:1.3; margin-bottom:2px; }
  .kan-card .meta { color:var(--muted); font-size:10px; display:flex; gap:6px; }
  .kan-card .type-tag { padding:0 4px; border-radius:2px; background:#21262d; }
  .kan-card .pts { color:var(--accent); }
  .kan-card .assignee { color:var(--state-in_progress); }

  /* Activity strip */
  #activity {
    background:var(--panel); border:1px solid var(--border); border-radius:6px;
    padding:8px 12px; max-height:340px; overflow-y:auto;
    font-family:"SF Mono",Menlo,Consolas,monospace; font-size:11.5px;
  }
  .act-row {
    padding:4px 0; border-bottom:1px dashed #21262d;
    display:grid; grid-template-columns:60px 20px 1fr; gap:8px; align-items:baseline;
  }
  .act-row:last-child { border-bottom:none; }
  .act-row .ts { color:var(--muted); font-size:10.5px; }
  .act-row .emoji { text-align:center; font-size:14px; }
  .act-row .msg { color:var(--fg); }
  .act-row .msg .story-id { color:var(--accent); }
  .act-row .msg .voter { color:var(--state-in_progress); }
  .act-row .msg .points { color:var(--wiki); font-weight:600; }
  .act-row .msg .just { color:var(--muted); font-style:italic; }
  .act-row.fresh {
    animation: fresh-row 1.6s ease-out;
  }
  @keyframes fresh-row {
    0% { background:#1f6feb33; }
    100% { background:transparent; }
  }

  /* Story list (below kanban — full table view) */
  .stories { background:var(--panel); border:1px solid var(--border); border-radius:6px; }
  .story-row { padding:10px 14px; border-bottom:1px solid var(--border); cursor:pointer;
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

  .envelope-summary {
    background:#0b0f14; border:1px solid var(--accent); border-radius:6px;
    padding:12px 14px; margin:10px 0; color:var(--fg); font-size:13px;
    line-height:1.55;
  }
  .envelope-summary .kv { display:grid; grid-template-columns:120px 1fr; gap:6px 12px; font-size:12px; }
  .envelope-summary .kv .k { color:var(--muted); text-transform:uppercase; letter-spacing:0.4px; font-size:10.5px; }
  .envelope-summary .kv .v { font-family:"SF Mono",monospace; font-size:11.5px; word-break:break-word; }
  .envelope-summary .status-committed { color:var(--good); font-weight:600; }
  .envelope-summary .status-failed    { color:var(--bad); font-weight:600; }
  .envelope-summary .status-no_commit { color:var(--bad); }
  .envelope-summary .story-summary { color:var(--fg); font-size:13px; margin-bottom:8px; }
  .section-heading {
    margin:16px 0 6px 0; font-size:12px; color:var(--muted); text-transform:uppercase;
    letter-spacing:0.4px; font-weight:500; border-top:1px solid var(--border);
    padding-top:10px;
  }

  .wiki-block {
    background:#1a1305; border:1px dashed var(--wiki); border-radius:6px;
    padding:12px 14px; margin-top:8px;
    font-family:"SF Mono",monospace; font-size:11.5px; white-space:pre-wrap;
    max-height:360px; overflow-y:auto;
  }
  .sprint-timeline {
    display:grid; gap:8px;
  }
  .sprint-row {
    background:var(--panel); border:1px solid var(--border); border-radius:6px;
    padding:12px 14px; display:grid;
    grid-template-columns:60px 90px 1fr 120px; gap:12px; align-items:center;
    font-size:12.5px;
  }
  .sprint-row.current { border-left:3px solid var(--good); }
  .sprint-row .num {
    font-family:"SF Mono",monospace; font-weight:600; font-size:14px;
    color:var(--accent); text-align:center;
  }
  .sprint-row .bar {
    background:#0b0f14; border-radius:4px; padding:4px 8px; font-size:11px;
    display:flex; gap:8px; font-variant-numeric:tabular-nums;
  }
  .sprint-row .bar .done { color:var(--good); }
  .sprint-row .bar .blocked { color:var(--bad); }
  .sprint-row .action {
    color:var(--fg); font-style:italic; font-size:12px;
  }
  .sprint-row .action:before { content: "🎯 "; }
  .sprint-row .meta {
    color:var(--muted); font-size:10.5px; text-align:right;
    font-variant-numeric:tabular-nums;
  }

  .retro-block {
    background:#0b1a12; border:1px solid var(--good); border-radius:8px;
    padding:16px 20px; margin-top:8px; font-size:13px;
  }
  .retro-block h4 { margin:12px 0 6px 0; font-size:12px; color:var(--muted);
    text-transform:uppercase; letter-spacing:0.5px; font-weight:500; }
  .retro-block h4:first-child { margin-top:0; }
  .retro-block ul { margin:0; padding-left:20px; color:var(--fg); }
  .retro-block li { margin-bottom:4px; }
  .retro-block .action { background:#0d3d1c; border-radius:4px; padding:8px 12px;
    color:var(--good); font-weight:500; margin-top:4px; }
  .retro-block .header { color:var(--muted); font-size:11px; margin-bottom:12px;
    padding-bottom:8px; border-bottom:1px solid #21262d; }

  .agent-row {
    display: grid; grid-template-columns: 120px 80px 1fr 120px 80px;
    gap: 12px; padding: 8px 12px; border-bottom: 1px solid var(--border);
    font-size: 12.5px;
  }
  .agent-row .role { font-weight: 500; }
  .agent-row .status.alive { color: var(--good); }
  .agent-row .status.dead { color: var(--bad); }
  .agent-row .story { color: var(--muted); font-family: "SF Mono", monospace; }
  .agent-row .last { color: var(--muted); font-size: 11px; }
  .agent-row .restarts { color: var(--muted); font-variant-numeric: tabular-nums; text-align: right; }
</style>
</head>
<body>
<header>
  <div>
    <h1>
      <span>orgos team — <span id="team-id"></span></span>
      <span id="live-badge"><span class="dot"></span> LIVE</span>
    </h1>
    <div class="goal" id="goal"></div>
    <div class="meta" id="meta"></div>
  </div>
  <div class="right" id="right-meta"></div>
</header>
<main>

<section>
  <h2>Totals</h2>
  <div class="cards" id="cards"></div>
</section>

<section>
  <h2>Agents</h2>
  <div id="agent-statuses"></div>
</section>

<section>
  <h2>Board <span class="count" id="kanban-count"></span></h2>
  <div class="kanban" id="kanban"></div>
</section>

<section>
  <h2>Live activity <span class="count" id="act-count"></span></h2>
  <div id="activity"></div>
</section>

<section id="sprint-timeline-section" style="display:none;">
  <h2>Sprint timeline <span class="count" id="sprint-timeline-count"></span></h2>
  <div class="sprint-timeline" id="sprint-timeline"></div>
</section>

<section id="retro-section" style="display:none;">
  <h2>Latest sprint retrospective</h2>
  <div class="retro-block" id="retro"></div>
</section>

<section>
  <h2>Wiki decisions (tail)</h2>
  <div class="wiki-block" id="wiki"></div>
</section>

<section>
  <h2>Stories (full table)</h2>
  <div class="stories" id="stories"></div>
  <div class="detail" id="detail" style="display:none;">
    <h3 id="d-title"></h3>
    <div class="body" id="d-body"></div>

    <div class="envelope-summary" id="d-envelope-summary"></div>

    <h4 class="section-heading">Diff (this story's commit)</h4>
    <pre class="diff" id="d-diff"></pre>

    <h4 class="section-heading">Audit trail</h4>
    <div class="audit" id="d-audit"></div>

    <details><summary>Poker votes</summary><pre id="d-votes"></pre></details>
    <details><summary>Full envelope JSON</summary><pre id="d-envelope"></pre></details>
  </div>
</section>

<section>
  <h2>Full branch diff (all commits since baseline)</h2>
  <pre class="diff" id="full-diff" style="max-height:500px;">(loading…)</pre>
</section>

</main>

<script>
// Initial data — populated when the report is written statically.
// In live mode, /live/state overwrites these on each poll.
let MANIFEST = __MANIFEST__;
let RESULT = __RESULT__;
let STORIES = __STORIES__;
let AUDIT = __AUDIT__;
let WIKI = __WIKI_TAIL__;
let RESULTS_BY_STORY = __RESULTS_BY_STORY__;
let EVENTS = __EVENTS__;
let SPRINT_HISTORY = __SPRINT_HISTORY__;
let AGENT_STATUSES = __AGENT_STATUSES__;

const STATE_ORDER = ["draft", "refinement", "ready", "in_progress", "review", "done"];
// Blocked is shown as an extra column when non-empty.
const KAN_STATE_ORDER = ["draft", "refinement", "ready", "in_progress", "review", "done"];

function esc(s) { return String(s == null ? "" : s).replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c])); }
function fmt(n, dp=0) { if (n==null) return "—"; if (typeof n !== "number") return n;
  return n.toLocaleString(undefined, {maximumFractionDigits: dp}); }
function pricingCost(model, tin, tout) {
  const p = ({"deepseek/deepseek-chat":{i:0.27,o:1.10},
              "deepseek/deepseek-reasoner":{i:0.55,o:2.19},
              "unknown":{i:0.50,o:1.50}})[model] || {i:0.50,o:1.50};
  return (tin/1e6)*p.i + (tout/1e6)*p.o;
}

function renderAgents() {
  const el = document.getElementById("agent-statuses");
  if (!el) return;
  const rows = AGENT_STATUSES || [];
  el.innerHTML = rows.map(a => `
    <div class="agent-row">
      <div class="role">${esc(a.role)}</div>
      <div class="status ${a.is_alive ? 'alive' : 'dead'}">${a.is_alive ? '● live' : '○ down'}</div>
      <div class="story">${esc(a.current_story || '(idle)')}</div>
      <div class="last">${esc((a.last_event_at || '').slice(11, 19))}</div>
      <div class="restarts">${a.restart_count > 0 ? '↺' + a.restart_count : ''}</div>
    </div>
  `).join("");
}

function renderHeader() {
  document.getElementById("team-id").textContent = MANIFEST.team_id || "(no team)";
  document.getElementById("goal").textContent = MANIFEST.goal || "";
  document.getElementById("meta").textContent =
    "model: " + (MANIFEST.model || "?") +
    " · created: " + (MANIFEST.created_at || "").slice(0,19).replace("T"," ") +
    " · branch: " + (MANIFEST.branch || "");
}

function renderTotals() {
  const tin = RESULT.total_tokens_input || 0;
  const tout = RESULT.total_tokens_output || 0;
  const cost = pricingCost(MANIFEST.model || "unknown", tin, tout);
  const counts = {};
  for (const s of Object.values(STORIES)) counts[s.state] = (counts[s.state]||0) + 1;
  const totals = [
    {l:"stories created", v: Object.keys(STORIES).length},
    {l:"done", v: counts.done || 0},
    {l:"in progress", v: counts.in_progress || 0},
    {l:"blocked", v: counts.blocked || 0},
    {l:"tokens (in+out)", v: fmt(tin + tout, 0)},
    {l:"cost (USD)", v: "$" + fmt(cost, 4)},
    {l:"stopped", v: RESULT.reason_stopped || "—"},
  ];
  if (RESULT.pr_url) {
    totals.push({l:"draft PR", raw: true,
                 v: '<a href="' + esc(RESULT.pr_url) + '" target="_blank" style="color:var(--accent);text-decoration:underline;">open ↗</a>'});
  }
  const el = document.getElementById("cards");
  el.innerHTML = "";
  for (const t of totals) {
    const d = document.createElement("div");
    d.className = "card";
    const vHtml = t.raw ? t.v : esc(t.v);
    d.innerHTML = '<div class="l">'+esc(t.l)+'</div><div class="v">'+vHtml+'</div>';
    el.appendChild(d);
  }
}

// Track which story IDs are already rendered where so we can add
// a "fresh" pulse when a story moves columns.
let lastStoryStateHash = {};

function renderKanban() {
  const el = document.getElementById("kanban");
  const kanCount = document.getElementById("kanban-count");
  const cols = KAN_STATE_ORDER.slice();
  const hasBlocked = Object.values(STORIES).some(s => s.state === "blocked");
  if (hasBlocked) cols.push("blocked");
  kanCount.textContent = "(" + Object.keys(STORIES).length + " total)";

  // If the number of columns changed, rebuild from scratch
  if (el.children.length !== cols.length) {
    el.innerHTML = "";
    for (const state of cols) {
      const col = document.createElement("div");
      col.className = "kan-col state-" + state;
      col.dataset.state = state;
      col.innerHTML = '<h3><span>' + state.replace('_',' ') + '</span><span class="n">0</span></h3><div class="col-body"></div>';
      el.appendChild(col);
    }
  }

  // Bucket stories
  const buckets = {};
  for (const s of cols) buckets[s] = [];
  for (const s of Object.values(STORIES)) {
    if (buckets[s.state]) buckets[s.state].push(s);
  }

  // Sort each bucket by priority desc, then by id
  for (const state of cols) {
    buckets[state].sort((a,b) => (b.priority||0) - (a.priority||0) || a.issue_id.localeCompare(b.issue_id));
  }

  // Render
  for (const state of cols) {
    const col = el.querySelector('.kan-col[data-state="' + state + '"]');
    col.querySelector(".n").textContent = buckets[state].length;
    const body = col.querySelector(".col-body");
    body.innerHTML = "";
    for (const s of buckets[state]) {
      const prevState = lastStoryStateHash[s.issue_id];
      const isFresh = prevState && prevState !== s.state;
      lastStoryStateHash[s.issue_id] = s.state;
      const card = document.createElement("div");
      card.className = "kan-card" + (isFresh ? " fresh" : "");
      card.dataset.id = s.issue_id;
      card.innerHTML =
        '<div class="title">' + esc(s.title) + '</div>' +
        '<div class="meta">' +
          '<span class="type-tag">' + esc(s.type) + '</span>' +
          (s.points != null ? '<span class="pts">' + s.points + 'pt</span>' : '') +
          (s.assignee ? '<span class="assignee">@' + esc(s.assignee) + '</span>' : '') +
        '</div>';
      card.addEventListener("click", () => showDetail(s.issue_id));
      body.appendChild(card);
    }
  }
}

// Activity strip
let renderedEventKeys = new Set();
function eventKey(e) { return e.timestamp + "|" + e.action + "|" + (e.story_id||"") + "|" + (e.voter||""); }

function formatEventMsg(e) {
  const sid = e.story_id ? '<span class="story-id">' + esc(e.story_id.slice(0, 34)) + '</span>' : "";
  switch (e.action) {
    case "campaign_started":
      return "campaign started (mode=<b>" + esc(e.mode || "?") + "</b>)";
    case "goal_ingest_start": return "PO decomposing the goal";
    case "goal_ingest_done": return "PO produced <b>" + e.n_stories + "</b> stories";
    case "goal_ingest_failed": return "decomposition FAILED: " + esc(e.summary);
    case "decomposition_warning":
      return "overlap warning: " + sid + " ↔ " + esc(e.other || "") +
        " share " + esc(JSON.stringify(e.shared_paths || []));
    case "story_drafted": return "drafted " + sid + " <span class=\"type-tag\">" + esc(e.type) + "</span> — " + esc(e.title || "");
    case "poker_vote":
      return "<span class=\"voter\">" + esc(e.voter) + "</span> voted <span class=\"points\">" + e.points + " pts</span> on " + sid +
        (e.justification ? ' <span class="just">"' + esc(e.justification) + '"</span>' : "");
    case "poker_divergent":
      return "poker divergent on " + sid + " (votes " + JSON.stringify(e.votes || []) + ") — discussion round";
    case "refined_ready":
      return sid + " refined → <b>READY</b> (points=" + (e.points ?? "?") + ")";
    case "refined_blocked":
      return sid + " refined → <b>BLOCKED</b> — " + esc(e.summary || "");
    case "story_pulled":
      return "<span class=\"voter\">" + esc(e.worker) + "</span> pulled " + sid + " (" + esc(e.story_type) + ")";
    case "commit_landed":
      return sid + " committed <b>" + esc(e.commit_sha) + "</b>";
    case "story_no_commit":
      return sid + " NO COMMIT (" + esc(e.summary || "") + ")";
    case "story_done_noop":
      return sid + " <b>DONE (no-op)</b> — already satisfied: " + esc(e.summary || "");
    case "story_review_pass":
      return sid + " review <b>PASS</b> — " + esc(e.summary || "");
    case "story_review_fail":
      return sid + " review <b>FAIL</b>";
    case "wiki_write":
      return "wiki updated (" + esc(e.summary || "DECISIONS.md") + ")";
    case "campaign_finished":
      return "campaign done — stopped: <b>" + esc(e.reason || "") + "</b>";
    case "pr_opened":
      return "draft PR opened: <a href=\"" + esc(e.pr_url || "") + "\" target=\"_blank\" style=\"color:var(--accent);\">"
        + esc(e.pr_url || "") + "</a>";
    case "pr_skipped":
      return "PR skipped: " + esc(e.reason || e.summary || "");
    case "pr_failed":
      return "PR FAILED: " + esc(e.error || e.summary || "");
    case "retro_started":
      return "scrum master writing sprint retrospective";
    case "retro_written":
      return "retrospective written → <code>" + esc(e.path || "wiki/RETRO.md") + "</code>" +
        (e.action_item ? " (action: <em>" + esc(e.action_item) + "</em>)" : "");
    case "retro_failed":
      return "retro FAILED: " + esc(e.error || e.summary || "");
    case "replan_started":
      return "PO planning next sprint";
    case "replan_done":
      return "next sprint planned: " + esc(e.summary || "");
    case "replan_failed":
      return "replan FAILED: " + esc(e.error || e.summary || "");
    case "multi_sprint_started":
      return "multi-sprint run started (" + (e.n_sprints || "?") + " sprints planned)";
    case "multi_sprint_finished":
      return "multi-sprint run finished: " + esc(e.summary || "");
    default:
      return esc(e.label || e.action) + " " + sid;
  }
}

function renderActivity(newlyAddedOnly) {
  const el = document.getElementById("activity");
  const countEl = document.getElementById("act-count");
  const events = EVENTS || [];
  countEl.textContent = "(" + events.length + " events)";

  // We render bottom-up; latest at bottom.
  if (!newlyAddedOnly) {
    el.innerHTML = "";
    renderedEventKeys = new Set();
  }
  let addedAny = false;
  for (const e of events) {
    const k = eventKey(e);
    if (renderedEventKeys.has(k)) continue;
    renderedEventKeys.add(k);
    const row = document.createElement("div");
    row.className = "act-row" + (newlyAddedOnly ? " fresh" : "");
    const ts = (e.timestamp || "").slice(11, 19);
    row.innerHTML =
      '<span class="ts">' + esc(ts) + '</span>' +
      '<span class="emoji">' + esc(e.emoji || "•") + '</span>' +
      '<span class="msg">' + formatEventMsg(e) + '</span>';
    el.appendChild(row);
    addedAny = true;
  }
  if (addedAny) el.scrollTop = el.scrollHeight;
}

function renderWiki() {
  document.getElementById("wiki").textContent = WIKI || "(no wiki entries yet)";
}

function renderSprintTimeline() {
  const section = document.getElementById("sprint-timeline-section");
  const el = document.getElementById("sprint-timeline");
  const countEl = document.getElementById("sprint-timeline-count");
  if (!section || !el) return;
  const hist = SPRINT_HISTORY || [];
  if (hist.length < 1) { section.style.display = "none"; return; }
  section.style.display = "block";
  countEl.textContent = "(" + hist.length + " " + (hist.length === 1 ? "sprint" : "sprints") + ")";
  const lastNum = hist[hist.length - 1].sprint_num;
  el.innerHTML = hist.map(r => {
    const isCurrent = r.sprint_num === lastNum;
    const stop = (r.reason_stopped || "").split("(")[0].trim();
    return (
      '<div class="sprint-row' + (isCurrent ? ' current' : '') + '">' +
        '<div class="num">S' + r.sprint_num + '</div>' +
        '<div class="bar">' +
          '<span class="done">✓ ' + (r.stories_done || 0) + '</span>' +
          '<span class="blocked">⛔ ' + (r.stories_blocked || 0) + '</span>' +
          (r.spe ? '<span class="spe">⚡ SPE ' + Math.round(r.spe * 100) + '%</span>' : '') +
        '</div>' +
        '<div class="action">' + esc(r.retro_action_item || "(no action item)") + '</div>' +
        '<div class="meta">' + esc(stop || "?") + '</div>' +
      '</div>'
    );
  }).join("");
}

// ── Retrospective ──────────────────────────────────────────────────
// Parse the latest "## Retro — sprint <id>" block out of the retro payload
// (which we fetch separately from wiki/RETRO.md) and render it.
let RETRO_MD = "";
async function refreshRetro() {
  const el = document.getElementById("retro");
  const section = document.getElementById("retro-section");
  if (!el || !section) return;
  try {
    const r = await fetch("/live/retro", {cache: "no-store"});
    if (!r.ok) throw new Error("no retro");
    RETRO_MD = await r.text();
  } catch (e) {
    section.style.display = "none";
    return;
  }
  // Extract the LAST block starting with "## Retro — sprint <this team>"
  const teamId = MANIFEST.team_id || "";
  const blockRe = new RegExp("## Retro — sprint " + teamId.replace(/[.*+?^${}()|[\\]\\\\]/g,'\\\\$&') + "[\\s\\S]*?(?=\\n## |$)", "g");
  const matches = [...RETRO_MD.matchAll(blockRe)];
  if (!matches.length) { section.style.display = "none"; return; }
  const block = matches[matches.length - 1][0];
  section.style.display = "block";

  // Naive parse of the retro sections
  function bullets(section) {
    const re = new RegExp("### " + section + "\\n((?:  - .+\\n?)+)");
    const m = block.match(re);
    if (!m) return [];
    return m[1].trim().split("\n").map(l => l.replace(/^\s*-\s*/, "").trim()).filter(Boolean);
  }
  function actionItem() {
    const m = block.match(/### Action item for next sprint\n\s*(.+)/);
    return m ? m[1].trim() : "";
  }
  function meta(field) {
    const m = block.match(new RegExp("- " + field + ":\\s*(.+)"));
    return m ? m[1].trim() : "";
  }

  const wentWell = bullets("What went well");
  const wentWrong = bullets("What went wrong");
  const action = actionItem();
  el.innerHTML =
    '<div class="header">by ' + esc(meta("author")) + ' · ' + esc(meta("timestamp")) +
      ' · stopped: <code>' + esc(meta("stopped")) + '</code></div>' +
    '<h4>✅ What went well</h4>' +
    '<ul>' + wentWell.map(b => '<li>' + esc(b) + '</li>').join("") + '</ul>' +
    '<h4>⚠️ What went wrong</h4>' +
    '<ul>' + wentWrong.map(b => '<li>' + esc(b) + '</li>').join("") + '</ul>' +
    '<h4>🎯 Action item for next sprint</h4>' +
    '<div class="action">' + esc(action || "(none)") + '</div>';
}

function renderStoryTable() {
  const stateOrder = {done:0, review:1, in_progress:2, ready:3, refinement:4, draft:5, blocked:6};
  const ids = Object.keys(STORIES).sort((a,b) => {
    const sa = stateOrder[STORIES[a].state] ?? 9;
    const sb = stateOrder[STORIES[b].state] ?? 9;
    if (sa !== sb) return sa - sb;
    return (STORIES[b].priority||0) - (STORIES[a].priority||0);
  });
  const el = document.getElementById("stories");
  el.innerHTML = "";
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
    el.appendChild(row);
  }
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

function renderEnvelopeSummary(r, story) {
  if (!r || !r.envelope) {
    return '<div class="story-summary">(no work result yet for this story)</div>';
  }
  const env = r.envelope || {};
  const payload = env.payload || {};
  const statusClass = "status-" + (r.status || "");
  const files = payload.files_touched || [];
  const filesStr = Array.isArray(files) && files.length
    ? files.join(", ") : "(none)";
  const testCmd = payload.test_command || "(no test run)";
  const testPassed = payload.test_passed;
  const testStr = testPassed === true ? '<span class="status-committed">passed</span>'
                : testPassed === false ? '<span class="status-failed">failed</span>'
                : "(not run)";
  return (
    '<div class="story-summary"><b>' + esc(env.summary || "(no summary)") + '</b></div>' +
    '<div class="kv">' +
      '<div class="k">worker</div>       <div class="v">' + esc(r.role || "?") + '</div>' +
      '<div class="k">status</div>       <div class="v ' + statusClass + '">' + esc(r.status || "?") + '</div>' +
      '<div class="k">commit</div>       <div class="v">' + esc((r.commit_sha || "").slice(0,10) || "(none)") + '</div>' +
      '<div class="k">files touched</div><div class="v">' + esc(filesStr) + '</div>' +
      '<div class="k">test command</div> <div class="v">' + esc(testCmd) + '</div>' +
      '<div class="k">test result</div>  <div class="v">' + testStr + '</div>' +
      '<div class="k">tokens</div>       <div class="v">' + fmt((r.tokens_input||0)+(r.tokens_output||0),0) + '</div>' +
      '<div class="k">wall seconds</div> <div class="v">' + fmt(r.wall_seconds, 1) + '</div>' +
    '</div>'
  );
}

function showDetail(id) {
  document.querySelectorAll(".story-row").forEach(r =>
    r.classList.toggle("active", r.dataset.id === id));
  document.getElementById("detail").style.display = "block";
  const s = STORIES[id];
  if (!s) return;
  document.getElementById("d-title").textContent = "[" + s.type + "] " + s.title + "  (" + s.state + ")";
  document.getElementById("d-body").textContent = s.body || "(no body)";
  const r = (RESULTS_BY_STORY || {})[id] || {};
  document.getElementById("d-envelope-summary").innerHTML = renderEnvelopeSummary(r, s);
  const trail = (AUDIT || {})[id] || [];
  document.getElementById("d-audit").innerHTML = trail.map(e =>
    '<div class="row"><span>'+esc((e.timestamp||"").slice(11,19))+'</span> ' +
    '<span class="action">'+esc(e.action)+'</span> ' +
    '<span>by '+esc(e.actor||"?")+'</span> ' +
    (e.to_state ? '<span>→ '+esc(e.to_state)+'</span>' : '') +
    (e.reason ? '<span> ('+esc(e.reason)+')</span>' : '') +
    '</div>'
  ).join("");
  document.getElementById("d-votes").textContent = JSON.stringify(s.votes || [], null, 2);
  document.getElementById("d-envelope").textContent = JSON.stringify(r.envelope || {}, null, 2);
  document.getElementById("d-diff").innerHTML = renderDiff(r.diff_summary || "(no per-story diff captured)");
}

// Full-branch diff — fetch from /live/diff (works in live mode) or falls back
// to a message when opened statically. Updates periodically in live mode.
async function refreshFullDiff() {
  const el = document.getElementById("full-diff");
  if (!el) return;
  try {
    const r = await fetch("/live/diff", {cache: "no-store"});
    if (!r.ok) throw new Error("no diff endpoint");
    const text = await r.text();
    el.innerHTML = renderDiff(text || "(no diff)");
  } catch (e) {
    el.textContent = "(diff endpoint unavailable — open with `orgos serve` to see the live branch diff)";
  }
}

// ── Live polling ─────────────────────────────────────────────────────
let liveMode = false;
let lastEventTs = "";
async function tryEnterLiveMode() {
  try {
    const r = await fetch("/live/state", {cache: "no-store"});
    if (!r.ok) return;
    liveMode = true;
    document.getElementById("live-badge").classList.add("on");
    scheduleNextPoll();
  } catch (e) {
    // Not served — stay in static mode.
  }
}

async function pollOnce() {
  try {
    const r = await fetch("/live/state", {cache: "no-store"});
    if (!r.ok) throw new Error("state fetch failed");
    const j = await r.json();
    // Fold in updates
    STORIES = j.stories || STORIES;
    AUDIT = j.audit || AUDIT;
    WIKI = j.wiki || WIKI;
    RESULT = j.result || RESULT;
    RESULTS_BY_STORY = j.results_by_story || RESULTS_BY_STORY;
    SPRINT_HISTORY = j.sprint_history || SPRINT_HISTORY;
    AGENT_STATUSES = j.agent_statuses || AGENT_STATUSES;
    // Tail events since last seen
    const evUrl = "/live/tail" + (lastEventTs ? ("?since=" + encodeURIComponent(lastEventTs)) : "");
    const er = await fetch(evUrl, {cache: "no-store"});
    if (er.ok) {
      const newEvents = await er.json();
      if (newEvents && newEvents.length) {
        EVENTS = (EVENTS || []).concat(newEvents);
        lastEventTs = newEvents[newEvents.length - 1].timestamp;
        renderActivity(true);
      }
    }
    renderTotals();
    renderAgents();
    renderKanban();
    renderSprintTimeline();
    renderStoryTable();
    renderWiki();
    refreshFullDiff();
    refreshRetro();
  } catch (e) {
    // Server likely stopped — turn off live badge and stop polling
    document.getElementById("live-badge").classList.remove("on");
    liveMode = false;
    return;
  }
  scheduleNextPoll();
}

function scheduleNextPoll() {
  if (!liveMode) return;
  setTimeout(pollOnce, 2000);
}

// ── Initial render ───────────────────────────────────────────────────
renderHeader();
renderTotals();
renderAgents();
renderKanban();
renderActivity(false);
renderWiki();
renderStoryTable();
renderSprintTimeline();
refreshFullDiff();
refreshRetro();
if (EVENTS && EVENTS.length) lastEventTs = EVENTS[EVENTS.length - 1].timestamp;
tryEnterLiveMode();
</script>
</body>
</html>
"""


def collect_blocked_reasons(workspace) -> dict:
    """Bucket blocked stories by category so the team knows what's hurting.

    Categories: no_commit, merge_conflict, dod, dropped, other.
    Read from board audit trails (the reason text is stamped on the
    `transition ... to blocked` action).
    """
    board = BoardStore(workspace.board_dir)
    buckets = {"no_commit": 0, "merge_conflict": 0, "dod": 0,
               "dropped": 0, "other": 0}
    reason_by_story: dict[str, str] = {}
    for s in board.list_state("blocked"):
        trail = board.audit_trail(s.issue_id)
        last_reason = ""
        for e in reversed(trail):
            if e.get("action") == "transition" and e.get("to_state") == "blocked":
                last_reason = e.get("reason", "") or ""
                break
        reason_by_story[s.issue_id] = last_reason
        text = last_reason.lower()
        if "no_commit" in text or "no commit" in text or "attempts" in text:
            buckets["no_commit"] += 1
        elif "merge_conflict" in text or "merge conflict" in text or "ff_failed" in text:
            buckets["merge_conflict"] += 1
        elif "dod" in text:
            buckets["dod"] += 1
        elif "dropped" in text:
            buckets["dropped"] += 1
        else:
            buckets["other"] += 1
    return {"totals": buckets, "by_story": reason_by_story}


def _enumerate_agent_instances(workspace) -> list[str]:
    """Return every agent instance key that has a worktree on disk.

    Keys look like `po`, `scrum_master`, `architect`, `architect#1`,
    `architect#2`, `test`, `test#1`, `devsecops`, etc. — matching the
    `actor` string an AsyncAgent uses to emit events.

    Falls back to the historical singleton list if the workspace has no
    agents/ dir yet (bootstrap/tests).
    """
    fallback = ["po", "scrum_master", "architect", "test", "devsecops"]
    try:
        agents_root = getattr(workspace, "agents_root", None)
        if agents_root is None or not agents_root.exists():
            return fallback
        keys: list[str] = []
        for d in sorted(agents_root.iterdir()):
            if not d.is_dir():
                continue
            name = d.name  # e.g. 'architect' or 'architect-1'
            if "-" in name and name.rsplit("-", 1)[-1].isdigit():
                role, inst = name.rsplit("-", 1)
                key = role if inst == "0" else f"{role}#{inst}"
            else:
                key = name
            if key not in keys:
                keys.append(key)
        return keys or fallback
    except (OSError, AttributeError):
        return fallback


def collect_agent_statuses(workspace) -> list[dict]:
    """Read each agent's current status from disk. Best-effort.

    Returns a list of dicts, one per agent INSTANCE. Distinguishes
    ALIVE-IDLE from DEAD via agent_heartbeat events (§H5) — an agent
    that's ticking will fire a heartbeat every ~120s even when nothing
    to pull, whereas a stuck agent stops firing them.
    """
    events = read_events(workspace.root)
    keys = _enumerate_agent_instances(workspace)
    status = {
        k: {
            "role": k, "is_alive": False,
            "current_story": "", "last_event_at": "",
            "last_heartbeat_at": "",
            "restart_count": 0,
            "pull_success": 0, "pull_idle": 0, "pull_attempts": 0,
        }
        for k in keys
    }
    for e in events:
        # Prefer per-instance worker field (§H5); fall back to bare role
        worker = e.get("worker") or ""
        role_bare = e.get("role") or ""
        if worker and worker in status:
            key = worker
        elif worker:
            key = worker.split("#", 1)[0]
        else:
            key = role_bare.split("#", 1)[0]
        if key not in status:
            continue
        s = status[key]
        s["last_event_at"] = e.get("timestamp", s["last_event_at"])
        action = e.get("action", "")
        if action == "agent_started":
            s["is_alive"] = True
        elif action in ("agent_stopped", "agent_crashed"):
            s["is_alive"] = False
        elif action == "agent_restarted":
            s["is_alive"] = True
            s["restart_count"] += 1
        elif action == "agent_heartbeat":
            # §H5 — the definitive alive signal
            s["is_alive"] = True
            s["last_heartbeat_at"] = e.get("timestamp", "")
            s["pull_attempts"] = e.get("pull_attempts", s["pull_attempts"])
            s["pull_success"] = e.get("pull_success", s["pull_success"])
            s["pull_idle"] = e.get("pull_idle", s["pull_idle"])
        elif action == "story_pulled":
            s["current_story"] = e.get("story_id", "")
        elif action in ("commit_landed", "story_done_noop",
                        "story_no_commit", "story_review_pass"):
            s["current_story"] = ""
    return [status[k] for k in keys]


def render_team_report(workspace: TeamWorkspace) -> Path:
    """Render <workspace.root>/report.html. Returns the path."""
    manifest = _load(workspace.manifest_path)
    result = _load(workspace.root / "campaign_result.json")

    board = BoardStore(workspace.board_dir)
    stories = {s.issue_id: asdict(s) for s in board.all_stories()}
    audit = {iid: board.audit_trail(iid) for iid in stories}

    wiki_tail = _wiki_decisions_tail(workspace.wiki_dir)
    if wiki_tail == "(no DECISIONS.md yet)":
        wiki_tail = _wiki_decisions_tail(workspace.source_repo / "wiki")

    events = read_events(workspace.root)
    from dataclasses import asdict as _asdict
    history = [_asdict(r) for r in read_history(workspace.root)]

    results_by_story: dict = {}
    for r in result.get("per_story_results", []):
        results_by_story[r.get("story_id", "")] = r

    html_content = _HTML
    replacements = {
        "__TEAM_ID__": html.escape(manifest.get("team_id", "")),
        "__MANIFEST__": json.dumps(manifest),
        "__RESULT__": json.dumps(result),
        "__STORIES__": json.dumps(stories),
        "__AUDIT__": json.dumps(audit),
        "__WIKI_TAIL__": json.dumps(wiki_tail),
        "__EVENTS__": json.dumps(events),
        "__RESULTS_BY_STORY__": json.dumps(results_by_story),
        "__SPRINT_HISTORY__": json.dumps(history),
        "__AGENT_STATUSES__": json.dumps(collect_agent_statuses(workspace)),
    }
    for k, v in replacements.items():
        html_content = html_content.replace(k, v)

    out_path = workspace.root / "report.html"
    out_path.write_text(html_content, encoding="utf-8")
    return out_path


# ── Public helpers used by the serve endpoint ────────────────────────────

def build_state_payload(workspace: TeamWorkspace) -> dict:
    """The JSON payload returned by /live/state."""
    manifest = _load(workspace.manifest_path)
    result = _load(workspace.root / "campaign_result.json")
    board = BoardStore(workspace.board_dir)
    stories = {s.issue_id: asdict(s) for s in board.all_stories()}
    audit = {iid: board.audit_trail(iid) for iid in stories}
    wiki_tail = _wiki_decisions_tail(workspace.wiki_dir)
    if wiki_tail == "(no DECISIONS.md yet)":
        wiki_tail = _wiki_decisions_tail(workspace.source_repo / "wiki")
    results_by_story = {r.get("story_id", ""): r
                         for r in result.get("per_story_results", [])}
    from dataclasses import asdict as _asdict
    history = [_asdict(r) for r in read_history(workspace.root)]
    return {
        "manifest": manifest,
        "result": result,
        "stories": stories,
        "audit": audit,
        "wiki": wiki_tail,
        "results_by_story": results_by_story,
        "sprint_history": history,
        "agent_statuses": collect_agent_statuses(workspace),
    }
