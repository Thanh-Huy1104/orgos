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


_DECOMPOSE_BRIEF_TEMPLATE = """You are the Product Owner. Decompose the goal into 6-12 stories.

GOAL:
{goal}

REPO CONTEXT (top-level tree — for orientation, not exhaustive):
{repo_tree}

RULES:
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
4. Story titles are ≤ 80 chars, imperative form ("Add X", "Extract Y").
5. Body is a mini-spec: what to add, where, what tests to write, what
   'done' looks like. Include target file paths if you can name them.
6. Output the JSON array. If you wrap in an envelope (your persona may
   push you to), put the ARRAY inside the `payload` field. Either of these
   is accepted:

   Bare:
     [
       {{"title": "...", "body": "...", "type": "architecture", "priority": 90}},
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


def _repo_tree_snapshot(repo_root: Path, max_entries: int = 40) -> str:
    """Cheap tree snapshot for PO orientation. Top-level dirs + top-level .py files."""
    parts = []
    try:
        for p in sorted(Path(repo_root).iterdir()):
            if p.name.startswith(".") or p.name in ("__pycache__", "node_modules"):
                continue
            if p.is_dir():
                parts.append(f"  {p.name}/")
            elif p.suffix in (".py", ".md", ".txt", ".toml", ".yaml", ".yml", ".json"):
                parts.append(f"  {p.name}")
            if len(parts) >= max_entries:
                parts.append(f"  … ({len(parts)} entries shown)")
                break
    except OSError:
        return "(cannot enumerate repo)"
    return "\n".join(parts) if parts else "(empty)"


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

    # Sanitize, then draft each.
    created: list[str] = []
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

        issue_id = f"{id_prefix}-{i:02d}-{_slugify(title)}"
        # If a story with this id already exists, append a suffix.
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

    return created
