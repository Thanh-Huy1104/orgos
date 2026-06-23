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

class _FakeStatus:
    def __init__(self, status, avg=None):
        self.status = status
        self.avgFillPrice = avg


class _FakeTrade:
    def __init__(self, oid, status="Submitted", avg=None):
        self.order = type("O", (), {"orderId": oid})()
        self.orderStatus = _FakeStatus(status, avg)


class _FakeTicker:
    def __init__(self, bid, ask):
        self.bid, self.ask = bid, ask


class _FakeIB:
    def __init__(self, account="DU1234567", bid=1.40, ask=1.60):
        self._account = account
        self._bid, self._ask = bid, ask
        self.placed = []
        self._trades: list[_FakeTrade] = []

    def managedAccounts(self):
        return [self._account] if self._account else []

    def qualifyContracts(self, *contracts):
        return list(contracts)

    def reqMarketDataType(self, t):
        self.market_data_type = t

    def reqTickers(self, *contracts):
        return [_FakeTicker(self._bid, self._ask) for _ in contracts]

    def placeOrder(self, contract, order):
        self.placed.append((contract, order))
        t = _FakeTrade(oid=1000 + len(self.placed))
        self._trades.append(t)
        return t

    def reqAllOpenOrders(self):
        pass

    def sleep(self, _s):
        pass

    def trades(self):
        return self._trades

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
        # IBKR quote (2.00/2.20 -> mid 2.10) differs from the yfinance liq mid (1.50),
        # so this also proves the limit is priced from IBKR, not yfinance.
        ib = _FakeIB(bid=2.00, ask=2.20)
        out = place_paper_order(_csp(), ib=ib, ledger=ledger)
        assert out["ok"]
        assert out["ib_order_ids"] == [1001]      # one leg placed
        assert len(ib.placed) == 1
        assert ib.placed[0][1].lmtPrice == 2.10   # priced from IBKR mid
        assert out["net_price"] == -2.10          # SELL one leg -> net credit
        assert ledger.count_open_positions() == 1

    def test_falls_back_to_yfinance_mid_when_ibkr_has_no_quote(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ex, "run_liquidity_check", lambda *a, **k: _liq_ok())
        monkeypatch.setattr(ex, "_halted", lambda: False)
        ib = _FakeIB(bid=0, ask=0)  # IBKR returns no usable quote
        out = place_paper_order(_csp(), ib=ib, ledger=_ledger(tmp_path))
        assert ib.placed[0][1].lmtPrice == 1.50   # fell back to the liquidity mid

    def test_reconcile_marks_filled(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ex, "run_liquidity_check", lambda *a, **k: _liq_ok())
        monkeypatch.setattr(ex, "_halted", lambda: False)
        ledger = _ledger(tmp_path)
        ib = _FakeIB()
        place_paper_order(_csp(), ib=ib, ledger=ledger)
        # simulate the broker filling the resting order
        ib._trades[0].orderStatus.status = "Filled"
        ib._trades[0].orderStatus.avgFillPrice = 1.55
        res = ex.reconcile(ib=ib, ledger=ledger)
        assert res["filled_updated"] == 1
        row = ledger.conn.execute(
            "SELECT status, fill_price FROM options_paper_orders").fetchone()
        assert row["status"] == "filled" and row["fill_price"] == 1.55

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


# ── Dedicated options halt ────────────────────────────────────────────────────

class TestOptionsHalt:
    def test_reads_dedicated_options_key(self, monkeypatch):
        import orgos.quant.kill_switch as ks
        monkeypatch.setattr(ks, "options_halt_state", lambda: True)
        assert ex._halted() is True
        monkeypatch.setattr(ks, "options_halt_state", lambda: False)
        assert ex._halted() is False

    def test_fails_open_on_redis_error(self, monkeypatch):
        import orgos.quant.kill_switch as ks

        def boom():
            raise RuntimeError("redis down")
        monkeypatch.setattr(ks, "options_halt_state", boom)
        assert ex._halted() is False  # unreachable Redis is not an options halt


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
