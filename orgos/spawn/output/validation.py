"""Per-role structured output validation.

Governance decides *whether* a run succeeded; this module decides whether
the run's *output* is well-formed. A role can register a pydantic model
whose schema the raw LLM output must satisfy before it counts as a
successful handoff.

Registration is process-global (a dict keyed by role name) — consumers who
need per-request schemas should call :func:`validate_output_with` directly
with an explicit model.

The parser is deliberately lenient about the surrounding text (LLMs often
wrap JSON in code fences or add commentary) but strict about the JSON
itself: bad shape → :class:`OutputValidationError`.
"""

from __future__ import annotations

import json
import re
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

TModel = TypeVar("TModel", bound=BaseModel)


class OutputValidationError(ValueError):
    """Raised when an LLM output can't be parsed / validated against its schema.

    ``role_name`` names the role whose output failed; ``raw`` is the
    original output for post-hoc debugging (may be truncated to 4KB).
    ``errors`` is the pydantic error list if a shape mismatch, else empty.
    """

    def __init__(
        self,
        role_name: str,
        raw: str,
        errors: list[dict[str, Any]] | None = None,
        detail: str | None = None,
    ) -> None:
        self.role_name = role_name
        self.raw = (raw[:4096] + "…") if len(raw) > 4096 else raw
        self.errors = errors or []
        msg = f"[{role_name}] output failed validation"
        if detail:
            msg += f": {detail}"
        super().__init__(msg)


_REGISTRY: dict[str, type[BaseModel]] = {}

# Match ```json ... ``` and ``` ... ``` fenced blocks — first capture wins.
_FENCED_JSON = re.compile(
    r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```",
    re.DOTALL | re.IGNORECASE,
)


def register_output_schema(role_name: str, model: type[BaseModel]) -> None:
    """Register ``model`` as the required output shape for ``role_name``.

    Re-registering the same role replaces the previous schema — intentional
    so consumers can hot-swap during dev without a restart.
    """
    _REGISTRY[role_name] = model


def unregister_output_schema(role_name: str) -> None:
    _REGISTRY.pop(role_name, None)


def get_output_schema(role_name: str) -> type[BaseModel] | None:
    return _REGISTRY.get(role_name)


def validate_output(role_name: str, raw: str) -> BaseModel:
    """Validate ``raw`` LLM output against the schema registered for the role.

    If no schema is registered the raw text is returned wrapped in a
    :class:`_PassThrough` — callers can always ``.model_dump()`` on the
    result without checking the type.
    """
    model = _REGISTRY.get(role_name)
    if model is None:
        return _PassThrough(text=raw)
    return validate_output_with(model, raw, role_name=role_name)


def validate_output_with(
    model: type[TModel],
    raw: str,
    *,
    role_name: str = "<ad-hoc>",
    inject: dict[str, Any] | None = None,
) -> TModel:
    """Validate ``raw`` against an explicit ``model``. See :func:`validate_output`.

    ``inject`` supplies default values for keys the parsed object omitted —
    e.g. injecting the known role name so an otherwise-valid handoff isn't
    rejected for missing a field the caller can supply authoritatively.
    Injected values never override what the model actually produced.
    """
    payload = _extract_json(raw)
    if payload is None:
        raise OutputValidationError(role_name, raw, detail="no parseable JSON found")
    if inject and isinstance(payload, dict):
        for key, value in inject.items():
            payload.setdefault(key, value)
    try:
        return model.model_validate(payload)
    except ValidationError as e:
        raise OutputValidationError(
            role_name, raw, errors=e.errors(), detail=f"{len(e.errors())} shape errors"
        ) from e


def _extract_json(text: str) -> Any | None:
    """Best-effort JSON extraction from a possibly-fenced / narrated response.

    Order:
      1. Fenced ```json {..} ``` block.
      2. First balanced object or array in the string.
      3. Full string as JSON.

    Returns ``None`` if nothing parses.
    """
    if not text:
        return None
    stripped = text.strip()

    m = _FENCED_JSON.search(stripped)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Cheapest balanced-brace scan for object or array.
    for opener, closer in [("{", "}"), ("[", "]")]:
        start = stripped.find(opener)
        if start == -1:
            continue
        depth = 0
        for i in range(start, len(stripped)):
            c = stripped[i]
            if c == opener:
                depth += 1
            elif c == closer:
                depth -= 1
                if depth == 0:
                    candidate = stripped[start : i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None


class _PassThrough(BaseModel):
    """Wrapper returned when no schema is registered.

    Lets consumers uniformly call ``.model_dump()`` regardless of whether
    strict validation is on for a given role.
    """

    text: str
