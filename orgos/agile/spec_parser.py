"""Spec-file parser — turn a markdown PRD into pre-declared stories.

When the user passes `--spec-file spec.md` to `orgos start` or `orgos plan`,
we try to honor any explicit story boundaries they wrote. The convention:

    ## Story: <title>
    <body paragraphs>

    Files: path/one.py, path/two.py
    Component: auth
    Priority: 80
    Type: feature | architecture | test | security | docs
    Depends: 2, 4                   # 1-based indices into the story list
    AC:                             # acceptance criteria bullets
      - The endpoint returns 201 on success.
      - Duplicate emails return 409.

    ## Story: <next title>
    ...

Everything is optional except the `## Story:` header. Missing fields default
to sensible values (`type=feature`, `priority=50`, empty files, empty AC).
`## Feature:` and `## Task:` are accepted as synonyms of `## Story:`.

When NO `## Story:` headers are present in the file, `parse_spec_file()`
returns an empty list — the caller should fall back to letting the PO
decompose the goal string as it always has.

Rationale: for real PRDs the human writing the spec knows the natural
story boundaries better than an LLM re-inventing them. Honor what they
wrote; only re-decompose when nothing is declared.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


_HEADER_RE = re.compile(
    r"^##\s+(?:Story|Feature|Task)\s*:?\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

_VALID_TYPES = ("architecture", "test", "security", "feature", "docs")


@dataclass
class SpecStory:
    title: str
    body: str = ""
    type: str = "feature"
    priority: int = 50
    files_to_touch: list[str] = field(default_factory=list)
    component: Optional[str] = None
    depends_on: list[int] = field(default_factory=list)  # 1-based indices
    acceptance_criteria: list[str] = field(default_factory=list)


def _split_csv(value: str) -> list[str]:
    return [p.strip() for p in re.split(r"[,\n]+", value) if p.strip()]


def _parse_ac_block(text: str) -> list[str]:
    """Bullets after `AC:` (until blank line or next `<Field>:` header)."""
    out: list[str] = []
    in_block = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if not in_block:
            if re.match(r"^AC\s*:\s*$", line, re.IGNORECASE):
                in_block = True
            continue
        stripped = line.strip()
        if not stripped:
            # blank line ends the AC block
            break
        if re.match(r"^[A-Z][A-Za-z]{1,20}\s*:", line) and not stripped.startswith(("-", "*")):
            break
        m = re.match(r"^\s*[-*]\s*(.+)$", line)
        if m:
            out.append(m.group(1).strip())
    return out


_FIELD_PATTERNS = {
    "files_to_touch": re.compile(r"^Files?\s*:\s*(.+)$", re.MULTILINE | re.IGNORECASE),
    "component":     re.compile(r"^Component\s*:\s*(.+)$", re.MULTILINE | re.IGNORECASE),
    "priority":      re.compile(r"^Priority\s*:\s*(\d+)", re.MULTILINE | re.IGNORECASE),
    "type":          re.compile(r"^Type\s*:\s*([A-Za-z]+)", re.MULTILINE | re.IGNORECASE),
    "depends":       re.compile(r"^Depends?(?:_on)?\s*:\s*(.+)$", re.MULTILINE | re.IGNORECASE),
}


def _parse_one_story(title: str, chunk: str) -> SpecStory:
    story = SpecStory(title=title.strip())

    # Extract fields; strip them out to leave a clean body.
    stripped = chunk
    for name, pat in _FIELD_PATTERNS.items():
        m = pat.search(stripped)
        if not m:
            continue
        value = m.group(1).strip()
        if name == "files_to_touch":
            story.files_to_touch = _split_csv(value)
        elif name == "component":
            story.component = value.lower().replace(" ", "-") or None
        elif name == "priority":
            try:
                story.priority = int(value)
            except ValueError:
                pass
        elif name == "type":
            t = value.strip().lower()
            if t in _VALID_TYPES:
                story.type = t
        elif name == "depends":
            deps: list[int] = []
            for tok in _split_csv(value):
                try:
                    deps.append(int(tok))
                except ValueError:
                    continue
            story.depends_on = deps
        # Remove the matched line from the body chunk
        stripped = stripped.replace(m.group(0), "", 1)

    story.acceptance_criteria = _parse_ac_block(chunk)
    # Remove the AC block from the body
    stripped = re.sub(
        r"^AC\s*:\s*\n(?:\s*[-*].*\n?)+", "", stripped,
        flags=re.MULTILINE | re.IGNORECASE,
    )

    story.body = stripped.strip()
    return story


def parse_spec_text(spec_text: str) -> list[SpecStory]:
    """Extract SpecStory objects from a spec markdown blob.

    Returns [] when there are no `## Story:` headers — the caller should
    fall back to LLM decomposition of the goal string.
    """
    if not spec_text or not spec_text.strip():
        return []

    matches = list(_HEADER_RE.finditer(spec_text))
    if not matches:
        return []

    stories: list[SpecStory] = []
    for i, m in enumerate(matches):
        title = m.group(1).strip()
        chunk_start = m.end()
        chunk_end = matches[i + 1].start() if i + 1 < len(matches) else len(spec_text)
        chunk = spec_text[chunk_start:chunk_end]
        stories.append(_parse_one_story(title, chunk))
    return stories


def parse_spec_file(path: Path) -> list[SpecStory]:
    """Convenience: read the file, delegate to parse_spec_text.

    Returns [] on read error or when no stories were declared.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return []
    return parse_spec_text(text)


def spec_stories_to_draft_dicts(stories: list[SpecStory]) -> list[dict]:
    """Convert SpecStory list to the dict shape decompose_goal expects.

    depends_on stays as 1-based indices for now; the caller resolves them
    to real issue_ids after all stories are drafted (matches how the LLM
    output path already works, minus the off-by-one).
    """
    out: list[dict] = []
    for i, s in enumerate(stories):
        # Convert 1-based to 0-based indices; ignore self-references.
        deps0 = [d - 1 for d in s.depends_on if 1 <= d <= len(stories) and (d - 1) != i]
        out.append({
            "title": s.title,
            "body": s.body,
            "type": s.type,
            "priority": s.priority,
            "files_to_touch": s.files_to_touch,
            "component": s.component,
            "depends_on": deps0,
            "acceptance_criteria": s.acceptance_criteria,
        })
    return out
