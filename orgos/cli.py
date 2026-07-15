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

    # Create or resume the workspace
    try:
        ws = TeamWorkspace.create(
            args.team_id, repo, goal=args.goal, model=args.model,
        )
        print(f"[cli] created workspace {ws.root}", flush=True)
    except TeamWorkspaceExists:
        if args.fresh:
            print(f"[cli] --fresh: resetting existing workspace {args.team_id}", flush=True)
            TeamWorkspace.open(args.team_id, repo).reset()
            ws = TeamWorkspace.create(
                args.team_id, repo, goal=args.goal, model=args.model,
            )
        else:
            print(f"[cli] resuming existing workspace {args.team_id}", flush=True)
            ws = TeamWorkspace.open(args.team_id, repo)

    if args.waterfall:
        print(f"[cli] mode=waterfall", flush=True)
        from orgos.agile.waterfall_runner import run_waterfall_campaign
        result = run_waterfall_campaign(
            workspace=ws, goal=ws.manifest().goal, model=args.model,
            max_stories_worked=args.max_stories,
            max_wall_seconds=args.max_seconds,
        )
    else:
        print(f"[cli] mode=scrum", flush=True)
        from orgos.agile.dispatcher import Dispatcher
        d = Dispatcher(
            workspace=ws, model=args.model,
            max_stories_worked=args.max_stories,
            max_wall_seconds=args.max_seconds,
        )
        result = d.run_campaign(goal=ws.manifest().goal)

    # Persist result to workspace
    result_path = ws.root / "campaign_result.json"
    from dataclasses import asdict
    result_dict = asdict(result)
    result_path.write_text(json.dumps(result_dict, indent=2, default=str))
    print(f"\n[cli] campaign complete — result at {result_path}", flush=True)
    print(f"[cli] stopped_because: {result.reason_stopped}", flush=True)
    print(f"[cli] stories: created={result.stories_created} done={result.stories_done} blocked={result.stories_blocked}", flush=True)
    print(f"[cli] tokens: in={result.total_tokens_input} out={result.total_tokens_output}", flush=True)

    # Render a per-team report
    from orgos.agile.team_report import render_team_report
    report_path = render_team_report(ws)
    print(f"[cli] report: {report_path}", flush=True)
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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="orgos", description="Deploy a Scrum team of AI agents against a goal.")
    sub = p.add_subparsers(dest="command", required=True)

    # run
    run_p = sub.add_parser("run", help="Run a team against a goal")
    run_p.add_argument("--repo", type=str, required=True,
                        help="Path to target git repo (worktree is created under it)")
    run_p.add_argument("--goal", type=str, required=True,
                        help="Goal description (a paragraph is fine)")
    run_p.add_argument("--team-id", type=str, required=True,
                        help="Unique team identifier (used for workspace dir)")
    run_p.add_argument("--model", type=str, default="deepseek/deepseek-chat")
    run_p.add_argument("--waterfall", action="store_true",
                        help="Use the waterfall 5-role pipeline instead of scrum")
    run_p.add_argument("--fresh", action="store_true",
                        help="If team-id already exists, wipe and start over")
    run_p.add_argument("--max-stories", type=int, default=20)
    run_p.add_argument("--max-seconds", type=int, default=3600)
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

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
