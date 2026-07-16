"""Goal decomposer — PO turns a goal into typed stories on the board.

Spawns the PO persona with a decomposition brief. PO emits a JSON array of
stories, one per intended piece of work. Each has:
  { title, body, type, priority }

We then draft each into the BoardStore. All stories start in `draft`; a
downstream refinement phase moves them to `ready`.

The prompt is deliberately concrete about the type taxonomy and asks for
6–12 stories so the team gets meaningful decomposition without the PO
producing 30 tickets on a small goal.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from orgos.agile.board_store import BoardStore, VALID_TYPES
from orgos.spawn import TaskBrief, spawn
from orgos.subagents import po_role


def _extract_json_arrays(text: str) -> list[str]:
    """Return every balanced JSON array span found in text.

    Handles arrays anywhere in the prose — fenced (```json), bare, or embedded.
    Object-in-array is fine; we track brace/bracket depth and string state.
    """
    import re
    out: list[str] = []
    # Fenced ```json [...] ``` first — most reliable.
    for m in re.finditer(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL):
        out.append(m.group(1))
    consumed_spans = [(text.find(s), text.find(s) + len(s)) for s in out if s in text]
    i = 0
    while i < len(text):
        ch = text[i]
        if ch != "[":
            i += 1
            continue
        if any(a <= i < b for a, b in consumed_spans):
            i += 1
            continue
        depth = 0
        in_str = False
        esc = False
        for j in range(i, len(text)):
            c = text[j]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    out.append(text[i : j + 1])
                    i = j + 1
                    break
        else:
            i += 1
            continue
    return out


_DECOMPOSE_BRIEF_TEMPLATE = """You are the Product Owner. Decompose the goal into 4-10 stories.

GOAL:
{goal}

REPO CONTEXT (top-level tree — for orientation, not exhaustive):
{repo_tree}

RULES:
0. **DO NOT PROPOSE WORK THAT ALREADY EXISTS.** Scan the repo tree above
   BEFORE drafting anything. If a package, module, directory, or test file
   already exists, do NOT create a story for it unless the story is
   explicitly to MODIFY it (add a function, fix a bug, extend behavior).
   "Create orgos/agile/__init__.py" when orgos/agile/ is already visible
   in the tree above is wrong — skip it.
1. Every story must be SMALL and INDEPENDENTLY testable — the sort a single
   engineer can finish in one focused session (≤ ~400 LOC diff).
2. Every story has exactly ONE type from this taxonomy:
     - architecture — new modules, refactors, cross-file design
     - test         — test infrastructure, coverage, regression tests
     - security     — auth, secrets, input validation, permission checks
     - feature      — user-visible functionality that isn't architectural
     - docs         — README, ADR, wiki entry, code comments
3. Assign a priority (0-100). Higher = do first. Foundational work (types,
   base classes, shared modules) gets high priority. Polish gets low.
4. Story titles are ≤ 80 chars, imperative form ("Add X", "Extract Y",
   "Modify Y"). If a story targets an existing file, make that explicit:
   "Add greet() to orgos/agile/greeting.py" rather than "Create greeting.py".
5. Body is a mini-spec: what to add, where, what tests to write, what
   'done' looks like. Include target file paths — and note whether the
   target file is expected to already exist or be newly created.
6. Optional `depends_on`: a story can list issue indices (0-based, into
   your OWN output array) that must complete before this story is workable.
   Use this for dependencies: e.g. "implement POST /notes" depends on
   "add Note data model". Field is optional; default is no dependencies.

7. Output the JSON array. If you wrap in an envelope (your persona may
   push you to), put the ARRAY inside the `payload` field. Either of these
   is accepted:

   Bare:
     [
       {{"title": "...", "body": "...", "type": "architecture", "priority": 90, "depends_on": []}},
       {{"title": "...", "body": "...", "type": "feature",      "priority": 80, "depends_on": [0]}},
       ...
     ]

   Envelope with payload as array:
     {{
       "role": "PO",
       "status": "completed",
       "payload": [
         {{"title": "...", "body": "...", "type": "architecture", "priority": 90}},
         ...
       ]
     }}

   BOTH formats work. But `payload: "[]"` (empty string) does NOT — the array must be a real JSON array, not a stringified one.

Output the array (or the envelope containing it) and nothing else.
"""


_INTERESTING_DIRS = ("orgos", "src", "app", "lib", "tests", "test", "spec")
_IGNORE = {"__pycache__", "node_modules", ".git", ".venv", "venv", ".pytest_cache",
           ".orgos_teams", ".sprints", "dist", "build", ".mypy_cache", ".ruff_cache",
           "_audit_logs", "_orgos_memory", ".superpowers"}


def _skip(name: str) -> bool:
    # Hide dotfiles, .egg-info, and underscore-prefixed dirs / scratch —
    # but keep dunder Python files (__init__.py, __main__.py) so PO can
    # clearly see which packages exist.
    if name in ("__init__.py", "__main__.py"):
        return False
    return name.startswith(".") or name.startswith("_") or name in _IGNORE \
        or name.endswith(".egg-info")


def _repo_tree_snapshot(repo_root: Path, max_entries: int = 120) -> str:
    """Tree snapshot for PO orientation.

    Shows top-level plus one level deep inside interesting dirs (orgos/,
    tests/, src/, etc.). Enough for PO to see which packages and modules
    already exist without dumping the entire tree.
    """
    parts = []
    root = Path(repo_root)

    def _add(rel_path: str, is_dir: bool) -> bool:
        parts.append(f"  {rel_path}{'/' if is_dir else ''}")
        return len(parts) < max_entries

    try:
        for p in sorted(root.iterdir()):
            if _skip(p.name):
                continue
            if p.is_dir():
                if not _add(p.name, True):
                    break
                # One level deeper for interesting dirs
                if p.name in _INTERESTING_DIRS:
                    for child in sorted(p.iterdir()):
                        if _skip(child.name):
                            continue
                        rel = f"{p.name}/{child.name}"
                        if not _add(rel, child.is_dir()):
                            break
                        # For orgos/ specifically, go one more level so PO sees modules
                        if p.name == "orgos" and child.is_dir():
                            for gc in sorted(child.iterdir()):
                                if _skip(gc.name):
                                    continue
                                if gc.suffix in (".py", ".md"):
                                    if not _add(f"{rel}/{gc.name}", False):
                                        break
                    if len(parts) >= max_entries:
                        break
            elif p.suffix in (".py", ".md", ".txt", ".toml", ".yaml", ".yml", ".json"):
                if not _add(p.name, False):
                    break
    except OSError:
        return "(cannot enumerate repo)"
    if not parts:
        return "(empty)"
    if len(parts) >= max_entries:
        parts.append(f"  … (truncated at {max_entries} entries)")
    return "\n".join(parts)


def _slugify(title: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9\-]+", "-", title.lower().strip("-"))
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:max_len] or "story"


def decompose_goal(
    *,
    goal: str,
    repo_root: Path,
    board: BoardStore,
    model: str,
    run_budget_tokens: int = 400_000,
    id_prefix: str = "GS",
) -> list[str]:
    """Spawn PO, decompose the goal, draft each story into the board.

    Returns the list of created issue_ids in priority order.
    """
    po = po_role(model=model)
    brief = TaskBrief(
        objective=_DECOMPOSE_BRIEF_TEMPLATE.format(
            goal=goal.strip(),
            repo_tree=_repo_tree_snapshot(repo_root),
        ),
        expected_output="A JSON array of 6-12 stories.",
        success_criteria=[
            "Output is a valid JSON array.",
            "Each element has title, body, type, priority.",
            "Types come from the valid taxonomy.",
        ],
    )
    result = spawn(po, brief, run_budget_tokens=run_budget_tokens)

    # Find the largest JSON array in the raw output. We look in three places:
    #   1. Bare arrays anywhere in the text.
    #   2. The `payload` field of a HandoffEnvelope (may be a JSON-array string).
    #   3. The `stories` field of a HandoffEnvelope (may be a list directly).
    from orgos.agile.sprint import _extract_json_objects
    parsed_stories: list[dict] = []
    last_raw = ""

    def _consider(candidate: Any) -> None:
        nonlocal parsed_stories
        if isinstance(candidate, list) and candidate and isinstance(candidate[0], dict):
            if len(candidate) > len(parsed_stories):
                parsed_stories = candidate

    for tout in result.tasks_output:
        raw = getattr(tout, "raw", "") or ""
        last_raw = raw

        # 1. Bare JSON arrays
        for blob in _extract_json_arrays(raw):
            try:
                data = json.loads(blob)
            except json.JSONDecodeError:
                continue
            _consider(data)

        # 2, 3. HandoffEnvelope objects with payload/stories field
        for blob in _extract_json_objects(raw):
            try:
                obj = json.loads(blob)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            for key in ("payload", "stories", "backlog", "artifacts"):
                v = obj.get(key)
                if isinstance(v, list):
                    _consider(v)
                elif isinstance(v, str):
                    # payload may be a JSON-array-string
                    try:
                        _consider(json.loads(v))
                    except (json.JSONDecodeError, TypeError):
                        pass

    if not parsed_stories:
        raise RuntimeError(
            "PO produced no parseable JSON array of stories. "
            f"Raw output tail: {last_raw[-500:]!r}"
        )

    # Sanitize, then draft each (first pass: assign ids without deps).
    created: list[str] = []
    dep_specs: list[list] = []
    for i, s in enumerate(parsed_stories):
        title = str(s.get("title", "")).strip() or f"story-{i:02d}"
        body = str(s.get("body", "")).strip()
        story_type = str(s.get("type", "feature")).strip().lower()
        if story_type not in VALID_TYPES:
            story_type = "feature"
        try:
            priority = int(s.get("priority", 0))
        except (TypeError, ValueError):
            priority = 0

        # Capture depends_on for the second pass (indices or ids)
        raw_deps = s.get("depends_on") or s.get("dependsOn") or []
        if not isinstance(raw_deps, list):
            raw_deps = []
        dep_specs.append(raw_deps)

        issue_id = f"{id_prefix}-{i:02d}-{_slugify(title)}"
        while board.exists(issue_id):
            issue_id = f"{issue_id}-{len(created)}"

        board.draft_story(
            issue_id=issue_id,
            title=title,
            body=body,
            story_type=story_type,
            priority=priority,
            actor="po",
        )
        created.append(issue_id)

    # Second pass: resolve depends_on positional indices to real issue_ids
    for i, raw_deps in enumerate(dep_specs):
        if not raw_deps:
            continue
        resolved: list[str] = []
        for d in raw_deps:
            if isinstance(d, int) and 0 <= d < len(created) and d != i:
                resolved.append(created[d])
            elif isinstance(d, str):
                # Might be a literal issue_id or a slug — accept as-is if it maps
                if d in created:
                    resolved.append(d)
        if resolved:
            story = board.read(created[i])
            story.depends_on = resolved
            board._write_story(story)
            board._audit(created[i], "po", "set_depends_on", deps=resolved)

    return created


def detect_decomposition_overlaps(
    board: BoardStore, issue_ids: list[str],
) -> list[dict]:
    """Heuristic check: find stories that target the same file with similar verbs.

    Not fatal. Returns a list of warnings, each shaped as:
      {"story_a": <id>, "story_b": <id>, "shared_paths": [...], "reason": "..."}

    Callers may surface these as decomposition_warning events so the human
    watching can see PO over-decomposed. In the current version we don't
    auto-merge — that's too risky. We just flag.
    """
    import re
    # Extract file-path-like tokens from each story body
    path_re = re.compile(r"[a-zA-Z_][\w/\-]*\.(?:py|md|js|ts|tsx|jsx|go|rs|yaml|yml|toml|json|txt|html|css|sh)")
    verb_re = re.compile(
        r"\b(add|create|implement|build|write|make|extend|modify|update|fix|"
        r"refactor|rename|delete|remove)\b",
        re.IGNORECASE,
    )

    stories = [board.read(iid) for iid in issue_ids]
    paths_per: dict[str, set[str]] = {}
    verbs_per: dict[str, set[str]] = {}
    for s in stories:
        text = f"{s.title}\n{s.body}"
        paths_per[s.issue_id] = set(path_re.findall(text))
        verbs_per[s.issue_id] = {v.lower() for v in verb_re.findall(text)}

    warnings = []
    for i, a in enumerate(stories):
        for b in stories[i + 1:]:
            shared_paths = paths_per[a.issue_id] & paths_per[b.issue_id]
            if not shared_paths:
                continue
            # If BOTH mention the same path AND both have creative verbs
            # ("add"/"implement"/"create"), that's a probable overlap.
            creative = {"add", "create", "implement", "build", "write", "make"}
            shared_creative = (verbs_per[a.issue_id] & creative) and \
                               (verbs_per[b.issue_id] & creative)
            if shared_creative:
                warnings.append({
                    "story_a": a.issue_id,
                    "story_b": b.issue_id,
                    "shared_paths": sorted(shared_paths),
                    "reason": ("both use creative verbs against the same "
                               f"file(s): {sorted(shared_paths)}"),
                })
    return warnings
