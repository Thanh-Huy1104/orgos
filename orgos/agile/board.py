"""Board READY gate — pure logic for the pull-based work assignment model.

Checks whether a story meets the conditions for being marked READY:
  1. All required roles have signed off during refinement.
  2. Story fits within size caps (files, LOC).
  3. Story has a non-empty title and acceptance criteria.

Does not depend on GitHub or any I/O — callers supply the data.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MAX_FILES = 5
MAX_LOC = 400
REQUIRED_ROLES: tuple[str, ...] = ("architect", "test", "devsecops")


@dataclass
class ReadyGateResult:
    ready: bool
    missing_signoffs: list[str] = field(default_factory=list)
    size_failures: list[str] = field(default_factory=list)
    reason: str = ""


def check_ready_gate(
    *,
    title: str = "",
    acceptance_criteria: list[str] | None = None,
    estimated_files: int = 0,
    estimated_loc: int = 0,
    role_signoffs: dict[str, bool] | None = None,
) -> ReadyGateResult:
    signoffs = role_signoffs or {}
    missing: list[str] = []
    failures: list[str] = []
    reasons: list[str] = []

    if not title.strip():
        reasons.append("story has no title")
    ac = acceptance_criteria or []
    if not ac:
        reasons.append("story has no acceptance criteria")

    for role in REQUIRED_ROLES:
        if role not in signoffs or not signoffs[role]:
            missing.append(role)

    if missing:
        reasons.append(f"missing signoffs: {', '.join(sorted(missing))}")

    if estimated_files > MAX_FILES:
        msg = f"estimated files ({estimated_files}) exceeds cap ({MAX_FILES})"
        failures.append(msg)
        reasons.append(msg)

    if estimated_loc > MAX_LOC:
        msg = f"estimated LOC ({estimated_loc}) exceeds cap ({MAX_LOC})"
        failures.append(msg)
        reasons.append(msg)

    return ReadyGateResult(
        ready=(not reasons),
        missing_signoffs=sorted(missing),
        size_failures=failures,
        reason="; ".join(reasons) if reasons else "story is ready",
    )


def story_fits_size_caps(estimated_files: int, estimated_loc: int) -> tuple[bool, str]:
    fails: list[str] = []
    if estimated_files > MAX_FILES:
        fails.append(f"files {estimated_files} > {MAX_FILES}")
    if estimated_loc > MAX_LOC:
        fails.append(f"LOC {estimated_loc} > {MAX_LOC}")
    return (not fails), "; ".join(fails) if fails else "within caps"
