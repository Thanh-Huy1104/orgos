"""Self-contained HTML report renderer for benchmark runs.

Reads benchmark_reports/<run_id>/{team,scrum,solo}/*.json and produces a
single report.html with everything embedded — no CDN, no server, no
external deps.

Approaches:
  - team  = waterfall (5-role sequential handoff pipeline)
  - scrum = self-organizing (N interchangeable full-stack workers, shared wiki)
  - solo  = single-agent baseline (no team, no wiki)

Open the resulting file in any browser.
"""

from __future__ import annotations

import html
import json
from pathlib import Path


APPROACHES = ("team", "scrum", "solo")
APPROACH_LABELS = {"team": "waterfall team", "scrum": "scrum team", "solo": "solo"}
APPROACH_COLORS = {"team": "#fb923c", "scrum": "#4ade80", "solo": "#a78bfa"}


def _load_runs(base: Path) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {a: [] for a in APPROACHES}
    for approach in APPROACHES:
        d = base / approach
        if not d.exists():
            continue
        for f in sorted(d.glob("*.json")):
            try:
                out[approach].append(json.loads(f.read_text()))
            except Exception:
                continue
    return out


def _load_summary(base: Path) -> dict:
    p = base / "summary.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def _load_manifest(base: Path) -> dict:
    p = base / "manifest.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text())


_HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>orgos benchmark — __RUN_ID__</title>
<style>
  :root {
    --bg: #0d1117;
    --panel: #161b22;
    --border: #30363d;
    --fg: #e6edf3;
    --muted: #7d8590;
    --accent: #58a6ff;
    --team:  #fb923c;   /* waterfall */
    --scrum: #4ade80;   /* self-organizing */
    --solo:  #a78bfa;   /* baseline */
    --good: #4ade80;
    --bad: #f87171;
    --add: #033a16;
    --rem: #67060c;
    --add-fg: #7ee787;
    --rem-fg: #ffa198;
  }
  * { box-sizing: border-box; }
  html, body {
    margin: 0; padding: 0;
    background: var(--bg); color: var(--fg);
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI",
                 Roboto, Helvetica, Arial, sans-serif;
    font-size: 14px; line-height: 1.5;
  }
  header {
    padding: 24px 32px; border-bottom: 1px solid var(--border);
    display: flex; align-items: baseline; justify-content: space-between;
    flex-wrap: wrap; gap: 16px;
  }
  header h1 { margin: 0; font-size: 20px; }
  header .meta { color: var(--muted); font-size: 12px; }
  main { padding: 24px 32px; max-width: 1600px; margin: 0 auto; }
  section { margin-bottom: 40px; }
  section h2 {
    font-size: 16px; margin: 0 0 12px 0;
    padding-bottom: 6px; border-bottom: 1px solid var(--border);
    color: var(--muted); font-weight: 500;
  }
  .cards { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }
  .card {
    background: var(--panel); border: 1px solid var(--border); border-radius: 6px;
    padding: 14px;
  }
  .card .label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px; }
  .card .row { font-size: 14px; font-variant-numeric: tabular-nums; margin-top: 3px; display: flex; justify-content: space-between; }
  .card .row .name { text-transform: lowercase; font-weight: 500; font-size: 11px; }
  .card .row.team .name  { color: var(--team); }
  .card .row.scrum .name { color: var(--scrum); }
  .card .row.solo .name  { color: var(--solo); }

  #curve-wrap {
    background: var(--panel); border: 1px solid var(--border); border-radius: 6px;
    padding: 16px; height: 340px;
  }
  canvas { width: 100% !important; height: 100% !important; }

  .legend { display: flex; gap: 16px; margin-top: 8px; font-size: 12px; color: var(--muted); flex-wrap: wrap; }
  .legend .sw { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 4px; vertical-align: middle; }
  .sw.team  { background: var(--team); }
  .sw.scrum { background: var(--scrum); }
  .sw.solo  { background: var(--solo); }

  .drill { display: grid; grid-template-columns: 260px 1fr; gap: 16px; }
  .picker {
    background: var(--panel); border: 1px solid var(--border); border-radius: 6px;
    padding: 8px; max-height: 680px; overflow-y: auto;
  }
  .picker .item {
    padding: 8px 10px; border-radius: 4px; cursor: pointer;
    font-size: 12px; margin-bottom: 2px;
    display: flex; justify-content: space-between; gap: 8px;
  }
  .picker .item:hover { background: #21262d; }
  .picker .item.active { background: #1f6feb33; border-left: 2px solid var(--accent); }
  .picker .item .qual { color: var(--muted); font-variant-numeric: tabular-nums; font-size: 10.5px; }

  .compare { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; }
  @media (max-width: 1200px) { .compare { grid-template-columns: 1fr; } }
  .side {
    background: var(--panel); border: 1px solid var(--border); border-radius: 6px;
    padding: 12px 14px; min-width: 0;
  }
  .side .h {
    display: flex; justify-content: space-between; align-items: baseline;
    margin-bottom: 8px; padding-bottom: 8px; border-bottom: 1px solid var(--border);
    gap: 8px;
  }
  .side .h .name { font-weight: 500; font-size: 13px; text-transform: lowercase; }
  .side .h.team  .name { color: var(--team); }
  .side .h.scrum .name { color: var(--scrum); }
  .side .h.solo  .name { color: var(--solo); }
  .side .h .stats { color: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; text-align: right; }
  .side .q { font-size: 12px; color: var(--muted); margin-bottom: 8px; }
  .side .q .good { color: var(--good); }
  .side .q .bad { color: var(--bad); }
  .side details { margin-top: 8px; }
  .side details summary {
    cursor: pointer; padding: 4px 0; color: var(--muted); font-size: 12px;
    user-select: none;
  }
  .side details summary:hover { color: var(--fg); }
  .side pre {
    background: #0b0f14; border: 1px solid var(--border); border-radius: 4px;
    padding: 10px; overflow-x: auto; max-height: 400px; overflow-y: auto;
    font-family: "SF Mono", Menlo, Consolas, monospace; font-size: 11px;
    margin: 6px 0 0 0; white-space: pre; line-height: 1.4;
  }

  .diff .line-add   { background: var(--add); color: var(--add-fg); display: block; }
  .diff .line-rem   { background: var(--rem); color: var(--rem-fg); display: block; }
  .diff .line-hunk  { color: var(--accent); display: block; }
  .diff .line-file  { color: var(--muted); font-weight: 500; display: block; }

  .envelope-row { border-bottom: 1px dashed var(--border); padding: 4px 0; font-size: 11.5px; }
  .envelope-row:last-child { border-bottom: none; }
  .envelope-row .role { color: var(--accent); font-weight: 500; }
  .envelope-row .status { color: var(--muted); margin-left: 8px; }
  .envelope-row .summary { color: var(--fg); margin-top: 2px; word-wrap: break-word; }

  footer { padding: 24px 32px; text-align: center; color: var(--muted); font-size: 12px; border-top: 1px solid var(--border); }
</style>
</head>
<body>
<header>
  <div>
    <h1>orgos benchmark — waterfall team vs scrum team vs solo</h1>
    <div class="meta" id="meta"></div>
  </div>
  <div class="meta" id="model"></div>
</header>

<main>

<section id="totals">
  <h2>Totals</h2>
  <div class="cards" id="cards"></div>
</section>

<section id="curve-section">
  <h2>Quality curve — rolling avg over issue sequence</h2>
  <div id="curve-wrap"><canvas id="curve"></canvas></div>
  <div class="legend">
    <span><span class="sw team"></span>team (waterfall) — sequential 5-role pipeline</span>
    <span><span class="sw scrum"></span>scrum — N full-stack workers, shared wiki</span>
    <span><span class="sw solo"></span>solo — single agent, no wiki</span>
  </div>
</section>

<section id="drilldown">
  <h2>Per-issue drilldown</h2>
  <div class="drill">
    <div class="picker" id="picker"></div>
    <div class="compare">
      <div class="side">
        <div class="h team"><span class="name">waterfall team</span><span class="stats" id="team-stats"></span></div>
        <div class="q" id="team-q"></div>
        <div id="team-envelopes"></div>
        <details open><summary>diff</summary><pre class="diff" id="team-diff"></pre></details>
        <details><summary>raw envelope JSON</summary><pre id="team-raw"></pre></details>
      </div>
      <div class="side">
        <div class="h scrum"><span class="name">scrum team</span><span class="stats" id="scrum-stats"></span></div>
        <div class="q" id="scrum-q"></div>
        <div id="scrum-envelopes"></div>
        <details open><summary>diff</summary><pre class="diff" id="scrum-diff"></pre></details>
        <details><summary>raw envelope JSON</summary><pre id="scrum-raw"></pre></details>
      </div>
      <div class="side">
        <div class="h solo"><span class="name">solo</span><span class="stats" id="solo-stats"></span></div>
        <div class="q" id="solo-q"></div>
        <details open><summary>diff</summary><pre class="diff" id="solo-diff"></pre></details>
        <details><summary>raw output</summary><pre id="solo-raw"></pre></details>
      </div>
    </div>
  </div>
</section>

</main>

<footer>Self-contained HTML — no server, no CDN. Refresh to reload embedded data.</footer>

<script>
const DATA = __DATA_JSON__;
const SUMMARY = __SUMMARY_JSON__;
const MANIFEST = __MANIFEST_JSON__;
const APPROACHES = ["team", "scrum", "solo"];
const COLORS = {team: "#fb923c", scrum: "#4ade80", solo: "#a78bfa"};
const LABELS = {team: "team (waterfall)", scrum: "scrum", solo: "solo"};

// ---- Header meta ----
document.getElementById("meta").textContent =
  (MANIFEST.run_id || "") + " · " +
  APPROACHES.map(a => (DATA[a]||[]).length + " " + a).join(", ") +
  " · " + (MANIFEST.started_at || "").slice(0,19).replace("T"," ");
document.getElementById("model").textContent = "model: " + (MANIFEST.model || "?");

// ---- Utilities ----
function fmt(n, dp=0) {
  if (n === undefined || n === null) return "—";
  if (typeof n !== "number") return n;
  return n.toLocaleString(undefined, {maximumFractionDigits: dp});
}
function esc(s) {
  return String(s || "").replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
}
function avgQ(rs) {
  const vals = rs.flatMap(r => [r.quality_ac, r.quality_code, r.quality_tests].filter(x => x != null));
  return vals.length ? (vals.reduce((a,b)=>a+b,0) / vals.length) : null;
}

// ---- Cards ----
function getSummary(a) { return SUMMARY[a] || {}; }
function nrunsFor(a) { return getSummary(a).n_runs ?? (DATA[a]||[]).length; }
function commitsFor(a) { return getSummary(a).commits_produced ?? 0; }

const cards = [
  {label: "issues run",           fn: a => nrunsFor(a)},
  {label: "total tokens",         fn: a => fmt(getSummary(a).tokens_total, 0)},
  {label: "total cost (USD)",     fn: a => "$" + fmt(getSummary(a).cost_usd_total, 4)},
  {label: "wall time (s)",        fn: a => fmt(getSummary(a).wall_seconds_total, 1)},
  {label: "commits produced",     fn: a => commitsFor(a) + "/" + nrunsFor(a)},
  {label: "avg quality (all axes)", fn: a => fmt(avgQ(DATA[a] || []), 2)},
  {label: "cost per commit",      fn: a => {
      const c = getSummary(a).cost_usd_total, k = commitsFor(a);
      return k ? "$" + fmt(c / k, 4) : "—";
  }},
  {label: "tokens per commit",    fn: a => {
      const t = getSummary(a).tokens_total, k = commitsFor(a);
      return k ? fmt(Math.round(t / k), 0) : "—";
  }},
];
const cardsEl = document.getElementById("cards");
for (const c of cards) {
  const d = document.createElement("div");
  d.className = "card";
  let html = '<div class="label">' + c.label + '</div>';
  for (const a of APPROACHES) {
    if (!(DATA[a] || []).length && !getSummary(a).n_runs) continue;
    html += '<div class="row ' + a + '"><span class="name">' + a + '</span><span>' + c.fn(a) + '</span></div>';
  }
  d.innerHTML = html;
  cardsEl.appendChild(d);
}

// ---- Curve ----
function rollingAvgQuality(rs, window=3) {
  const arr = rs.map(r => avgQ([r]));
  return arr.map((_, i) => {
    const start = Math.max(0, i - window + 1);
    const win = arr.slice(start, i+1).filter(v => v != null);
    return win.length ? win.reduce((a,b)=>a+b,0) / win.length : null;
  });
}
function drawCurve() {
  const canvas = document.getElementById("curve");
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);

  const w = rect.width, h = rect.height;
  const pad = {l: 40, r: 20, t: 20, b: 30};
  const innerW = w - pad.l - pad.r;
  const innerH = h - pad.t - pad.b;

  const series = APPROACHES.map(a => ({
    name: a, color: COLORS[a],
    vals: rollingAvgQuality(DATA[a] || [], 3),
  }));
  const maxLen = Math.max(...series.map(s => s.vals.length), 1);
  const yMin = 0.5, yMax = 5.2;
  function xOf(i) { return pad.l + (i / Math.max(maxLen-1, 1)) * innerW; }
  function yOf(v) { return pad.t + (1 - (v - yMin) / (yMax - yMin)) * innerH; }

  // grid
  ctx.strokeStyle = "#30363d"; ctx.lineWidth = 1;
  ctx.font = "10px monospace"; ctx.fillStyle = "#7d8590";
  for (let q = 1; q <= 5; q++) {
    ctx.beginPath(); ctx.moveTo(pad.l, yOf(q)); ctx.lineTo(w - pad.r, yOf(q)); ctx.stroke();
    ctx.fillText(String(q), 8, yOf(q) + 3);
  }
  ctx.strokeStyle = "#7d8590";
  ctx.beginPath(); ctx.moveTo(pad.l, pad.t); ctx.lineTo(pad.l, h - pad.b); ctx.lineTo(w - pad.r, h - pad.b); ctx.stroke();

  function drawLine(vals, color) {
    ctx.strokeStyle = color; ctx.lineWidth = 2.2;
    ctx.beginPath(); let started = false;
    for (let i = 0; i < vals.length; i++) {
      if (vals[i] == null) continue;
      const x = xOf(i), y = yOf(vals[i]);
      if (!started) { ctx.moveTo(x, y); started = true; } else { ctx.lineTo(x, y); }
    }
    ctx.stroke();
    ctx.fillStyle = color;
    for (let i = 0; i < vals.length; i++) {
      if (vals[i] == null) continue;
      ctx.beginPath(); ctx.arc(xOf(i), yOf(vals[i]), 3, 0, Math.PI*2); ctx.fill();
    }
  }
  for (const s of series) drawLine(s.vals, s.color);

  ctx.fillStyle = "#7d8590";
  const step = Math.max(1, Math.floor(maxLen / 10));
  for (let i = 0; i < maxLen; i += step) {
    ctx.fillText("#" + (i+1), xOf(i) - 6, h - pad.b + 14);
  }
}
window.addEventListener("resize", drawCurve);
setTimeout(drawCurve, 0);

// ---- Drilldown ----
const byId = {};
for (const a of APPROACHES) {
  byId[a] = {};
  for (const r of DATA[a] || []) byId[a][r.issue_id] = r;
}
const allIds = Array.from(new Set(APPROACHES.flatMap(a => (DATA[a] || []).map(r => r.issue_id))));

function renderDiff(diffText) {
  if (!diffText) return "(no diff)";
  return diffText.split("\n").map(line => {
    const e = esc(line);
    if (line.startsWith("+++") || line.startsWith("---") || line.startsWith("diff --git")) {
      return '<span class="line-file">' + e + '</span>';
    } else if (line.startsWith("@@")) {
      return '<span class="line-hunk">' + e + '</span>';
    } else if (line.startsWith("+")) {
      return '<span class="line-add">' + e + '</span>';
    } else if (line.startsWith("-")) {
      return '<span class="line-rem">' + e + '</span>';
    }
    return e;
  }).join("\n");
}

function renderEnvelopes(trail) {
  if (!trail || !trail.length) return "";
  return trail.map(env => {
    const role = env.role || (env.worker_idx ? "worker_" + env.worker_idx : "?");
    const status = env.status || "";
    const summary = (env.summary || "").slice(0, 200);
    return '<div class="envelope-row">' +
             '<span class="role">' + esc(role) + '</span>' +
             '<span class="status">' + esc(status) + '</span>' +
             '<div class="summary">' + esc(summary) + '</div>' +
           '</div>';
  }).join("");
}

function renderSide(a, id) {
  const r = byId[a][id] || {};
  document.getElementById(a + "-stats").textContent =
    (r.tokens_total ? fmt(r.tokens_total, 0) + " tok · $" + (r.cost_usd || 0).toFixed(4) + " · " + (r.wall_seconds || 0) + "s" : "(no run)");
  document.getElementById(a + "-q").innerHTML =
    "quality AC/code/tests: " + (r.quality_ac ?? "—") + " / " + (r.quality_code ?? "—") + " / " + (r.quality_tests ?? "—") +
    " · commit: " + (r.commit_produced ? '<span class="good">yes</span>' : '<span class="bad">no</span>') +
    (r.quality_summary ? '<br/><em>' + esc(r.quality_summary.slice(0, 300)) + '</em>' : '');
  const envEl = document.getElementById(a + "-envelopes");
  if (envEl) envEl.innerHTML = renderEnvelopes(r.envelope_trail);
  document.getElementById(a + "-diff").innerHTML = renderDiff(r.diff_text);
  const rawEl = document.getElementById(a + "-raw");
  if (a === "solo") rawEl.textContent = (r.raw_output || "");
  else rawEl.textContent = JSON.stringify(r.envelope_trail || [], null, 2);
}

function selectIssue(id) {
  document.querySelectorAll("#picker .item").forEach(el =>
    el.classList.toggle("active", el.dataset.id === id));
  for (const a of APPROACHES) renderSide(a, id);
}

const pickerEl = document.getElementById("picker");
for (const id of allIds) {
  const qs = APPROACHES.map(a => {
    const r = byId[a][id];
    return {a, q: r ? avgQ([r]) : null};
  });
  const el = document.createElement("div");
  el.className = "item";
  el.dataset.id = id;
  el.innerHTML =
    '<span>' + id + '</span>' +
    '<span class="qual">' +
      qs.map(({a,q}) => a[0] + (q != null ? q.toFixed(1) : "—")).join(" · ") +
    '</span>';
  el.addEventListener("click", () => selectIssue(id));
  pickerEl.appendChild(el);
}
if (allIds.length) selectIssue(allIds[0]);

</script>
</body>
</html>
"""


def render_report(base: Path, out_path: Path) -> Path:
    """Render report.html from benchmark_reports/<run_id>/."""
    runs = _load_runs(base)
    summary = _load_summary(base)
    manifest = _load_manifest(base)

    html_content = _HTML_TEMPLATE
    html_content = html_content.replace("__RUN_ID__", html.escape(manifest.get("run_id", "")))
    html_content = html_content.replace("__DATA_JSON__", json.dumps(runs))
    html_content = html_content.replace("__SUMMARY_JSON__", json.dumps(summary))
    html_content = html_content.replace("__MANIFEST_JSON__", json.dumps(manifest))

    out_path.write_text(html_content, encoding="utf-8")
    return out_path
