"""Tests for orgos.legal — policy rules, pre-filter, LLM review.

No LLM key required — tests the deterministic pre-filter and policy rendering.
"""

import pytest

from orgos import (
    DEFAULT_POLICY,
    LegalPolicy,
    LegalPolicyRule,
    HandoffEnvelope,
    legal_review,
)
from orgos.legal import LegalVerdict


@pytest.fixture
def policy():
    return DEFAULT_POLICY


# ── Pre-filter (deterministic) ────────────────────────────────────────────


class TestPreFilter:
    def test_benign_passes(self, policy):
        env = HandoffEnvelope(
            role="scanner", status="completed",
            summary="Found 3 cointegrated pairs. All verified.",
            success_criteria_met=True,
        )
        result = legal_review(env, policy=policy)
        assert result["approved"] is True
        assert result["verdict"] == "approved"

    def test_destructive_denied(self, policy):
        env = HandoffEnvelope(
            role="worker", status="completed",
            summary="Running rm -rf /tmp/data to clean up.",
            success_criteria_met=True,
        )
        result = legal_review(env, policy=policy)
        assert result["approved"] is False
        assert result["verdict"] == "denied"
        assert any("LGL-002" in d for d in result["denials"])

    def test_password_denied(self, policy):
        env = HandoffEnvelope(
            role="worker", status="completed",
            summary="Reset password for user account.",
            success_criteria_met=True,
        )
        result = legal_review(env, policy=policy)
        assert result["approved"] is False
        assert result["verdict"] == "denied"

    def test_financial_passes_prefilter(self, policy):
        """Prefilter only catches hard-denies. Financial actions pass pre-filter
        but will be caught by the LLM review (requires_owner)."""
        env = HandoffEnvelope(
            role="trader", status="completed",
            summary="Execute trade: buy 100 shares at market.",
            success_criteria_met=True,
        )
        result = legal_review(env, policy=policy)
        assert result["approved"] is True  # pre-filter passes — LLM will catch it

    def test_publish_passes_prefilter(self, policy):
        """Publish actions pass pre-filter — LLM review catches them."""
        env = HandoffEnvelope(
            role="publisher", status="completed",
            summary="Publishing trade signals to production API.",
            success_criteria_met=True,
        )
        result = legal_review(env, policy=policy)
        assert result["approved"] is True  # pre-filter passes


# ── Policy rendering ───────────────────────────────────────────────────────


class TestPolicyRendering:
    def test_to_prompt_block_includes_rules(self, policy):
        block = policy.to_prompt_block()
        assert "LGL-001" in block
        assert "LGL-002" in block
        assert "LGL-008" in block
        assert "Your task" in block
        assert "Policy" in block

    def test_to_prompt_block_has_verdict_icons(self, policy):
        block = policy.to_prompt_block()
        assert "🚫" in block or "BLOCK" in block  # deny rules
        assert "OWNER" in block  # require_owner rules

    def test_custom_policy_renders(self):
        policy = LegalPolicy(
            name="Custom",
            rules=[
                LegalPolicyRule(
                    id="CUST-1",
                    title="No cats",
                    rule="Cats are not permitted in the workspace.",
                    verdict="deny",
                    examples="Bringing a cat to the office.",
                ),
            ],
        )
        block = policy.to_prompt_block()
        assert "CUST-1" in block
        assert "No cats" in block
        assert "Cats are not permitted" in block


# ── Custom policies ────────────────────────────────────────────────────────


class TestCustomPolicy:
    def test_custom_deny_rule(self):
        policy = LegalPolicy(rules=[
            LegalPolicyRule(
                id="CUST-1",
                title="No dogs",
                rule="Dogs are prohibited in the workspace.",
                verdict="deny",
                keywords="dog, dogs, canine, puppy",
            ),
        ])
        env = HandoffEnvelope(
            role="test", status="completed",
            summary="Walk the dog in the park.",
            success_criteria_met=True,
        )
        result = legal_review(env, policy=policy)
        assert result["approved"] is False
        assert "CUST-1" in result["denials"][0]

    def test_custom_rule_no_match_passes(self):
        policy = LegalPolicy(rules=[
            LegalPolicyRule(
                id="CUST-1",
                title="No dogs",
                rule="Dogs are prohibited.",
                verdict="deny",
                keywords="dog, dogs, canine",
            ),
        ])
        env = HandoffEnvelope(
            role="test", status="completed",
            summary="Pet the cat.",
            success_criteria_met=True,
        )
        result = legal_review(env, policy=policy)
        assert result["approved"] is True


# ── LegalVerdict model ─────────────────────────────────────────────────────


class TestLegalVerdict:
    def test_default_verdict(self):
        v = LegalVerdict()
        assert v.verdict == "approved"
        assert v.requires_owner is False
        assert v.risk_level == "low"

    def test_denied_verdict(self):
        v = LegalVerdict(
            verdict="denied",
            policy_ids=["LGL-002"],
            reasoning="Destructive operation detected.",
            risk_level="critical",
        )
        assert v.verdict == "denied"
        assert len(v.policy_ids) == 1

    def test_needs_changes(self):
        v = LegalVerdict(
            verdict="needs_changes",
            required_changes="Add owner approval step before executing.",
            risk_level="high",
        )
        assert v.verdict == "needs_changes"
        assert "owner approval" in v.required_changes


# ── Pre-filter edge cases ──────────────────────────────────────────────────


class TestPreFilterEdgeCases:
    def test_empty_envelope(self, policy):
        env = HandoffEnvelope(
            role="test", status="completed",
            summary="", success_criteria_met=True,
        )
        result = legal_review(env, policy=policy)
        assert result["approved"] is True

    def test_verdict_never_approved_when_denied(self, policy):
        """If pre-filter denies, verdict must never be 'approved'."""
        env = HandoffEnvelope(
            role="worker", status="completed",
            summary="rm -rf /everything",
            success_criteria_met=True,
        )
        result = legal_review(env, policy=policy)
        assert result["verdict"] != "approved"
        assert result["approved"] is False
