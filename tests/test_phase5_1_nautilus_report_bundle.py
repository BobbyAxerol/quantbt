from __future__ import annotations

import types

import pandas as pd

from quantbt import BacktestResultV2, export_nautilus_report_bundle
from quantbt.reporting.nautilus_bundle import (
    build_nautilus_trade_log,
    format_nautilus_event_log,
    _resampled_returns_for_quantstats,
)


def _synthetic_result():
    idx = pd.date_range("2024-01-01", periods=8, freq="12h", tz="UTC")
    equity = pd.Series([10_000, 10_050, 10_025, 10_120, 10_200, 10_180, 10_260, 10_300], index=idx, dtype=float)
    returns = equity.pct_change().fillna(0.0)
    positions = pd.DataFrame({"Position_BTCUSDT-PERP.BINANCE": [0, 1, 1, 0, 0, -1, -1, 0]}, index=idx)
    closes = pd.DataFrame({"Close_BTCUSDT-PERP.BINANCE": [100, 101, 102, 103, 104, 103, 102, 101]}, index=idx)
    account = pd.DataFrame({"total": [f"{v} USDT" for v in equity.iloc[[0, 3, 7]].tolist()]}, index=idx[[0, 3, 7]])
    fills = pd.DataFrame(
        {
            "instrument_id": ["BTCUSDT-PERP.BINANCE", "BTCUSDT-PERP.BINANCE", "BTCUSDT-PERP.BINANCE"],
            "side": ["BUY", "SELL", "SELL"],
            "filled_qty": [1.0, 1.0, 1.0],
            "avg_px": [101.0, 103.0, 103.0],
            "commissions": ["0.10 USDT", "0.10 USDT", "0.12 USDT"],
            "client_order_id": ["o1", "o2", "o3"],
            "ts_last": [idx[1], idx[3], idx[5]],
        }
    )
    positions_report = pd.DataFrame(
        {
            "instrument_id": ["BTCUSDT-PERP.BINANCE"],
            "entry": ["BUY"],
            "ts_opened": [idx[1]],
            "ts_closed": [idx[3]],
            "avg_px_open": [101.0],
            "avg_px_close": [103.0],
            "quantity": [1.0],
            "realized_pnl": ["1.80 USDT"],
        }
    )
    return BacktestResultV2(
        equity=equity,
        returns=returns,
        positions=positions,
        closes=closes,
        symbols=["BTCUSDT-PERP.BINANCE"],
        initial_capital=10_000.0,
        leverage=3.0,
        metadata={
            "backend": "nautilus",
            "engine": "NautilusTrader BacktestEngine",
            "instrument_id": "BTCUSDT-PERP.BINANCE",
            "bar_type": "BTCUSDT-PERP.BINANCE-12-HOUR-LAST-EXTERNAL",
            "sizing_mode": "%_equity",
            "trade_notional": 0.5,
            "orders_count": 3,
            "fills_count": 3,
            "positions_count": 1,
            "account_final_equity": 10_300.0,
            "reconstructed_final_equity": 10_300.0,
            "account_reconstructed_diff": 0.0,
            "account_report": account,
            "orders_report": fills.copy(),
            "fills_report": fills,
            "positions_report": positions_report,
        },
    )


def test_export_nautilus_report_bundle_creates_audit_files(tmp_path, monkeypatch):
    result = _synthetic_result()

    def fake_html(returns, benchmark=None, output=None, title=None):
        assert not returns.empty
        assert output is not None
        with open(output, "w", encoding="utf-8") as handle:
            handle.write("<html>fake quantstats</html>")

    monkeypatch.setitem(__import__("sys").modules, "quantstats", types.SimpleNamespace(reports=types.SimpleNamespace(html=fake_html)))

    report_dir = export_nautilus_report_bundle(
        result=result,
        output_dir=tmp_path,
        strategy_id="alpha-test",
        config={"timeframe": "12h"},
        make_quantstats=True,
        print_fills=False,
        fill_log_limit=2,
    )

    expected = {
        "equity_curve.csv",
        "returns.csv",
        "account_report.csv",
        "orders_report.csv",
        "fills_report.csv",
        "positions_report.csv",
        "trade_log.csv",
        "fill_log.txt",
        "metrics_summary.json",
        "run_manifest.json",
        "config.json",
        "quantstats_daily.html",
    }
    assert expected <= {path.name for path in report_dir.iterdir()}

    manifest = pd.read_json(report_dir / "run_manifest.json", typ="series")
    assert manifest["backend"] == "nautilus"
    assert manifest["execution_model"] == "event-driven bar execution"
    assert manifest["orders_count"] == 3
    assert manifest["fills_count"] == 3
    assert manifest["positions_count"] == 1
    assert manifest["account_reconstructed_diff"] == 0

    trade_log = pd.read_csv(report_dir / "trade_log.csv")
    assert list(trade_log.columns)[:5] == ["strategy_id", "symbol", "exchange", "instrument_id", "position_type"]
    assert trade_log.loc[0, "realized_pnl"] == 1.8

    fill_log = (report_dir / "fill_log.txt").read_text(encoding="utf-8").strip().splitlines()
    assert len(fill_log) == 2
    assert "FILL BUY" in fill_log[0]
    assert "BTCUSDT-PERP.BINANCE" in fill_log[0]


def test_export_nautilus_report_bundle_handles_empty_raw_reports(tmp_path):
    idx = pd.date_range("2024-01-01", periods=3, freq="1D", tz="UTC")
    equity = pd.Series([10_000.0, 10_010.0, 10_005.0], index=idx)
    result = BacktestResultV2(
        equity=equity,
        returns=equity.pct_change().fillna(0.0),
        positions=pd.DataFrame({"Position_BTC": 0.0}, index=idx),
        closes=pd.DataFrame({"Close_BTC": [1.0, 1.1, 1.0]}, index=idx),
        symbols=["BTC"],
        initial_capital=10_000.0,
        metadata={"backend": "nautilus"},
    )

    report_dir = export_nautilus_report_bundle(result, tmp_path, "empty", make_quantstats=False)

    assert (report_dir / "account_report.csv").exists()
    assert (report_dir / "trade_log.csv").exists()
    assert pd.read_csv(report_dir / "trade_log.csv").empty


def test_trade_log_parses_nautilus_money_strings_and_skips_open_positions():
    idx = pd.date_range("2024-01-01", periods=3, freq="1h", tz="UTC")
    positions = pd.DataFrame(
        {
            "instrument_id": ["ETHUSDT-PERP.BINANCE", "ETHUSDT-PERP.BINANCE"],
            "entry": ["SELL", "BUY"],
            "ts_opened": [idx[0], idx[1]],
            "ts_closed": [idx[1], pd.NaT],
            "avg_px_open": [2000.0, 2010.0],
            "avg_px_close": [1990.0, None],
            "quantity": [0.5, 0.25],
            "realized_pnl": ["[5.0 USDT]", "0 USDT"],
        }
    )

    trade_log = build_nautilus_trade_log(positions, pd.DataFrame(), strategy_id="arb")

    assert len(trade_log) == 1
    assert trade_log.loc[0, "position_type"] == "SHORT"
    assert trade_log.loc[0, "realized_pnl"] == 5.0
    assert trade_log.loc[0, "return_pct"] > 0.0


def test_fill_log_modes_and_limit_are_stable():
    result = _synthetic_result()
    fills = result.metadata["fills_report"]

    fill_lines = format_nautilus_event_log(fills_report=fills, mode="fills_only", limit=1)
    bars_lines = format_nautilus_event_log(positions=result.positions, mode="bars_debug", limit=2)

    assert len(fill_lines) == 1
    assert fill_lines[0].startswith("2024-01-01")
    assert len(bars_lines) == 2
    assert "POSITION" in bars_lines[0]


def test_quantstats_returns_are_daily_resampled_from_intraday_equity():
    result = _synthetic_result()

    daily = _resampled_returns_for_quantstats(result.equity, frequency="1D")

    assert len(daily) == 3
    assert daily.index.freq is None or str(daily.index.freq).startswith("<Day")
