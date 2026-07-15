"""Typed HandoffEnvelope subclasses for the seven sprint phases.

Each subclass inherits the strict HandoffEnvelope schema and adds a
`parsed_payload()` helper that JSON-decodes the `payload` field. We keep
payload as a JSON string (not a nested model) to stay compatible with
OpenAI strict structured outputs — the parent enforces this.
"""

from __future__ import annotations

import json
from typing import Any

from orgos.spawn.contracts import HandoffEnvelope


class _PayloadMixin:
    payload: str

    def parsed_payload(self) -> dict[str, Any]:
        if not self.payload:
            return {}
        try:
            return json.loads(self.payload)
        except json.JSONDecodeError:
            return {}


class BacklogEnvelope(_PayloadMixin, HandoffEnvelope):
    """Phase [00] Intake. payload.candidates: list[{issue_id, title, size, risk}]."""


class BriefEnvelope(_PayloadMixin, HandoffEnvelope):
    """Phase [01] PM brief. payload: {picked_issue_id, task_brief_json,
    touched_files_allowlist, acceptance_tests}."""


class EngineeringEnvelope(_PayloadMixin, HandoffEnvelope):
    """Phase [02] Engineer chain. payload: {diff, commit_sha, files_touched,
    test_command, test_output, test_passed}."""


class GradeEnvelope(_PayloadMixin, HandoffEnvelope):
    """Phase [03] QA gate. payload: {criteria: [{name, passed, reason}],
    rubric_score: float in [0,1]}."""


class ReleaseEnvelope(_PayloadMixin, HandoffEnvelope):
    """Phase [04] Release. payload: {pr_url, branch, mock_mode}."""


class RetroEnvelope(_PayloadMixin, HandoffEnvelope):
    """Phase [05] Retro. payload: {retro_markdown, candidate_heuristics,
    role_attribution}."""


class DoraEnvelope(_PayloadMixin, HandoffEnvelope):
    """Phase [06] DORA snapshot. payload: {deploy_freq, lead_time_p50, cfr,
    mttr_p50, tier}."""


class QualityEnvelope(_PayloadMixin, HandoffEnvelope):
    """Phase [07] Quality evaluation. payload: {overall: float 0-1,
    deterministic: {criterion: bool}, llm_scores: {ac_compliance: float,
    code_quality: float, test_relevance: float}, llm_summary: str}."""


class RefinementEnvelope(_PayloadMixin, HandoffEnvelope):
    """Phase [07] Refinement. payload: {story_id, role_signoffs: [{role, agent_id,
    concern, approved}], size_ok, ready_for_grooming}."""


class ReadyEnvelope(_PayloadMixin, HandoffEnvelope):
    """Phase [08] READY gate. payload: {story_id, size_caps_pass, all_roles_signed,
    rank_in_backlog, ready_for_pull}."""


class PullEnvelope(_PayloadMixin, HandoffEnvelope):
    """Phase [09] Pull. payload: {story_id, captain_agent_id, wiki_consulted,
    parent_epic_verified}."""
