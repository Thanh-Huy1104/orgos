"""AsyncAgent — one asyncio task per role. No dispatcher; agent self-organizes.

Two modes:
  - is_delivery_agent=True  → checks the board on each heartbeat, pulls
                              matching stories, invokes CodingExecutor.
  - is_delivery_agent=False → skips the board (coordination agents like
                              PO/scrum_master don't consume stories).

Both modes run scheduled tasks from HEARTBEAT.md (retro, replan, poker, etc.).
Concrete ceremony action wiring happens in a follow-up task; this module
provides the pull-and-work loop + the tick-per-schedule mechanic.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from pathlib import Path
from typing import Any, Optional


def _matches_any(text: str, *words: str) -> bool:
    """Word-boundary match — 'spec' matches 'the spec' but not 'retrospective'."""
    return any(re.search(rf"\b{re.escape(w)}\b", text) for w in words)

from orgos.agile.board_store import BoardStore
from orgos.agile.coding_executor import CodingExecutor, ExecutionResult
from orgos.agile.heartbeat_scheduler import HeartbeatScheduler
from orgos.agile.live_events import EventEmitter
from orgos.agile.merge_queue import MergeQueue, MergeRequest


class AsyncAgent:
    def __init__(
        self,
        *,
        role: str,
        workspace: Any,
        board: BoardStore,
        executor: CodingExecutor,
        merge_queue: MergeQueue,
        emitter: EventEmitter,
        heartbeat_md: str,
        is_delivery_agent: bool = True,
        persona_scaffold: str = "",
        instance: int = 0,
    ):
        self.role = role
        # instance = 0 → historical single-agent-per-role layout.
        # instance > 0 → this is the Nth extra agent of the same role
        # (uses agents/<role>-<i>/worktree and team/T/agent/<role>-<i>).
        self.instance = instance
        # Actor label carries the instance so audit trails are unambiguous
        # when N>1 agents of the same role are pulling.
        self.actor = role if instance == 0 else f"{role}#{instance}"
        self.workspace = workspace
        self.board = board
        self.executor = executor
        self.merge_queue = merge_queue
        self.emitter = emitter
        self.scheduler = HeartbeatScheduler(heartbeat_md)
        self.is_delivery_agent = is_delivery_agent
        self.persona_scaffold = persona_scaffold or f"You are the {role} agent."
        self._alive = True
        self._start_wall = 0.0

    def stop(self) -> None:
        self._alive = False

    async def loop(self) -> None:
        self._start_wall = time.time()
        # Reset scheduled-task fired markers so that a crash+restart doesn't
        # leave _last_fired_at holding a value from the previous session
        # (which would make (now - _last_fired_at) negative and freeze tasks
        # for up to one full cadence interval after restart).
        for t in self.scheduler.tasks:
            t._last_fired_at = -1.0
        self.emitter.emit("agent_started", role=self.role,
                          summary=f"{self.role} online")

        while self._alive:
            now = time.time() - self._start_wall
            due_tasks = self.scheduler.pending(now)

            for task in due_tasks:
                text = task.action_text.lower()
                # Delivery: implicit "check board" for short-cadence tasks
                if self.is_delivery_agent and task.cadence_seconds <= 60 \
                   and ("board" in text or "story" in text or "check" in text):
                    await self._pull_and_work_once()
                    continue
                # Ceremony routing. Order matters because persona text may
                # mention several action nouns; the most-specific-first order:
                #   1. 'retrospective' → retro (SM's primary verb)
                #   2. 'replan' → replan (PO's primary verb; overrides bare
                #      'RETRO.md' filename references in PO's text)
                #   3. bare 'retro' → retro (fallback)
                #   4. 'backlog'/'spec' → replan
                #   5. 'poker'/'refinement' → poker
                #   6. 'pr' + [comment|feedback|review] → pr_feedback
                # All checks use word boundaries so 'spec' does not match
                # 'retrospective', etc.
                if _matches_any(text, "sprint") and _matches_any(
                    text, "open", "close", "start", "boundary", "planning",
                ):
                    await self._run_sprint_boundary()
                    continue
                if _matches_any(text, "accept", "acceptance") and \
                        _matches_any(text, "story", "stories", "review", "merged"):
                    await self._run_acceptance()
                    continue
                if _matches_any(text, "retrospective"):
                    await self._run_retro()
                    continue
                if _matches_any(text, "replan"):
                    await self._run_replan()
                    continue
                if _matches_any(text, "retro"):
                    await self._run_retro()
                    continue
                if _matches_any(text, "backlog", "spec"):
                    await self._run_replan()
                    continue
                if _matches_any(text, "elevate", "elevation", "reclaim", "stuck"):
                    await self._run_elevation()
                    continue
                if _matches_any(text, "poker", "refinement"):
                    await self._run_poker()
                    continue
                if _matches_any(text, "pr") and _matches_any(
                    text, "comment", "comments", "feedback", "review",
                ):
                    await self._run_pr_feedback()
                    continue
                # Otherwise: no-op (unknown scheduled task; log for the retro to notice)
                self.emitter.emit(
                    "scheduled_noop", role=self.role,
                    summary=f"unrouted schedule: {task.action_text[:80]}",
                )

            # Sleep until next scheduled tick (or 1s min, so stop() is responsive)
            await asyncio.sleep(min(1.0, self.scheduler.next_tick_in(now)))

        self.emitter.emit("agent_stopped", role=self.role,
                          summary=f"{self.role} shut down cleanly")

    async def _run_retro(self) -> None:
        try:
            from orgos.agile.retrospective import run_retrospective
            m = self.workspace.manifest()
            await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: run_retrospective(
                    workspace=self.workspace, board=self.board,
                    emitter=self.emitter, model=m.model,
                    goal=m.goal, reason_stopped="scheduled",
                    started_at=m.created_at, ended_at=m.created_at,
                    tokens_total=0,
                ),
            )
        except Exception as e:
            self.emitter.emit("retro_failed", role=self.role, summary=str(e)[:200])

    async def _run_replan(self) -> None:
        try:
            from orgos.agile.replan import run_replan
            from orgos.agile.sprint_history import read_history
            m = self.workspace.manifest()
            await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: run_replan(
                    workspace=self.workspace, board=self.board,
                    emitter=self.emitter, model=m.model,
                    goal=m.goal, history=read_history(self.workspace.root),
                ),
            )
        except Exception as e:
            self.emitter.emit("replan_failed", role=self.role, summary=str(e)[:200])

    async def _run_elevation(self) -> None:
        """Fix §B7 — bump stale ready stories, reclaim stuck in_progress.

        Scheduled from SM's `Every 3 minutes` heartbeat block. All the real
        logic lives in orgos.agile.elevate for testability; this is just the
        async wrapper that dispatches to a thread.
        """
        try:
            from orgos.agile.elevate import run_elevation_pass
            counts = await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: run_elevation_pass(self.board, self.emitter),
            )
            if counts.get("elevated_ready") or counts.get("reclaimed_in_progress"):
                self.emitter.emit(
                    "elevation_pass",
                    elevated=counts["elevated_ready"],
                    reclaimed=counts["reclaimed_in_progress"],
                    summary=(
                        f"elevated {counts['elevated_ready']} ready, "
                        f"reclaimed {counts['reclaimed_in_progress']} in_progress"
                    ),
                )
        except Exception as e:
            self.emitter.emit(
                "elevation_failed", role=self.role, summary=str(e)[:200],
            )

    async def _run_poker(self) -> None:
        """Refinement ceremony: vote on each draft/refinement story, converge
        on a point value, and transition the story to ready so delivery agents
        can pull it.

        Flow per story:
          draft → refinement (if in draft)
          run_poker_round → 3 votes
          if divergent → run_discussion_and_revote
          set_points(median of Fibonacci indices)
          refinement → ready
        """
        try:
            from orgos.agile.poker import (
                run_poker_round, discussion_needed,
                run_discussion_and_revote, FIB,
            )
            m = self.workspace.manifest()
            # Snapshot the list — set_points/transition below would mutate what
            # list_state returns mid-iteration otherwise.
            stories = list(self.board.list_state("draft")) + \
                      list(self.board.list_state("refinement"))
            for story in stories:
                await asyncio.get_running_loop().run_in_executor(
                    None,
                    lambda s=story: self._refine_one_story(
                        s, m.model, run_poker_round, discussion_needed,
                        run_discussion_and_revote, FIB,
                    ),
                )
        except Exception as e:
            self.emitter.emit("poker_failed", role=self.role, summary=str(e)[:200])

    def _refine_one_story(
        self, story, model, run_poker_round, discussion_needed,
        run_discussion_and_revote, FIB,
    ) -> None:
        """Blocking helper — called from _run_poker's executor thread."""
        # 1. draft → refinement (skip if already there)
        if story.state == "draft":
            try:
                self.board.transition(
                    story.issue_id, "refinement", actor=self.role,
                )
            except Exception:
                return  # already moved by another actor; skip

        # 2. First-round vote
        votes = run_poker_round(
            story=story, board=self.board, model=model,
            token_accumulator=lambda r: (0, 0),
        )
        # 3. Discussion if divergent
        if discussion_needed(votes):
            votes = run_discussion_and_revote(
                story=story, board=self.board, model=model,
                token_accumulator=lambda r: (0, 0),
                first_votes=votes,
            )
        # 4. Converge — median of Fibonacci indices, snapped to a Fib value
        pts = sorted(v["points"] for v in votes if isinstance(v.get("points"), int))
        if not pts:
            return  # all votes malformed; leave in refinement for retro to notice
        median = pts[len(pts) // 2]
        # Snap to nearest Fibonacci value if not already one
        final_points = min(FIB, key=lambda f: abs(f - median))

        # 5. set_points + transition to ready
        try:
            self.board.set_points(story.issue_id, final_points, actor=self.role)
            self.board.transition(story.issue_id, "ready", actor=self.role)
            self.emitter.emit(
                "story_refined", story_id=story.issue_id, points=final_points,
                summary=f"{story.issue_id} refined to {final_points} pts",
            )
        except Exception as e:
            self.emitter.emit(
                "poker_failed", role=self.role,
                summary=f"{story.issue_id}: {e}"[:200],
            )

    async def _run_sprint_boundary(self) -> None:
        """Close the current sprint (if open) and open the next one.

        Runs sprint planning: picks up to `velocity_target` ready stories that
        are not yet in a sprint and assigns them the new sprint's number.
        Emits sprint_closed + sprint_opened events with metrics.
        """
        try:
            from orgos.agile.sprints import (
                close_sprint, open_sprint, current_sprint_number,
            )

            def _boundary() -> tuple:
                prev_num = current_sprint_number(self.workspace)
                closed = None
                if prev_num > 0:
                    closed = close_sprint(
                        self.workspace, self.board, reason="scheduled",
                    )
                # Scale velocity_target with team size — a 6-story ceiling
                # starves parallelism at N>1 delivery agents. Falls back to
                # 6 for the historical single-agent-per-role layout.
                vt = getattr(self.workspace, "velocity_target", None)
                velocity_target = vt if isinstance(vt, int) and vt > 0 else 6
                new_sprint = open_sprint(
                    self.workspace, self.board,
                    velocity_target=velocity_target,
                )
                return closed, new_sprint

            closed, opened = await asyncio.get_running_loop().run_in_executor(
                None, _boundary,
            )
            if closed is not None:
                self.emitter.emit(
                    "sprint_closed", sprint_number=closed.number,
                    stories_done=len(closed.stories_done),
                    points_completed=closed.points_completed,
                    spe=closed.spe,
                    final_commit=closed.final_commit,
                    duration_hours=closed.duration_hours,
                    reason=closed.reason_closed,
                    summary=(
                        f"sprint {closed.number} closed: "
                        f"{len(closed.stories_done)} done, "
                        f"{closed.points_completed} pts, "
                        f"SPE {closed.spe:.0%}"
                    ),
                )
            self.emitter.emit(
                "sprint_opened", sprint_number=opened.number,
                committed_backlog_size=len(opened.committed_backlog),
                summary=(
                    f"sprint {opened.number} opened with "
                    f"{len(opened.committed_backlog)} committed stories"
                ),
            )
        except Exception as e:
            self.emitter.emit(
                "sprint_boundary_failed", role=self.role, summary=str(e)[:200],
            )

    def _architecture_decision_recorded(self, issue_id: str) -> bool:
        """DoD check: an architecture story may only be accepted once it has
        recorded its decision in wiki/DECISIONS.md with the mandatory three
        fields (author, timestamp, source) citing this story's issue_id.

        Reads from the INTEGRATION worktree (where agent commits land after
        merge) — NOT from source_repo (which is the target's main working
        tree, never touched by orgos agents). Falls back to source_repo only
        if the integration worktree doesn't exist yet (bootstrap case).

        Returns False (blocking acceptance) if the wiki is unreadable or the
        story is not cited — fabricated/undocumented decisions must not pass.
        """
        from orgos.mcps.wiki_mcp import decisions_cite_source
        # Check integration worktree first (where merged agent work lives)
        candidates = []
        try:
            candidates.append(self.workspace.integration_worktree / "wiki" / "DECISIONS.md")
        except (AttributeError, TypeError):
            pass
        try:
            candidates.append(self.workspace.source_repo / "wiki" / "DECISIONS.md")
        except (AttributeError, TypeError):
            pass
        for p in candidates:
            try:
                if p.exists():
                    content = p.read_text(encoding="utf-8")
                    if decisions_cite_source(content, issue_id):
                        return True
            except OSError:
                continue
        return False

    async def _run_acceptance(self) -> None:
        """PO acceptance gate: review stories in pending_acceptance and
        transition to done (accept) or blocked (reject).

        Acceptance policy (in order — first failure blocks):
          1. Story must carry a commit_sha (proof of work).
          2. DoD wiki gate: architecture stories must have recorded their
             decision in wiki/DECISIONS.md (author, timestamp, source
             citing the story).
          3. AC gate (Fix §A1): if the story carries acceptance_criteria,
             each bullet is LLM-graded against the commit's diff. Any
             UNMET bullet rejects the story — this is what turns
             "commit landed" into "commit actually satisfies the spec".

        The AC gate fails OPEN: if the grading LLM call errors or returns
        garbage, the story is accepted with degraded=True. Rationale:
        stranding stories on infra hiccups is worse than accepting
        occasionally-flawed work; the failure surfaces in the story_ac_check
        event's degraded field.
        """
        try:
            m = self.workspace.manifest()
        except Exception:
            m = None
        model = m.model if m else "deepseek/deepseek-chat"

        try:
            def _accept_batch() -> tuple[int, int, int]:
                from orgos.agile.ac_gate import grade_acceptance_criteria
                pending = self.board.list_state("pending_acceptance")
                accepted = 0
                rejected_dod = 0
                rejected_ac = 0
                for story in pending:
                    reason = ""
                    accept = bool(story.commit_sha)
                    if not accept:
                        reason = "no commit_sha on story"
                    elif story.type == "architecture" and \
                            not self._architecture_decision_recorded(story.issue_id):
                        accept = False
                        reason = (
                            "DoD: architecture story missing a compliant "
                            "wiki/DECISIONS.md entry (author, timestamp, "
                            "source) citing this story"
                        )
                        rejected_dod += 1
                    # AC gate — only run when the story has criteria to grade
                    # AND passed the earlier gates. Grading is one LLM call
                    # per story per accept-tick, so keep pending queue small.
                    ac_verdict = None
                    if accept and (getattr(story, "acceptance_criteria", None) or []):
                        try:
                            ac_verdict = grade_acceptance_criteria(
                                story=story,
                                integration_worktree=self.workspace.integration_worktree,
                                model=model,
                            )
                        except Exception as e:
                            ac_verdict = None
                            self.emitter.emit(
                                "story_ac_check", story_id=story.issue_id,
                                degraded=True,
                                summary=f"AC grade crashed: {e}"[:200],
                            )
                        if ac_verdict is not None:
                            self.emitter.emit(
                                "story_ac_check", story_id=story.issue_id,
                                accept=ac_verdict.accept,
                                degraded=ac_verdict.degraded,
                                met=ac_verdict.met_count,
                                unmet=ac_verdict.unmet_count,
                                total=len(ac_verdict.per_bullet),
                                per_bullet=[
                                    {"ac": v.ac[:80], "verdict": v.verdict}
                                    for v in ac_verdict.per_bullet
                                ],
                                summary=f"AC: {ac_verdict.summary()}",
                            )
                            if not ac_verdict.accept:
                                accept = False
                                reason = f"AC: {ac_verdict.reason[:160]}"
                                rejected_ac += 1
                    try:
                        if accept:
                            self.board.transition(
                                story.issue_id, "done", actor="po",
                                reason="accepted",
                            )
                            accepted += 1
                        else:
                            self.board.transition(
                                story.issue_id, "blocked", actor="po",
                                reason=f"rejected:{reason}"[:200],
                            )
                            if reason.startswith("DoD:"):
                                self.emitter.emit(
                                    "story_blocked_dod", story_id=story.issue_id,
                                    summary=reason,
                                )
                            elif reason.startswith("AC:"):
                                self.emitter.emit(
                                    "story_blocked_ac", story_id=story.issue_id,
                                    summary=reason,
                                )
                    except Exception:
                        continue
                return accepted, rejected_dod, rejected_ac

            count, rejected_dod, rejected_ac = await asyncio.get_running_loop().run_in_executor(
                None, _accept_batch,
            )
            if count > 0:
                self.emitter.emit(
                    "stories_accepted", accepted=count,
                    rejected_dod=rejected_dod, rejected_ac=rejected_ac,
                    summary=(
                        f"PO accepted {count}"
                        + (f", rejected {rejected_dod} DoD" if rejected_dod else "")
                        + (f", rejected {rejected_ac} AC" if rejected_ac else "")
                    ),
                )
        except Exception as e:
            self.emitter.emit(
                "acceptance_failed", role=self.role, summary=str(e)[:200],
            )

    async def _run_pr_feedback(self) -> None:
        try:
            from orgos.agile.pr_feedback import ingest_pr_feedback
            import json
            # Look for pr_url in (a) a dedicated pr_url.txt written by
            # pr_publisher when a PR is opened mid-run, or (b) a
            # campaign_result.json from a previous shutdown of this workspace.
            pr_url = ""
            pr_url_file = self.workspace.root / "pr_url.txt"
            if pr_url_file.exists():
                try:
                    pr_url = pr_url_file.read_text(encoding="utf-8").strip()
                except Exception:
                    pass
            if not pr_url:
                r_path = self.workspace.root / "campaign_result.json"
                if r_path.exists():
                    try:
                        pr_url = json.loads(r_path.read_text()).get("pr_url", "")
                    except Exception:
                        pass
            if not pr_url:
                return  # no PR published yet
            await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: ingest_pr_feedback(
                    workspace=self.workspace, pr_url=pr_url,
                    board=self.board, emitter=self.emitter,
                    sprint_num=1,
                ),
            )
        except Exception as e:
            self.emitter.emit(
                "pr_feedback_error", role=self.role, summary=str(e)[:200],
            )

    def _build_sibling_context(self, story) -> str:
        """Fix §A4 — Inject team context so executors know what siblings did.

        Kills two collision classes we've measured:
          1. Two agents both create `tests/<X>/__init__.py` (marker file
             collisions — merge conflict on rebase).
          2. An agent rewrites a module that a sibling just created (import
             cycles + lost work).

        Content:
          - Recently-merged files (last 20-25) with the author
          - In-flight peer stories with their component + files_to_touch
          - A note about append-vs-overwrite for shared files

        Never raises — an empty context string is fine; the executor just
        doesn't get the extra info. Kept under ~2 KB so the prompt cache
        stays warm.
        """
        try:
            from orgos.agile.live_events import read_events
        except Exception:
            return ""

        # 1. Recently-merged files — scan the last ~200 events for commit_landed
        recent: list[tuple[str, str]] = []  # (file, actor)
        seen: set[str] = set()
        try:
            all_events = read_events(self.workspace.root)
            for e in reversed(all_events[-300:]):
                if e.get("action") != "commit_landed":
                    continue
                actor = e.get("worker") or "unknown"
                sha = (e.get("commit_sha") or "").strip()
                if not sha:
                    continue
                # We don't have files_touched on commit_landed events; look up
                # via the story's board record for files_to_touch as a proxy.
                sid = e.get("story_id", "")
                if not sid:
                    continue
                try:
                    s = self.board.read(sid)
                except Exception:
                    continue
                for f in (s.files_to_touch or []):
                    if f not in seen:
                        recent.append((f, actor))
                        seen.add(f)
                if len(recent) >= 20:
                    break
        except Exception:
            pass

        # 2. In-flight peer stories (same role or different — all in-flight
        # peers matter). Exclude the current story.
        peers: list[str] = []
        try:
            for state in ("in_progress", "review"):
                for s in self.board.list_state(state):
                    if s.issue_id == story.issue_id:
                        continue
                    files = ",".join((s.files_to_touch or [])[:3]) or "(no files)"
                    peers.append(
                        f"  - {s.issue_id[:32]} [{s.assignee or '?'}] {s.type} · "
                        f"{s.component} · {files}"
                    )
                    if len(peers) >= 8:
                        break
        except Exception:
            pass

        if not recent and not peers:
            return ""

        block: list[str] = []
        block.append("")
        block.append("---")
        block.append("## TEAM CONTEXT (updated at pull time — do not re-create sibling work)")
        if recent:
            block.append("")
            block.append("Recently merged files (last 20):")
            for f, actor in recent[:20]:
                block.append(f"  - {f}  (by {actor})")
            block.append("")
            block.append(
                "  RULE: if your story needs one of these files, `cat >>` to append, "
                "NEVER `cat >` to overwrite. For __init__.py files, check if the "
                "file already exists before creating — it usually does after a peer "
                "landed their story."
            )
        if peers:
            block.append("")
            block.append("Peer stories currently in flight:")
            for line in peers:
                block.append(line)
            block.append("")
            block.append(
                "  RULE: don't touch files listed in peer stories' file scope. If your "
                "story naturally needs one of those files, comment on the story to "
                "raise the conflict rather than racing."
            )
        return "\n".join(block)

    async def _pull_and_work_once(self) -> None:
        """Delivery-agent action: check board, pull if match, run executor, enqueue merge."""
        from dataclasses import replace as _replace
        from orgos.agile.sprints import current_sprint_number
        try:
            sn = current_sprint_number(self.workspace)
        except Exception:
            sn = 0
        story = self.board.try_claim_next_for(
            self.role, actor=self.actor, sprint_number=sn,
        )
        if story is None:
            return

        self.emitter.emit(
            "story_pulled", story_id=story.issue_id,
            worker=self.actor, story_type=story.type,
            title=story.title[:80],
        )

        # §A4 — inject sibling context so the executor knows what recently
        # landed and what peers are working on. Mutates a story COPY (dataclass
        # replace) so we don't persist context into the board itself.
        sibling_ctx = self._build_sibling_context(story)
        executor_story = story
        if sibling_ctx:
            try:
                executor_story = _replace(story, body=f"{story.body or ''}\n{sibling_ctx}")
            except (TypeError, ValueError):
                executor_story = story  # fallback: send unmodified

        # Run the coding executor in a thread pool (it may be blocking I/O).
        # Uses this instance's OWN worktree (per-instance for N>1).
        try:
            result: ExecutionResult = await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: self.executor.run_story(
                    worktree=self.workspace.agent_worktree(self.role, self.instance),
                    story=executor_story,
                    persona_scaffold=self.persona_scaffold,
                    session_id=self.actor,
                ),
            )
        except Exception as e:
            # Executor crashed — always retry until MAX (crashes are usually transient).
            self._handle_no_commit(
                story, tokens_in=0, tokens_out=0, wall_seconds=0.0,
                summary=f"executor crashed: {e}", is_hard=False,
            )
            return

        if not result.success:
            # No commit landed. Retry up to MAX_ATTEMPTS_PER_STORY before
            # permanently blocking. Most no-commits are transient (executor
            # timeout, LLM skipped a step). Retry catches ~half of them.
            hard_fail = "not found" in result.error.lower()
            self._handle_no_commit(
                story,
                tokens_in=result.tokens_input,
                tokens_out=result.tokens_output,
                wall_seconds=result.wall_seconds,
                summary=result.error[:200],
                is_hard=hard_fail,
            )
            return

        # §A5 — charge every executor result against the run's budget.
        # Called for success AND failure paths (no_commit path is handled in
        # _handle_no_commit). Doing it here avoids double-counting.
        try:
            from orgos.agile.budget import charge_if_active
            charge_if_active(
                result.tokens_input or 0,
                result.tokens_output or 0,
            )
        except Exception:
            pass

        # Success: transition to review, enqueue merge
        self.board.transition(story.issue_id, "review", actor=self.actor)
        self.board.set_commit(story.issue_id, result.commit_sha, actor=self.actor)
        self.emitter.emit(
            "commit_landed", story_id=story.issue_id,
            commit_sha=result.commit_sha[:7], worker=self.actor,
            tokens_in=result.tokens_input,
            tokens_out=result.tokens_output,
            wall_seconds=result.wall_seconds,
            summary=f"{self.actor} committed {result.commit_sha[:7]}",
        )
        await self.merge_queue.enqueue(MergeRequest(
            story_id=story.issue_id,
            from_branch=self.workspace.agent_branch(self.role, self.instance),
            files_touched=result.files_touched,
        ))

    # Executor budget for retries. Most no_commit events are transient
    # (LLM timed out, skipped commit step, etc.). Retry catches ~half of
    # them per the 4h at-scale run. After MAX_ATTEMPTS the story goes to
    # blocked so PO/human can look at it. Overridable via env var
    # ORGOS_MAX_ATTEMPTS_PER_STORY for experiments.
    try:
        MAX_ATTEMPTS_PER_STORY = max(1, int(os.environ.get(
            "ORGOS_MAX_ATTEMPTS_PER_STORY", "3",
        )))
    except (TypeError, ValueError):
        MAX_ATTEMPTS_PER_STORY = 3

    def _persist_failure_log(self, story_id: str, attempts: int, summary: str) -> None:
        """Write the full failure body to agents/<role>/failures/<story>.log.

        The event stream only carries the first 200 chars of `summary` (kept
        small for the report). But when a story hits its MAX_ATTEMPTS wall
        we want the full diagnostic on disk for the retro/human to read.
        """
        try:
            failures_dir = self.workspace.agent_dir(self.role, self.instance) / "failures"
            failures_dir.mkdir(parents=True, exist_ok=True)
            log_path = failures_dir / f"{story_id}.log"
            with log_path.open("a", encoding="utf-8") as f:
                f.write(f"----- attempt {attempts} by {self.actor} -----\n")
                f.write(summary or "(no summary provided)")
                f.write("\n\n")
        except (OSError, AttributeError):
            pass  # never let disk trouble kill the agent loop

    def _handle_no_commit(
        self, story, *, tokens_in, tokens_out, wall_seconds, summary, is_hard,
    ) -> None:
        """No commit landed. Decide: retry (back to ready) vs block."""
        # §A5 — charge failed attempts too. The LLM burned real tokens.
        try:
            from orgos.agile.budget import charge_if_active
            charge_if_active(tokens_in or 0, tokens_out or 0)
        except Exception:
            pass

        try:
            updated = self.board.increment_attempts(story.issue_id, actor=self.actor)
            attempts = updated.attempts
        except Exception:
            attempts = self.MAX_ATTEMPTS_PER_STORY  # be conservative if we can't count

        # §l — persist FULL failure text (not just 200 chars) to disk.
        self._persist_failure_log(story.issue_id, attempts, summary)

        will_retry = (not is_hard) and (attempts < self.MAX_ATTEMPTS_PER_STORY)
        if will_retry:
            # Return to ready so another agent (or this one on next tick) retries.
            try:
                self.board.transition(
                    story.issue_id, "ready", actor=self.actor,
                    reason=f"retry:no_commit (attempt {attempts})",
                )
            except Exception:
                # Fallback: block if the transition fails
                self.board.transition(
                    story.issue_id, "blocked", actor=self.actor,
                    reason=summary[:200],
                )
                will_retry = False

        if not will_retry:
            try:
                self.board.transition(
                    story.issue_id, "blocked", actor=self.actor,
                    reason=f"{summary[:180]} (after {attempts} attempts)",
                )
            except Exception:
                pass

        self.emitter.emit(
            "story_no_commit", story_id=story.issue_id,
            worker=self.actor, attempts=attempts,
            tokens_in=tokens_in, tokens_out=tokens_out,
            wall_seconds=wall_seconds,
            retry=will_retry,
            summary=f"{summary[:180]} (attempt {attempts}/{self.MAX_ATTEMPTS_PER_STORY}"
                    + (", retrying" if will_retry else ", blocked") + ")",
        )
        # §n — dedicated final_block event when the story permanently
        # blocks. Downstream tools can group by this to build a "why
        # each story failed" panel.
        if not will_retry:
            try:
                failure_log_path = str(
                    self.workspace.agent_dir(self.role, self.instance)
                    / "failures" / f"{story.issue_id}.log"
                )
            except (AttributeError, TypeError):
                failure_log_path = ""
            self.emitter.emit(
                "story_final_block", story_id=story.issue_id,
                worker=self.actor, attempts=attempts,
                failure_log=failure_log_path,
                summary=f"blocked after {attempts} attempts: {summary[:120]}",
            )
