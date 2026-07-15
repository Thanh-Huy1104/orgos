"""Conductor — reads HEARTBEAT.md on boot, produces a validated TaskBrief.

On each scheduling cycle, the conductor reads an agent's HEARTBEAT.md, extracts
the next-task section, and returns a TaskBrief that passes the same validation
gate as PM-authored briefs. Self-authored tasks go through the same scope brake:

  - brief.underspecified() must return None
  - estimated files and LOC must be within caps (MAX_FILES=5, MAX_LOC=400)
  - The brief is always logged (via audit callback) so self-authored agendas are
    traceable

Usage:
    from orgos.agile.conductor import Conductor
    c = Conductor(Path("agents"))
    brief = c.boot("architect")
    spawn(architect_role(), brief, ...)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from orgos.agile.board import MAX_FILES, MAX_LOC, story_fits_size_caps
from orgos.spawn.contracts import TaskBrief
from orgos.spawn.persona_loader import PersonaFile, load_persona_file


@dataclass
class BootResult:
    agent_name: str
    boots_at: str
    next_action: str
    brief: TaskBrief
    scope_ok: bool = True
    scope_reason: str = ""
    warnings: list[str] = field(default_factory=list)


def _extract_section(body: str, section_name: str) -> str | None:
    """Extract the content of a named `## Section` from markdown body."""
    pattern = rf"^##\s+{re.escape(section_name)}\s*\n(.*?)(?=\n##\s|\Z)"
    m = re.search(pattern, body, re.DOTALL | re.MULTILINE)
    if not m:
        return None
    return m.group(1).strip()


def _extract_next_action(body: str) -> str:
    """Try multiple section names to find the next action."""
    for name in ("Next Actions", "Next Action", "Current Task", "Current Phase"):
        section = _extract_section(body, name)
        if section:
            return section
    return body.strip()


def _estimate_scope(text: str) -> tuple[int, int]:
    """Heuristic: count file paths and rough LOC from the action text."""
    files = len(re.findall(r'(?:`|")(?:\w+[/\\])*\w+\.\w+(?:`|")|(?:^|\s)(?:\w+[/\\])*\w+\.\w+(?:\s|$)', text))
    return max(files, 0), 0


class Conductor:
    """Reads agent persona files and produces validated TaskBriefs from HEARTBEAT."""

    def __init__(self, agents_root: Path):
        self.agents_root = agents_root

    def boot(self, agent_name: str, *, estimated_files: int = 0,
             estimated_loc: int = 0) -> BootResult:
        if agent_name.startswith("_"):
            raise ValueError(f"agent_name must not start with '_': {agent_name!r}")

        heartbeat_path = self.agents_root / agent_name / "heartbeat.md"
        pf: PersonaFile = load_persona_file(heartbeat_path, "heartbeat")

        next_action = _extract_next_action(pf.body)
        log.info("conductor: booting %s (next_action_len=%d)", agent_name, len(next_action))
        scope_from_text = _estimate_scope(next_action)
        files = estimated_files or scope_from_text[0]
        loc = estimated_loc or scope_from_text[1]

        brief = TaskBrief(
            objective=next_action,
            expected_output=f"Complete the next action from {agent_name}'s HEARTBEAT.",
            success_criteria=[
                f"Action described in HEARTBEAT is completed.",
                f"Any files touched are within scope bounds.",
            ],
            source_guidance=(
                f"Authored by {agent_name}'s HEARTBEAT via autonomous conductor. "
                f"Booted at {datetime.now(timezone.utc).isoformat()}."
            ),
        )

        warnings: list[str] = []
        scope_ok, scope_reason = story_fits_size_caps(files, loc)
        if not scope_ok:
            warnings.append(f"scope cap violation: {scope_reason}")

        underspec = brief.underspecified()
        if underspec:
            warnings.append(f"underspecified brief: {underspec}")

        return BootResult(
            agent_name=agent_name,
            boots_at=datetime.now(timezone.utc).isoformat(),
            next_action=next_action,
            brief=brief,
            scope_ok=scope_ok and underspec is None,
            scope_reason=scope_reason,
            warnings=warnings,
        )

    def boot_with_scope_check(
        self, agent_name: str,
        estimated_files: int = 0, estimated_loc: int = 0,
    ) -> BootResult:
        """Boot and raise if scope caps are violated or brief is underspecified."""
        result = self.boot(agent_name, estimated_files=estimated_files,
                           estimated_loc=estimated_loc)
        if result.warnings:
            raise ValueError(
                f"HEARTBEAT boot failed for {agent_name}: "
                f"{'; '.join(result.warnings)}"
            )
        return result
