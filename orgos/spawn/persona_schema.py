"""Schema for persona markdown files (autonomous scrum team model).

Every persona file starts with YAML frontmatter validated against one of the
models below, followed by a markdown body whose top-level ## sections must
include the entries listed in REQUIRED_SECTIONS for that file type.

Frontmatter is validated strictly (missing fields raise); body sections are
validated warn-only in Plan 1 (missing sections log but do not raise).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PersonaValidationError(ValueError):
    """Raised when a persona file's frontmatter is missing or malformed."""


FILE_TYPES: tuple[str, ...] = ("soul", "brain", "habits", "memory", "heartbeat")


REQUIRED_SECTIONS: dict[str, list[str]] = {
    "principles": [
        "Delivery Philosophy",
        "Universal Identity Beliefs",
        "Universal Habits",
    ],
    "soul": ["Identity", "Values", "Stance", "Optimizes For"],
    "brain": ["Decision Framework", "Domain Knowledge", "Reasoning Patterns"],
    "habits": ["Habits"],
    "memory": [
        "Foundational Principles",
        "Sprint History",
        "Recurring Patterns",
        "Key Decisions",
    ],
    "heartbeat": ["Current Task", "Recent Session Summary", "Next Actions"],
}


class BaseFrontmatter(BaseModel):
    """Common frontmatter across every persona file type."""

    version: str
    layer: Literal["principles", "worker_base", "specific"]


class SoulFrontmatter(BaseFrontmatter):
    """SOUL.md carries all the RoleSpec-shaping metadata for the agent."""

    agent_name: str
    tier: Literal["worker", "validator", "publisher", "orchestrator"]
    description: str = ""
    model: str | None = None
    max_iter: int = 20
    is_worker: bool = False  # True => include Layer 2 worker_base at load time
    success_criteria: list[str] = Field(default_factory=list)


class SimpleFrontmatter(BaseFrontmatter):
    """Frontmatter for brain/habits/memory/heartbeat/principles.

    agent_name is required for Layer 3 (specific) files and optional for
    inherited layers (principles / worker_base).
    """

    agent_name: str | None = None
