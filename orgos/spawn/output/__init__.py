"""orgos.spawn.output — per-role structured output validation.

Register a pydantic model against a role name to guarantee the model's
output conforms to a schema before the audit trail records it as
successful. Failures raise :class:`OutputValidationError` so the outer
governance layer can retry or mark the run failed.

Usage:

    from pydantic import BaseModel
    from orgos.spawn.output import register_output_schema, validate_output

    class ReviewFindings(BaseModel):
        summary: str
        severity: Literal["low", "medium", "high"]
        blocking_issues: list[str]

    register_output_schema("code-reviewer", ReviewFindings)

    validated = validate_output("code-reviewer", raw_llm_output)
"""

from .validation import (
    OutputValidationError,
    get_output_schema,
    register_output_schema,
    unregister_output_schema,
    validate_output,
)

__all__ = [
    "OutputValidationError",
    "get_output_schema",
    "register_output_schema",
    "unregister_output_schema",
    "validate_output",
]
