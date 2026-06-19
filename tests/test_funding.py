"""Funding-rate carry analytics — pure math, no network."""

import numpy as np

from orgos.quant.funding import annualize, carry_backtest, scan_funding, summarize_funding


def test_annualize_8h():
    # 0.0001 per 8h × 3/day × 365 = 10.95% APR
    assert abs(annualize(0.0001) - 10.95) < 0.01


class TestSummarize:
    def test_basic(self):
        s = summarize_funding([0.0001, 0.0002, -0.0001, 0.0003])
        assert s["n"] == 4
        assert s["pct_positive"] == 75.0
        assert s["now_apr"] == round(annualize(0.0003), 2)

    def test_empty(self):
        assert summarize_funding([])["now_apr"] is None


class TestCarryBacktest:
    def test_positive_funding_nets_positive(self):
        bt = carry_backtest([0.0001] * 100, cost_bps=0.0)
        assert bt["gross_apr"] > 0 and bt["net_apr"] > 0
        assert bt["pct_positive"] == 100.0
        assert bt["max_dd"] == 0.0  # never drew down

    def test_negative_funding_loses(self):
        bt = carry_backtest([-0.0002] * 100, cost_bps=0.0)
        assert bt["net_apr"] < 0
        assert bt["max_dd"] < 0  # cumulative funding kept falling

    def test_regime_filter_sits_out_negative_stretch(self):
        # first half pays, second half bleeds; a regime filter should skip the bleed
        rates = [0.0003] * 60 + [-0.0003] * 60
        always = carry_backtest(rates, cost_bps=0.0)
        filtered = carry_backtest(rates, cost_bps=0.0, regime_window=8)
        assert filtered["time_in_market"] < 100.0
        assert filtered["net_apr"] > always["net_apr"]  # avoided the negative regime

    def test_costs_reduce_net(self):
        rates = [0.0001] * 100
        cheap = carry_backtest(rates, cost_bps=0.0)
        pricey = carry_backtest(rates, cost_bps=50.0, regime_window=4)
        assert pricey["net_apr"] < cheap["net_apr"]


class TestScanFunding:
    def test_ranks_by_avg_apr_with_fake_exchange(self):
        class FakeEx:
            def milliseconds(self):
                return 1_000_000_000_000
            def fetch_funding_rate_history(self, sym, since=None, limit=None):
                rate = {"AAA/USDT:USDT": 0.0003, "BBB/USDT:USDT": -0.0001}[sym]
                return [{"fundingRate": rate}] * 10
        ranked = scan_funding(["BBB", "AAA"], exchange=FakeEx())
        assert [r["coin"] for r in ranked] == ["AAA", "BBB"]  # higher carry first
        assert ranked[0]["avg_apr"] > ranked[1]["avg_apr"]
