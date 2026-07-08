"""Loader for the three-layer persona markdown files.

Spec: docs/superpowers/specs/2026-07-07-autonomous-scrum-team-design.md
Plan: docs/superpowers/plans/2026-07-08-persona-file-loader.md
Roadmap: docs/superpowers/plans/2026-07-08-autonomous-scrum-team-roadmap.md

Layered inheritance:
  Layer 1 (principles)   → agents/_principles/principles.md
  Layer 2 (worker_base)  → agents/_worker_base/{soul,brain,habits,memory,heartbeat}.md
  Layer 3 (specific)     → agents/<agent_name>/{soul,brain,habits,memory,heartbeat}.md

Concatenation order in the assembled system_prompt is
  principles → worker_base(soul→brain→habits→memory→heartbeat)
             → specific(soul→brain→habits→memory→heartbeat)
so HEARTBEAT lands at the end of context (recency-attention window), per §0.1
of the spec.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, cast

from pydantic import BaseModel, ValidationError
from ruamel.yaml import YAML

from orgos.spawn.persona_schema import (
    FILE_TYPES,
    REQUIRED_SECTIONS,
    PersonaValidationError,
    SimpleFrontmatter,
    SoulFrontmatter,
)

log = logging.getLogger(__name__)

_YAML = YAML(typ="safe")


@dataclass(frozen=True)
class PersonaFile:
    file_type: str
    frontmatter: BaseModel
    body: str


_FRONTMATTER_MODELS: dict[str, type[BaseModel]] = {
    "principles": SimpleFrontmatter,
    "soul": SoulFrontmatter,
    "brain": SimpleFrontmatter,
    "habits": SimpleFrontmatter,
    "memory": SimpleFrontmatter,
    "heartbeat": SimpleFrontmatter,
}


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Return (yaml_text, body_text). Raises if no closing '---' found."""
    # Normalize CRLF to LF once at entry so YAML parsing doesn't see stray \r
    text = text.replace("\r\n", "\n")

    if not text.startswith("---\n"):
        raise PersonaValidationError("file must start with YAML frontmatter (---)")
    # Skip the opening '---' line.
    rest = text.split("\n", 1)[1]
    if "\n---\n" not in rest:
        raise PersonaValidationError("frontmatter is not closed with a '---' line")
    yaml_text, body = rest.split("\n---\n", 1)
    # Trim trailing whitespace from yaml_text for good measure
    yaml_text = yaml_text.rstrip()
    # Body starts after the closing '---\n'; strip the leading newline.
    body = body.lstrip("\n")
    return yaml_text, body


def _warn_missing_sections(body: str, file_type: str, path: Path) -> None:
    required = REQUIRED_SECTIONS.get(file_type, [])
    for section in required:
        needle = f"## {section}"
        if needle not in body:
            log.warning(
                "persona: %s missing section %r (file_type=%s)",
                path, section, file_type,
            )


def load_persona_file(path: Path, file_type: str) -> PersonaFile:
    """Read one persona file, validate its frontmatter, return a PersonaFile."""
    if file_type not in _FRONTMATTER_MODELS:
        raise PersonaValidationError(
            f"unknown file_type {file_type!r}; expected one of "
            f"{sorted(_FRONTMATTER_MODELS)}"
        )
    if not path.exists():
        raise PersonaValidationError(f"persona file not found: {path}")

    text = path.read_text(encoding="utf-8")
    yaml_text, body = _split_frontmatter(text)

    try:
        data = _YAML.load(io.StringIO(yaml_text)) or {}
    except Exception as e:  # ruamel raises its own tree of errors
        raise PersonaValidationError(f"{path}: invalid YAML frontmatter: {e}") from e

    model_cls = _FRONTMATTER_MODELS[file_type]
    try:
        frontmatter = model_cls(**data)
    except ValidationError as e:
        raise PersonaValidationError(f"{path}: frontmatter validation failed: {e}") from e

    _warn_missing_sections(body, file_type, path)
    return PersonaFile(file_type=file_type, frontmatter=frontmatter, body=body)


def load_layer(
    dir_path: Path, file_types: Sequence[str],
) -> dict[str, PersonaFile]:
    """Load every file_type from dir_path. Missing files raise."""
    if not dir_path.is_dir():
        raise PersonaValidationError(f"layer directory not found: {dir_path}")
    out: dict[str, PersonaFile] = {}
    for ft in file_types:
        out[ft] = load_persona_file(dir_path / f"{ft}.md", ft)
    return out


_LAYER_ORDER: tuple[str, ...] = FILE_TYPES  # soul → brain → habits → memory → heartbeat


def _render_layer_body(header: str, files: dict[str, PersonaFile]) -> str:
    parts = [f"=== LAYER: {header} ==="]
    for ft in _LAYER_ORDER:
        pf = files[ft]
        parts.append(f"--- {ft.upper()} ---")
        parts.append(pf.body.rstrip())
    return "\n\n".join(parts)


def assemble_system_prompt(
    principles: PersonaFile,
    worker_base: dict[str, PersonaFile] | None,
    specific: dict[str, PersonaFile],
) -> str:
    parts: list[str] = [
        "=== LAYER: PRINCIPLES ===",
        principles.body.rstrip(),
    ]
    if worker_base is not None:
        parts.append(_render_layer_body("WORKER_BASE", worker_base))
    parts.append(_render_layer_body("SPECIFIC", specific))
    return "\n\n".join(parts) + "\n"


def load_agent(agents_root: Path, agent_name: str) -> "RoleSpec":
    """Top-level entrypoint: load an agent's layers and return a RoleSpec."""
    # Deferred import to avoid a circular reference at module import time.
    from orgos.spawn.contracts import PermissionTier, RoleSpec

    if agent_name.startswith("_"):
        raise PersonaValidationError(
            f"agent_name must not start with '_' (reserved for layers): {agent_name!r}"
        )

    principles_path = agents_root / "_principles" / "principles.md"
    principles = load_persona_file(principles_path, "principles")

    specific_dir = agents_root / agent_name
    specific = load_layer(specific_dir, FILE_TYPES)
    soul_fm = cast(SoulFrontmatter, specific["soul"].frontmatter)

    worker_base: dict[str, PersonaFile] | None = None
    if soul_fm.is_worker:
        worker_base = load_layer(agents_root / "_worker_base", FILE_TYPES)

    system_prompt = assemble_system_prompt(principles, worker_base, specific)

    return RoleSpec(
        name=soul_fm.agent_name,
        description=soul_fm.description,
        tier=PermissionTier(soul_fm.tier),
        system_prompt=system_prompt,
        model=soul_fm.model,
        max_iter=soul_fm.max_iter,
        success_criteria=list(soul_fm.success_criteria),
    )
