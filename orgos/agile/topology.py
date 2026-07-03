"""Topology mutation proposal rules.

Reads role_attribution + qa_failure_tags + blocker_tags from PMStore,
compares against thresholds, and emits Proposals as ruamel.yaml diffs
against config/org.yaml. Never writes; only proposes.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML


_yaml = YAML()
_yaml.preserve_quotes = True


@dataclass
class Proposal:
    kind: str  # ADD_ROLE | REMOVE_ROLE | SPLIT_ROLE | MERGE_ROLES | MODIFY_THRESHOLD
    before_yaml: str
    after_yaml: str
    rationale: str


def _load(path: Path) -> Any:
    return _yaml.load(path.read_text())


def _dump(node: Any) -> str:
    buf = io.StringIO()
    _yaml.dump(node, buf)
    return buf.getvalue()


def _current_members(cfg: Any) -> list[str]:
    depts = cfg.get("departments") or []
    if not depts:
        return []
    return [m["name"] for m in (depts[0].get("members") or [])]


def _remove_member(cfg: Any, role_name: str) -> Any:
    import copy
    new = copy.deepcopy(cfg)
    for d in new.get("departments") or []:
        d["members"] = [m for m in d.get("members") or [] if m["name"] != role_name]
    return new


def _add_member(cfg: Any, role_name: str, expire_at: str | None = None) -> Any:
    import copy
    new = copy.deepcopy(cfg)
    entry = {"name": role_name, "tier": "worker", "system_prompt": ""}
    if expire_at:
        entry["expire_at"] = expire_at
    if new.get("departments"):
        (new["departments"][0].setdefault("members", [])).append(entry)
    return new


def _split_member(cfg: Any, role_name: str, split_suffix: str) -> Any:
    import copy
    new = copy.deepcopy(cfg)
    for d in new.get("departments") or []:
        out = []
        for m in d.get("members") or []:
            if m["name"] == role_name:
                out.append(m)
                out.append({**m, "name": f"{role_name}-{split_suffix}"})
            else:
                out.append(m)
        d["members"] = out
    return new


def propose_topology_mutations(
    pm: Any, org_yaml_path: Path, *, window_sprints: int = 5,
) -> list[Proposal]:
    cfg = _load(org_yaml_path)
    before_yaml = _dump(cfg)
    proposals: list[Proposal] = []

    # 1. REMOVE_ROLE — contribution < 0.05 for `window_sprints` sprints
    for role in _current_members(cfg):
        rows = pm.list_role_attribution(role, since_days=30)
        last = [r["score"] for r in rows[:window_sprints]]
        if len(last) >= window_sprints and all(s < 0.05 for s in last):
            proposals.append(Proposal(
                kind="REMOVE_ROLE",
                before_yaml=before_yaml,
                after_yaml=_dump(_remove_member(cfg, role)),
                rationale=(
                    f"{role} contribution < 0.05 for {window_sprints} sprints "
                    f"(scores={last!r})"
                ),
            ))

    # 2. SPLIT_ROLE — QA failure tag with >= 3 occurrences maps to the Engineer
    fails = pm.list_qa_failure_tags(since_sprints=window_sprints)
    for tag, count in fails:
        if count >= 3 and tag in ("no-canary", "files_in_allowlist"):
            suffix = "release-eng" if tag == "no-canary" else "guardian"
            proposals.append(Proposal(
                kind="SPLIT_ROLE",
                before_yaml=before_yaml,
                after_yaml=_dump(_split_member(cfg, "engineer", suffix)),
                rationale=(
                    f"QA failures cluster on {tag} ({count} in last "
                    f"{window_sprints} sprints); split Engineer -> engineer-{suffix}"
                ),
            ))
            break

    # 3. ADD_ROLE — blocker tag with no owning role
    owners = set(_current_members(cfg))
    blockers = pm.list_blocker_tags(since_sprints=window_sprints)
    for tag, count in blockers:
        role_name = f"{tag}-specialist"
        if count >= 3 and role_name not in owners:
            expire = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
            proposals.append(Proposal(
                kind="ADD_ROLE",
                before_yaml=before_yaml,
                after_yaml=_dump(_add_member(cfg, role_name, expire_at=expire)),
                rationale=(
                    f"Blocker tag {tag!r} appeared {count} times with no owner; "
                    f"adding temporary specialist (expires {expire})."
                ),
            ))

    return proposals
