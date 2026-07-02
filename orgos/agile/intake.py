"""Backlog ranker — pure Python, no LLM."""

from __future__ import annotations

from typing import Iterable

_SIZE_THRESHOLDS = {"S": 500, "M": 2500}  # body chars
_RISK_LABELS_HIGH = {"security", "compliance", "data-migration"}
_RISK_LABELS_MED = {"bug", "regression"}
_LABEL_PRIORITY = {
    "agent-eligible": 0, "good-first-issue": 1, "docs": 2, "chore": 3,
}


def _size(body: str) -> str:
    n = len(body or "")
    if n < _SIZE_THRESHOLDS["S"]:
        return "S"
    if n < _SIZE_THRESHOLDS["M"]:
        return "M"
    return "L"


def _risk(labels: Iterable[str]) -> str:
    s = set(labels)
    if s & _RISK_LABELS_HIGH:
        return "high"
    if s & _RISK_LABELS_MED:
        return "med"
    return "low"


def _label_priority(labels: Iterable[str]) -> int:
    return min((_LABEL_PRIORITY.get(l, 99) for l in labels), default=99)


def rank_backlog(
    issues: list[dict],
    *,
    allowed_labels: set[str] | None = None,
    max_candidates: int = 10,
) -> list[dict]:
    allowed = allowed_labels or {"agent-eligible", "good-first-issue"}
    filtered = [i for i in issues if set(i.get("labels", [])) & allowed]
    enriched = []
    for i in filtered:
        size = _size(i.get("body", ""))
        risk = _risk(i.get("labels", []))
        enriched.append({
            **i,
            "size_estimate": size,
            "risk_estimate": risk,
            "rank_reason": f"size={size},risk={risk}",
        })
    # Sort key: prefer S over M over L; within size, by label priority.
    size_rank = {"S": 0, "M": 1, "L": 2}
    enriched.sort(key=lambda c: (
        size_rank[c["size_estimate"]],
        _label_priority(c["labels"]),
        c["issue_id"],
    ))
    return enriched[:max_candidates]
