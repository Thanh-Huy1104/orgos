"""Tests for FDR correction, crypto bars cache, and the crypto scanner (offline)."""

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from orgos.icarus_quant import benjamini_hochberg, scan
from orgos import crypto_data
from orgos.tools import crypto_tool


def _idx(n):
    return pd.date_range("2024-01-01", periods=n, freq="D")  # daily (crypto 24/7)


class TestBenjaminiHochberg:
    def test_all_tiny_pvalues_pass(self):
        cutoff = benjamini_hochberg([1e-6, 1e-5, 1e-4], fdr=0.10)
        assert cutoff >= 1e-4                     # all real → cutoff at the largest

    def test_all_large_pvalues_rejected(self):
        # 100 p-values all ~0.5 → none beats the BH line → cutoff 0 (no discoveries)
        assert benjamini_hochberg([0.5] * 100, fdr=0.10) == 0.0

    def test_controls_false_discoveries(self):
        # 5 genuine signals among 1000 noise p-values: BH keeps the signals,
        # rejects (almost) all noise. A raw p<0.05 would pass ~50 noise pairs.
        rng = np.random.default_rng(0)
        noise = list(rng.uniform(0, 1, 995))
        signals = [1e-8, 1e-7, 1e-6, 1e-5, 1e-4]
        cutoff = benjamini_hochberg(noise + signals, fdr=0.10)
        kept = sum(1 for p in noise + signals if p <= cutoff)
        assert kept < 20                          # vs ~55 at raw p<0.05
        assert all(s <= cutoff for s in signals)  # the real ones survive

    def test_empty(self):
        assert benjamini_hochberg([], fdr=0.10) == 0.0


class TestScanFDR:
    def _panel(self, n=400, seed=0):
        """One durable cointegrated pair (CY/CX) + 6 independent walks."""
        rng = np.random.default_rng(seed)
        x_log = rng.normal(0, 0.02, n).cumsum()
        spread = np.zeros(n)
        for i in range(1, n):
            spread[i] = 0.90 * spread[i - 1] + rng.normal(0, 0.012)
        data = {
            "CY": 100 * np.exp(0.5 * x_log + spread),
            "CX": 80 * np.exp(x_log),
        }
        for k in range(6):
            data[f"N{k}"] = 50 * np.exp(rng.normal(0, 0.02, n).cumsum())
        return pd.DataFrame(data, index=_idx(n))

    def test_fdr_keeps_real_pair(self):
        survivors = scan(self._panel(n=600), fdr=0.10, max_half_life=40.0,
                         max_hurst=0.6, require_stable=False)
        pairs = {s.pair for s in survivors}
        assert any("CY" in p and "CX" in p for p in pairs)

    def test_fdr_rejects_pure_noise_panel(self):
        rng = np.random.default_rng(3)
        # 8 independent random walks → no true cointegration; FDR should keep ~0.
        data = {f"N{k}": 50 * np.exp(rng.normal(0, 0.02, 400).cumsum()) for k in range(8)}
        survivors = scan(pd.DataFrame(data, index=_idx(400)), fdr=0.10,
                         max_half_life=40.0, max_hurst=0.6, require_stable=False)
        assert len(survivors) == 0


class TestCryptoCache:
    def test_upsert_roundtrip(self, tmp_path):
        db = str(tmp_path / "c.db")
        crypto_data.ensure_table(db)
        idx = pd.date_range("2024-01-01", periods=10, freq="D")
        crypto_data._upsert("ETH", pd.Series(range(1, 11), index=idx, dtype=float), "binance", db)
        panel = crypto_data.get_cached_panel(["ETH"], 365, end=dt.date(2024, 1, 11), db_path=db)
        assert list(panel.columns) == ["ETH"] and len(panel) == 10

    def test_incremental_fetches_only_gap(self, tmp_path, monkeypatch):
        db = str(tmp_path / "c.db")
        crypto_data.ensure_table(db)
        last = dt.date(2024, 6, 10)
        monkeypatch.setattr(crypto_data, "cached_max_dates", lambda syms, *a, **k: {"ETH": last})
        calls = {}

        def fake_fetch(symbol, since_ms):
            calls["since_ms"] = since_ms
            return pd.Series([1.0], index=pd.to_datetime(["2024-06-11"]))

        monkeypatch.setattr(crypto_data, "_fetch_ohlcv_closes", fake_fetch)
        monkeypatch.setattr(crypto_data, "_upsert", lambda *a, **k: 1)
        crypto_data.refresh(["ETH"], end=dt.date(2024, 6, 12), db_path=db)
        # since_ms should correspond to the day AFTER last cached (2024-06-11)
        since_date = dt.date.fromtimestamp(calls["since_ms"] / 1000)
        assert since_date >= dt.date(2024, 6, 11)

    def test_fetch_error_recorded(self, tmp_path, monkeypatch):
        db = str(tmp_path / "c.db")
        crypto_data.ensure_table(db)
        monkeypatch.setattr(crypto_data, "cached_max_dates", lambda syms, *a, **k: {})

        def boom(symbol, since_ms):
            raise RuntimeError("exchange down")

        monkeypatch.setattr(crypto_data, "_fetch_ohlcv_closes", boom)
        out = crypto_data.refresh(["ETH"], end=dt.date(2024, 6, 12), db_path=db)
        assert "ETH" in out["errors"]


class TestCryptoScanTool:
    def _panel(self, n=600, seed=1):
        # phi=0.80/sd=0.02 → cointegrated in BOTH full and recent windows
        # (passes the recent-window durability gate), hl~3.4d, hurst~0.08.
        rng = np.random.default_rng(seed)
        x_log = rng.normal(0, 0.02, n).cumsum()
        spread = np.zeros(n)
        for i in range(1, n):
            spread[i] = 0.80 * spread[i - 1] + rng.normal(0, 0.02)
        return pd.DataFrame({
            "ETH": 100 * np.exp(0.5 * x_log + spread),
            "SOL": 80 * np.exp(x_log),
            "BTC": 400 * np.exp(rng.normal(0, 0.01, n).cumsum()),
        }, index=_idx(n))

    def test_factor_excluded_from_results(self, monkeypatch):
        monkeypatch.setattr(crypto_tool, "get_panel", lambda syms, lb, **k: self._panel())
        out = crypto_tool.run_crypto_scan(["ETH", "SOL"], refresh_cache=False)
        assert "BTC" not in out["coins_scanned"]   # BTC is the factor
        assert out["asset_class"] == "crypto"

    def test_finds_durable_pair_with_oos_flag(self, monkeypatch):
        monkeypatch.setattr(crypto_tool, "get_panel", lambda syms, lb, **k: self._panel())
        out = crypto_tool.run_crypto_scan(["ETH", "SOL"], refresh_cache=False)
        assert out["candidates_found"] >= 1
        c = out["candidates"][0]
        # every candidate carries the new durability + confidence fields
        assert "p_recent" in c and "p_oos" in c and "oos_confirmed" in c
        assert c["p_recent"] < 0.05               # regime-current gate held

    def test_hub_pairs_excluded(self, monkeypatch):
        # add a hub coin (FIL) to the panel; it must not appear in coins_scanned.
        def panel(syms, lb, **k):
            p = self._panel()
            p["FIL"] = p["ETH"] * 1.01            # cointegrated-looking hub
            return p
        monkeypatch.setattr(crypto_tool, "get_panel", panel)
        out = crypto_tool.run_crypto_scan(["ETH", "SOL", "FIL"], refresh_cache=False)
        assert "FIL" not in out["coins_scanned"]
        assert "FIL" in out["hubs_excluded"]

    def test_tool_returns_valid_json(self, monkeypatch):
        monkeypatch.setattr(crypto_tool, "get_panel", lambda syms, lb, **k: self._panel())
        import json

        out = json.loads(crypto_tool.CryptoScannerTool()._run("ETH SOL"))
        assert "candidates" in out and out["fdr"] == crypto_tool.CRYPTO_FDR

    def test_empty_panel_errors(self, monkeypatch):
        monkeypatch.setattr(crypto_tool, "get_panel", lambda *a, **k: pd.DataFrame())
        assert "error" in crypto_tool.run_crypto_scan(["ETH"], refresh_cache=False)
