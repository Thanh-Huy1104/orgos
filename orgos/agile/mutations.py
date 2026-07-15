"""BriefMutation types for counterfactual sprint replays."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field


@dataclass
class SwapBacklogPick:
    new_issue_id: str
    kind: str = "swap_backlog_pick"


@dataclass
class InjectHeuristic:
    rule: str
    why: str
    tags: list[str] = field(default_factory=list)
    kind: str = "inject_heuristic"


@dataclass
class SwapRole:
    role_name: str
    alt_model: str | None = None
    alt_system_prompt: str | None = None
    kind: str = "swap_role"


@dataclass
class SwapTopology:
    agents_dir: str
    kind: str = "swap_topology"


BriefMutation = SwapBacklogPick | InjectHeuristic | SwapRole | SwapTopology


def apply_mutation(snapshot: dict, mutation) -> dict:
    out = copy.deepcopy(snapshot)
    out.setdefault("role_overrides", {})

    if isinstance(mutation, SwapBacklogPick):
        candidates = out.get("backlog", [])
        match = next(
            (c for c in candidates if str(c.get("issue_id")) == mutation.new_issue_id),
            None,
        )
        if match is None:
            raise ValueError(f"issue_id {mutation.new_issue_id!r} not in backlog")
        out["picked_issue"] = match
    elif isinstance(mutation, InjectHeuristic):
        out.setdefault("heuristics", []).append({
            "rule": mutation.rule, "why": mutation.why, "tags": mutation.tags,
        })
    elif isinstance(mutation, SwapRole):
        out["role_overrides"][mutation.role_name] = {
            "model": mutation.alt_model,
            "system_prompt": mutation.alt_system_prompt,
        }
    elif isinstance(mutation, SwapTopology):
        out["agents_dir"] = mutation.agents_dir
    else:
        raise TypeError(f"unknown mutation type: {type(mutation).__name__}")
    return out
