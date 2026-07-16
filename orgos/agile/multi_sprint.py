"""Multi-sprint runner — chain N Scrum sprints against one goal.

Real Scrum: teams don't finish a goal in one sprint. They run sprints
back-to-back, doing a retrospective + PO replan between each, until either
the goal is met (PO declares it) or the sprint budget is exhausted.

This module orchestrates the outer loop:

  for i in 1..N sprints:
    - if not the first sprint: run PO replan (reads retro + backlog, may draft new stories)
    - run sprint (dispatcher.run_campaign)  →  retro auto-fires at end
    - append record to workspace.root/sprints.jsonl
    - check stop conditions: goal_met_by_po, stagnation (no progress N in a row)
  → open PR (opt-in, once at very end)

Each sprint uses the SAME persistent worktree, board, and wiki. The board
accumulates: blocked stories from sprint 1 might get unblocked in sprint 3;
wiki decisions from sprint 2 inform architecture in sprint 4.

The dispatcher itself doesn't know it's inside a multi-sprint run — it just
runs a normal sprint against the current board. This module is the outer
loop that wraps it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from orgos.agile.board_store import BoardStore
from orgos.agile.dispatcher import Dispatcher, DispatchResult
from orgos.agile.live_events import EventEmitter
from orgos.agile.replan import run_replan
from orgos.agile.sprint_history import (
    SprintRecord, append_record, next_sprint_num, read_history, stagnation_detected,
)
from orgos.agile.team_workspace import TeamWorkspace


@dataclass
class MultiSprintResult:
    team_id: str
    goal: str
    started_at: str
    ended_at: str
    n_sprints_run: int
    stop_reason: str
    total_stories_done: int
    total_stories_blocked: int
    total_tokens_input: int = 0
    total_tokens_output: int = 0
    pr_url: str = ""
    sprint_records: list[SprintRecord] = field(default_factory=list)


def _extract_retro_from_wiki(workspace: TeamWorkspace, team_id: str
                              ) -> tuple[str, list[str], list[str]]:
    """Parse the most recent retro block for this team out of wiki/RETRO.md.

    Returns (action_item, went_well_list, went_wrong_list). All empty if not found.
    """
    import re
    p = workspace.source_repo / "wiki" / "RETRO.md"
    if not p.exists():
        return "", [], []
    text = p.read_text(encoding="utf-8")
    # Find every "## Retro — sprint <team_id>" block, take the last one
    header = f"## Retro — sprint {team_id}"
    if header not in text:
        return "", [], []
    blocks = text.split("## Retro — sprint ")
    # Each element after split (except [0]) starts with a team_id
    matching = [b for b in blocks[1:] if b.startswith(team_id)]
    if not matching:
        return "", [], []
    last = matching[-1]

    def _bullets(section_header: str) -> list[str]:
        m = re.search(rf"### {re.escape(section_header)}\n((?:  - .+\n?)+)", last)
        if not m:
            return []
        return [
            line.strip().lstrip("- ").strip()
            for line in m.group(1).strip().split("\n")
            if line.strip()
        ]

    action = ""
    m = re.search(r"### Action item for next sprint\n\s*(.+)", last)
    if m:
        action = m.group(1).strip()

    return action, _bullets("What went well"), _bullets("What went wrong")


def run_multi_sprint(
    *,
    workspace: TeamWorkspace,
    goal: str,
    model: str,
    role_models: Optional[dict[str, str]] = None,
    n_workers: int = 1,
    n_sprints: int = 3,
    sprint_story_cap: int = 20,
    sprint_duration_sec: int = 3600,
    open_pr: bool = False,
    pr_base: str = "main",
    stagnation_window: int = 2,
    max_total_usd: Optional[float] = None,
    max_total_tokens: Optional[int] = None,
    log: Optional[Callable[[str], None]] = None,
) -> MultiSprintResult:
    """Run N sprints back-to-back against the same goal.

    Stops early if:
      - PO's replan declares goal_met=true
      - stagnation: `stagnation_window` sprints in a row shipped 0 stories
      - n_sprints exhausted
    """
    _log = log or (lambda m: print(f"[multi-sprint] {m}", flush=True))
    started_at = datetime.now(timezone.utc).isoformat()
    emitter = EventEmitter(workspace.root, console_log=_log)

    emitter.emit(
        "multi_sprint_started",
        n_sprints=n_sprints, goal=goal[:200],
        summary=f"planning {n_sprints} sprints against goal",
    )

    total_in = 0
    total_out = 0
    stop_reason = ""
    all_records: list[SprintRecord] = read_history(workspace.root)
    sprints_this_run: list[SprintRecord] = []
    last_pr_url = ""
    # If a PR was opened in an earlier run, resume tracking it
    prior_pr_urls = [r.pr_url for r in all_records if r.pr_url]
    if prior_pr_urls:
        last_pr_url = prior_pr_urls[-1]

    # Wrap the dispatcher's token accumulator so we can roll totals up here
    # too (dispatchers reset per-sprint).
    accum_lock_holder = {"in": 0, "out": 0}

    for sprint_idx in range(1, n_sprints + 1):
        sprint_num = next_sprint_num(workspace.root)
        _log(f"── sprint {sprint_num} (multi-run pass {sprint_idx}/{n_sprints}) ──")

        # PO replan between sprints (skip on the very first sprint of the
        # multi-run — the dispatcher will run its own decompose on an empty board).
        if all_records:  # there IS prior sprint history — replan
            board = BoardStore(workspace.board_dir)

            # Before replan: ingest any new PR review comments as new stories.
            # Then the PO's replan sees them in the backlog snapshot.
            if last_pr_url:
                try:
                    from orgos.agile.pr_feedback import ingest_pr_feedback
                    ingest_pr_feedback(
                        workspace=workspace, pr_url=last_pr_url,
                        board=board, emitter=emitter, sprint_num=sprint_num,
                    )
                except Exception as e:
                    emitter.emit(
                        "pr_feedback_error", error=str(e),
                        summary=f"ingest crashed: {e}",
                    )

            action, well, wrong = _extract_retro_from_wiki(
                workspace, workspace.team_id,
            )
            last_record = all_records[-1]
            # Enrich the record with retro-mined content for the replan brief
            last_record.retro_action_item = action or last_record.retro_action_item
            last_record.retro_went_well = well or last_record.retro_went_well
            last_record.retro_went_wrong = wrong or last_record.retro_went_wrong

            decision = run_replan(
                workspace=workspace, board=board, emitter=emitter,
                model=model, goal=goal, history=all_records,
                last_retro=last_record,
                token_accumulator=lambda r: _accum_from_result(
                    r, accum_lock_holder,
                ),
            )
            if decision.get("goal_met"):
                stop_reason = "goal_met_declared_by_po"
                _log(f"PO declared goal met: {decision.get('reasoning','')[:200]}")
                break

        # Run one sprint
        dispatcher = Dispatcher(
            workspace=workspace, model=model, role_models=role_models,
            n_workers=n_workers,
            max_stories_worked=sprint_story_cap,
            max_wall_seconds=sprint_duration_sec,
            open_pr=False,  # never per-sprint; open once at multi-run end
            log=_log,
        )
        sprint_result: DispatchResult = dispatcher.run_campaign(goal=goal)
        total_in += sprint_result.total_tokens_input
        total_out += sprint_result.total_tokens_output

        # Mine retro back out of the wiki (the dispatcher's retro just wrote it)
        action, well, wrong = _extract_retro_from_wiki(
            workspace, workspace.team_id,
        )

        record = SprintRecord(
            sprint_num=sprint_num,
            started_at=sprint_result.started_at,
            ended_at=sprint_result.ended_at,
            reason_stopped=sprint_result.reason_stopped,
            stories_done=sprint_result.stories_done,
            stories_blocked=sprint_result.stories_blocked,
            stories_created=sprint_result.stories_created,
            tokens_input=sprint_result.total_tokens_input,
            tokens_output=sprint_result.total_tokens_output,
            pr_url=sprint_result.pr_url,
            retro_action_item=action,
            retro_went_well=well,
            retro_went_wrong=wrong,
        )
        append_record(workspace.root, record)
        all_records.append(record)
        sprints_this_run.append(record)

        _log(
            f"sprint {sprint_num} done — done={record.stories_done} "
            f"blocked={record.stories_blocked} action=\"{record.retro_action_item[:80]}\""
        )

        # Open PR early (after first sprint w/ a commit) so reviewer feedback
        # can flow back into later sprints. Only if --open-pr and not yet open.
        if open_pr and not last_pr_url and record.stories_done > 0:
            try:
                from orgos.agile.pr_publisher import open_pr_for_team
                pub = open_pr_for_team(workspace, base=pr_base)
                if pub.published:
                    last_pr_url = pub.pr_url
                    emitter.emit("pr_opened", pr_url=pub.pr_url,
                                  summary=f"draft PR: {pub.pr_url}")
                elif pub.error:
                    emitter.emit("pr_failed", error=pub.error,
                                  summary=pub.error[:200])
                else:
                    emitter.emit("pr_skipped", reason=pub.skipped_reason,
                                  summary=pub.skipped_reason)
            except Exception as e:
                emitter.emit("pr_failed", error=str(e),
                              summary=f"publisher crashed: {e}")
        elif open_pr and last_pr_url and record.stories_done > 0:
            # PR already open — push the branch so reviewers see new commits
            try:
                from orgos.agile.pr_publisher import _push_branch
                ok, msg = _push_branch(workspace.worktree, workspace.manifest().branch)
                if ok:
                    emitter.emit(
                        "pr_opened", pr_url=last_pr_url,
                        summary=f"pushed sprint {sprint_num} commits to PR",
                    )
                else:
                    emitter.emit("pr_failed", error=msg, summary=msg[:200])
            except Exception as e:
                emitter.emit("pr_failed", error=str(e),
                              summary=f"push crashed: {e}")

        # Stagnation check
        if stagnation_detected(workspace.root, window=stagnation_window,
                                min_done=1):
            stop_reason = f"stagnation ({stagnation_window} sprints with no stories done)"
            _log(f"stopping: {stop_reason}")
            break

        # Budget check — token cap
        if max_total_tokens is not None and (total_in + total_out) >= max_total_tokens:
            stop_reason = (
                f"budget_exhausted: tokens {total_in + total_out} >= "
                f"cap {max_total_tokens}"
            )
            _log(f"stopping: {stop_reason}")
            break

        # Budget check — dollar cap
        if max_total_usd is not None:
            from orgos.agile.pricing import cost_usd
            spent = cost_usd(model, total_in, total_out)
            if spent >= max_total_usd:
                stop_reason = (
                    f"budget_exhausted: cost ${spent:.4f} >= cap ${max_total_usd:.2f}"
                )
                _log(f"stopping: {stop_reason}")
                break

    else:  # for-loop completed without break
        stop_reason = f"n_sprints_exhausted ({n_sprints})"

    # (PR is opened after the first sprint w/ commits; subsequent sprints
    # push their commits to the same PR.)

    ended_at = datetime.now(timezone.utc).isoformat()
    emitter.emit(
        "multi_sprint_finished",
        n_sprints=len(sprints_this_run), stop_reason=stop_reason,
        total_stories_done=sum(r.stories_done for r in sprints_this_run),
        summary=(
            f"ran {len(sprints_this_run)} sprints, "
            f"stopped: {stop_reason}"
        ),
    )

    return MultiSprintResult(
        team_id=workspace.team_id,
        goal=goal,
        started_at=started_at,
        ended_at=ended_at,
        n_sprints_run=len(sprints_this_run),
        stop_reason=stop_reason,
        total_stories_done=sum(r.stories_done for r in sprints_this_run),
        total_stories_blocked=sum(r.stories_blocked for r in sprints_this_run),
        total_tokens_input=total_in,
        total_tokens_output=total_out,
        pr_url=last_pr_url,
        sprint_records=sprints_this_run,
    )


def _accum_from_result(result: Any, holder: dict) -> tuple[int, int]:
    """Token accumulator for replan spawns (dispatcher has its own)."""
    tu = getattr(result, "token_usage", None) or {}
    i = tu.get("prompt_tokens", 0)
    o = tu.get("completion_tokens", 0)
    holder["in"] = holder.get("in", 0) + i
    holder["out"] = holder.get("out", 0) + o
    return i, o
