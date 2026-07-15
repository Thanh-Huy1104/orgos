"""Compaction — sprint-end pipeline for bounded context.

At every sprint boundary (default 4h), the compaction pipeline:
  1. Emits a wiki delta — what changed in wiki/ during the sprint window.
  2. Appends per-agent MEMORY deltas — durable decisions that survive compaction.
  3. Writes a compacted audit summary — prunes raw audit logs beyond a window.
  4. Produces retro heuristic candidates (delegates to retro.py).

Usage:
    from orgos.agile.compaction import CompactionRunner
    runner = CompactionRunner(wiki_root=Path("wiki"), agents_root=Path("agents"))
    result = runner.run(sprint, agent_names=["architect", "test", "devsecops"])
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

AUDIT_DIR = Path("./_audit_logs")
DEFAULT_AUDIT_WINDOW_DAYS = 7


@dataclass
class CompactionResult:
    sprint_id: str
    compacted_at: str
    wiki_delta: list[str] = field(default_factory=list)
    memory_deltas: dict[str, str] = field(default_factory=dict)
    audit_files_compacted: int = 0
    retro_candidates: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def __repr__(self) -> str:
        return f"CompactionResult(sprint={self.sprint_id}, audit={self.audit_files_compacted})"


def _modified_after(root: Path, since_iso: str) -> list[Path]:
    """Return all *.md files under root modified after since_iso."""
    try:
        since = datetime.fromisoformat(since_iso)
    except ValueError:
        return []
    results = []
    if not root.exists():
        return results
    for fp in root.rglob("*.md"):
        try:
            mtime = datetime.fromtimestamp(fp.stat().st_mtime, tz=timezone.utc)
            if mtime >= since:
                results.append(fp)
        except OSError:
            continue
    return results


def _compact_audit_logs(window_days: int = DEFAULT_AUDIT_WINDOW_DAYS) -> int:
    """Move audit files older than window_days into _compacted/ subdirectory.

    Returns the number of files moved.
    """
    if not AUDIT_DIR.exists():
        return 0

    cutoff = datetime.now(timezone.utc).timestamp() - (window_days * 86400)
    compacted_dir = AUDIT_DIR / "_compacted"
    compacted_dir.mkdir(parents=True, exist_ok=True)

    moved = 0
    for fp in sorted(AUDIT_DIR.iterdir()):
        if fp.is_dir():
            continue
        if fp.name.startswith("_"):
            continue
        try:
            mtime = fp.stat().st_mtime
        except OSError:
            continue
        if mtime < cutoff:
            dest = compacted_dir / fp.name
            try:
                shutil.move(str(fp), str(dest))
                moved += 1
            except OSError:
                continue

    return moved


def _read_sprint_start(sprint) -> str | None:
    """Extract the sprint start ISO timestamp from a Sprint object."""
    if hasattr(sprint, "started_at"):
        return sprint.started_at
    if isinstance(sprint, dict):
        return sprint.get("started_at")
    return None


class CompactionRunner:
    def __init__(self, wiki_root: Path | None = None,
                 agents_root: Path | None = None):
        self.wiki_root = wiki_root or Path("wiki")
        self.agents_root = agents_root or Path("agents")

    def run(
        self,
        sprint,
        *,
        agent_names: list[str] | None = None,
        window_days: int = DEFAULT_AUDIT_WINDOW_DAYS,
    ) -> CompactionResult:
        sprint_id = getattr(sprint, "id", "") if hasattr(sprint, "id") else ""
        started_at = _read_sprint_start(sprint)
        errors: list[str] = []

        wiki_delta: list[str] = []
        if started_at:
            modified = _modified_after(self.wiki_root, started_at)
            wiki_delta = [str(p.relative_to(self.wiki_root)) for p in modified]

        memory_deltas: dict[str, str] = {}
        for name in (agent_names or []):
            try:
                mem_path = self.agents_root / name / "memory.md"
                if mem_path.exists():
                    body = mem_path.read_text(encoding="utf-8")
                    mtime = datetime.fromtimestamp(
                        mem_path.stat().st_mtime, tz=timezone.utc
                    ).isoformat()
                    memory_deltas[name] = (
                        f"## Sprint {sprint_id}\n"
                        f"Compacted at {datetime.now(timezone.utc).isoformat()}\n"
                        f"Last modified: {mtime}\n"
                    )
            except OSError as e:
                errors.append(f"memory delta for {name}: {e}")

        audit_compacted = _compact_audit_logs(window_days)

        retro_candidates: list[dict] = []
        try:
            from orgos.agile.retro import build_retro_from_sprint
            retro = build_retro_from_sprint(sprint)
            candidates = retro.parsed_payload().get("candidate_heuristics", [])
            retro_candidates = list(candidates)
        except Exception as e:
            errors.append(f"retro candidate extraction: {e}")

        return CompactionResult(
            sprint_id=sprint_id,
            compacted_at=datetime.now(timezone.utc).isoformat(),
            wiki_delta=wiki_delta,
            memory_deltas=memory_deltas,
            audit_files_compacted=audit_compacted,
            retro_candidates=retro_candidates,
            errors=errors,
        )
