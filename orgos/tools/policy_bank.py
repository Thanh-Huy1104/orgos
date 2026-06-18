"""Policy bank tool — loads the living policy document for compliance review."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

DEFAULT_POLICY_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "policy-bank.yaml"


class _PolicyInput(BaseModel):
    query: str = Field(default="", description="Search term to filter policies (e.g. 'privacy', 'finance', 'security') or empty for all.")
    category: str = Field(default="", description="Filter by category: privacy, finance, legal, ethics, security, communications, governance.")


class PolicyBankTool(BaseTool):
    name: str = "check_policy_bank"
    description: str = (
        "Search the policy bank for applicable laws, regulations, and internal policies. "
        "Use this to check if a proposed action violates any policy. "
        "Returns matching policies with their rules and legal references."
    )
    args_schema: type[BaseModel] = _PolicyInput
    tool_category: str = "read"

    policy_path: str = Field(default=str(DEFAULT_POLICY_PATH), exclude=True)

    def _run(self, query: str = "", category: str = "") -> str:
        try:
            data = yaml.safe_load(Path(self.policy_path).read_text())
            policies = data.get("policies", [])
        except Exception:
            return json.dumps({"error": "Policy bank not found"})

        results = []
        for p in policies:
            pid = p.get("id", "")
            title = p.get("title", "")
            cats = p.get("categories", []) or [p.get("category", "")]
            cat = cats[0] if cats else ""
            rule = p.get("rule", "")

            if category and category.lower() not in [c.lower() for c in cats]:
                continue
            if query:
                search_in = f"{title} {' '.join(cats)} {rule}".lower()
                if query.lower() not in search_in:
                    continue

            results.append({
                "id": pid,
                "title": title,
                "categories": cats,
                "severity": p.get("severity", "medium"),
                "rule": rule[:500],
                "references": p.get("references", []),
            })

        return json.dumps(results[:5], indent=2)  # top 5 to avoid overwhelming


def create_policy_bank_tool(path: str | None = None) -> PolicyBankTool:
    """Create a PolicyBankTool pointing at the policy bank YAML."""
    return PolicyBankTool(policy_path=path or str(DEFAULT_POLICY_PATH))
