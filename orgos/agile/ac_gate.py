"""Acceptance-criteria gate — LLM-grade each AC bullet against the commit.

Called from AsyncAgent._run_acceptance when a story arrives at
pending_acceptance carrying a non-empty acceptance_criteria list. Spawns
the PO briefly with:
  - The story (title + body + AC bullets)
  - The commit's file list + a truncated diff snippet
And parses back a per-bullet verdict (MET / UNMET / UNCERTAIN) with a
short reason. Returns the overall accept/reject decision.

Design principles:
  - Never crash the acceptance loop — a broken LLM call returns
    AcceptanceVerdict(accept=True, degraded=True) so we fail *open*
    (unblock the story). "Fail closed" would strand stories on any
    transient hiccup and undo the point of having a gate at all.
  - Truncate the diff aggressively (~2 KB) — the AC bullets are the
    signal, the diff is just corroboration.
  - Cache-friendly prompt shape (system + AC + fixed diff format) so
    prompt-caching backends can hit on repeated stories.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class ACVerdict:
    """One bullet's grade."""
    ac: str
    verdict: str            # "MET" | "UNMET" | "UNCERTAIN"
    reason: str = ""


@dataclass
class AcceptanceVerdict:
    """Overall accept/reject decision for a story."""
    accept: bool
    reason: str = ""                                  # short reason if reject
    per_bullet: list[ACVerdict] = field(default_factory=list)
    degraded: bool = False                            # True if we couldn't grade (LLM error)
    tokens_input: int = 0
    tokens_output: int = 0

    @property
    def unmet_count(self) -> int:
        return sum(1 for v in self.per_bullet if v.verdict == "UNMET")

    @property
    def met_count(self) -> int:
        return sum(1 for v in self.per_bullet if v.verdict == "MET")

    def summary(self) -> str:
        if self.degraded:
            return f"(gate degraded — accepted without grading)"
        if not self.per_bullet:
            return "(no AC bullets to grade)"
        return f"{self.met_count} MET / {self.unmet_count} UNMET of {len(self.per_bullet)}"


_GRADE_TEMPLATE = """You are the Product Owner deciding whether to ACCEPT this story.

STORY
  id: {issue_id}
  title: {title}
  type: {story_type}

STORY BODY (what was asked for)
{body}

ACCEPTANCE CRITERIA (each must be observably satisfied by the commit)
{ac_block}

THE COMMIT
  sha: {commit_sha}
  files changed:
{files_block}

DIFF (truncated)
{diff_block}

YOUR JOB
For each acceptance criterion, decide:
  MET       — the diff clearly shows the behavior/property is satisfied
  UNMET     — the diff shows the criterion is NOT satisfied (missing / wrong)
  UNCERTAIN — cannot tell from the diff alone (e.g. requires running tests)

Then decide accept vs reject:
  - Accept if every criterion is MET or UNCERTAIN
  - Reject if ANY criterion is UNMET
  - When rejecting, `reason_if_reject` names the specific unmet AC.

Reply with ONLY this JSON (no prose, no fences):

{{
  "verdicts": [
    {{"ac": "<the criterion text>", "verdict": "MET", "reason": "<1 sentence pointing at the diff>"}}
  ],
  "accept": true,
  "reason_if_reject": ""
}}

Rules:
  - Include one verdict per acceptance criterion, in the same order.
  - Reasons are ONE sentence, terse.
  - UNCERTAIN is legitimate — don't reject just because the diff is
    incomplete; only reject when the criterion is clearly unmet.
"""


def _git_diff_for_commit(worktree: Path, commit_sha: str) -> tuple[list[str], str]:
    """Return (files_changed, truncated_diff_text) for the given commit.

    Uses the parent-vs-commit diff. On error, returns ([], "").
    """
    try:
        r = subprocess.run(
            ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit_sha],
            cwd=str(worktree), capture_output=True, text=True, timeout=10,
        )
        files = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
    except (subprocess.SubprocessError, OSError):
        files = []

    diff_text = ""
    try:
        r = subprocess.run(
            ["git", "show", "--pretty=format:", commit_sha],
            cwd=str(worktree), capture_output=True, text=True, timeout=15,
        )
        diff_text = r.stdout or ""
    except (subprocess.SubprocessError, OSError):
        diff_text = ""

    # Truncate — keep first 1.5KB (usually the interesting adds) and last
    # 0.5KB (usually tests / signature blocks). AC signal is stronger than
    # diff volume; a bigger diff doesn't buy more grading accuracy.
    if len(diff_text) > 2200:
        head = diff_text[:1500]
        tail = diff_text[-500:]
        diff_text = f"{head}\n... [diff truncated, {len(diff_text)} chars total] ...\n{tail}"

    return files, diff_text


def _parse_grade_json(raw: str) -> Optional[dict]:
    """Find and parse the FIRST valid grade-shaped JSON in the raw text.

    Grade-shaped = a dict with either 'verdicts' or 'accept' key.
    """
    from orgos.agile.sprint import _extract_json_objects

    for blob in _extract_json_objects(raw):
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        if "verdicts" in data or "accept" in data:
            return data
        # Envelope form: unwrap payload
        payload = data.get("payload") if isinstance(data, dict) else None
        if isinstance(payload, dict) and ("verdicts" in payload or "accept" in payload):
            return payload
    return None


def grade_acceptance_criteria(
    *,
    story: Any,
    integration_worktree: Path,
    model: str,
    spawner: Any = None,
) -> AcceptanceVerdict:
    """Grade a story against its acceptance_criteria.

    `spawner` is `orgos.spawn.spawn` — passed in so tests can stub it. In
    production `AsyncAgent` passes the real spawn function.

    Returns AcceptanceVerdict. On any error, returns
    AcceptanceVerdict(accept=True, degraded=True) — fail open.
    """
    ac = list(getattr(story, "acceptance_criteria", []) or [])
    if not ac:
        # No criteria to grade — trivially accept.
        return AcceptanceVerdict(accept=True, per_bullet=[])

    files, diff_text = _git_diff_for_commit(
        integration_worktree, story.commit_sha,
    )
    files_block = "\n".join(f"  - {f}" for f in files) or "  (no files reported)"
    ac_block = "\n".join(f"  {i+1}. {c}" for i, c in enumerate(ac))

    prompt = _GRADE_TEMPLATE.format(
        issue_id=story.issue_id,
        title=story.title,
        story_type=story.type,
        body=(story.body or "")[:1200],
        ac_block=ac_block,
        commit_sha=(story.commit_sha or "")[:12],
        files_block=files_block,
        diff_block=diff_text or "(empty diff)",
    )

    if spawner is None:
        # Late import so tests can patch without pulling all of spawn.
        try:
            from orgos.spawn.governance import TaskBrief, spawn as _spawn
            from orgos.subagents import po_role
        except Exception:
            return AcceptanceVerdict(accept=True, degraded=True,
                                      reason="spawn import failed")
        try:
            po = po_role(model=model)
            po.mcp_servers = []
            brief = TaskBrief(
                objective=prompt,
                expected_output="JSON with verdicts + accept + reason_if_reject.",
                success_criteria=["Output is a valid JSON grade."],
            )
            result = _spawn(po, brief, run_budget_tokens=50_000)
        except Exception as e:
            return AcceptanceVerdict(
                accept=True, degraded=True,
                reason=f"grade spawn failed: {e}",
            )
    else:
        # Test/injected path — spawner is a callable returning result-like obj
        try:
            result = spawner(prompt=prompt, model=model)
        except Exception as e:
            return AcceptanceVerdict(
                accept=True, degraded=True,
                reason=f"grade spawner failed: {e}",
            )

    # Parse verdict from result
    tokens_in = getattr(result, "total_tokens_input", 0) or 0
    tokens_out = getattr(result, "total_tokens_output", 0) or 0
    parsed: Optional[dict] = None
    tasks_output = getattr(result, "tasks_output", None)
    if tasks_output:
        for to in tasks_output:
            raw = getattr(to, "raw", "") or ""
            parsed = _parse_grade_json(raw)
            if parsed:
                break

    if not parsed:
        return AcceptanceVerdict(
            accept=True, degraded=True,
            reason="grade produced no parseable JSON",
            tokens_input=tokens_in, tokens_output=tokens_out,
        )

    # Build per-bullet verdicts. Trust the model's ordering when possible.
    per_bullet: list[ACVerdict] = []
    for v in parsed.get("verdicts") or []:
        if not isinstance(v, dict):
            continue
        verdict_text = str(v.get("verdict", "")).strip().upper()
        if verdict_text not in ("MET", "UNMET", "UNCERTAIN"):
            verdict_text = "UNCERTAIN"
        per_bullet.append(ACVerdict(
            ac=str(v.get("ac", ""))[:200],
            verdict=verdict_text,
            reason=str(v.get("reason", ""))[:200],
        ))

    # Determine accept DETERMINISTICALLY from the per-bullet evidence: the
    # LLM is the witness, the code is the judge. Any UNMET → reject; zero
    # UNMET → accept, overriding the model's blanket `accept` flag either
    # way. Run 3 (2026-07-24, deepseek-v4-flash) showed why the inverse
    # override matters: the grader returned "5 MET / 0 UNMET of 6" (one
    # UNCERTAIN) with accept=false, bouncing an already-merged story back
    # to ready — three such bounces blocked the scaffolding story and
    # starved 12 dependent stories for the whole run. UNCERTAIN means
    # "couldn't verify", and the template forbids rejecting on it.
    unmet = [v for v in per_bullet if v.verdict == "UNMET"]
    if per_bullet:
        accept = not unmet
    else:
        accept = bool(parsed.get("accept", True))
    reason = ""
    if not accept:
        reason = str(parsed.get("reason_if_reject", "")).strip()
        if not reason and unmet:
            reason = f"UNMET: {unmet[0].ac[:100]} ({unmet[0].reason[:100]})"

    return AcceptanceVerdict(
        accept=accept, reason=reason, per_bullet=per_bullet,
        tokens_input=tokens_in, tokens_output=tokens_out,
    )
