"""Options pricer — pure math tests (no network, no crewai)."""

import math

from orgos.options.pricer import (
    bs_price,
    bs_greeks,
    implied_vol,
    binomial_price,
    intrinsic_value,
    time_value,
    payoff_at_expiry,
)


# ── Known Black-Scholes values (verified against standard references) ──────────

class TestBSPrice:
    def test_call_atm(self):
        # ATM call: S=K=100, T=1yr, r=5%, sigma=20%
        # Known: ~$10.45
        price = bs_price(100, 100, 1.0, 0.05, 0.20, "call")
        assert 10.0 < price < 11.0

    def test_put_atm(self):
        # By put-call parity: put = call - S + K*exp(-r*T)
        S, K, T, r, sigma = 100, 100, 1.0, 0.05, 0.20
        call = bs_price(S, K, T, r, sigma, "call")
        put = bs_price(S, K, T, r, sigma, "put")
        parity = call - S + K * math.exp(-r * T)
        assert abs(put - parity) < 1e-8

    def test_deep_itm_call_approaches_intrinsic(self):
        # Deep ITM call (S=200, K=100): price ≈ intrinsic (S - K*exp(-rT))
        price = bs_price(200, 100, 1.0, 0.05, 0.20, "call")
        intrinsic = 200 - 100 * math.exp(-0.05)
        assert abs(price - intrinsic) < 2.0

    def test_far_otm_call_near_zero(self):
        # Far OTM call: value approaches 0
        price = bs_price(100, 200, 0.1, 0.05, 0.20, "call")
        assert price < 0.01

    def test_zero_time_call_equals_intrinsic(self):
        # T → 0: call = max(S-K, 0). Use very small T.
        price = bs_price(110, 100, 1e-6, 0.05, 0.20, "call")
        assert abs(price - 10.0) < 0.1

    def test_zero_time_put_otm_near_zero(self):
        price = bs_price(110, 100, 1e-6, 0.05, 0.20, "put")
        assert price < 0.1

    def test_put_call_parity_various(self):
        cases = [
            (100, 100, 0.5, 0.05, 0.25),
            (150, 100, 1.0, 0.03, 0.30),
            (80, 100, 0.25, 0.04, 0.15),
        ]
        for S, K, T, r, sigma in cases:
            call = bs_price(S, K, T, r, sigma, "call")
            put = bs_price(S, K, T, r, sigma, "put")
            parity = call - S + K * math.exp(-r * T)
            assert abs(put - parity) < 1e-6, f"parity failed for S={S},K={K}"

    def test_higher_vol_increases_price(self):
        lo = bs_price(100, 100, 1.0, 0.05, 0.10, "call")
        hi = bs_price(100, 100, 1.0, 0.05, 0.50, "call")
        assert hi > lo

    def test_longer_time_increases_price(self):
        short = bs_price(100, 100, 0.1, 0.05, 0.20, "call")
        long_ = bs_price(100, 100, 2.0, 0.05, 0.20, "call")
        assert long_ > short

    def test_invalid_T_raises(self):
        import pytest
        with pytest.raises(ValueError):
            bs_price(100, 100, 0.0, 0.05, 0.20)

    def test_invalid_sigma_raises(self):
        import pytest
        with pytest.raises(ValueError):
            bs_price(100, 100, 1.0, 0.05, 0.0)


# ── Greeks ────────────────────────────────────────────────────────────────────

class TestBSGreeks:
    def _g(self, **kw):
        defaults = dict(S=100, K=100, T=1.0, r=0.05, sigma=0.20, option_type="call")
        defaults.update(kw)
        return bs_greeks(**defaults)

    def test_returns_all_keys(self):
        g = self._g()
        for k in ("price", "delta", "gamma", "theta", "vega", "rho"):
            assert k in g

    def test_call_delta_between_0_and_1(self):
        g = self._g(option_type="call")
        assert 0 < g["delta"] < 1

    def test_put_delta_between_neg1_and_0(self):
        g = self._g(option_type="put")
        assert -1 < g["delta"] < 0

    def test_atm_call_delta_near_half(self):
        g = self._g()
        assert 0.45 < g["delta"] < 0.65  # ATM delta ≈ 0.5-0.6

    def test_gamma_positive(self):
        # Gamma is always positive (long options gain delta as they move ITM)
        assert self._g(option_type="call")["gamma"] > 0
        assert self._g(option_type="put")["gamma"] > 0

    def test_theta_negative(self):
        # Long options lose value each day (time decay)
        assert self._g(option_type="call")["theta"] < 0
        assert self._g(option_type="put")["theta"] < 0

    def test_vega_positive(self):
        # Higher vol = more expensive options (for long holders)
        assert self._g(option_type="call")["vega"] > 0
        assert self._g(option_type="put")["vega"] > 0

    def test_call_put_same_gamma_and_vega(self):
        c = self._g(option_type="call")
        p = self._g(option_type="put")
        assert abs(c["gamma"] - p["gamma"]) < 1e-8
        assert abs(c["vega"] - p["vega"]) < 1e-8

    def test_deep_itm_call_delta_near_1(self):
        g = bs_greeks(S=200, K=100, T=1.0, r=0.05, sigma=0.20, option_type="call")
        assert g["delta"] > 0.95

    def test_deep_otm_call_delta_near_0(self):
        g = bs_greeks(S=50, K=100, T=1.0, r=0.05, sigma=0.20, option_type="call")
        assert g["delta"] < 0.05

    def test_price_matches_bs_price(self):
        g = self._g()
        direct = bs_price(100, 100, 1.0, 0.05, 0.20, "call")
        assert abs(g["price"] - direct) < 0.001


# ── Implied vol solver ────────────────────────────────────────────────────────

class TestImpliedVol:
    def _roundtrip(self, S, K, T, r, sigma, otype="call"):
        """Price → IV solver → should recover the original sigma."""
        price = bs_price(S, K, T, r, sigma, otype)
        recovered = implied_vol(price, S, K, T, r, otype)
        return recovered

    def test_atm_call_roundtrip(self):
        iv = self._roundtrip(100, 100, 1.0, 0.05, 0.25)
        assert iv is not None
        assert abs(iv - 0.25) < 1e-4

    def test_otm_call_roundtrip(self):
        iv = self._roundtrip(100, 120, 1.0, 0.05, 0.30)
        assert iv is not None
        assert abs(iv - 0.30) < 1e-4

    def test_put_roundtrip(self):
        iv = self._roundtrip(100, 95, 0.5, 0.04, 0.18, "put")
        assert iv is not None
        assert abs(iv - 0.18) < 1e-4

    def test_various_vols(self):
        for sigma in (0.10, 0.20, 0.30, 0.50, 0.80):
            iv = self._roundtrip(100, 100, 1.0, 0.05, sigma)
            assert iv is not None, f"solver failed for sigma={sigma}"
            assert abs(iv - sigma) < 1e-3

    def test_below_intrinsic_returns_none(self):
        # Price below intrinsic → no valid IV
        iv = implied_vol(0.0, 100, 90, 1.0, 0.05, "call")  # price=0 < intrinsic=10
        assert iv is None


# ── Binomial vs Black-Scholes ─────────────────────────────────────────────────

class TestBinomial:
    def test_european_matches_bs(self):
        # European binomial should converge to BS with enough steps
        bs = bs_price(100, 100, 1.0, 0.05, 0.20, "call")
        binom = binomial_price(100, 100, 1.0, 0.05, 0.20, "call", steps=200, american=False)
        assert abs(bs - binom) < 0.05

    def test_american_put_geq_european(self):
        # American put ≥ European put (early exercise has value)
        amer = binomial_price(100, 110, 1.0, 0.05, 0.20, "put", steps=200, american=True)
        euro = binomial_price(100, 110, 1.0, 0.05, 0.20, "put", steps=200, american=False)
        assert amer >= euro - 1e-6  # allow tiny floating point tolerance

    def test_call_above_intrinsic(self):
        binom = binomial_price(100, 90, 1.0, 0.05, 0.20, "call")
        assert binom >= 10.0  # at least intrinsic


# ── Intrinsic and time value ──────────────────────────────────────────────────

class TestIntrinsicTimeValue:
    def test_itm_call_intrinsic(self):
        assert abs(intrinsic_value(110, 100, "call") - 10.0) < 1e-9

    def test_otm_call_zero_intrinsic(self):
        assert intrinsic_value(90, 100, "call") == 0.0

    def test_itm_put_intrinsic(self):
        assert abs(intrinsic_value(90, 100, "put") - 10.0) < 1e-9

    def test_time_value_positive_for_otm(self):
        mkt = bs_price(100, 110, 1.0, 0.05, 0.20, "call")  # OTM call, all time value
        tv = time_value(mkt, 100, 110, "call")
        assert tv > 0
        assert abs(tv - mkt) < 1e-4  # intrinsic = 0, so time value = price


# ── Payoff diagram ────────────────────────────────────────────────────────────

class TestPayoff:
    def test_call_buyer_breakeven(self):
        premium = 5.0
        payoffs = payoff_at_expiry(100, premium, "call", spot_range=(90, 120), n_points=100)
        # Breakeven at K + premium = 105
        breakeven = [p for p in payoffs if abs(p["spot"] - 105) < 1.0]
        assert breakeven
        assert abs(breakeven[0]["pnl"]) < 1.0

    def test_put_buyer_profits_below_strike(self):
        premium = 3.0
        payoffs = payoff_at_expiry(100, premium, "put", spot_range=(80, 120))
        # At spot=80: pnl = (100-80) - 3 = 17
        low = [p for p in payoffs if p["spot"] < 82]
        assert all(p["pnl"] > 0 for p in low)

    def test_correct_number_of_points(self):
        payoffs = payoff_at_expiry(100, 5.0, "call", n_points=25)
        assert len(payoffs) == 25

    def test_max_loss_is_premium(self):
        premium = 4.0
        payoffs = payoff_at_expiry(100, premium, "call", spot_range=(50, 99))
        assert all(abs(p["pnl"] + premium) < 0.01 for p in payoffs)
