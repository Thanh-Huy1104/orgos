"""Tests for the deterministic cointegration rubric grader — it judges from the
scan trail (ground truth), not the synth's prose."""

import orgos.quant.grading as grading
from orgos.quant.grading import grade_cointegration
from orgos.spawn import HandoffEnvelope, SpawnResult


def _result(run_id="run-x"):
    return SpawnResult(
        envelope=HandoffEnvelope(role="quant-synth", status="completed", summary="s"),
        run_id=run_id, token_usage=None, raw_output=None, tasks_output=[],
    )


def _trail(*previews, tool="scan_cointegrated_pairs", ok=True):
    return [{"tool": tool, "ok": ok, "output_preview": p} for p in previews]


class TestCointegrationGrader:
    def test_passes_when_a_pair_survives(self, monkeypatch):
        monkeypatch.setattr(grading, "read_trail",
                            lambda rid: _trail('{\n  "candidates_found": 2,\n  "candidates": []\n}'))
        g = grade_cointegration(_result())
        assert g.passed and "2 durable pair" in g.notes

    def test_fails_when_all_scans_empty(self, monkeypatch):
        monkeypatch.setattr(grading, "read_trail",
                            lambda rid: _trail('{"candidates_found": 0}', '{"candidates_found": 0}'))
        g = grade_cointegration(_result())
        assert not g.passed
        assert "0 durable pairs" in g.failures[0]

    def test_fails_when_no_scan_ran(self, monkeypatch):
        # trail has tool calls, but none are scans (e.g. only news/arxiv)
        monkeypatch.setattr(grading, "read_trail",
                            lambda rid: _trail('{"news": []}', tool="news_catalysts"))
        g = grade_cointegration(_result())
        assert not g.passed
        assert "no cointegration scan ran" in g.failures[0]

    def test_ignores_errored_scan_calls(self, monkeypatch):
        monkeypatch.setattr(grading, "read_trail",
                            lambda rid: _trail('{"error": "boom"}', ok=False))
        g = grade_cointegration(_result())
        assert not g.passed  # the only scan failed → treated as no successful scan

    def test_sums_across_multiple_universes(self, monkeypatch):
        monkeypatch.setattr(grading, "read_trail",
                            lambda rid: _trail('{"candidates_found": 0}', '{"candidates_found": 1}'))
        g = grade_cointegration(_result())
        assert g.passed and "1 durable pair" in g.notes

    def test_registered_under_name(self):
        from orgos.spawn.rubric import GRADERS
        assert "cointegration_gates" in GRADERS


class TestTradeablePnlGrader:
    def test_passes_when_profitable_with_enough_trades_and_folds(self, monkeypatch):
        monkeypatch.setattr(grading, "read_trail", lambda rid: _trail(
            '{"candidates_found":1,"candidates":[{"pair":"A/B","oos_sharpe":1.5,'
            '"n_trades":12,"folds_profitable":3}]}'))
        from orgos.quant.grading import grade_tradeable_pnl
        g = grade_tradeable_pnl(_result())
        assert g.passed and abs(g.score - 0.5) < 1e-9  # 1.5 / 3
        assert "12 trades" in g.notes

    def test_fails_on_small_sample_even_if_sharpe_high(self, monkeypatch):
        # great Sharpe but only 3 trades → the lesson: don't trust it
        monkeypatch.setattr(grading, "read_trail", lambda rid: _trail(
            '{"candidates":[{"oos_sharpe":2.4,"n_trades":3,"folds_profitable":3}]}'))
        from orgos.quant.grading import grade_tradeable_pnl
        g = grade_tradeable_pnl(_result())
        assert not g.passed
        assert "too few to trust" in g.failures[0]

    def test_fails_when_not_robust_across_folds(self, monkeypatch):
        monkeypatch.setattr(grading, "read_trail", lambda rid: _trail(
            '{"candidates":[{"oos_sharpe":1.2,"n_trades":20,"folds_profitable":1}]}'))
        from orgos.quant.grading import grade_tradeable_pnl
        g = grade_tradeable_pnl(_result())
        assert not g.passed
        assert "fold" in g.failures[0]

    def test_fails_when_best_sharpe_below_bar(self, monkeypatch):
        monkeypatch.setattr(grading, "read_trail",
                            lambda rid: _trail('{"candidates":[{"oos_sharpe":0.1}]}'))
        from orgos.quant.grading import grade_tradeable_pnl
        g = grade_tradeable_pnl(_result())
        assert not g.passed
        assert "didn't trade profitably" in g.failures[0]

    def test_fails_when_no_pnl_reported(self, monkeypatch):
        monkeypatch.setattr(grading, "read_trail",
                            lambda rid: _trail('{"candidates_found":1,"candidates":[{"adf_p":0.001}]}'))
        from orgos.quant.grading import grade_tradeable_pnl
        g = grade_tradeable_pnl(_result())
        assert not g.passed
        assert "out-of-sample P&L" in g.failures[0]

    def test_registered(self):
        from orgos.spawn.rubric import GRADERS
        assert "tradeable_pnl" in GRADERS

    def test_score_reflects_best_pvalue(self, monkeypatch):
        # two pairs found; the most significant (lowest adf_p) sets the score.
        # Use the REAL scan field name "adf_p" (not "adf_pvalue").
        preview = '{"candidates_found": 2, "candidates": [' \
                  '{"pair": "A/B", "adf_p": 0.02}, {"pair": "C/D", "adf_p": 0.004}]}'
        monkeypatch.setattr(grading, "read_trail", lambda rid: _trail(preview))
        g = grade_cointegration(_result())
        assert g.passed
        assert abs(g.score - (1.0 - 0.004)) < 1e-9   # 1 - min(adf_p)
        assert "best adf_p=0.0040" in g.notes
