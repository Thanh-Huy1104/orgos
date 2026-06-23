"""Tests for the options paper executor: safety guard, risk caps, liquidity gate,
ledger, and the place pipeline — all with a fake IB client (no gateway needed)."""

import pytest

import orgos.quant.options_exec as ex
from orgos.quant.options_exec import (
    OrderLeg, PaperOrderRequest, OrderRejected, check_risk, check_liquidity,
    place_paper_order,
)
from orgos.quant.options_exec_config import (
    RiskLimits, UnsafeExecutionError, assert_paper_safe, is_paper_account,
)
from orgos.quant.options_paper_ledger import OptionsPaperLedger


# ── Fakes ─────────────────────────────────────────────────────────────────────

class _FakeTrade:
    def __init__(self, oid):
        self.order = type("O", (), {"orderId": oid})()


class _FakeIB:
    def __init__(self, account="DU1234567"):
        self._account = account
        self.placed = []

    def managedAccounts(self):
        return [self._account] if self._account else []

    def qualifyContracts(self, *contracts):
        return list(contracts)

    def placeOrder(self, contract, order):
        self.placed.append((contract, order))
        return _FakeTrade(oid=1000 + len(self.placed))

    def fills(self):
        return []

    def disconnect(self):
        pass


def _ledger(tmp_path):
    return OptionsPaperLedger(db_path=tmp_path / "paper.db")


def _csp(strike=180.0, expiry="2026-07-17", max_loss=300.0):
    """A single-leg cash-secured put order request."""
    return PaperOrderRequest(
        ticker="SPY", strategy="cash_secured_put",
        legs=[OrderLeg(right="P", action="SELL", strike=strike, expiry=expiry, qty=1)],
        max_loss_usd=max_loss, run_id="chain-test",
    )


def _liq_ok():
    return {"liquid": True, "spot_sanity_ok": True, "spot": 185.0,
            "legs": [{"type": "put", "requested_strike": 180.0, "mid": 1.50}]}


# ── Safety guard ──────────────────────────────────────────────────────────────

class TestPaperGuard:
    def test_paper_account_detection(self):
        assert is_paper_account("DU1234567")
        assert not is_paper_account("U1234567")
        assert not is_paper_account(None)

    def test_refuses_live_port(self):
        with pytest.raises(UnsafeExecutionError):
            assert_paper_safe(4001)  # live gateway
        with pytest.raises(UnsafeExecutionError):
            assert_paper_safe(7496)  # live TWS

    def test_allows_paper_port(self):
        assert_paper_safe(4002)              # paper gateway, no account yet
        assert_paper_safe(4002, "DU123")     # paper account ok

    def test_refuses_live_account_on_paper_port(self):
        with pytest.raises(UnsafeExecutionError):
            assert_paper_safe(4002, "U999")  # live-looking account


# ── Risk caps ─────────────────────────────────────────────────────────────────

class TestRiskCaps:
    def test_too_many_contracts(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ex, "RISK", RiskLimits(max_contracts_per_order=1))
        req = _csp()
        req.legs[0].qty = 3
        with pytest.raises(OrderRejected, match="contracts"):
            check_risk(req, _ledger(tmp_path))

    def test_defined_risk_over_cap(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ex, "RISK", RiskLimits(max_defined_risk_usd=100))
        with pytest.raises(OrderRejected, match="defined risk"):
            check_risk(_csp(max_loss=500), _ledger(tmp_path))

    def test_max_open_positions(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ex, "RISK", RiskLimits(max_open_positions=0))
        with pytest.raises(OrderRejected, match="open positions"):
            check_risk(_csp(), _ledger(tmp_path))

    def test_daily_order_cap(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ex, "RISK", RiskLimits(max_new_orders_per_day=0))
        with pytest.raises(OrderRejected, match="daily order cap"):
            check_risk(_csp(), _ledger(tmp_path))

    def test_within_limits_ok(self, tmp_path):
        check_risk(_csp(), _ledger(tmp_path))  # no raise


# ── Liquidity gate ────────────────────────────────────────────────────────────

class TestLiquidityGate:
    def test_rejects_stale_spot(self, monkeypatch):
        monkeypatch.setattr(ex, "run_liquidity_check",
                            lambda *a, **k: {"liquid": False, "spot_sanity_ok": False,
                                             "reasons": ["stale"]})
        with pytest.raises(OrderRejected, match="spot-sanity"):
            check_liquidity(_csp())

    def test_rejects_illiquid(self, monkeypatch):
        monkeypatch.setattr(ex, "run_liquidity_check",
                            lambda *a, **k: {"liquid": False, "spot_sanity_ok": True,
                                             "reasons": ["wide spread"]})
        with pytest.raises(OrderRejected, match="not tradeable"):
            check_liquidity(_csp())

    def test_rejects_mixed_expiries(self):
        req = _csp()
        req.legs.append(OrderLeg(right="C", action="BUY", strike=190, expiry="2026-08-21"))
        with pytest.raises(OrderRejected, match="one expiry"):
            check_liquidity(req)

    def test_passes_when_liquid(self, monkeypatch):
        monkeypatch.setattr(ex, "run_liquidity_check", lambda *a, **k: _liq_ok())
        liq = check_liquidity(_csp())
        assert liq["liquid"]


# ── Place pipeline (fake IB) ──────────────────────────────────────────────────

class TestPlacePipeline:
    def test_happy_path_places_and_records(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ex, "run_liquidity_check", lambda *a, **k: _liq_ok())
        monkeypatch.setattr(ex, "_halted", lambda: False)
        ledger = _ledger(tmp_path)
        ib = _FakeIB()
        out = place_paper_order(_csp(), ib=ib, ledger=ledger)
        assert out["ok"]
        assert out["ib_order_ids"] == [1001]      # one leg placed
        assert len(ib.placed) == 1
        # placed at the validated mid 1.50
        assert ib.placed[0][1].lmtPrice == 1.50
        # ledger reflects an open position
        assert ledger.count_open_positions() == 1

    def test_blocked_when_halted(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ex, "_halted", lambda: True)
        with pytest.raises(OrderRejected, match="halt"):
            place_paper_order(_csp(), ib=_FakeIB(), ledger=_ledger(tmp_path))

    def test_blocked_for_live_account(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ex, "run_liquidity_check", lambda *a, **k: _liq_ok())
        monkeypatch.setattr(ex, "_halted", lambda: False)
        with pytest.raises(UnsafeExecutionError):
            place_paper_order(_csp(), ib=_FakeIB(account="U999"),
                              ledger=_ledger(tmp_path))


# ── Ledger ────────────────────────────────────────────────────────────────────

class TestLedger:
    def test_record_open_close_pnl(self, tmp_path):
        led = _ledger(tmp_path)
        oid = led.record_order(ticker="SPY", strategy="csp", legs=[{"x": 1}],
                               limit_price=1.5, run_id="r1")
        pid = led.open_position(order_id=oid, ticker="SPY", strategy="csp",
                                legs=[{"x": 1}], open_price=1.5, run_id="r1")
        assert led.count_open_positions() == 1
        led.close_position(pid, close_price=0.5, realized_pnl=100.0)
        assert led.count_open_positions() == 0
        assert led.all_positions()[0]["realized_pnl"] == 100.0
