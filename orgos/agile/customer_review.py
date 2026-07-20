"""§D2 — Customer agent review of the shipped increment.

Second-layer signal on top of the AC gate:
  - AC gate:      "does this story's own commit satisfy its own AC bullets?"
  - Customer:     "does the WHOLE shipped increment look like what the spec
                   author asked for?"

Runs on a slower cadence (every ~15 min, one review batch at a time).
Reads: wiki/SPEC.md + last N done stories + their commit diffs
Writes: rejection transitions (done → blocked with customer_feedback)
        + new customer-added stories for missing pieces

Design principles:
  - Fail OPEN: any LLM error means no rejections this cycle (never strand
    working software on an infra hiccup).
  - Never reject the same story more than CUSTOMER_MAX_REJECTS times.
    Track via story.comments.
  - Batch review: look at 3-8 done stories per pass, not the whole board.
  - No customer intervention on newly-drafted stories — only on `done`
    state stories that shipped code.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


CUSTOMER_MAX_REJECTS = 3       # per story
CUSTOMER_REVIEW_BATCH = 5      # done stories per review pass


@dataclass
class CustomerFeedback:
    story_id: str
    verdict: str                  # "accept" | "reject"
    reason: str = ""
    spec_quote: str = ""          # the exact spec text being violated (if reject)


@dataclass
class CustomerReview:
    reviewed: int = 0
    accepted: int = 0
    rejected: int = 0
    new_stories_proposed: int = 0
    feedback: list[CustomerFeedback] = field(default_factory=list)
    degraded: bool = False
    reason_degraded: str = ""


_REVIEW_PROMPT = """You are the Customer for this project. You wrote the spec.
Your job: judge whether the shipped stories match your intent.

The spec is authoritative. If a shipped story diverges from what the spec
says (wrong field names, missing error paths, silent stubs, wrong API
shape, wrong CLI flags), you REJECT it. If it delivers what the spec
asked for, you ACCEPT it.

You do NOT judge code quality, style, or comments. You ONLY judge:
does the shipped behavior match the spec's stated intent?

--- SPEC (wiki/SPEC.md) ---
{spec_text}

--- SHIPPED STORIES TO REVIEW ---
{stories_block}

--- REVIEW GUIDELINES ---
For each story, output one JSON object per line (JSONL) with this shape:

  {{"story_id": "<id>", "verdict": "accept"|"reject", "reason": "<one sentence>", "spec_quote": "<exact spec text if rejecting>"}}

Rejection reasons must cite the specific spec violation, not aesthetic
opinions. Examples:
  - "spec says Bar has 'symbol' field; code uses 'instrument_id'"
  - "spec says GET /health returns JSON {{status: ok}}; code returns plain text 'ok'"
  - "spec requires 'quant backtest --limit N'; code uses '-n N' flag"

If the story matches spec: verdict=accept, reason="matches spec".

Do NOT output anything except the JSONL. No prose, no markdown fences.
"""


def _load_spec_text(workspace: Any, max_chars: int = 8000) -> str:
    """Best-effort load of wiki/SPEC.md from any known location."""
    candidates = []
    for attr in ("wiki_dir", "integration_worktree", "source_repo"):
        try:
            base = getattr(workspace, attr, None)
            if base:
                if attr == "wiki_dir":
                    candidates.append(base / "SPEC.md")
                else:
                    candidates.append(base / "wiki" / "SPEC.md")
        except Exception:
            continue
    for p in candidates:
        try:
            if p.exists():
                text = p.read_text(encoding="utf-8")
                if len(text) > max_chars:
                    return text[:max_chars * 2 // 3] + "\n\n… (truncated) …\n\n" + text[-max_chars // 3:]
                return text
        except OSError:
            continue
    return ""


def _story_diff(worktree: Path, commit_sha: str, max_chars: int = 1200) -> str:
    """Small diff of a single story's commit for review context."""
    if not commit_sha:
        return "(no commit)"
    try:
        r = subprocess.run(
            ["git", "show", "--stat", "--pretty=format:%s", commit_sha],
            cwd=str(worktree), capture_output=True, text=True, timeout=10,
        )
        text = r.stdout or ""
    except (subprocess.SubprocessError, OSError):
        return "(diff unavailable)"
    if len(text) > max_chars:
        text = text[:max_chars] + "\n… (diff truncated) …"
    return text


def _count_previous_customer_rejects(story: Any) -> int:
    """How many times has the customer rejected this story before?"""
    n = 0
    for c in (getattr(story, "comments", None) or []):
        if isinstance(c, dict) and c.get("author") == "customer" and "reject" in (c.get("body", "") or ""):
            n += 1
    return n


def _parse_review_jsonl(raw: str) -> list[CustomerFeedback]:
    """Extract JSONL feedback objects. Skip anything that doesn't parse."""
    out: list[CustomerFeedback] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        sid = str(obj.get("story_id", "")).strip()
        verdict = str(obj.get("verdict", "")).strip().lower()
        if not sid or verdict not in ("accept", "reject"):
            continue
        out.append(CustomerFeedback(
            story_id=sid,
            verdict=verdict,
            reason=str(obj.get("reason", ""))[:400],
            spec_quote=str(obj.get("spec_quote", ""))[:400],
        ))
    return out


def _pick_stories_to_review(board: Any) -> list[Any]:
    """Return up to CUSTOMER_REVIEW_BATCH done stories that the customer
    hasn't already rejected too many times."""
    try:
        done = board.list_state("done")
    except Exception:
        return []
    eligible = []
    for s in done:
        if _count_previous_customer_rejects(s) >= CUSTOMER_MAX_REJECTS:
            continue
        eligible.append(s)
        if len(eligible) >= CUSTOMER_REVIEW_BATCH:
            break
    return eligible


def run_customer_review(
    *,
    workspace: Any,
    board: Any,
    model: str,
    emitter: Optional[Any] = None,
    spawner: Optional[Any] = None,
) -> CustomerReview:
    """Do one customer review pass. Never raises — degrades gracefully.

    `spawner` is orgos.spawn.spawn — passed in so tests can stub it.
    """
    review = CustomerReview()

    stories = _pick_stories_to_review(board)
    if not stories:
        return review

    spec_text = _load_spec_text(workspace)
    if not spec_text.strip():
        review.degraded = True
        review.reason_degraded = "no wiki/SPEC.md — customer has nothing to compare against"
        return review

    try:
        worktree = workspace.integration_worktree
    except Exception:
        worktree = None

    story_blocks: list[str] = []
    for s in stories:
        diff = _story_diff(worktree, s.commit_sha) if worktree else "(no worktree)"
        ac_lines = "\n".join(
            f"    - {c}" for c in (getattr(s, "acceptance_criteria", None) or [])
        )
        story_blocks.append(
            f"### story {s.issue_id}: {s.title}\n"
            f"  type: {s.type}\n"
            f"  body: {(s.body or '')[:400]}\n"
            f"  declared AC:\n{ac_lines}\n"
            f"  commit_sha: {(s.commit_sha or '')[:12]}\n"
            f"  diff:\n{diff}\n"
        )
    prompt = _REVIEW_PROMPT.format(
        spec_text=spec_text,
        stories_block="\n\n".join(story_blocks),
    )

    # Run the customer spawn
    result = None
    if spawner is None:
        try:
            from orgos.spawn import TaskBrief, spawn as _spawn
            from orgos.subagents.scrum_team import _load_agent
            role = _load_agent("customer", model)
            role.mcp_servers = []
            brief = TaskBrief(
                objective=prompt,
                expected_output="JSONL: one {story_id, verdict, reason, spec_quote} per story",
                success_criteria=["Each line is a valid JSON object with story_id + verdict"],
            )
            result = _spawn(role, brief, run_budget_tokens=80_000)
        except Exception as e:
            review.degraded = True
            review.reason_degraded = f"spawn failed: {e}"[:200]
            return review
    else:
        try:
            result = spawner(prompt=prompt, model=model)
        except Exception as e:
            review.degraded = True
            review.reason_degraded = f"spawner failed: {e}"[:200]
            return review

    # Parse verdicts
    raw = ""
    for to in getattr(result, "tasks_output", []) or []:
        raw += (getattr(to, "raw", "") or "") + "\n"
    feedback = _parse_review_jsonl(raw)
    review.feedback = feedback
    review.reviewed = len(stories)

    # Apply verdicts
    story_by_id = {s.issue_id: s for s in stories}
    for f in feedback:
        story = story_by_id.get(f.story_id)
        if story is None:
            continue
        if f.verdict == "accept":
            review.accepted += 1
            # Store the accept as a comment for audit trail
            try:
                board.add_comment(
                    story.issue_id, author="customer",
                    body=f"customer accept: {f.reason[:200]}",
                )
            except Exception:
                pass
            continue

        # reject path — transition done → blocked with customer_feedback
        try:
            board.transition(
                story.issue_id, "blocked", actor="customer",
                reason=f"customer_reject: {f.reason[:180]}",
            )
            board.add_comment(
                story.issue_id, author="customer",
                body=(
                    f"customer reject #{_count_previous_customer_rejects(story) + 1}: "
                    f"{f.reason}\n\nspec quote: {f.spec_quote}"
                ),
            )
            review.rejected += 1
            if emitter is not None:
                try:
                    emitter.emit(
                        "customer_reject", story_id=story.issue_id,
                        reason=f.reason[:200],
                        spec_quote=f.spec_quote[:200],
                        summary=f"customer rejected {story.issue_id}: {f.reason[:120]}",
                    )
                except Exception:
                    pass
        except Exception:
            # Story may already be in blocked or done; skip
            continue

    if emitter is not None:
        try:
            emitter.emit(
                "customer_review", reviewed=review.reviewed,
                accepted=review.accepted, rejected=review.rejected,
                summary=(
                    f"customer reviewed {review.reviewed}: "
                    f"{review.accepted} accept / {review.rejected} reject"
                ),
            )
        except Exception:
            pass

    return review
