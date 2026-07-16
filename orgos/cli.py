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
        role_models = {
            k: v for k, v in (
                ("po", args.po_model),
                ("architect", args.architect_model),
                ("test", args.test_model),
                ("devsecops", args.devsecops_model),
            ) if v
        }
        if role_models:
            print(f"[cli] role model overrides: {role_models}", flush=True)

        if args.sprints > 1:
            print(f"[cli] mode=scrum · MULTI-SPRINT ({args.sprints} sprints) · "
                  f"n_workers={args.n_workers} · "
                  f"sprint_story_cap={args.max_stories} · "
                  f"sprint_duration={args.max_seconds}s", flush=True)
            from orgos.agile.multi_sprint import run_multi_sprint
            result = run_multi_sprint(
                workspace=ws, goal=ws.manifest().goal, model=args.model,
                role_models=role_models,
                n_workers=args.n_workers,
                n_sprints=args.sprints,
                sprint_story_cap=args.max_stories,
                sprint_duration_sec=args.max_seconds,
                open_pr=args.open_pr, pr_base=args.pr_base,
                stagnation_window=args.stagnation_window,
                max_total_usd=args.max_usd,
                max_total_tokens=args.max_tokens,
            )
        else:
            print(f"[cli] mode=scrum · one sprint · n_workers={args.n_workers} · "
                  f"sprint_story_cap={args.max_stories} · "
                  f"sprint_duration={args.max_seconds}s", flush=True)
            from orgos.agile.dispatcher import Dispatcher
            d = Dispatcher(
                workspace=ws, model=args.model,
                role_models=role_models,
                n_workers=args.n_workers,
                max_stories_worked=args.max_stories,
                max_wall_seconds=args.max_seconds,
                open_pr=args.open_pr,
                pr_base=args.pr_base,
            )
            result = d.run_campaign(goal=ws.manifest().goal)

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


def _cmd_watch(args: argparse.Namespace) -> int:
    """Run sprints indefinitely on an existing team, with PR-feedback ingestion.

    Effectively: `while True: multi_sprint --sprints 1` on the same team.
    Between sprints: ingest PR review comments, replan, run next sprint.
    Stops on stagnation, budget cap, or SIGINT.
    """
    import signal
    import time
    from orgos.agile.multi_sprint import run_multi_sprint
    from orgos.agile.team_workspace import (
        TeamWorkspace, TeamWorkspaceMissing,
    )
    repo = Path(args.repo).resolve()
    _load_dotenv(repo)
    try:
        ws = TeamWorkspace.open(args.team_id, repo)
    except TeamWorkspaceMissing as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print("Hint: run `orgos run --team-id X --goal '...'` once first, "
              "then `orgos watch --team-id X` to keep it running.",
              file=sys.stderr)
        return 2

    role_models = {
        k: v for k, v in (
            ("po", args.po_model),
            ("architect", args.architect_model),
            ("test", args.test_model),
            ("devsecops", args.devsecops_model),
        ) if v
    }
    if role_models:
        print(f"[watch] role model overrides: {role_models}", flush=True)

    stopped = {"flag": False}
    def _handle_sigint(sig, frame):
        print("\n[watch] SIGINT received — will stop after this sprint", flush=True)
        stopped["flag"] = True
    signal.signal(signal.SIGINT, _handle_sigint)

    iteration = 0
    total_in = 0
    total_out = 0
    print(f"[watch] starting on team={args.team_id} "
          f"interval={args.interval}s (between-sprint pause) "
          f"max_sprints={args.max_sprints or 'unbounded'}", flush=True)

    while not stopped["flag"]:
        iteration += 1
        if args.max_sprints and iteration > args.max_sprints:
            print(f"[watch] max_sprints {args.max_sprints} reached", flush=True)
            break

        # Budget check across iterations
        if args.max_usd is not None:
            from orgos.agile.pricing import cost_usd
            spent = cost_usd(args.model, total_in, total_out)
            if spent >= args.max_usd:
                print(f"[watch] budget cap ${args.max_usd:.2f} reached "
                      f"(spent ${spent:.4f}) — stopping", flush=True)
                break

        print(f"\n[watch] ── iteration {iteration} ──", flush=True)
        result = run_multi_sprint(
            workspace=ws, goal=ws.manifest().goal, model=args.model,
            role_models=role_models,
            n_workers=args.n_workers,
            n_sprints=1,  # each watch iteration = one sprint
            sprint_story_cap=args.max_stories,
            sprint_duration_sec=args.max_seconds,
            open_pr=args.open_pr, pr_base=args.pr_base,
            stagnation_window=1,
            max_total_usd=args.max_usd,
            max_total_tokens=args.max_tokens,
        )
        total_in += result.total_tokens_input
        total_out += result.total_tokens_output

        # Check the just-finished sprint for stop conditions
        if "goal_met" in result.stop_reason:
            print(f"[watch] PO declared goal met — stopping", flush=True)
            break
        if "stagnation" in result.stop_reason:
            print(f"[watch] stagnation detected — stopping for human review", flush=True)
            break
        if "budget_exhausted" in result.stop_reason:
            print(f"[watch] budget exhausted — stopping", flush=True)
            break
        if result.total_stories_done == 0:
            print(f"[watch] sprint shipped 0 stories — stopping", flush=True)
            break

        if stopped["flag"]:
            break

        if args.interval > 0:
            print(f"[watch] sleeping {args.interval}s before next sprint "
                  f"(Ctrl-C to stop)…", flush=True)
            slept = 0
            while slept < args.interval and not stopped["flag"]:
                time.sleep(min(2, args.interval - slept))
                slept += 2

    print(f"\n[watch] done — {iteration} iterations · "
          f"total tokens in/out={total_in}/{total_out}", flush=True)
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

    # watch — run sprints indefinitely on an existing team
    watch_p = sub.add_parser(
        "watch",
        help="Run sprints indefinitely on an existing team, with PR feedback loop.",
        description=(
            "Continuous mode. Runs one sprint, ingests any new PR review "
            "comments as new stories, replans, runs the next sprint. Stops on "
            "goal met, stagnation (zero-progress sprint), budget cap, "
            "max_sprints, or Ctrl-C. Requires the team to already exist "
            "(create it with `orgos run` first)."
        ),
    )
    watch_p.add_argument("--repo", type=str, default=".")
    watch_p.add_argument("--team-id", type=str, required=True)
    watch_p.add_argument("--interval", type=int, default=0,
                          help="Seconds to sleep between sprints (default: 0).")
    watch_p.add_argument("--max-sprints", type=int, default=0,
                          help="Cap on iterations (default: 0 = unbounded).")
    watch_p.add_argument("--model", type=str, default="deepseek/deepseek-chat")
    watch_p.add_argument("--po-model", type=str, default=None)
    watch_p.add_argument("--architect-model", type=str, default=None)
    watch_p.add_argument("--test-model", type=str, default=None)
    watch_p.add_argument("--devsecops-model", type=str, default=None)
    watch_p.add_argument("--n-workers", type=int, default=1)
    watch_p.add_argument("--max-stories", type=int, default=20,
                          help="Per-sprint story cap.")
    watch_p.add_argument("--max-seconds", type=int, default=3600,
                          help="Per-sprint wall-clock timebox.")
    watch_p.add_argument("--open-pr", action="store_true",
                          help="Open a draft PR after the first sprint w/ commits, "
                               "then push subsequent sprint commits to it.")
    watch_p.add_argument("--pr-base", type=str, default="main")
    watch_p.add_argument("--max-usd", type=float, default=None,
                          help="Total $ cap across the watch session.")
    watch_p.add_argument("--max-tokens", type=int, default=None,
                          help="Total token cap across the watch session.")
    watch_p.set_defaults(func=_cmd_watch)

    # reset
    rst_p = sub.add_parser("reset", help="Wipe a team's workspace and branch")
    rst_p.add_argument("--repo", type=str, default=".")
    rst_p.add_argument("--team-id", type=str, required=True)
    rst_p.set_defaults(func=_cmd_reset)

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
