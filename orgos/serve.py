"""Live HTTP server for team reports.

Two modes:

  1. Single-team (serve_team):
       /                → team's report.html
       /live/state      → team's board + audit + wiki + results JSON
       /live/tail?since → new events since timestamp
       /live/diff       → git diff since baseline

  2. Multi-team index (serve_repo_index):
       /                → index page listing all teams in the repo
       /teams/<id>/     → that team's report.html
       /teams/<id>/live/state | live/tail | live/diff → per-team live endpoints

Stdlib only. Zero deps.
"""

from __future__ import annotations

import html
import json
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

from orgos.agile.live_events import read_events
from orgos.agile.team_report import build_state_payload, render_team_report
from orgos.agile.team_workspace import (
    TeamWorkspace, TeamWorkspaceMissing, list_team_ids,
)


# ── Common request helpers ────────────────────────────────────────────────

class _ResponseHelpers(BaseHTTPRequestHandler):
    """Mixin-style base with response helpers. Not registered on its own."""

    server_version = "orgos-serve/0.2"

    def log_message(self, format, *args):
        return

    def _send_json(self, obj: Any, status: int = 200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html_str: str, status: int = 200):
        body = html_str.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text: str, status: int = 200):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_404(self, msg: str = "not found"):
        self._send_text(msg, status=404)


# ── Per-team endpoints (used by both modes) ───────────────────────────────

def _handle_team_endpoint(handler: _ResponseHelpers,
                           workspace: TeamWorkspace, subpath: str,
                           qs: dict) -> bool:
    """Handle /live/state, /live/tail, /live/diff, or root report for a team.

    subpath is the part AFTER the team prefix (e.g. "" or "live/state").
    Returns True if handled, False if the path didn't match anything.
    """
    if subpath in ("", "/", "index.html"):
        try:
            report_path = render_team_report(workspace)
            handler._send_html(report_path.read_text(encoding="utf-8"))
        except Exception as e:
            handler._send_text(f"failed to render report: {e}", status=500)
        return True

    if subpath == "live/state":
        try:
            handler._send_json(build_state_payload(workspace))
        except Exception as e:
            handler._send_json({"error": str(e)}, status=500)
        return True

    if subpath == "live/tail":
        since = (qs.get("since") or [""])[0]
        try:
            events = read_events(workspace.root, since_iso=since)
            handler._send_json(events)
        except Exception as e:
            handler._send_json({"error": str(e)}, status=500)
        return True

    if subpath == "live/diff":
        baseline = workspace.manifest().baseline_sha or "HEAD"
        try:
            text = subprocess.run(
                ["git", "diff", f"{baseline}..HEAD"],
                cwd=str(workspace.worktree),
                capture_output=True, text=True, timeout=30,
            ).stdout
            handler._send_text(text or "(no diff)")
        except Exception as e:
            handler._send_text(f"diff failed: {e}", status=500)
        return True

    if subpath == "live/retro":
        # RETRO.md lives in the SHARED wiki, not per-team. Return the file
        # contents (client filters by "## Retro — sprint <team_id>" blocks).
        retro_path = workspace.source_repo / "wiki" / "RETRO.md"
        if not retro_path.exists():
            handler._send_text("", status=404)
            return True
        try:
            handler._send_text(retro_path.read_text(encoding="utf-8"))
        except Exception as e:
            handler._send_text(f"retro read failed: {e}", status=500)
        return True

    return False


# ── Index page (multi-team mode) ──────────────────────────────────────────

_INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>orgos — teams</title>
<style>
  :root {
    --bg:#0d1117; --panel:#161b22; --border:#30363d; --fg:#e6edf3;
    --muted:#7d8590; --accent:#58a6ff; --good:#4ade80; --bad:#f87171;
    --wiki:#fbbf24;
  }
  * { box-sizing: border-box; }
  html, body { margin:0; padding:0; background:var(--bg); color:var(--fg);
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI",
                 Roboto, Helvetica, Arial, sans-serif;
    font-size:14px; line-height:1.5; }
  header { padding:24px 32px; border-bottom:1px solid var(--border); }
  header h1 { margin:0 0 4px 0; font-size:20px; }
  header .sub { color:var(--muted); font-size:12px; }
  main { padding:24px 32px; max-width:1400px; margin:0 auto; }
  section h2 { font-size:14px; color:var(--muted); font-weight:500;
    text-transform:uppercase; letter-spacing:0.5px; margin:0 0 12px 0;
    padding-bottom:6px; border-bottom:1px solid var(--border); }

  .teams { display:grid; gap:12px; grid-template-columns:repeat(auto-fit, minmax(320px, 1fr)); }
  .team-card {
    background:var(--panel); border:1px solid var(--border); border-radius:8px;
    padding:16px; display:block; text-decoration:none; color:var(--fg);
    transition:border-color 0.15s, background 0.15s;
  }
  .team-card:hover { border-color:var(--accent); background:#1a1f2a; }
  .team-card h3 { margin:0 0 6px 0; font-size:15px; display:flex;
    justify-content:space-between; align-items:baseline; gap:8px; }
  .team-card .goal { color:var(--muted); font-size:12px; margin-bottom:12px;
    display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical;
    overflow:hidden; }
  .team-card .stats { display:flex; gap:14px; font-size:11px; color:var(--muted);
    font-variant-numeric:tabular-nums; }
  .team-card .stat b { color:var(--fg); font-weight:600; }
  .team-card .stat.done b { color:var(--good); }
  .team-card .stat.blocked b { color:var(--bad); }
  .team-card .meta {
    margin-top:10px; padding-top:10px; border-top:1px solid var(--border);
    display:flex; justify-content:space-between; color:var(--muted); font-size:10.5px;
  }
  .team-card .meta code { background:#0b0f14; padding:1px 5px; border-radius:2px;
    font-size:10.5px; }
  .badge-live {
    background:#0d3d1c; color:var(--good); padding:2px 8px; border-radius:10px;
    font-size:10px; text-transform:uppercase; letter-spacing:0.5px; font-weight:600;
  }
  .badge-idle {
    background:#21262d; color:var(--muted); padding:2px 8px; border-radius:10px;
    font-size:10px; text-transform:uppercase; letter-spacing:0.5px;
  }
  .empty { color:var(--muted); text-align:center; padding:40px; font-size:13px; }
  code { font-family:"SF Mono",Menlo,Consolas,monospace; }
  .toolbar { display:flex; gap:12px; align-items:baseline; margin-bottom:16px;
    color:var(--muted); font-size:12px; }
  .toolbar code { background:var(--panel); padding:4px 8px; border-radius:4px;
    border:1px solid var(--border); }
</style>
</head>
<body>
<header>
  <h1>orgos — teams</h1>
  <div class="sub">Auto-refreshes every 5s. Click a card to open its live report.</div>
</header>
<main>
  <div class="toolbar">
    <span>repo:</span> <code>__REPO_PATH__</code>
    <span>·</span>
    <span id="team-count">loading…</span>
  </div>
  <section>
    <div class="teams" id="teams"></div>
  </section>
</main>
<script>
function esc(s) { return String(s == null ? "" : s).replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c])); }

async function refresh() {
  try {
    const r = await fetch("/api/teams", {cache: "no-store"});
    const teams = await r.json();
    document.getElementById("team-count").textContent = teams.length + " teams";
    const el = document.getElementById("teams");
    if (!teams.length) {
      el.innerHTML = '<div class="empty">No teams yet. Run <code>orgos run --repo . --team-id &lt;name&gt; --goal "…"</code>.</div>';
      return;
    }
    el.innerHTML = teams.map(t => {
      const done = t.stories_done || 0;
      const blocked = t.stories_blocked || 0;
      const total = t.stories_total || 0;
      const inflight = total - done - blocked;
      const badge = t.live ? '<span class="badge-live">● LIVE</span>' : '<span class="badge-idle">idle</span>';
      return (
        '<a class="team-card" href="/teams/' + esc(t.team_id) + '/">' +
          '<h3><span>' + esc(t.team_id) + '</span>' + badge + '</h3>' +
          '<div class="goal">' + esc(t.goal || "(no goal)") + '</div>' +
          '<div class="stats">' +
            '<span class="stat done">done: <b>' + done + '</b></span>' +
            '<span class="stat">in-flight: <b>' + inflight + '</b></span>' +
            '<span class="stat blocked">blocked: <b>' + blocked + '</b></span>' +
            '<span class="stat">total: <b>' + total + '</b></span>' +
          '</div>' +
          '<div class="meta">' +
            '<span>model: <code>' + esc(t.model || "?") + '</code></span>' +
            '<span>updated: ' + esc(t.updated_at || "—") + '</span>' +
          '</div>' +
          (t.pr_url
            ? '<div class="meta"><span></span><a href="' + esc(t.pr_url) + '" target="_blank" onclick="event.stopPropagation();" style="color:var(--good);text-decoration:underline;">🔀 draft PR ↗</a></div>'
            : '') +
        '</a>'
      );
    }).join("");
  } catch (e) {
    document.getElementById("team-count").textContent = "error loading teams";
  }
}
refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""


def _teams_summary(repo_root: Path) -> list[dict]:
    """Cheap per-team summary for the index page."""
    from orgos.agile.board_store import BoardStore
    import time
    out = []
    for tid in list_team_ids(repo_root):
        try:
            ws = TeamWorkspace.open(tid, repo_root)
            m = ws.manifest()
        except (TeamWorkspaceMissing, Exception):
            continue

        # Board counts
        try:
            board = BoardStore(ws.board_dir)
            counts = board.counts_by_state()
            total = sum(counts.values())
            done = counts.get("done", 0)
            blocked = counts.get("blocked", 0)
        except Exception:
            total = done = blocked = 0

        # Liveness heuristic: live.jsonl mtime within the last 60s
        live = False
        live_path = ws.root / "live.jsonl"
        if live_path.exists():
            try:
                age = time.time() - live_path.stat().st_mtime
                live = age < 60
            except OSError:
                live = False

        # Updated timestamp: prefer manifest / most-recent file mtime
        updated_at = ""
        try:
            latest = max(
                (p.stat().st_mtime for p in ws.root.rglob("*") if p.is_file()),
                default=0,
            )
            if latest:
                from datetime import datetime, timezone
                updated_at = datetime.fromtimestamp(latest, tz=timezone.utc) \
                    .strftime("%Y-%m-%d %H:%M:%S UTC")
        except Exception:
            pass

        # PR URL from campaign result if available
        pr_url = ""
        result_path = ws.root / "campaign_result.json"
        if result_path.exists():
            try:
                import json as _json
                pr_url = _json.loads(result_path.read_text()).get("pr_url", "")
            except Exception:
                pass

        out.append({
            "team_id": tid,
            "goal": m.goal,
            "model": m.model,
            "branch": m.branch,
            "stories_total": total,
            "stories_done": done,
            "stories_blocked": blocked,
            "live": live,
            "updated_at": updated_at,
            "pr_url": pr_url,
        })
    # Live teams first, then updated_at desc
    out.sort(key=lambda t: (not t["live"], t["updated_at"]), reverse=False)
    out.sort(key=lambda t: (0 if t["live"] else 1))
    return out


# ── Single-team handler (existing behavior) ───────────────────────────────

def _single_team_handler_factory(workspace: TeamWorkspace):
    class Handler(_ResponseHelpers):
        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            qs = parse_qs(parsed.query)

            if path == "/healthz":
                self._send_text("ok")
                return

            # Root and /live/* all belong to the single team
            if path == "/":
                subpath = ""
            elif path.startswith("/live/"):
                subpath = path[1:]  # strip leading /
            else:
                self._send_404()
                return

            if _handle_team_endpoint(self, workspace, subpath, qs):
                return
            self._send_404()
    return Handler


def serve_team(workspace: TeamWorkspace, host: str = "127.0.0.1",
                port: int = 8080) -> None:
    handler = _single_team_handler_factory(workspace)
    server = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{port}/"
    print(f"[serve] team={workspace.team_id} listening on {url}", flush=True)
    print(f"[serve]   open in browser: {url}", flush=True)
    print(f"[serve]   endpoints: /live/state /live/tail?since=<iso> /live/diff", flush=True)
    print(f"[serve]   press Ctrl-C to stop", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[serve] shutting down", flush=True)
        server.shutdown()


# ── Multi-team index handler (new) ────────────────────────────────────────

def _index_handler_factory(repo_root: Path):
    class Handler(_ResponseHelpers):
        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            qs = parse_qs(parsed.query)

            if path == "/healthz":
                self._send_text("ok")
                return

            if path == "/":
                page = _INDEX_HTML.replace("__REPO_PATH__", html.escape(str(repo_root)))
                self._send_html(page)
                return

            if path == "/api/teams":
                try:
                    self._send_json(_teams_summary(repo_root))
                except Exception as e:
                    self._send_json({"error": str(e)}, status=500)
                return

            # /teams/<id> or /teams/<id>/live/...
            if path.startswith("/teams/"):
                rest = path[len("/teams/"):]
                # Split team_id from subpath
                if "/" in rest:
                    team_id, subpath = rest.split("/", 1)
                else:
                    team_id, subpath = rest, ""
                try:
                    ws = TeamWorkspace.open(team_id, repo_root)
                except TeamWorkspaceMissing:
                    self._send_404(f"unknown team: {team_id}")
                    return
                if _handle_team_endpoint(self, ws, subpath, qs):
                    return
                self._send_404()
                return

            self._send_404()
    return Handler


def serve_repo_index(repo_root: Path, host: str = "127.0.0.1",
                      port: int = 8080) -> None:
    handler = _index_handler_factory(repo_root)
    server = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{port}/"
    teams = list_team_ids(repo_root)
    print(f"[serve] index mode — {len(teams)} teams in {repo_root}", flush=True)
    print(f"[serve]   open in browser: {url}", flush=True)
    print(f"[serve]   endpoints: /api/teams /teams/<id>/ /teams/<id>/live/*", flush=True)
    print(f"[serve]   press Ctrl-C to stop", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[serve] shutting down", flush=True)
        server.shutdown()
