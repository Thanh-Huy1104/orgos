"""Reflector — Strategic Brain for the two-loop learning architecture.

Tactical loop  (rubric.py):  run → grade → retry → store attempt_grades
Strategic loop (this file):  diff attempts → extract heuristics → deduplicate
                              → store in OrgMemory → inject into future briefs

The key insight: instead of letting the prose journal grow unboundedly (context
blowup), we extract *structured, queryable* heuristics from the rubric diffs.
Each heuristic is a short rule with a domain tag, retrieved by keyword match,
and injected as a compact bullet list — constant context cost regardless of how
many runs have happened.

No embeddings, no LLM call for extraction — purely deterministic from grade
notes and failure messages. Zero marginal cost per reflection.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

_DB_PATH = "./_orgos_memory/memory.db"


@dataclass
class Heuristic:
    id: str
    domain: str
    tags: list[str]
    rule: str
    why: str
    source_run_id: str | None
    score: float
    use_count: int = 0
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class Reflector:
    """Extract, store, retrieve, and inject heuristics from rubric loop results.

    One instance per strategist type is enough; share across calls:

        _reflector = Reflector(domain="quant_pairs")
        heuristics = _reflector.retrieve(objective, n=3)
        # ... build brief with inject_block(heuristics) ...
        result = chain_until(...)
        _reflector.reflect(result)
    """

    def __init__(self, domain: str, db_path: str = _DB_PATH) -> None:
        self.domain = domain
        self._db_path = db_path

    # ── Public API ─────────────────────────────────────────────────────────

    def reflect(self, result: Any) -> list[Heuristic]:
        """Extract heuristics from a SpawnResult and persist them.

        Reads `result.attempt_grades` (populated by the rubric loop). If there
        were failures before a pass, extracts a 'what went wrong → what fixed it'
        heuristic. Always extracts a 'what worked' heuristic from a passing run.
        Returns the list of newly stored heuristics (empty if nothing to learn).
        """
        grades = getattr(result, "attempt_grades", [])
        if not grades:
            return []

        objective = getattr(result.envelope, "summary", "") or ""
        run_id = getattr(result, "run_id", None)
        new_heuristics: list[Heuristic] = []

        # Find the boundary between failure streak and first pass
        fail_grades = [g for g in grades if not g.passed]
        pass_grades = [g for g in grades if g.passed]

        if fail_grades and pass_grades:
            # Learning moment: something changed between failure and success
            best_pass = max(pass_grades, key=lambda g: g.score)
            h = self._extract_failure_recovery(
                fail_grades, best_pass, objective, run_id
            )
            if h and not self._is_duplicate(h):
                self._store(h)
                new_heuristics.append(h)

        if pass_grades:
            best = max(pass_grades, key=lambda g: g.score)
            if best.score >= 0.7:  # only crystallise strong passes
                h = self._extract_success(best, objective, run_id)
                if h and not self._is_duplicate(h):
                    self._store(h)
                    new_heuristics.append(h)

        return new_heuristics

    def retrieve(self, objective: str, n: int = 4) -> list[Heuristic]:
        """Return the top-N heuristics relevant to `objective` by tag overlap.

        Updates use_count so popular heuristics can be promoted over time.
        """
        all_h = self._load_domain()
        if not all_h:
            return []

        obj_words = _tokenise(objective)
        scored = []
        for h in all_h:
            overlap = len(obj_words & set(h.tags))
            # Blend keyword overlap with stored quality score
            blend = overlap * 0.6 + h.score * 0.4
            scored.append((blend, h))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = [h for _, h in scored[:n] if _ > 0]

        if top:
            self._bump_use_count([h.id for h in top])
        return top

    def inject_block(self, heuristics: list[Heuristic]) -> str:
        """Format heuristics as a compact markdown block for brief injection.

        Returns empty string if the list is empty (safe to concatenate).
        """
        if not heuristics:
            return ""
        lines = ["## Playbook (learned from prior runs — apply these)\n"]
        for h in heuristics:
            lines.append(f"- **{h.rule}**")
            if h.why:
                lines.append(f"  _(why: {h.why})_")
        return "\n".join(lines)

    # ── Extraction ─────────────────────────────────────────────────────────

    def _extract_failure_recovery(
        self,
        fails: list[Any],
        win: Any,
        objective: str,
        run_id: str | None,
    ) -> Heuristic | None:
        all_failures = []
        for g in fails:
            all_failures.extend(g.failures or [])
        if not all_failures:
            return None

        failure_summary = "; ".join(all_failures[:3])  # keep it short
        rule = f"Avoid: {_truncate(failure_summary, 120)}"
        why = f"Led to rubric failure (score {fails[-1].score:.2f}); retry scored {win.score:.2f}"
        tags = _extract_tags(objective) + _extract_tags(failure_summary)

        return Heuristic(
            id=uuid.uuid4().hex[:12],
            domain=self.domain,
            tags=list(set(tags))[:10],
            rule=rule,
            why=why,
            source_run_id=run_id,
            score=win.score,
        )

    def _extract_success(
        self, win: Any, objective: str, run_id: str | None
    ) -> Heuristic | None:
        notes = (win.notes or "").strip()
        if not notes:
            return None

        rule = f"Works: {_truncate(notes, 120)}"
        why = f"Passed rubric with score {win.score:.2f}"
        tags = _extract_tags(objective) + _extract_tags(notes)

        return Heuristic(
            id=uuid.uuid4().hex[:12],
            domain=self.domain,
            tags=list(set(tags))[:10],
            rule=rule,
            why=why,
            source_run_id=run_id,
            score=win.score,
        )

    # ── Deduplication ──────────────────────────────────────────────────────

    def _is_duplicate(self, candidate: Heuristic, threshold: float = 0.6) -> bool:
        """Reject if an existing heuristic has high token overlap with candidate."""
        existing = self._load_domain()
        cand_tokens = set(_tokenise(candidate.rule))
        if not cand_tokens:
            return False
        for h in existing:
            existing_tokens = set(_tokenise(h.rule))
            union = cand_tokens | existing_tokens
            if not union:
                continue
            jaccard = len(cand_tokens & existing_tokens) / len(union)
            if jaccard >= threshold:
                return True
        return False

    # ── Persistence ────────────────────────────────────────────────────────

    def _conn(self):  # type: ignore[return]
        import sqlite3
        from pathlib import Path

        path = Path(self._db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS heuristics (
                id            TEXT PRIMARY KEY,
                domain        TEXT NOT NULL,
                tags          TEXT NOT NULL DEFAULT '[]',
                rule          TEXT NOT NULL,
                why           TEXT NOT NULL DEFAULT '',
                source_run_id TEXT,
                score         REAL NOT NULL DEFAULT 0.0,
                use_count     INTEGER NOT NULL DEFAULT 0,
                created_at    TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_heuristics_domain
                ON heuristics(domain, score DESC);
        """)
        return conn

    def _store(self, h: Heuristic) -> None:
        conn = self._conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO heuristics
                   (id, domain, tags, rule, why, source_run_id, score, use_count, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    h.id, h.domain, json.dumps(h.tags), h.rule, h.why,
                    h.source_run_id, h.score, h.use_count, h.created_at,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def _load_domain(self) -> list[Heuristic]:
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM heuristics WHERE domain = ? ORDER BY score DESC LIMIT 50",
                (self.domain,),
            ).fetchall()
            return [_row_to_heuristic(r) for r in rows]
        finally:
            conn.close()

    def _bump_use_count(self, ids: list[str]) -> None:
        conn = self._conn()
        try:
            for hid in ids:
                conn.execute(
                    "UPDATE heuristics SET use_count = use_count + 1 WHERE id = ?", (hid,)
                )
            conn.commit()
        finally:
            conn.close()


# ── Helpers ────────────────────────────────────────────────────────────────────

_STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "that", "this", "it", "its", "not", "no", "do", "did", "has", "have",
    "had", "will", "would", "could", "should", "may", "might", "must",
}


def _tokenise(text: str) -> set[str]:
    words = re.findall(r"[a-z]{3,}", text.lower())
    return {w for w in words if w not in _STOP_WORDS}


def _extract_tags(text: str, max_tags: int = 8) -> list[str]:
    return list(_tokenise(text))[:max_tags]


def _truncate(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + "…"


def _row_to_heuristic(row: Any) -> Heuristic:
    return Heuristic(
        id=row["id"],
        domain=row["domain"],
        tags=json.loads(row["tags"] or "[]"),
        rule=row["rule"],
        why=row["why"] or "",
        source_run_id=row["source_run_id"],
        score=float(row["score"]),
        use_count=int(row["use_count"]),
        created_at=row["created_at"],
    )
