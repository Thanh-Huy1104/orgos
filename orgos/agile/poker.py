"""Planning poker mechanic — vote + justify + discuss.

Each specialist spawns to evaluate a story and produces:
  - a Fibonacci vote: 1|2|3|5|8|13 (or "?" if truly can't estimate)
  - a 2-sentence justification

If votes span more than 2 Fibonacci steps AND justifications reveal different
assumptions, the caller triggers a discussion round.

Fibonacci sequence used: [1, 2, 3, 5, 8, 13].
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Optional

from orgos.agile.board_store import BoardStore, Story
from orgos.agile.sprint import _extract_json_objects
from orgos.spawn.governance import TaskBrief, spawn
from orgos.subagents import architect_role, devsecops_role, test_role


FIB = [1, 2, 3, 5, 8, 13]


ROLE_FACTORIES = {
    "architect": architect_role,
    "test":      test_role,
    "devsecops": devsecops_role,
}


_POKER_BRIEF_TEMPLATE = """You are the {role_label}. Vote on this story's story-points.

STORY
  issue_id: {issue_id}
  title:    {title}
  type:     {type}

BODY:
{body}

YOUR JOB:
  Estimate the effort in Fibonacci story points: 1, 2, 3, 5, 8, or 13.
  1  = trivial (< 30 min)
  2  = small (< 1 hr)
  3  = medium (< 2 hr)
  5  = larger (half a day, some unknowns)
  8  = big (a full day, real design work)
  13 = too big — should probably be split

  Then write a 2-sentence justification from YOUR ROLE's perspective. The
  {role_label} sees different risks than other roles — surface what stands
  out to you specifically.

OUTPUT ONLY THIS JSON (no prose, no fences):

{{
  "role": "{role_lower}",
  "points": <int>,
  "justification": "<2 sentences from your role's perspective>"
}}
"""


_DISCUSSION_BRIEF_TEMPLATE = """You are the {role_label}. Poker just produced divergent votes on this story.

STORY
  issue_id: {issue_id}
  title:    {title}
  body:     {body}

VOTES SO FAR (this round):
{votes_summary}

YOUR JOB:
  You get ONE turn to respond. Do you:
    a) Update your estimate (if a peer surfaced something you missed)
    b) Hold your estimate (if you still believe your read is right — explain
       why the peers' reasoning doesn't change yours)

  Keep response to 2 sentences.

OUTPUT ONLY THIS JSON:

{{
  "role": "{role_lower}",
  "points": <int>,
  "justification": "<2 sentences>"
}}
"""


def _extract_first_json(text: str) -> Optional[dict]:
    for blob in _extract_json_objects(text):
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


def _coerce_points(raw: Any) -> Optional[int]:
    """Map an LLM's vote to the nearest legal Fibonacci step."""
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return None
    if v in FIB:
        return v
    # Snap to nearest legal value
    return min(FIB, key=lambda f: abs(f - v))


def _spawn_one_vote(
    role_name: str,
    role_label: str,
    story: Story,
    model: str,
    token_accumulator: Callable[[Any], tuple[int, int]],
    template: str,
    extra_ctx: Optional[dict] = None,
) -> dict:
    """Spawn one specialist to vote. Returns {voter, points, justification}."""
    factory = ROLE_FACTORIES[role_name]
    role = factory(model=model)  # no BashTool — voting is prose-only
    role.mcp_servers = []          # no wiki access during vote (bias-free)

    fmt_kwargs = {
        "role_label": role_label,
        "role_lower": role_name,
        "issue_id": story.issue_id,
        "title": story.title,
        "type": story.type,
        "body": story.body[:1500],  # cap to keep the brief small
    }
    if extra_ctx:
        fmt_kwargs.update(extra_ctx)

    brief = TaskBrief(
        objective=template.format(**fmt_kwargs),
        expected_output="A JSON object with role, points, justification.",
        success_criteria=["Valid JSON with a Fibonacci points value."],
    )
    result = spawn(role, brief, run_budget_tokens=80_000)
    token_accumulator(result)

    parsed = None
    for to in result.tasks_output:
        raw = getattr(to, "raw", "") or ""
        parsed = _extract_first_json(raw)
        if parsed and "points" in parsed:
            break

    points = _coerce_points(parsed.get("points")) if parsed else None
    justification = (parsed or {}).get("justification", "") if parsed else ""
    return {
        "voter": role_name,
        "points": points if points is not None else 5,  # default center
        "justification": justification or "(no justification)",
    }


def run_poker_round(
    *,
    story: Story,
    board: BoardStore,
    model: str,
    token_accumulator: Callable[[Any], tuple[int, int]],
    roles: tuple[str, ...] = ("architect", "test", "devsecops"),
    model_for: Optional[Callable[[str], str]] = None,
) -> list[dict]:
    """Run one round of poker. Records votes on the board. Returns the votes.

    If `model_for` is given, each role uses model_for(role_name) — otherwise
    they all use `model`. Concurrent execution across roles for speed.
    """
    import concurrent.futures
    labels = {"architect": "Architect", "test": "Test", "devsecops": "DevSecOps"}
    resolver = model_for or (lambda _r: model)

    def _vote(role_name: str) -> dict:
        return _spawn_one_vote(
            role_name=role_name,
            role_label=labels[role_name],
            story=story,
            model=resolver(role_name),
            token_accumulator=token_accumulator,
            template=_POKER_BRIEF_TEMPLATE,
        )

    votes: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(roles)) as ex:
        future_to_role = {ex.submit(_vote, r): r for r in roles}
        for fut in concurrent.futures.as_completed(future_to_role):
            vote = fut.result()
            board.add_poker_vote(
                story.issue_id, voter=vote["voter"],
                points=vote["points"], justification=vote["justification"],
            )
            votes.append(vote)
    # Preserve requested role order for stable display
    votes.sort(key=lambda v: roles.index(v["voter"]) if v["voter"] in roles else 99)
    return votes


def discussion_needed(votes: list[dict]) -> bool:
    """True if votes span more than 2 Fibonacci steps.

    (Trigger definition per the plan: 'votes span > 2 Fibonacci steps'.
    Simpler and cheaper than parsing justifications for divergent assumptions,
    which we can add in v2 if we see false positives.)
    """
    if not votes:
        return False
    pts = [v["points"] for v in votes if isinstance(v.get("points"), int)]
    if len(pts) < 2:
        return False
    try:
        indices = [FIB.index(p) for p in pts]
    except ValueError:
        return True  # non-Fibonacci vote → treat as divergent
    return (max(indices) - min(indices)) > 2


def run_discussion_and_revote(
    *,
    story: Story,
    board: BoardStore,
    model: str,
    token_accumulator: Callable[[Any], tuple[int, int]],
    first_votes: list[dict],
    roles: tuple[str, ...] = ("architect", "test", "devsecops"),
    model_for: Optional[Callable[[str], str]] = None,
) -> list[dict]:
    """Show first round's votes to each agent, they get one turn to re-vote."""
    import concurrent.futures
    labels = {"architect": "Architect", "test": "Test", "devsecops": "DevSecOps"}
    resolver = model_for or (lambda _r: model)
    votes_summary = "\n".join(
        f"  - {v['voter']}: {v['points']} pts  \"{v['justification'][:200]}\""
        for v in first_votes
    )

    def _revote(role_name: str) -> dict:
        return _spawn_one_vote(
            role_name=role_name,
            role_label=labels[role_name],
            story=story,
            model=resolver(role_name),
            token_accumulator=token_accumulator,
            template=_DISCUSSION_BRIEF_TEMPLATE,
            extra_ctx={"votes_summary": votes_summary},
        )

    new_votes: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(roles)) as ex:
        futs = {ex.submit(_revote, r): r for r in roles}
        for fut in concurrent.futures.as_completed(futs):
            vote = fut.result()
            board.add_poker_vote(
                story.issue_id, voter=vote["voter"],
                points=vote["points"], justification=vote["justification"],
            )
            new_votes.append(vote)
    new_votes.sort(key=lambda v: roles.index(v["voter"]) if v["voter"] in roles else 99)
    return new_votes
