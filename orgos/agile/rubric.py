"""QA Validator rubric — deterministic grading of an EngineeringEnvelope.

Each criterion returns (passed: bool, reason: str). The rubric_score is
the weight-averaged pass rate. Lives outside the LLM so it is reproducible
and replay-safe.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

from .envelopes import BriefEnvelope, EngineeringEnvelope, GradeEnvelope

DIFF_LINE_CAP = 400


def _refinement_signoffs_complete(brief: dict, eng: dict) -> tuple[bool, str]:
    ref = brief.get("refinement", {})
    signoffs = ref.get("role_signoffs", [])
    required = {"architect", "test", "devsecops"}
    signed = {s["role"] for s in signoffs if s.get("approved")}
    missing = required - signed
    return (not missing), f"missing signoffs: {sorted(missing)}" if missing else ""


def _wiki_consulted(brief: dict, eng: dict) -> tuple[bool, str]:
    wiki = bool(eng.get("wiki_consulted"))
    return wiki, "wiki not consulted before implementation" if not wiki else ""


def _scope_drift_check(brief: dict, eng: dict) -> tuple[bool, str]:
    story_files = set(brief.get("touched_files_allowlist", []))
    touched = set(eng.get("files_touched", []))
    drift = touched - story_files
    if not story_files:
        return True, "no allowlist to drift from"
    return (not drift), (
        f"{len(drift)} file(s) outside scope: {sorted(drift)} "
        f"(allowlist had {len(story_files)} file(s))"
    ) if drift else ""


def _story_completed_matches_booted(brief: dict, eng: dict) -> tuple[bool, str]:
    booted_title = brief.get("booted_story_title", "")
    completed_title = eng.get("story_title", "")
    if not booted_title or not completed_title:
        return True, "no booted/completed story titles to compare"
    ok = booted_title.strip() == completed_title.strip()
    return ok, (
        f"story drift: booted '{booted_title[:80]}' != completed '{completed_title[:80]}'"
        if not ok else ""
    )


@dataclass
class Criterion:
    name: str
    weight: float
    fn: Callable[[dict, dict], tuple[bool, str]]


def _tests_pass(brief: dict, eng: dict) -> tuple[bool, str]:
    return bool(eng.get("test_passed")), eng.get("test_output", "")[:200]


def _files_in_allowlist(brief: dict, eng: dict) -> tuple[bool, str]:
    allow = set(brief.get("touched_files_allowlist", []))
    touched = set(eng.get("files_touched", []))
    extras = touched - allow
    return (not extras), f"unauthorised: {sorted(extras)}" if extras else ""


def _diff_size_ok(brief: dict, eng: dict) -> tuple[bool, str]:
    diff = eng.get("diff", "") or ""
    n = sum(1 for line in diff.splitlines() if line.startswith(("+", "-")))
    return n <= DIFF_LINE_CAP, f"diff_lines={n}"


def _commit_recorded(brief: dict, eng: dict) -> tuple[bool, str]:
    sha = eng.get("commit_sha", "") or ""
    return bool(sha) and len(sha) >= 7, f"sha={sha!r}"


def _test_command_matches(brief: dict, eng: dict) -> tuple[bool, str]:
    expected = brief.get("acceptance_tests", [])
    actual = eng.get("test_command", "")
    ok = any(actual.strip() == e.strip() for e in expected)
    return ok, f"expected one of {expected!r}, got {actual!r}"


def qa_criteria() -> list[Criterion]:
    return [
        Criterion("tests_pass", 0.30, _tests_pass),
        Criterion("files_in_allowlist", 0.15, _files_in_allowlist),
        Criterion("diff_size_ok", 0.10, _diff_size_ok),
        Criterion("commit_recorded", 0.10, _commit_recorded),
        Criterion("test_command_matches", 0.10, _test_command_matches),
        Criterion("refinement_signoffs_complete", 0.10, _refinement_signoffs_complete),
        Criterion("wiki_consulted", 0.05, _wiki_consulted),
        Criterion("scope_drift_check", 0.05, _scope_drift_check),
        Criterion("story_completed_matches_booted", 0.05, _story_completed_matches_booted),
    ]


def grade(brief: BriefEnvelope, eng: EngineeringEnvelope) -> GradeEnvelope:
    b = brief.parsed_payload()
    e = eng.parsed_payload()
    results = []
    score = 0.0
    for c in qa_criteria():
        passed, reason = c.fn(b, e)
        results.append({"name": c.name, "passed": passed, "reason": reason})
        if passed:
            score += c.weight
    payload = json.dumps({"criteria": results, "rubric_score": round(score, 3)})
    status = "completed" if score >= 0.99 else "needs_revision"
    return GradeEnvelope(
        role="qa-validator",
        status=status,
        summary=f"rubric_score={score:.2f}",
        success_criteria_met=(score >= 0.99),
        requires_human_approval=False,
        payload=payload,
    )
