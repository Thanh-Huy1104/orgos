"""orgos CLI — deploy a Scrum team against a goal.

Usage:
    python -m orgos.cli run --repo <path> --goal "<text>" --team-id <name>
    python -m orgos.cli run --repo <path> --goal "<text>" --team-id <name> --waterfall
    python -m orgos.cli report --team-id <name>
    python -m orgos.cli list-teams
    python -m orgos.cli reset --team-id <name>

Both --scrum (default) and --waterfall modes produce a report at
<repo>/.orgos_teams/<team-id>/report.html.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _load_dotenv(repo_root: Path) -> None:
    """Load .env keys into os.environ so litellm/crewai see them."""
    env_path = repo_root / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def _cmd_run(args: argparse.Namespace) -> int:
    from orgos.agile.team_workspace import (
        TeamWorkspace, TeamWorkspaceExists,
    )
    repo = Path(args.repo).resolve()
    _load_dotenv(repo)

    if not (repo / ".git").exists():
        print(f"ERROR: {repo} is not a git repo (no .git dir)", file=sys.stderr)
        return 2

    # Merge --goal and --spec-file into a single "goal" string.
    # Spec-file gets copied into wiki/SPEC.md for future-sprint reference.
    goal = args.goal or ""
    spec_text = ""
    if args.spec_file:
        spec_path = Path(args.spec_file).resolve()
        if not spec_path.exists():
            print(f"ERROR: --spec-file not found: {spec_path}", file=sys.stderr)
            return 2
        try:
            spec_text = spec_path.read_text(encoding="utf-8")
        except OSError as e:
            print(f"ERROR: reading spec file: {e}", file=sys.stderr)
            return 2
        # Copy the spec into the target repo's wiki so it becomes part of the
        # persistent team knowledge base (referenced by every future sprint).
        wiki_dir = repo / "wiki"
        wiki_dir.mkdir(parents=True, exist_ok=True)
        spec_dest = wiki_dir / "SPEC.md"
        spec_dest.write_text(spec_text, encoding="utf-8")
        print(f"[cli] spec copied to {spec_dest.relative_to(repo)}", flush=True)

        # Prepend a compact reference line so PO reads the spec.
        goal = (
            (goal + "\n\n" if goal else "")
            + f"See wiki/SPEC.md for the full product spec (already available "
              f"via wiki_read). The spec's contents are also inlined below.\n\n"
              f"--- BEGIN SPEC ---\n{spec_text}\n--- END SPEC ---"
        )

    if not goal.strip():
        print("ERROR: provide --goal or --spec-file (or both)", file=sys.stderr)
        return 2

    # Create or resume the workspace
    try:
        ws = TeamWorkspace.create(
            args.team_id, repo, goal=goal, model=args.model,
        )
        print(f"[cli] created workspace {ws.root}", flush=True)
    except TeamWorkspaceExists:
        if args.fresh:
            print(f"[cli] --fresh: resetting existing workspace {args.team_id}", flush=True)
            TeamWorkspace.open(args.team_id, repo).reset()
            ws = TeamWorkspace.create(
                args.team_id, repo, goal=goal, model=args.model,
            )
        else:
            print(f"[cli] resuming existing workspace {args.team_id}", flush=True)
            ws = TeamWorkspace.open(args.team_id, repo)

    # Optionally spin up the live HTTP server in a background thread so the
    # user gets a single-command experience.
    serve_thread = None
    server_shutdown = None
    if args.serve:
        import threading
        import webbrowser
        from http.server import ThreadingHTTPServer
        from orgos.serve import _single_team_handler_factory
        handler_cls = _single_team_handler_factory(ws)
        try:
            server = ThreadingHTTPServer((args.host, args.port), handler_cls)
        except OSError as e:
            print(f"[cli] WARN: cannot bind {args.host}:{args.port} ({e}) — "
                  f"continuing without serve", flush=True)
        else:
            url = f"http://{args.host}:{args.port}/"
            serve_thread = threading.Thread(
                target=server.serve_forever, daemon=True, name="orgos-serve",
            )
            serve_thread.start()
            server_shutdown = server.shutdown
            print(f"[cli] 🌐 live report: {url}", flush=True)
            if args.open_browser:
                try:
                    webbrowser.open(url)
                except Exception:
                    pass

    if args.waterfall:
        print(f"[cli] mode=waterfall", flush=True)
        from orgos.agile.waterfall_runner import run_waterfall_campaign
        result = run_waterfall_campaign(
            workspace=ws, goal=ws.manifest().goal, model=args.model,
            max_stories_worked=args.max_stories,
            max_wall_seconds=args.max_seconds,
        )
    else:
        print(
            "[cli] ERROR: `orgos run` in scrum mode has been replaced by "
            "`orgos start` (v2 async runtime). See docs/superpowers/specs/"
            "2026-07-16-orgos-v2-async-scrum-team.md",
            file=sys.stderr,
        )
        return 3

    # Persist result to workspace
    result_path = ws.root / "campaign_result.json"
    from dataclasses import asdict
    result_dict = asdict(result)
    result_path.write_text(json.dumps(result_dict, indent=2, default=str))
    # Unified summary — MultiSprintResult uses different field names than
    # DispatchResult; handle both.
    reason = getattr(result, "reason_stopped", None) or getattr(result, "stop_reason", "")
    done = getattr(result, "stories_done", None)
    if done is None:
        done = getattr(result, "total_stories_done", 0)
    blocked = getattr(result, "stories_blocked", None)
    if blocked is None:
        blocked = getattr(result, "total_stories_blocked", 0)
    created = getattr(result, "stories_created", "—")
    n_sprints = getattr(result, "n_sprints_run", None)

    print(f"\n[cli] sprint complete — result at {result_path}", flush=True)
    if n_sprints is not None:
        print(f"[cli] sprints run: {n_sprints}", flush=True)
    print(f"[cli] stopped_because: {reason}", flush=True)
    print(f"[cli] stories: created={created} done={done} blocked={blocked}", flush=True)
    print(f"[cli] tokens: in={result.total_tokens_input} out={result.total_tokens_output}", flush=True)
    if getattr(result, "pr_url", ""):
        print(f"[cli] 🔀 draft PR opened: {result.pr_url}", flush=True)

    # Render a per-team report
    from orgos.agile.team_report import render_team_report
    report_path = render_team_report(ws)
    print(f"[cli] report: {report_path}", flush=True)

    # If we started a serve thread, keep it alive so the user can view the
    # final state, then Ctrl-C to exit. Skip the wait if the server never
    # started (bind error above).
    if serve_thread is not None and serve_thread.is_alive():
        print(f"[cli] serve still running at http://{args.host}:{args.port}/  "
              f"— Ctrl-C to stop", flush=True)
        try:
            serve_thread.join()
        except KeyboardInterrupt:
            print("\n[cli] shutting down serve", flush=True)
            if server_shutdown:
                server_shutdown()
    return 0


def _resolve_goal_and_spec(repo: Path, args) -> tuple[str, str]:
    """Extract goal + optionally load a spec file."""
    goal = args.goal or ""
    spec_text = ""
    if getattr(args, "spec_file", None):
        spec_path = Path(args.spec_file).resolve()
        if spec_path.exists():
            spec_text = spec_path.read_text(encoding="utf-8")
            wiki_dir = repo / "wiki"
            wiki_dir.mkdir(parents=True, exist_ok=True)
            (wiki_dir / "SPEC.md").write_text(spec_text, encoding="utf-8")
            goal = (
                (goal + "\n\n" if goal else "")
                + f"See wiki/SPEC.md for the full spec. Contents:\n\n"
                + f"--- BEGIN SPEC ---\n{spec_text}\n--- END SPEC ---"
            )
    return goal, spec_text


def _cmd_start(args: argparse.Namespace) -> int:
    """Start the async agent team. Runs until stopped by SIGINT or `orgos stop`."""
    import asyncio
    import signal
    from orgos.agile.agent_loop import AsyncAgent
    from orgos.agile.board_store import BoardStore
    from orgos.agile.coding_executor import ClaudeCodeExecutor, CopilotCliExecutor
    from orgos.agile.spawn_executor import SpawnCodingExecutor
    import shutil
    from orgos.agile.live_events import EventEmitter
    from orgos.agile.merge_queue import MergeQueue, run_merge_worker
    from orgos.agile.supervisor import TeamSupervisor
    from orgos.agile.team_workspace import (
        TeamWorkspace, TeamWorkspaceExists,
    )

    repo = Path(args.repo).resolve()
    _load_dotenv(repo)

    if not (repo / ".git").exists():
        print(f"ERROR: {repo} is not a git repo", file=sys.stderr)
        return 2

    goal, _spec_text = _resolve_goal_and_spec(repo, args)
    if not goal.strip():
        print("ERROR: provide --goal or --spec-file", file=sys.stderr)
        return 2
    try:
        ws = TeamWorkspace.create(args.team_id, repo, goal=goal, model=args.model)
        print(f"[cli] created workspace {ws.root}", flush=True)
    except TeamWorkspaceExists:
        if args.fresh:
            TeamWorkspace.open(args.team_id, repo).reset()
            ws = TeamWorkspace.create(args.team_id, repo, goal=goal, model=args.model)
        else:
            ws = TeamWorkspace.open(args.team_id, repo)
            print(f"[cli] resuming existing workspace {args.team_id}", flush=True)

    roles = ["po", "scrum_master", "architect", "test", "devsecops"]
    for r in roles:
        ws.ensure_agent_workspace(r)

    board = BoardStore(ws.root / "board")
    emitter = EventEmitter(ws.root)

    # Pick coding executor.
    #  auto → prefer claude, else copilot, else fall back to spawn (API-key path).
    choice = args.executor
    if choice == "auto":
        if shutil.which("claude"):
            choice = "claude"
        elif shutil.which("copilot"):
            choice = "copilot"
        else:
            choice = "spawn"
    if choice == "claude":
        executor = ClaudeCodeExecutor()
        exec_label = "claude (Claude Code CLI, user's Claude subscription — no API key)"
    elif choice == "copilot":
        executor = CopilotCliExecutor()
        exec_label = "copilot (GitHub Copilot CLI, user's Copilot subscription — no API key)"
    else:
        executor = SpawnCodingExecutor(model=args.model)
        exec_label = f"spawn (LiteLLM backend, model={args.model} — needs API key in .env)"
    print(f"[cli] coding executor: {exec_label}", flush=True)
    merge_queue = MergeQueue(ws)

    # Seed the board on first start (PO decomposes the goal into stories).
    # PO's replan ceremony tops up the backlog later; this call bootstraps it.
    from orgos.agile.goal_decomposer import decompose_goal
    existing = list(board.list_state("draft")) + list(board.list_state("refinement")) \
             + list(board.list_state("ready")) + list(board.list_state("in_progress"))
    if not existing:
        print("[cli] decomposing goal into initial stories...", flush=True)
        try:
            ids = decompose_goal(
                goal=goal, repo_root=repo, board=board, model=args.model,
            )
            print(f"[cli] drafted {len(ids)} stories", flush=True)
        except Exception as e:
            print(f"[cli] WARNING: goal decomposition failed: {e}", file=sys.stderr, flush=True)

    def _load_heartbeat(role: str) -> str:
        # Personas live in the orgos repo (source of truth), not the target.
        orgos_root = Path(__file__).resolve().parent.parent
        p = orgos_root / "agents" / role / "HEARTBEAT.md"
        return p.read_text(encoding="utf-8") if p.exists() else "## Every 30 seconds\nCheck board."

    delivery_roles = {"architect", "test", "devsecops"}
    agents = {}
    for r in roles:
        agents[r] = AsyncAgent(
            role=r, workspace=ws, board=board, executor=executor,
            merge_queue=merge_queue, emitter=emitter,
            heartbeat_md=_load_heartbeat(r),
            is_delivery_agent=(r in delivery_roles),
        )

    supervisor = TeamSupervisor(agents, emitter)

    async def _run_all():
        merge_task = asyncio.create_task(run_merge_worker(merge_queue, ws, board, emitter))
        sup_task = asyncio.create_task(supervisor.run())

        # Optional wall-clock timeout — useful for CI, comparison runs, and
        # anything driven by an LLM that can't remember to SIGINT.
        timeout_task = None
        if args.timeout_seconds and args.timeout_seconds > 0:
            async def _auto_stop():
                await asyncio.sleep(args.timeout_seconds)
                print(
                    f"\n[cli] --timeout-seconds={args.timeout_seconds} reached; "
                    f"shutting down team", flush=True,
                )
                supervisor.stop()
            timeout_task = asyncio.create_task(_auto_stop())

        try:
            await sup_task
        finally:
            merge_task.cancel()
            if timeout_task is not None:
                timeout_task.cancel()

    def _handle_sigint(sig, frame):
        print("\n[cli] shutting down team", flush=True)
        supervisor.stop()
    signal.signal(signal.SIGINT, _handle_sigint)

    # Write a PID file so `orgos stop --team-id X` can find this process
    # exactly (not via fragile pgrep substring matching).
    pid_file = ws.root / "pid.txt"
    pid_file.write_text(str(os.getpid()), encoding="utf-8")

    print(f"[cli] team {args.team_id} started with roles {roles} (pid={os.getpid()})", flush=True)
    try:
        asyncio.run(_run_all())
    finally:
        try:
            pid_file.unlink()
        except FileNotFoundError:
            pass

    # Write campaign_result.json so scrum runs have parity with waterfall for
    # downstream comparison harnesses.
    try:
        from orgos.agile.campaign_summary import write_campaign_result
        reason = "timeout" if args.timeout_seconds else "sigint"
        out = write_campaign_result(
            ws, board, executor=choice, reason_stopped=reason,
        )
        print(f"[cli] wrote {out}", flush=True)
    except Exception as e:
        print(f"[cli] WARNING: could not write campaign_result.json: {e}",
              file=sys.stderr, flush=True)

    print(f"[cli] team {args.team_id} stopped", flush=True)
    return 0


def _cmd_stop(args: argparse.Namespace) -> int:
    """Signal a running team to stop. Reads the PID file `orgos start` wrote."""
    import subprocess
    from orgos.agile.team_workspace import TeamWorkspace, TeamWorkspaceMissing

    repo = Path(getattr(args, "repo", ".")).resolve()
    pids: list[str] = []
    try:
        ws = TeamWorkspace.open(args.team_id, repo)
        pid_file = ws.root / "pid.txt"
        if pid_file.exists():
            pid = pid_file.read_text(encoding="utf-8").strip()
            if pid.isdigit():
                pids = [pid]
    except TeamWorkspaceMissing:
        pass

    # Fallback: fragile pgrep substring match (for legacy workspaces that
    # predate pid.txt). Uses exact-boundary matching to avoid team-id
    # substring collisions.
    if not pids:
        r = subprocess.run(
            ["pgrep", "-f", f"orgos.cli.*start.*--team-id[= ]{args.team_id}( |$)"],
            capture_output=True, text=True,
        )
        pids = [p for p in r.stdout.strip().splitlines() if p]
    if not pids:
        print(f"ERROR: no running team found with team-id {args.team_id}", file=sys.stderr)
        return 2
    for pid in pids:
        subprocess.run(["kill", "-INT", pid], check=False)
    print(f"[cli] sent SIGINT to {len(pids)} process(es) for team {args.team_id}", flush=True)
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    from orgos.agile.team_workspace import TeamWorkspace, TeamWorkspaceMissing
    from orgos.agile.team_report import collect_agent_statuses
    repo = Path(args.repo).resolve()
    try:
        ws = TeamWorkspace.open(args.team_id, repo)
    except TeamWorkspaceMissing as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    for a in collect_agent_statuses(ws):
        mark = "●" if a["is_alive"] else "○"
        story = a["current_story"] or "(idle)"
        restarts = f" ↺{a['restart_count']}" if a["restart_count"] else ""
        print(f"  {mark} {a['role']:14s} {story:36s} last:{a['last_event_at'][:19]}{restarts}")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    from orgos.agile.team_workspace import TeamWorkspace, TeamWorkspaceMissing
    from orgos.agile.team_report import render_team_report
    repo = Path(args.repo).resolve()
    try:
        ws = TeamWorkspace.open(args.team_id, repo)
    except TeamWorkspaceMissing as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    report_path = render_team_report(ws)
    print(f"[cli] report: {report_path}", flush=True)
    return 0


def _cmd_list_teams(args: argparse.Namespace) -> int:
    from orgos.agile.team_workspace import list_team_ids, TeamWorkspace
    repo = Path(args.repo).resolve()
    ids = list_team_ids(repo)
    if not ids:
        print("(no teams)")
        return 0
    for tid in ids:
        ws = TeamWorkspace.open(tid, repo)
        m = ws.manifest()
        print(f"  {tid:24s}  branch={m.branch:24s}  goal={m.goal[:70]}")
    return 0


def _cmd_reset(args: argparse.Namespace) -> int:
    from orgos.agile.team_workspace import TeamWorkspace, TeamWorkspaceMissing
    repo = Path(args.repo).resolve()
    try:
        ws = TeamWorkspace.open(args.team_id, repo)
    except TeamWorkspaceMissing as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    ws.reset()
    print(f"[cli] reset team {args.team_id}", flush=True)
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    from orgos.agile.team_workspace import TeamWorkspace, TeamWorkspaceMissing
    from orgos.serve import serve_repo_index, serve_team
    repo = Path(args.repo).resolve()
    if args.index:
        serve_repo_index(repo, host=args.host, port=args.port)
        return 0
    if not args.team_id:
        print("ERROR: provide --team-id, or use --index to list all teams",
              file=sys.stderr)
        return 2
    try:
        ws = TeamWorkspace.open(args.team_id, repo)
    except TeamWorkspaceMissing as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    serve_team(ws, host=args.host, port=args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="orgos", description="Deploy a Scrum team of AI agents against a goal.")
    sub = p.add_subparsers(dest="command", required=True)

    # run
    run_p = sub.add_parser(
        "run",
        help="Run ONE Scrum sprint against a goal (timeboxed).",
        description=(
            "Run ONE Scrum sprint. The sprint is timeboxed by --sprint-story-cap "
            "and --sprint-duration; whichever hits first ends the sprint. "
            "At sprint end a mandatory retrospective is written to wiki/RETRO.md. "
            "Incomplete stories return to the backlog for a future sprint — "
            "the team NEVER 'stops early because it's done'. Sprints are sacred."
        ),
    )
    run_p.add_argument("--repo", type=str, required=True,
                        help="Path to target git repo (worktree is created under it)")
    run_p.add_argument("--goal", type=str, default="",
                        help="Goal description (a paragraph). Required unless "
                             "--spec-file is given.")
    run_p.add_argument("--spec-file", type=str, default=None,
                        help="Path to a product spec markdown file. Copied to "
                             "wiki/SPEC.md so every future sprint can reference "
                             "it. Combined with --goal (or used alone).")
    run_p.add_argument("--team-id", type=str, required=True,
                        help="Unique team identifier (used for workspace dir)")
    run_p.add_argument("--model", type=str, default="deepseek/deepseek-chat",
                        help="Default model for every role. Override per role with --<role>-model.")
    run_p.add_argument("--po-model", type=str, default=None,
                        help="Model for the Product Owner (decomposition). "
                             "Highest leverage — a smarter PO writes better stories.")
    run_p.add_argument("--architect-model", type=str, default=None,
                        help="Model for the Architect (code writing).")
    run_p.add_argument("--test-model", type=str, default=None,
                        help="Model for the Test worker (writes/runs tests + peer review).")
    run_p.add_argument("--devsecops-model", type=str, default=None,
                        help="Model for the DevSecOps worker (security review).")
    run_p.add_argument("--n-workers", type=int, default=1,
                        help="How many worker threads run concurrently in the WORK phase. "
                             "N=1 = sequential (feels waterfall-ish). N=3 = full scrum.")
    run_p.add_argument("--waterfall", action="store_true",
                        help="Use the waterfall 5-role pipeline instead of scrum")
    run_p.add_argument("--fresh", action="store_true",
                        help="If team-id already exists, wipe and start over")
    # Sprint boundaries — Scrum-honest naming. Old --max-* names kept as
    # aliases for backwards compatibility with previously scripted runs.
    run_p.add_argument("--sprint-story-cap", "--max-stories",
                        type=int, default=20, dest="max_stories",
                        help="Max stories this sprint will pull. Sprint ends when "
                             "either this cap is hit, sprint-duration is hit, or "
                             "the ready backlog empties. Default: 20.")
    run_p.add_argument("--sprint-duration", "--max-seconds",
                        type=int, default=3600, dest="max_seconds",
                        help="Sprint wall-clock timebox in seconds. Sprint ends "
                             "when this is reached. Default: 3600 (1h). The "
                             "chapter's model uses 14400 (4h).")
    run_p.add_argument("--sprints", type=int, default=1,
                        help="How many sprints to run back-to-back on the same "
                             "team + goal. Between sprints, PO reviews the retro "
                             "and replans (may draft new stories, unblock, or "
                             "declare goal met and stop early). Default: 1.")
    run_p.add_argument("--stagnation-window", type=int, default=2,
                        help="Multi-sprint only: stop early if this many "
                             "consecutive sprints ship 0 stories. Default: 2.")
    run_p.add_argument("--max-usd", type=float, default=None,
                        help="Multi-sprint only: hard $ ceiling. Stops between "
                             "sprints once cumulative cost >= this. No default.")
    run_p.add_argument("--max-tokens", type=int, default=None,
                        help="Multi-sprint only: hard token ceiling across all "
                             "sprints. No default.")
    run_p.add_argument("--open-pr", action="store_true",
                        help="At end of campaign, push the team branch and "
                             "open a draft PR via `gh pr create`. Requires "
                             "the gh CLI and an `origin` remote.")
    run_p.add_argument("--pr-base", type=str, default="main",
                        help="Base branch for --open-pr (default: main)")
    run_p.add_argument("--serve", action="store_true",
                        help="Also start the live HTTP report server in-process.")
    run_p.add_argument("--host", type=str, default="127.0.0.1",
                        help="Host for --serve (default: 127.0.0.1)")
    run_p.add_argument("--port", type=int, default=8080,
                        help="Port for --serve (default: 8080)")
    run_p.add_argument("--no-open", dest="open_browser",
                        action="store_false", default=True,
                        help="With --serve, do NOT auto-open a browser tab.")
    run_p.set_defaults(func=_cmd_run)

    # report
    rep_p = sub.add_parser("report", help="Re-render the HTML report for a team")
    rep_p.add_argument("--repo", type=str, default=".")
    rep_p.add_argument("--team-id", type=str, required=True)
    rep_p.set_defaults(func=_cmd_report)

    # list
    ls_p = sub.add_parser("list-teams", help="List teams in a repo")
    ls_p.add_argument("--repo", type=str, default=".")
    ls_p.set_defaults(func=_cmd_list_teams)

    # reset
    rst_p = sub.add_parser("reset", help="Wipe a team's workspace and branch")
    rst_p.add_argument("--repo", type=str, default=".")
    rst_p.add_argument("--team-id", type=str, required=True)
    rst_p.set_defaults(func=_cmd_reset)

    # start
    start_p = sub.add_parser(
        "start",
        help="Start the async agent team (runs until stopped by SIGINT).",
    )
    start_p.add_argument("--repo", type=str, required=True)
    start_p.add_argument("--team-id", type=str, required=True)
    start_p.add_argument("--goal", type=str, default="")
    start_p.add_argument("--spec-file", type=str, default=None)
    start_p.add_argument("--model", type=str, default="deepseek/deepseek-chat")
    start_p.add_argument(
        "--executor", type=str,
        choices=("auto", "claude", "copilot", "spawn"),
        default="auto",
        help="Coding executor. 'auto' (default) prefers 'claude', then "
             "'copilot', then falls back to 'spawn'. "
             "'claude' uses `claude -p` (Claude subscription — no API key). "
             "'copilot' uses `copilot -p` (GitHub Copilot subscription — no "
             "API key; run `copilot` + `/login` once first). "
             "'spawn' uses orgos.spawn + LiteLLM (needs an API key in .env; "
             "supports any OpenAI-compatible endpoint via OPENAI_BASE_URL, "
             "so this is where the DeepSeek / custom-URL path lives).",
    )
    start_p.add_argument("--fresh", action="store_true")
    start_p.add_argument(
        "--timeout-seconds", type=int, default=0,
        help="Auto-shutdown after N seconds (0 = run until SIGINT). Useful "
             "for CI / benchmarking / any driver that can't send SIGINT itself.",
    )
    start_p.set_defaults(func=_cmd_start)

    # stop
    stop_p = sub.add_parser(
        "stop",
        help="Signal a running team to shut down (SIGINT). Team finishes current stories then exits.",
    )
    stop_p.add_argument("--repo", type=str, default=".",
                        help="Target repo (default: CWD). Used to find the "
                             "team's pid.txt for exact-PID SIGINT.")
    stop_p.add_argument("--team-id", type=str, required=True)
    stop_p.set_defaults(func=_cmd_stop)

    # status
    status_p = sub.add_parser(
        "status",
        help="Print per-agent status for a team.",
    )
    status_p.add_argument("--repo", type=str, default=".")
    status_p.add_argument("--team-id", type=str, required=True)
    status_p.set_defaults(func=_cmd_status)

    # serve
    srv_p = sub.add_parser(
        "serve",
        help="Serve one team's live report OR the multi-team index page.",
    )
    srv_p.add_argument("--repo", type=str, default=".")
    srv_p.add_argument("--team-id", type=str, default=None,
                        help="Which team to serve. Omit when using --index.")
    srv_p.add_argument("--index", action="store_true",
                        help="Serve a multi-team index page instead of a "
                             "single team. Each team is at /teams/<id>/.")
    srv_p.add_argument("--host", type=str, default="127.0.0.1")
    srv_p.add_argument("--port", type=int, default=8080)
    srv_p.set_defaults(func=_cmd_serve)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
