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
        Criterion("tests_pass", 0.40, _tests_pass),
        Criterion("files_in_allowlist", 0.20, _files_in_allowlist),
        Criterion("diff_size_ok", 0.15, _diff_size_ok),
        Criterion("commit_recorded", 0.10, _commit_recorded),
        Criterion("test_command_matches", 0.15, _test_command_matches),
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
