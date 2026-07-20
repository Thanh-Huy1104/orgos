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
import time
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

    # `orgos run` is now waterfall-only. Scrum lives on `orgos start` (v2
    # async runtime). We keep --waterfall as a no-op flag for scripts that
    # already pass it — but the mode is forced regardless.
    if not args.waterfall:
        print(
            "[cli] note: `orgos run` is waterfall-only (scrum → `orgos start`)",
            flush=True,
        )
    print(f"[cli] mode=waterfall", flush=True)
    from orgos.agile.waterfall_runner import run_waterfall_campaign
    result = run_waterfall_campaign(
        workspace=ws, goal=ws.manifest().goal, model=args.model,
        max_stories_worked=args.max_stories,
        max_wall_seconds=args.max_seconds,
    )

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


def _resolve_goal_and_spec(repo: Path, args) -> tuple[str, str, list]:
    """Extract goal + optionally load a spec file.

    Returns (goal, spec_text, prewritten_stories). When the spec file has
    explicit `## Story:` blocks, prewritten_stories is the parsed list —
    the caller passes it to decompose_goal(prewritten_stories=…) to skip
    the LLM decomposition and honor the human-declared boundaries.
    """
    from orgos.agile.spec_parser import parse_spec_text, spec_stories_to_draft_dicts

    goal = args.goal or ""
    spec_text = ""
    prewritten: list = []
    if getattr(args, "spec_file", None):
        spec_path = Path(args.spec_file).resolve()
        if spec_path.exists():
            spec_text = spec_path.read_text(encoding="utf-8")
            wiki_dir = repo / "wiki"
            wiki_dir.mkdir(parents=True, exist_ok=True)
            (wiki_dir / "SPEC.md").write_text(spec_text, encoding="utf-8")
            # Try to extract explicit story blocks. When present, use them
            # directly (the human already declared story boundaries). When
            # absent, fall back to the LLM decomposing the goal text.
            spec_stories = parse_spec_text(spec_text)
            if spec_stories:
                prewritten = spec_stories_to_draft_dicts(spec_stories)
                print(
                    f"[cli] spec: parsed {len(prewritten)} story blocks from "
                    f"{spec_path.name} — PO will use these directly (no LLM "
                    f"decomposition)", flush=True,
                )
            # Prepend a compact reference line so PO reads the spec on replan.
            goal = (
                (goal + "\n\n" if goal else "")
                + f"See wiki/SPEC.md for the full spec. Contents inlined:\n\n"
                + f"--- BEGIN SPEC ---\n{spec_text[:8000]}\n--- END SPEC ---"
            )
    return goal, spec_text, prewritten


def _load_orgos_toml(repo: Path) -> dict:
    """Load [tool.orgos] from pyproject.toml or [orgos] from .orgos.toml.

    Returns a flat dict of default values that CLI defaults fall back to.
    Explicit CLI flags always override. Silently returns {} when neither
    file exists or when tomllib can't parse them.
    """
    try:
        import tomllib
    except ImportError:  # pragma: no cover — Python < 3.11
        try:
            import tomli as tomllib  # type: ignore
        except ImportError:
            return {}

    for candidate, section in (
        (repo / ".orgos.toml", "orgos"),
        (repo / "pyproject.toml", "tool.orgos"),
    ):
        if not candidate.exists():
            continue
        try:
            with candidate.open("rb") as f:
                data = tomllib.load(f)
        except (OSError, Exception):
            continue
        node = data
        for key in section.split("."):
            if not isinstance(node, dict) or key not in node:
                node = None
                break
            node = node[key]
        if isinstance(node, dict):
            return node
    return {}


def _apply_config_defaults(args: "argparse.Namespace", repo: Path) -> None:
    """Fill in args that were left at parser defaults from .orgos.toml.

    Mutates `args` in place. Applied AFTER argparse so explicit CLI flags
    always win. Keys in the TOML file use hyphens or underscores; both
    are normalized.
    """
    cfg = _load_orgos_toml(repo)
    if not cfg:
        return
    for raw_key, val in cfg.items():
        key = raw_key.replace("-", "_")
        if not hasattr(args, key):
            continue
        current = getattr(args, key)
        # Only override falsy / zero / empty-string values (i.e. defaults).
        # Truthy explicit CLI flags always win.
        if current in (None, "", 0, False, [], (), "auto"):
            setattr(args, key, val)


def _cmd_start(args: argparse.Namespace) -> int:
    """Start the async agent team. Runs until stopped by SIGINT or `orgos stop`."""
    import asyncio
    import signal
    from orgos.agile.agent_loop import AsyncAgent
    from orgos.agile.board_store import BoardStore
    from orgos.agile.coding_executor import ClaudeCodeExecutor, CopilotCliExecutor
    from orgos.agile.spawn_executor import SpawnCodingExecutor
    from orgos.agile.mock_executor import MockExecutor
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

    _apply_config_defaults(args, repo)
    goal, _spec_text, prewritten_stories = _resolve_goal_and_spec(repo, args)
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

    # Team shape: PO + SM are singletons; delivery roles can scale via
    # --architects/--testers/--devsecops (default 1 each).
    n_arch = max(1, int(getattr(args, "architects", 1) or 1))
    n_test = max(1, int(getattr(args, "testers", 1) or 1))
    n_sec  = max(1, int(getattr(args, "devsecops", 1) or 1))
    # (role, instance) pairs. Instance 0 keeps historical layout.
    delivery_instances: list[tuple[str, int]] = (
        [("architect", i) for i in range(n_arch)]
        + [("test",     i) for i in range(n_test)]
        + [("devsecops",i) for i in range(n_sec)]
    )
    # §D2 — Customer agent (optional; enabled via --customer). Coord role
    # that judges shipped work against spec intent, independent of the AC
    # gate. When enabled, adds one more agent to the team.
    coord_instances = [("po", 0), ("scrum_master", 0)]
    if getattr(args, "customer", False):
        coord_instances.append(("customer", 0))
    all_instances = coord_instances + delivery_instances
    for r, i in all_instances:
        ws.ensure_agent_workspace(r, i)

    # §D1 — Adaptive parameters: load from disk (or init to defaults) and
    # attach to the workspace. Any subsequent code that reads
    # workspace.adaptive_params.<field> gets tuned values that the
    # adaptation loop (SM sprint boundary) updates from real sprint data.
    from orgos.agile.team_adaptation import load_or_init as _load_adaptive
    adaptive = _load_adaptive(ws)
    # Seed velocity_target from team-size heuristic if it's still at
    # the default 6 (no prior sprints have tuned it).
    heuristic_vt = max(6, len(delivery_instances) * 2)
    if adaptive.velocity_target == 6 and heuristic_vt > 6:
        adaptive.velocity_target = heuristic_vt
        from orgos.agile.team_adaptation import _save_params
        _save_params(ws.root, adaptive)
    # Legacy attribute for code that still reads workspace.velocity_target
    ws.velocity_target = adaptive.velocity_target
    print(
        f"[cli] adaptive params: velocity_target={adaptive.velocity_target} "
        f"max_ac_retries={adaptive.max_ac_retries} "
        f"sprint_duration={adaptive.sprint_duration_seconds}s "
        f"(version={adaptive.version})", flush=True,
    )

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

    # Per-role model overrides. Only meaningful when executor=spawn (LiteLLM
    # backend). claude/copilot/mock ignore model choice — one executor
    # instance serves every role.
    role_model = {
        "architect":  getattr(args, "architect_model", None) or args.model,
        "test":       getattr(args, "test_model", None)      or args.model,
        "devsecops":  getattr(args, "devsecops_model", None) or args.model,
        "po":         getattr(args, "po_model", None)        or args.model,
        "scrum_master": args.model,
    }

    def _make_executor(role: str):
        if choice == "claude":
            return ClaudeCodeExecutor()
        if choice == "copilot":
            return CopilotCliExecutor()
        if choice == "mock":
            return MockExecutor(wall_seconds=0.05)
        return SpawnCodingExecutor(model=role_model.get(role, args.model))

    # Shared executor instance for the label + for coord agents that don't
    # actually run code (PO/SM). Delivery agents pull their own via the
    # per-role factory below so per-role model works when executor=spawn.
    executor = _make_executor("architect")
    if choice == "spawn":
        exec_label = (
            f"spawn (LiteLLM; models: arch={role_model['architect']}, "
            f"test={role_model['test']}, devsecops={role_model['devsecops']}, "
            f"po={role_model['po']})"
        )
    elif choice == "claude":
        exec_label = "claude (Claude Code CLI — no API key needed)"
    elif choice == "copilot":
        exec_label = "copilot (GitHub Copilot CLI — no API key needed)"
    elif choice == "mock":
        exec_label = "mock (zero-LLM stub — infrastructure smoke only)"
    else:
        exec_label = choice
    print(f"[cli] coding executor: {exec_label}", flush=True)
    merge_queue = MergeQueue(ws)

    # Seed the board on first start.
    # In mock mode: synthetic backlog (no LLM call).
    # In real mode: PO decomposes the goal.
    existing = list(board.list_state("draft")) + list(board.list_state("refinement")) \
             + list(board.list_state("ready")) + list(board.list_state("in_progress"))
    if not existing:
        if choice == "mock":
            print("[cli] mock mode: seeding synthetic backlog", flush=True)
            from orgos.agile.mock_executor import seed_mock_backlog
            ids = seed_mock_backlog(board)
            print(f"[cli] drafted {len(ids)} synthetic stories", flush=True)
        else:
            if prewritten_stories:
                print(
                    f"[cli] drafting {len(prewritten_stories)} pre-declared "
                    f"stories from spec-file (skipping LLM decomposition)...",
                    flush=True,
                )
            else:
                print("[cli] decomposing goal into initial stories...", flush=True)
            try:
                from orgos.agile.goal_decomposer import decompose_goal
                # Use PO-specific model if provided, else the default.
                po_model = getattr(args, "po_model", None) or args.model
                ids = decompose_goal(
                    goal=goal, repo_root=repo, board=board, model=po_model,
                    prewritten_stories=prewritten_stories or None,
                )
                print(f"[cli] drafted {len(ids)} stories", flush=True)
            except Exception as e:
                print(
                    f"[cli] WARNING: goal decomposition failed: {e}",
                    file=sys.stderr, flush=True,
                )

    def _load_heartbeat(role: str) -> str:
        # Personas live in the orgos repo (source of truth), not the target.
        orgos_root = Path(__file__).resolve().parent.parent
        p = orgos_root / "agents" / role / "HEARTBEAT.md"
        text = p.read_text(encoding="utf-8") if p.exists() else "## Every 30 seconds\nCheck board."
        # Override SM's sprint boundary cadence at runtime if the user set
        # --sprint-duration-seconds. Rewrites 'Every N hours' → 'Every S seconds'
        # for the block that contains 'sprint boundary'.
        override = int(getattr(args, "sprint_duration_seconds", 0) or 0)
        if role == "scrum_master" and override > 0:
            import re
            def _sub(match):
                whole, body = match.group(0), match.group(1)
                if "sprint" in body.lower() and (
                    "boundary" in body.lower() or "open" in body.lower()
                    or "close" in body.lower() or "planning" in body.lower()
                ):
                    return f"## Every {override} seconds\n{body}"
                return whole
            text = re.sub(
                r"## Every \d+ (?:seconds?|minutes?|hours?)\n((?:.*\n?)*?)(?=(?:## Every |\Z))",
                _sub, text, flags=re.MULTILINE,
            )
        return text

    delivery_roles = {"architect", "test", "devsecops"}
    agents = {}
    for r, i in all_instances:
        key = r if i == 0 else f"{r}#{i}"
        # Delivery agents get a role-specific executor (may be per-role
        # model when executor=spawn). Coord agents (PO/SM) don't call the
        # executor at all so they can share whatever.
        agent_executor = _make_executor(r) if r in delivery_roles else executor
        agents[key] = AsyncAgent(
            role=r, instance=i,
            workspace=ws, board=board, executor=agent_executor,
            merge_queue=merge_queue, emitter=emitter,
            heartbeat_md=_load_heartbeat(r),
            is_delivery_agent=(r in delivery_roles),
        )
    print(
        f"[cli] team shape: {n_arch} architect(s), {n_test} test(s), "
        f"{n_sec} devsecops + 1 PO + 1 SM = {len(agents)} agents total",
        flush=True,
    )

    supervisor = TeamSupervisor(agents, emitter)

    # §A5 — budget governor. If --max-usd is set, install a BudgetTracker
    # with callbacks that emit events and (on exhaustion) signal supervisor
    # to shut down cleanly. Delivery agents auto-charge via charge_if_active.
    max_usd = float(getattr(args, "max_usd", 0) or 0)
    if max_usd > 0:
        from orgos.agile.budget import BudgetTracker, set_active_tracker
        def _on_warn(snap):
            emitter.emit(
                "budget_warning", spent_usd=snap.spent_usd, max_usd=snap.max_usd,
                percent=snap.percent_used, summary=f"budget 80%: {snap.as_line()}",
            )
        def _on_exhausted(snap):
            emitter.emit(
                "budget_exhausted", spent_usd=snap.spent_usd, max_usd=snap.max_usd,
                summary=f"budget exhausted: {snap.as_line()} — stopping team",
            )
            supervisor.stop()
        tracker = BudgetTracker(
            max_usd=max_usd, model_default=args.model,
            on_warning=_on_warn, on_exhausted=_on_exhausted,
        )
        set_active_tracker(tracker)
        print(f"[cli] budget cap: ${max_usd:.2f}", flush=True)

    # §H7 — threading.Timer watchdog. asyncio-based _auto_stop was
    # unreliable under load (v4 ran 6h 35min past a 4h timeout despite the
    # event loop clearly ticking; asyncio.sleep(14400) never returned). A
    # regular OS thread scheduled with threading.Timer fires INDEPENDENTLY
    # of the asyncio event loop and can call os._exit() to guarantee exit.
    watchdog_timer = None
    if args.timeout_seconds and args.timeout_seconds > 0:
        import threading
        timeout_seconds = int(args.timeout_seconds)
        grace_seconds = 60  # graceful-stop grace period before hard exit

        def _graceful_then_hard_exit():
            print(
                f"\n[cli] --timeout-seconds={timeout_seconds} reached; "
                f"shutting down team (graceful, {grace_seconds}s grace)",
                flush=True,
            )
            try:
                supervisor.stop()
            except Exception:
                pass
            # Sleep in the OS thread (not asyncio) so nothing can starve it
            time.sleep(grace_seconds)
            print(
                f"[cli] graceful shutdown did not exit within {grace_seconds}s — "
                "forcing os._exit(0)", flush=True,
            )
            # Best-effort: flush campaign result and clean up pid file
            try:
                from orgos.agile.campaign_summary import write_campaign_result
                write_campaign_result(
                    ws, board, executor=choice, reason_stopped="timeout_force",
                )
            except Exception:
                pass
            try:
                pid_file.unlink()
            except (OSError, NameError):
                pass
            os._exit(0)

        watchdog_timer = threading.Timer(
            timeout_seconds, _graceful_then_hard_exit,
        )
        watchdog_timer.daemon = True  # dies with the process
        watchdog_timer.name = "orgos-timeout-watchdog"

    async def _run_all():
        # §B6 — pass model into merge worker so its LLM conflict resolver
        # (safe file classes only: __init__.py, markdown, test files) uses
        # the same backend as delivery agents.
        merge_task = asyncio.create_task(run_merge_worker(
            merge_queue, ws, board, emitter,
            resolve_llm=True, model=args.model,
        ))
        sup_task = asyncio.create_task(supervisor.run())

        try:
            await sup_task
        finally:
            merge_task.cancel()

    def _handle_sigint(sig, frame):
        print("\n[cli] shutting down team", flush=True)
        supervisor.stop()
    signal.signal(signal.SIGINT, _handle_sigint)

    # Write a PID file so `orgos stop --team-id X` can find this process
    # exactly (not via fragile pgrep substring matching).
    pid_file = ws.root / "pid.txt"
    pid_file.write_text(str(os.getpid()), encoding="utf-8")

    print(f"[cli] team {args.team_id} started with {len(agents)} agents (pid={os.getpid()})", flush=True)
    # §w — one-line pointer at the live report (if serve is likely running).
    # We don't auto-start serve here (would need a port choice + thread), but
    # we do print the hint so `orgos serve --team-id X` is one command away.
    print(
        f"[cli] 💡 watch live: `orgos status --watch --team-id {args.team_id}`",
        flush=True,
    )
    print(
        f"[cli] 💡 tail events: `orgos logs --follow --team-id {args.team_id}`",
        flush=True,
    )
    print(
        f"[cli] 💡 open report: `orgos serve --team-id {args.team_id}` "
        f"→ http://127.0.0.1:8080/", flush=True,
    )
    # §H7 — start the timeout watchdog just before entering the event loop.
    # threading.Timer runs the callback on a background OS thread that is
    # independent of the asyncio event loop, so it fires reliably even when
    # the loop is under heavy load.
    if watchdog_timer is not None:
        watchdog_timer.start()
        print(
            f"[cli] timeout watchdog armed for {args.timeout_seconds}s "
            "(§H7 threading.Timer)", flush=True,
        )

    try:
        asyncio.run(_run_all())
    finally:
        # Cancel the watchdog if we exited before the timeout fired
        if watchdog_timer is not None:
            watchdog_timer.cancel()
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
    import signal
    import subprocess
    from orgos.agile.team_workspace import TeamWorkspace, TeamWorkspaceMissing

    repo = Path(getattr(args, "repo", ".")).resolve()
    pids: list[int] = []
    try:
        ws = TeamWorkspace.open(args.team_id, repo)
        pid_file = ws.root / "pid.txt"
        if pid_file.exists():
            pid_str = pid_file.read_text(encoding="utf-8").strip()
            if pid_str.isdigit():
                pids = [int(pid_str)]
    except TeamWorkspaceMissing:
        pass

    # POSIX fallback for legacy workspaces predating pid.txt.
    # Windows: skip fallback — pgrep isn't available.
    if not pids and sys.platform != "win32":
        r = subprocess.run(
            ["pgrep", "-f", f"orgos.cli.*start.*--team-id[= ]{args.team_id}( |$)"],
            capture_output=True, text=True,
        )
        pids = [int(p) for p in r.stdout.strip().splitlines() if p.isdigit()]
    if not pids:
        print(f"ERROR: no running team found with team-id {args.team_id}", file=sys.stderr)
        return 2

    # Cross-platform signal: os.kill(pid, SIGINT) works on POSIX and Windows
    # (on Windows, Python translates to a CTRL_C_EVENT for console processes).
    sent = 0
    for pid in pids:
        try:
            os.kill(pid, signal.SIGINT)
            sent += 1
        except (ProcessLookupError, PermissionError, OSError) as e:
            print(f"[cli] failed to signal pid {pid}: {e}", file=sys.stderr)
    print(f"[cli] sent SIGINT to {sent}/{len(pids)} process(es) for team {args.team_id}", flush=True)
    return 0


def _print_status_snapshot(ws) -> None:
    """One-shot pretty print of agent statuses + board counts."""
    from orgos.agile.board_store import BoardStore
    from orgos.agile.team_report import collect_agent_statuses

    board = BoardStore(ws.root / "board")
    counts = board.counts_by_state()
    header = (
        f"drafted={sum(counts.values())} "
        f"ready={counts.get('ready',0)} "
        f"in_progress={counts.get('in_progress',0)} "
        f"review={counts.get('review',0)} "
        f"pending={counts.get('pending_acceptance',0)} "
        f"done={counts.get('done',0)} "
        f"blocked={counts.get('blocked',0)}"
    )
    print(f"  board: {header}")
    for a in collect_agent_statuses(ws):
        mark = "●" if a["is_alive"] else "○"
        story = a["current_story"] or "(idle)"
        restarts = f" ↺{a['restart_count']}" if a["restart_count"] else ""
        # §H5 — show pull stats + heartbeat freshness for alive-idle diagnosis
        pull_info = ""
        if a.get("pull_attempts", 0) > 0:
            pull_info = f" pulls:{a['pull_success']}/{a['pull_attempts']}"
        hb = a.get("last_heartbeat_at") or ""
        hb_info = f" hb:{hb[11:19]}" if hb else ""
        print(
            f"  {mark} {a['role']:16s} {story[:32]:32s} "
            f"last:{(a['last_event_at'] or '')[:19]}{hb_info}{pull_info}{restarts}"
        )


def _cmd_status(args: argparse.Namespace) -> int:
    import time as _time
    from orgos.agile.team_workspace import TeamWorkspace, TeamWorkspaceMissing
    repo = Path(args.repo).resolve()
    try:
        ws = TeamWorkspace.open(args.team_id, repo)
    except TeamWorkspaceMissing as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    if not getattr(args, "watch", False):
        _print_status_snapshot(ws)
        return 0

    # --watch mode: redraw every N seconds until Ctrl-C.
    interval = max(1, int(getattr(args, "interval", 3) or 3))
    try:
        while True:
            # Clear screen (works on POSIX + Windows terminals that respect ANSI)
            print("\033[2J\033[H", end="")
            print(
                f"orgos status --watch — team={args.team_id}  "
                f"(refresh {interval}s, Ctrl-C to exit)\n"
            )
            _print_status_snapshot(ws)
            _time.sleep(interval)
    except KeyboardInterrupt:
        print("\n[cli] status --watch exit")
    return 0


def _cmd_logs(args: argparse.Namespace) -> int:
    """Tail live.jsonl with pretty formatting.

    Each event is one JSON line; we render as `HH:MM:SS  <emoji> <action>
    story=<id> <summary>` so a human can watch a run in real time.
    """
    import json as _json
    import time as _time
    from orgos.agile.team_workspace import TeamWorkspace, TeamWorkspaceMissing

    repo = Path(args.repo).resolve()
    try:
        ws = TeamWorkspace.open(args.team_id, repo)
    except TeamWorkspaceMissing as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    live_path = ws.root / "live.jsonl"

    def _fmt(e: dict) -> str:
        ts = (e.get("timestamp") or "")[11:19]
        emoji = e.get("emoji", "•")
        action = e.get("action", "?")
        sid = e.get("story_id", "")
        summary = e.get("summary", "")
        actor = e.get("worker") or e.get("role") or ""
        actor_tag = f"[{actor}]" if actor else ""
        sid_tag = f"story={sid[:32]}" if sid else ""
        return f"  {ts}  {emoji} {action:24s} {actor_tag:16s} {sid_tag:38s} {summary[:120]}"

    # Print the full backlog first (tail semantics: last N first, then follow).
    n = max(1, int(getattr(args, "n", 50) or 50))
    lines: list[str] = []
    if live_path.exists():
        try:
            lines = live_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
    for raw in lines[-n:]:
        raw = raw.strip()
        if not raw:
            continue
        try:
            print(_fmt(_json.loads(raw)))
        except _json.JSONDecodeError:
            continue

    if not getattr(args, "follow", False):
        return 0

    # --follow mode: seek to end and poll for new lines.
    print(f"\n  (following {live_path} — Ctrl-C to exit)\n")
    try:
        pos = live_path.stat().st_size if live_path.exists() else 0
        while True:
            if not live_path.exists():
                _time.sleep(0.5); continue
            size = live_path.stat().st_size
            if size < pos:
                pos = 0  # file rotated / truncated
            if size > pos:
                with live_path.open("r", encoding="utf-8") as f:
                    f.seek(pos)
                    new = f.read()
                    pos = f.tell()
                for raw in new.splitlines():
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        print(_fmt(_json.loads(raw)))
                    except _json.JSONDecodeError:
                        continue
            _time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[cli] logs --follow exit")
    return 0


def _cmd_plan(args: argparse.Namespace) -> int:
    """Dry-run: decompose goal (or parse spec-file) and print the story list.

    No workspace is created; no worker is spawned. Optionally hits the LLM
    if you're testing the PO's decomposition quality. With --spec-file
    containing `## Story:` blocks, no LLM is called at all.
    """
    from orgos.agile.spec_parser import parse_spec_text
    repo = Path(args.repo).resolve()
    _load_dotenv(repo)
    _apply_config_defaults(args, repo)

    goal = args.goal or ""
    stories: list[dict] = []
    spec_text = ""
    if getattr(args, "spec_file", None):
        p = Path(args.spec_file).resolve()
        if not p.exists():
            print(f"ERROR: --spec-file not found: {p}", file=sys.stderr)
            return 2
        spec_text = p.read_text(encoding="utf-8")
        for s in parse_spec_text(spec_text):
            stories.append({
                "title": s.title, "body": s.body, "type": s.type,
                "priority": s.priority, "files_to_touch": s.files_to_touch,
                "component": s.component, "acceptance_criteria": s.acceptance_criteria,
                "depends_on": s.depends_on,
            })
        if stories:
            print(f"[plan] parsed {len(stories)} stories from {p.name} "
                  f"(no LLM decomposition)")

    if not stories:
        # Fall back to real LLM decomposition — but write to a scratch
        # in-memory board so nothing persists.
        if not goal.strip() and not spec_text.strip():
            print("ERROR: provide --goal or --spec-file", file=sys.stderr)
            return 2
        goal_for_llm = goal or spec_text
        print("[plan] running LLM decomposition (dry — nothing persisted)...")
        import tempfile as _tf
        from orgos.agile.board_store import BoardStore
        with _tf.TemporaryDirectory(prefix="orgos-plan-") as tmp:
            board = BoardStore(Path(tmp))
            from orgos.agile.goal_decomposer import decompose_goal
            model = getattr(args, "po_model", None) or args.model
            try:
                ids = decompose_goal(
                    goal=goal_for_llm, repo_root=repo, board=board,
                    model=model, autofill_files_to_touch=False,
                )
            except Exception as e:
                print(f"[plan] decomposition failed: {e}", file=sys.stderr)
                return 3
            for iid in ids:
                s = board.read(iid)
                stories.append({
                    "title": s.title, "body": s.body, "type": s.type,
                    "priority": s.priority, "files_to_touch": s.files_to_touch,
                    "component": s.component,
                    "acceptance_criteria": list(getattr(s, "acceptance_criteria", []) or []),
                    "depends_on": s.depends_on,
                })

    if not stories:
        print("[plan] no stories produced.")
        return 3

    # Print a compact table.
    print(f"\n[plan] {len(stories)} stories:\n")
    print(f"  {'#':>3}  {'type':12s} {'pri':>3}  {'component':16s} {'title':60s}")
    print(f"  {'-'*3}  {'-'*12} {'-'*3}  {'-'*16} {'-'*60}")
    for i, s in enumerate(stories):
        comp = s.get("component") or "(derived)"
        files = ",".join((s.get("files_to_touch") or [])[:3])
        line = (
            f"  {i:3d}  {str(s.get('type','feature')):12s} "
            f"{int(s.get('priority', 0)):3d}  "
            f"{str(comp)[:16]:16s} {str(s.get('title',''))[:60]:60s}"
        )
        print(line)
        if files:
            print(f"       files: {files}")
        ac = s.get("acceptance_criteria") or []
        for a in ac[:3]:
            print(f"       AC: {a[:100]}")
        if len(ac) > 3:
            print(f"       AC: (+{len(ac)-3} more)")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    """Fix §C10 — Overall Definition of Done.

    Runs the team's built code through its own pytest suite. Answers the
    single question orgos couldn't answer before: does the code actually
    work? Writes verification.json to the workspace and prints a summary.
    """
    from orgos.agile.team_workspace import TeamWorkspace, TeamWorkspaceMissing
    from orgos.agile.verifier import verify_integration
    from dataclasses import asdict
    import json as _json

    repo = Path(args.repo).resolve()
    try:
        ws = TeamWorkspace.open(args.team_id, repo)
    except TeamWorkspaceMissing as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    print(
        f"[verify] running pytest in {ws.integration_worktree} "
        f"(timeout {args.timeout_seconds}s)...",
        flush=True,
    )
    result = verify_integration(
        integration_worktree=ws.integration_worktree,
        pytest_args=None,
        timeout_seconds=int(args.timeout_seconds or 240),
    )
    out = ws.root / "verification.json"
    out.write_text(_json.dumps(asdict(result), indent=2, default=str))
    print(f"[verify] {result.summary()}")
    print(f"[verify] wrote {out}")

    if not result.verified:
        return 3  # not verified is not "failed", but still non-zero for CI
    if result.failed or result.errors:
        return 1
    return 0


def _cmd_ship(args: argparse.Namespace) -> int:
    """Fix §C11 — Ship a successful run as a PR.

    Gate: >=80% delivered AND (if verified) >=90% pass rate.
    Pushes the team's integration branch to origin and opens a draft PR
    via `gh pr create`, using the delivery-receipt as body.
    """
    from orgos.agile.board_store import BoardStore
    from orgos.agile.deliver import build_report, format_receipt
    from orgos.agile.team_workspace import TeamWorkspace, TeamWorkspaceMissing
    from orgos.agile.verifier import verify_integration
    from dataclasses import asdict
    import json as _json
    import shutil as _shutil
    import subprocess as _sp

    repo = Path(args.repo).resolve()
    try:
        ws = TeamWorkspace.open(args.team_id, repo)
    except TeamWorkspaceMissing as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    if not _shutil.which("gh"):
        print("ERROR: gh CLI not on PATH — install it or use `orgos deliver` "
              "to write the receipt and push manually.", file=sys.stderr)
        return 2

    # Locate spec-file: --spec-file, else wiki/SPEC.md fallbacks
    spec_path = getattr(args, "spec_file", None)
    if spec_path:
        spec_path = Path(spec_path).resolve()
    else:
        for cand in (
            ws.wiki_dir / "SPEC.md",
            ws.integration_worktree / "wiki" / "SPEC.md",
            repo / "wiki" / "SPEC.md",
        ):
            if cand.exists():
                spec_path = cand
                break
    if spec_path is None or not spec_path.exists():
        print("ERROR: no spec-file found; pass --spec-file", file=sys.stderr)
        return 2

    board = BoardStore(ws.root / "board")
    report = build_report(
        workspace=ws, board=board,
        spec_text=spec_path.read_text(encoding="utf-8"),
        spec_path=spec_path,
    )
    delivered_pct = (
        100.0 * report.delivered_count / report.declared_count
        if report.declared_count else 0.0
    )
    threshold_deliver = float(getattr(args, "min_delivered_pct", 80.0))
    if delivered_pct < threshold_deliver:
        print(
            f"ERROR: delivery too low: {delivered_pct:.0f}% < "
            f"{threshold_deliver:.0f}% threshold. Not shipping. "
            f"Override with --force.",
            file=sys.stderr,
        )
        if not args.force:
            return 3

    # Run verify unless --skip-verify
    verify_result = None
    if not args.skip_verify:
        print("[ship] running verify before shipping...", flush=True)
        verify_result = verify_integration(
            integration_worktree=ws.integration_worktree,
            timeout_seconds=int(args.verify_timeout or 300),
        )
        threshold_pass = float(getattr(args, "min_pass_rate", 0.90))
        if verify_result.verified and verify_result.pass_rate < threshold_pass:
            print(
                f"ERROR: pass rate too low: {verify_result.pass_rate:.0%} < "
                f"{threshold_pass:.0%}. Not shipping. Override with --force.",
                file=sys.stderr,
            )
            if not args.force:
                return 3

    # Push integration branch
    m = ws.manifest()
    branch = m.branch
    print(f"[ship] pushing {branch} to origin...", flush=True)
    r = _sp.run(
        ["git", "push", "-u", "origin", branch],
        cwd=str(ws.integration_worktree),
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        print(f"ERROR: git push failed: {r.stderr[:400]}", file=sys.stderr)
        return 4

    # Build PR body from receipt + verify result
    body_parts = [format_receipt(report)]
    if verify_result:
        body_parts.append("\n## Runtime verification\n")
        body_parts.append(f"- {verify_result.summary()}\n")
        if verify_result.verified:
            body_parts.append(f"- Pass rate: {verify_result.pass_rate:.0%}\n")
            body_parts.append(f"- Duration: {verify_result.duration_seconds:.1f}s\n")
    body = "\n".join(body_parts)

    title = f"orgos: {report.team_id} — {report.delivered_count}/{report.declared_count} delivered"
    print(f"[ship] opening draft PR: {title}", flush=True)
    r = _sp.run(
        ["gh", "pr", "create", "--draft",
         "--title", title, "--body", body,
         "--base", args.pr_base, "--head", branch],
        cwd=str(ws.integration_worktree),
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        print(f"ERROR: gh pr create failed: {r.stderr[:400]}", file=sys.stderr)
        return 4

    pr_url = (r.stdout or "").strip().splitlines()[-1] if r.stdout else ""
    print(f"[ship] 🔀 draft PR opened: {pr_url}")
    if pr_url:
        (ws.root / "pr_url.txt").write_text(pr_url, encoding="utf-8")
    return 0


def _cmd_deliver(args: argparse.Namespace) -> int:
    """Reconcile spec-declared stories against what the team actually shipped.

    Writes delivery-receipt.md to the team's workspace root. Also prints a
    one-line summary to stdout. Safe to run mid-flight or post-run.
    """
    from orgos.agile.board_store import BoardStore
    from orgos.agile.deliver import build_report, format_receipt
    from orgos.agile.team_workspace import TeamWorkspace, TeamWorkspaceMissing

    repo = Path(args.repo).resolve()
    try:
        ws = TeamWorkspace.open(args.team_id, repo)
    except TeamWorkspaceMissing as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    spec_path = getattr(args, "spec_file", None)
    if spec_path:
        spec_path = Path(spec_path).resolve()
        if not spec_path.exists():
            print(f"ERROR: --spec-file not found: {spec_path}", file=sys.stderr)
            return 2
    else:
        # Fall back to the wiki/SPEC.md copy orgos wrote at start
        for candidate in (
            ws.wiki_dir / "SPEC.md",
            ws.integration_worktree / "wiki" / "SPEC.md",
            repo / "wiki" / "SPEC.md",
        ):
            if candidate.exists():
                spec_path = candidate
                break
    if spec_path is None or not spec_path.exists():
        print("ERROR: no spec file found. Pass --spec-file, or place one at "
              "wiki/SPEC.md before running.", file=sys.stderr)
        return 2

    board = BoardStore(ws.root / "board")
    spec_text = spec_path.read_text(encoding="utf-8")
    report = build_report(
        workspace=ws, board=board, spec_text=spec_text, spec_path=spec_path,
    )
    receipt = format_receipt(report)
    out = ws.root / "delivery-receipt.md"
    out.write_text(receipt, encoding="utf-8")

    pct = (
        100.0 * report.delivered_count / report.declared_count
        if report.declared_count else 0.0
    )
    print(
        f"[deliver] {report.delivered_count}/{report.declared_count} "
        f"({pct:.0f}%) delivered · {report.blocked_count} blocked · "
        f"{report.in_flight_count} in-flight · "
        f"${report.estimated_cost_usd:.3f} spent",
    )
    print(f"[deliver] wrote {out}")
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    """Pre-flight health check. Verifies orgos can actually run on this box.

    Checks: git ≥ 2.5, worktree support, .env parseable, target repo has
    commits, chosen executor is available (claude / copilot / API key for
    spawn), optional gh auth for --open-pr.
    """
    import shutil
    import subprocess as _sp

    checks: list[tuple[str, bool, str]] = []

    # git version
    try:
        r = _sp.run(["git", "--version"], capture_output=True, text=True, timeout=5)
        ver = (r.stdout or "").strip()
        ok = r.returncode == 0
        checks.append(("git installed", ok, ver or "not found"))
        # git worktree support (2.5+)
        if ok:
            r2 = _sp.run(["git", "worktree", "list"], capture_output=True,
                          text=True, timeout=5)
            checks.append((
                "git worktree support",
                r2.returncode == 0,
                "supported" if r2.returncode == 0 else "unsupported (need git ≥ 2.5)",
            ))
    except (FileNotFoundError, _sp.SubprocessError) as e:
        checks.append(("git installed", False, f"error: {e}"))

    # Target repo is a git repo with commits
    repo = Path(getattr(args, "repo", ".")).resolve()
    if not (repo / ".git").exists():
        checks.append(("target repo is git", False, f"{repo} has no .git"))
    else:
        checks.append(("target repo is git", True, str(repo)))
        try:
            r = _sp.run(["git", "rev-parse", "HEAD"], cwd=str(repo),
                          capture_output=True, text=True, timeout=5)
            has_commits = r.returncode == 0
            checks.append((
                "target repo has commits", has_commits,
                (r.stdout or r.stderr).strip() or "?",
            ))
        except _sp.SubprocessError as e:
            checks.append(("target repo has commits", False, str(e)))

    # .env parsing (best-effort)
    env_file = repo / ".env"
    if env_file.exists():
        try:
            _load_dotenv(repo)
            checks.append((".env loaded", True, str(env_file)))
        except Exception as e:  # pragma: no cover
            checks.append((".env loaded", False, str(e)))
    else:
        checks.append((".env present", False, f"missing {env_file} (only "
                                              f"needed if using spawn executor)"))

    # Executor availability
    have_claude = bool(shutil.which("claude"))
    have_copilot = bool(shutil.which("copilot"))
    have_api = any(k in os.environ for k in (
        "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY",
    ))
    checks.append(("claude CLI (executor=claude)", have_claude,
                   "found" if have_claude else "not on PATH"))
    checks.append(("copilot CLI (executor=copilot)", have_copilot,
                   "found" if have_copilot else "not on PATH"))
    checks.append(("API key (executor=spawn)", have_api,
                   "found" if have_api else "no ANTHROPIC/OPENAI/DEEPSEEK key in env"))
    executor_choice = getattr(args, "executor", "auto") or "auto"
    at_least_one = have_claude or have_copilot or have_api
    checks.append(("some executor usable", at_least_one,
                   f"executor={executor_choice}; at least one path viable"))

    # gh CLI (for --open-pr)
    have_gh = bool(shutil.which("gh"))
    checks.append(("gh CLI (--open-pr)", have_gh,
                   "found" if have_gh else "not on PATH (only needed for --open-pr)"))

    # Print results
    ok_count = sum(1 for _, ok, _ in checks if ok)
    print(f"[orgos doctor] {ok_count}/{len(checks)} checks passing\n")
    for name, ok, detail in checks:
        mark = "✓" if ok else "✗"
        print(f"  {mark} {name:38s} {detail}")

    # Non-zero exit only if the essentials are missing
    essential = ["git installed", "target repo is git",
                 "target repo has commits", "some executor usable"]
    failing = [n for n, ok, _ in checks if n in essential and not ok]
    if failing:
        print(f"\n[doctor] FAIL — essentials missing: {', '.join(failing)}",
              file=sys.stderr)
        return 2
    print("\n[doctor] ready to run")
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
        help="Run the WATERFALL 5-role pipeline against a goal (single-shot).",
        description=(
            "Run ONE waterfall pipeline: PO drafts → arch → test → security → PO "
            "signs off, once per story. Timeboxed by --sprint-story-cap and "
            "--sprint-duration; whichever hits first stops. This is the baseline "
            "against which Scrum's team-scale parallelism is measured. "
            "For the scrum runtime, use `orgos start` (v2 async runtime with "
            "PO + SM + N delivery agents)."
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
    start_p.add_argument("--spec-file", type=str, default=None,
                          help="Markdown PRD. If it contains `## Story:` blocks, "
                               "they're used directly (no LLM decomposition). "
                               "Otherwise the PO decomposes the whole file.")
    start_p.add_argument("--model", type=str, default="deepseek/deepseek-chat")
    # Per-role models — highest-leverage variable per the RESULTS.md thesis.
    # Only wired on `start` because scrum runtime is where team-scale actually
    # runs. `run` (waterfall) has its own copies of these flags.
    start_p.add_argument("--po-model", type=str, default=None,
                          help="Model for the Product Owner (decomposition + "
                               "replan). Highest leverage; a smarter PO writes "
                               "better stories.")
    start_p.add_argument("--architect-model", type=str, default=None,
                          help="Model for architect delivery agents.")
    start_p.add_argument("--test-model", type=str, default=None,
                          help="Model for test delivery agents.")
    start_p.add_argument("--devsecops-model", type=str, default=None,
                          help="Model for devsecops delivery agents.")
    start_p.add_argument(
        "--executor", type=str,
        choices=("auto", "claude", "copilot", "spawn", "mock"),
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
    start_p.add_argument(
        "--sprint-duration-seconds", type=int, default=0,
        help="Override SM's sprint boundary cadence at runtime (0 = use the "
             "cadence written in agents/scrum_master/HEARTBEAT.md, currently 4h). "
             "Useful for demos and comparison runs — e.g. 300 makes SM close+open "
             "sprints every 5 minutes, so a 30-min run sees ~6 sprints and SPE "
             "becomes measurable per sprint.",
    )
    start_p.add_argument(
        "--architects", type=int, default=1,
        help="Number of concurrent architect agents (default 1). Each gets its "
             "own worktree + branch (agents/architect-N/). Tests whether Scrum's "
             "coordination overhead pays off at team scale.",
    )
    start_p.add_argument(
        "--testers", type=int, default=1,
        help="Number of concurrent test agents (default 1). Same as --architects.",
    )
    start_p.add_argument(
        "--devsecops", type=int, default=1,
        help="Number of concurrent devsecops agents (default 1). Same as --architects.",
    )
    start_p.add_argument(
        "--customer", action="store_true",
        help="§D2 — Enable the Customer agent (external voice of the spec author). "
             "Reviews the shipped increment every 15 min and rejects stories "
             "that pass the AC gate but diverge from the spec's intent. "
             "Adds 1 agent to the team.",
    )
    start_p.add_argument(
        "--max-usd", type=float, default=0.0,
        help="Budget cap in USD. When cumulative spend crosses this, the "
             "team stops cleanly (finishes in-flight stories, then exits). "
             "0 = no cap (default). Emits budget_warning at 80% and "
             "budget_exhausted at 100%.",
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
        help="Print per-agent status for a team. Use --watch for live top-like view.",
    )
    status_p.add_argument("--repo", type=str, default=".")
    status_p.add_argument("--team-id", type=str, required=True)
    status_p.add_argument("--watch", action="store_true",
                           help="Re-render every --interval seconds until Ctrl-C.")
    status_p.add_argument("--interval", type=int, default=3,
                           help="Refresh interval in seconds for --watch (default 3).")
    status_p.set_defaults(func=_cmd_status)

    # logs
    logs_p = sub.add_parser(
        "logs",
        help="Tail the team's event stream (live.jsonl) with pretty formatting.",
    )
    logs_p.add_argument("--repo", type=str, default=".")
    logs_p.add_argument("--team-id", type=str, required=True)
    logs_p.add_argument("-n", type=int, default=50,
                         help="Print the last N lines first (default 50).")
    logs_p.add_argument("-f", "--follow", action="store_true",
                         help="Follow the stream, printing new events as they arrive.")
    logs_p.set_defaults(func=_cmd_logs)

    # plan — dry-run decomposition of a goal or spec-file
    plan_p = sub.add_parser(
        "plan",
        help="Dry-run: show the story list a goal/spec-file would decompose to.",
        description=(
            "Print the story list without spinning up a team. If --spec-file has "
            "explicit `## Story:` blocks, no LLM is called. Otherwise the PO "
            "decomposes the goal and the resulting stories are printed to a "
            "temp board that's discarded."
        ),
    )
    plan_p.add_argument("--repo", type=str, default=".")
    plan_p.add_argument("--goal", type=str, default="")
    plan_p.add_argument("--spec-file", type=str, default=None)
    plan_p.add_argument("--model", type=str, default="deepseek/deepseek-chat")
    plan_p.add_argument("--po-model", type=str, default=None)
    plan_p.set_defaults(func=_cmd_plan)

    # doctor — pre-flight health check
    doc_p = sub.add_parser(
        "doctor",
        help="Verify orgos can run: git, worktree, .env, executor, gh, etc.",
    )
    doc_p.add_argument("--repo", type=str, default=".")
    doc_p.add_argument("--executor", type=str,
                        choices=("auto", "claude", "copilot", "spawn", "mock"),
                        default="auto")
    doc_p.set_defaults(func=_cmd_doctor)

    # verify — run the built code's own test suite (Fix §C10)
    verify_p = sub.add_parser(
        "verify",
        help="Run the team's built code through its own pytest suite (overall DoD).",
        description=(
            "Creates a venv in the team's integration worktree, pip-installs "
            "the built package, and runs pytest. Answers 'did the code we "
            "shipped actually work.' Writes verification.json. Exits with 0 "
            "on green, 1 on failure, 3 if unable to verify (missing test infra)."
        ),
    )
    verify_p.add_argument("--repo", type=str, default=".")
    verify_p.add_argument("--team-id", type=str, required=True)
    verify_p.add_argument("--timeout-seconds", type=int, default=240,
                           help="Kill pytest after N seconds (default 240).")
    verify_p.set_defaults(func=_cmd_verify)

    # ship — push branch + open PR gated on delivery + verify (Fix §C11)
    ship_p = sub.add_parser(
        "ship",
        help="Push integration branch + open draft PR when delivery/verify pass thresholds.",
        description=(
            "Ship a successful run as a PR. Gate: >=80%% delivered AND >=90%% "
            "pytest pass rate (both configurable). Uses gh CLI. Requires an "
            "origin remote."
        ),
    )
    ship_p.add_argument("--repo", type=str, default=".")
    ship_p.add_argument("--team-id", type=str, required=True)
    ship_p.add_argument("--spec-file", type=str, default=None)
    ship_p.add_argument("--pr-base", type=str, default="main")
    ship_p.add_argument("--min-delivered-pct", type=float, default=80.0,
                         help="Minimum delivery % to open PR (default 80).")
    ship_p.add_argument("--min-pass-rate", type=float, default=0.90,
                         help="Minimum pytest pass rate (0.0-1.0) to open PR (default 0.9).")
    ship_p.add_argument("--skip-verify", action="store_true",
                         help="Skip runtime verification (only apply delivery threshold).")
    ship_p.add_argument("--verify-timeout", type=int, default=300)
    ship_p.add_argument("--force", action="store_true",
                         help="Push even when thresholds aren't met.")
    ship_p.set_defaults(func=_cmd_ship)

    # deliver — spec-vs-delivered reconciliation
    deliver_p = sub.add_parser(
        "deliver",
        help="Reconcile spec-declared stories vs what the team shipped; write delivery-receipt.md.",
        description=(
            "Compare a spec-file's declared stories against the team's board. "
            "Writes delivery-receipt.md to the team's workspace root, listing "
            "per-story delivered / blocked / not-matched. Safe to run mid-flight "
            "or after --timeout-seconds fires. Uses wiki/SPEC.md as default "
            "when --spec-file is omitted."
        ),
    )
    deliver_p.add_argument("--repo", type=str, default=".")
    deliver_p.add_argument("--team-id", type=str, required=True)
    deliver_p.add_argument("--spec-file", type=str, default=None,
                            help="Path to spec markdown. Defaults to wiki/SPEC.md "
                                 "if the team was started with --spec-file.")
    deliver_p.set_defaults(func=_cmd_deliver)

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
