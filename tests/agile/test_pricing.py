"""Tests for §H10 cache-aware pricing."""

from __future__ import annotations

import pytest

from orgos.agile.pricing import (
    cost_usd, cost_usd_cached, estimate_with_cache_rate,
)


class TestLegacyCostUsd:
    def test_deepseek_chat_all_miss(self):
        # 1M input all miss + 1M output = 0.27 + 1.10 = 1.37
        assert cost_usd("deepseek/deepseek-chat", 1_000_000, 1_000_000) == pytest.approx(1.37)

    def test_deepseek_reasoner_all_miss(self):
        # 1M input miss + 1M output = 0.55 + 2.19 = 2.74
        assert cost_usd("deepseek/deepseek-reasoner", 1_000_000, 1_000_000) == pytest.approx(2.74)

    def test_unknown_falls_back(self):
        cost = cost_usd("mistral/nonexistent", 1_000_000, 1_000_000)
        # unknown fallback: 0.50 + 1.50 = 2.00
        assert cost == pytest.approx(2.00)


class TestCostUsdCached:
    def test_all_cache_hit_is_much_cheaper(self):
        chat_hit = cost_usd_cached("deepseek/deepseek-chat", 1_000_000, 0, 0)
        chat_miss = cost_usd_cached("deepseek/deepseek-chat", 0, 1_000_000, 0)
        # hit rate: 0.07 vs 0.27 miss = ~4x cheaper
        assert chat_hit == pytest.approx(0.07)
        assert chat_miss == pytest.approx(0.27)
        assert chat_hit * 3.5 < chat_miss  # significantly cheaper

    def test_reasoner_hit_vs_miss(self):
        hit = cost_usd_cached("deepseek/deepseek-reasoner", 1_000_000, 0, 0)
        miss = cost_usd_cached("deepseek/deepseek-reasoner", 0, 1_000_000, 0)
        assert hit == pytest.approx(0.14)
        assert miss == pytest.approx(0.55)

    def test_split_adds_correctly(self):
        # 900k hit + 100k miss + 500k output — deepseek-chat
        cost = cost_usd_cached("deepseek/deepseek-chat", 900_000, 100_000, 500_000)
        expected = 0.9 * 0.07 + 0.1 * 0.27 + 0.5 * 1.10
        assert cost == pytest.approx(expected)

    def test_zero_tokens_returns_zero(self):
        assert cost_usd_cached("deepseek/deepseek-chat", 0, 0, 0) == 0.0

    def test_handles_none_gracefully(self):
        cost = cost_usd_cached("deepseek/deepseek-chat", None, None, None)
        assert cost == 0.0


class TestEstimateWithCacheRate:
    def test_90_percent_hit_is_realistic(self):
        # Compare 100% miss vs 90% hit assumption for identical tokens
        conservative = cost_usd("deepseek/deepseek-chat", 1_000_000, 500_000)
        realistic = estimate_with_cache_rate(
            "deepseek/deepseek-chat", 1_000_000, 500_000,
            cache_hit_rate=0.90,
        )
        # Realistic should be cheaper; exact ratio depends on prompt:output mix
        assert realistic < conservative
        # For prompt-heavy agent workloads the ratio grows. On this mix
        # (2 prompt : 1 completion) it's ~1.3x cheaper.
        assert conservative / realistic > 1.2

    def test_prompt_heavy_workload_shows_bigger_savings(self):
        # 10:1 prompt-to-completion (typical agentic workload)
        conservative = cost_usd("deepseek/deepseek-chat", 10_000_000, 100_000)
        realistic = estimate_with_cache_rate(
            "deepseek/deepseek-chat", 10_000_000, 100_000,
            cache_hit_rate=0.90,
        )
        # Prompt-dominated → cache savings dominate → ~3x cheaper
        ratio = conservative / realistic
        assert 2.5 < ratio < 4.0, f"expected ~3x savings, got {ratio:.2f}x"

    def test_zero_cache_rate_equals_legacy(self):
        conservative = cost_usd("deepseek/deepseek-chat", 100_000, 50_000)
        no_cache = estimate_with_cache_rate(
            "deepseek/deepseek-chat", 100_000, 50_000, cache_hit_rate=0.0,
        )
        assert no_cache == pytest.approx(conservative)

    def test_100_cache_rate_uses_only_hit_rate(self):
        # 1M input all cache hit + 0 output — deepseek-reasoner
        cost = estimate_with_cache_rate(
            "deepseek/deepseek-reasoner", 1_000_000, 0, cache_hit_rate=1.0,
        )
        # 1M * 0.14 = 0.14
        assert cost == pytest.approx(0.14)
