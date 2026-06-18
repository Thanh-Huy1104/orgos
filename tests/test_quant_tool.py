"""Tests for the cointegration scanner skill (offline — panel mocked)."""

import json

import numpy as np
import pandas as pd
import pytest

from orgos.tools import quant_tool
from orgos.tools.quant_tool import (
    CointegrationScannerTool,
    resolve_universe,
    run_scan,
)


def _idx(n):
    return pd.date_range("2022-01-01", periods=n, freq="B")


def _panel_with_one_cointegrated(n=750, seed=0):
    """Panel where CY/CX are DURABLY cointegrated (AR(1) spread, phi=0.90 ≈ 8-day
    half-life, stable across sub-windows), plus an independent name + factor."""
    rng = np.random.default_rng(seed)
    x_log = rng.normal(0, 0.02, n).cumsum()          # log-price random walk
    spread = np.zeros(n)                             # mean-reverting AR(1) spread
    for i in range(1, n):
        spread[i] = 0.90 * spread[i - 1] + rng.normal(0, 0.012)
    y_log = 0.5 * x_log + spread
    x = 80 * np.exp(x_log)
    y = 100 * np.exp(y_log)
    indep = 50 * np.exp(rng.normal(0, 0.02, n).cumsum())
    factor = 400 * np.exp(rng.normal(0, 0.01, n).cumsum())
    return pd.DataFrame(
        {"CY": y, "CX": x, "IND": indep, "SPY": factor}, index=_idx(n)
    )


class TestResolveUniverse:
    def test_custom_ticker_list_space(self):
        tickers, sector = resolve_universe("aaa bbb ccc")
        assert sector == "custom"
        assert tickers == ["AAA", "BBB", "CCC"]

    def test_custom_ticker_list_comma(self):
        tickers, _ = resolve_universe("aaa, bbb,ccc")
        assert tickers == ["AAA", "BBB", "CCC"]


class TestRunScan:
    def test_finds_cointegrated_pair(self, monkeypatch):
        panel = _panel_with_one_cointegrated()
        monkeypatch.setattr(quant_tool, "get_panel", lambda syms, lb, **k: panel)
        out = run_scan("CY CX IND", max_half_life=500.0, refresh_cache=False)
        # The cointegrated pair should appear among candidates.
        pairs = {c["pair"] for c in out["candidates"]}
        assert any("CY" in p and "CX" in p for p in pairs)
        assert out["factor"] == "SPY"

    def test_too_few_tickers_errors(self, monkeypatch):
        monkeypatch.setattr(quant_tool, "get_panel", lambda *a, **k: pd.DataFrame())
        out = run_scan("AAA")  # one ticker
        assert "error" in out

    def test_empty_panel_errors(self, monkeypatch):
        monkeypatch.setattr(quant_tool, "get_panel", lambda *a, **k: pd.DataFrame())
        out = run_scan("AAA BBB", refresh_cache=False)
        assert "error" in out

    def test_factor_popped_from_scan(self, monkeypatch):
        panel = _panel_with_one_cointegrated()
        monkeypatch.setattr(quant_tool, "get_panel", lambda syms, lb, **k: panel)
        out = run_scan("CY CX IND", max_half_life=500.0, refresh_cache=False)
        # SPY is the factor — it must not be scanned as a tradeable leg.
        assert "SPY" not in out["tickers_scanned"]


class TestToolContract:
    def test_tool_returns_valid_json(self, monkeypatch):
        panel = _panel_with_one_cointegrated()
        monkeypatch.setattr(quant_tool, "get_panel", lambda syms, lb, **k: panel)
        tool = CointegrationScannerTool()
        out = tool._run("CY CX IND", max_half_life=500.0)
        parsed = json.loads(out)               # must be valid JSON
        assert "candidates" in parsed

    def test_tool_metadata(self):
        tool = CointegrationScannerTool()
        assert tool.name == "scan_cointegrated_pairs"
        assert tool.tool_category == "compute"

    def test_tool_swallows_errors_as_json(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("provider exploded")

        monkeypatch.setattr(quant_tool, "get_panel", boom)
        out = json.loads(CointegrationScannerTool()._run("CY CX"))
        assert "error" in out                   # never crashes the agent
