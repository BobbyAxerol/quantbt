from __future__ import annotations

import types
import json

import pandas as pd

from quantbt import BacktestResultV2, build_nautilus_pct_equity_diagnostic, export_nautilus_report_bundle
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
            "fee_rate": 0.0005,
            "fee_round_trip": 0.0004,
            "slippage": 0.0002,
            "slippage_bps": 0.0,
            "orders_count": 3,
            "fills_count": 3,
            "positions_count": 1,
            "input_mode": "explicit_orders",
            "order_count_input": 3,
            "account_final_equity": 10_300.0,
            "reconstructed_final_equity": 10_300.0,
            "account_reconstructed_diff": 0.0,
            "account_report": account,
            "orders_report": fills.copy(),
            "fills_report": fills,
            "positions_report": positions_report,
            "run_config": {
                "account": {
                    "initial_capital": 10_000.0,
                    "leverage": 3.0,
                    "maintenance_ratio": 0.005,
                    "margin_mode": "cross",
                    "oms_mode": "netting",
                    "base_currency": "USDT",
                },
                "sizing": {
                    "hedge_type": "%_equity",
                    "alloc_per_trade": 0.5,
                    "contract_size": 1.0,
                    "use_pyramiding": False,
                },
                "fees": {
                    "explicit_fee_rate": 0.0005,
                    "one_way_fee_rate": 0.0005,
                    "round_trip_fee": 0.0004,
                },
                "execution": {
                    "legacy_slippage_rate": 0.0002,
                    "slippage_bps": 0.0,
                    "fill_price_policy": "bar_market",
                    "same_bar_policy": "close",
                    "allow_partial_fill": False,
                    "reject_on_insufficient_margin": True,
                },
                "funding": {"use_funding": False, "funding_rate": 0.0},
                "nautilus": {"timeframe": "12h", "close_positions_on_stop": False},
            },
        },
    )


def test_export_nautilus_report_bundle_creates_audit_files(tmp_path, monkeypatch):
    result = _synthetic_result()

    def fake_html(returns, benchmark=None, output=None, title=None, periods_per_year=None, **kwargs):
        assert not returns.empty
        assert periods_per_year == 365
        assert output is not None
        with open(output, "w", encoding="utf-8") as handle:
            handle.write("<html>fake quantstats</html>")

    monkeypatch.setitem(__import__("sys").modules, "quantstats", types.SimpleNamespace(reports=types.SimpleNamespace(html=fake_html)))

    report_dir = export_nautilus_report_bundle(
        result=result,
        output_dir=tmp_path,
        strategy_id="alpha-test",
        config={"note": "manual annotation"},
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
    assert manifest["input_mode"] == "explicit_orders"
    assert manifest["order_count_input"] == 3
    assert manifest["cancelled_count"] == 0
    assert manifest["rejected_count"] == 0
    assert manifest["account_reconstructed_diff"] == 0

    config = json.loads((report_dir / "config.json").read_text(encoding="utf-8"))
    assert config["schema_version"] == 2
    assert config["effective_account"]["initial_capital"] == 10_000.0
    assert config["effective_account"]["leverage"] == 3.0
    assert config["effective_sizing"]["trade_notional"] == 0.5
    assert config["effective_sizing"]["sizing_mode"] == "%_equity"
    assert config["instrument"]["timeframe"] == "12-HOUR"
    assert config["annotations"]["note"] == "manual annotation"

    trade_log = pd.read_csv(report_dir / "trade_log.csv")
    assert list(trade_log.columns)[:5] == ["strategy_id", "symbol", "exchange", "instrument_id", "position_type"]
    assert trade_log.loc[0, "realized_pnl"] == 1.8

    fill_log = (report_dir / "fill_log.txt").read_text(encoding="utf-8").strip().splitlines()
    assert len(fill_log) == 2
    assert "FILL BUY" in fill_log[0]
    assert "BTCUSDT-PERP.BINANCE" in fill_log[0]


def test_report_bundle_manifest_counts_explicit_order_cancels_and_rejects(tmp_path):
    result = _synthetic_result()
    orders = result.metadata["orders_report"].copy()
    orders.loc[0, "status"] = "CANCELED"
    orders.loc[1, "status"] = "REJECTED"
    result.metadata["orders_report"] = orders
    result.metadata["order_count_input"] = 3
    result.metadata["input_mode"] = "explicit_orders"

    report_dir = export_nautilus_report_bundle(
        result=result,
        output_dir=tmp_path,
        strategy_id="explicit-status",
        make_quantstats=False,
    )

    manifest = json.loads((report_dir / "run_manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((report_dir / "metrics_summary.json").read_text(encoding="utf-8"))
    assert manifest["input_mode"] == "explicit_orders"
    assert manifest["order_count_input"] == 3
    assert manifest["cancelled_count"] == 1
    assert manifest["rejected_count"] == 1
    assert summary["cancelled_count"] == 1
    assert summary["rejected_count"] == 1


def test_config_json_has_single_effective_fee_and_execution_view(tmp_path):
    result = _synthetic_result()

    report_dir = export_nautilus_report_bundle(
        result=result,
        output_dir=tmp_path,
        strategy_id="clean-config",
        make_quantstats=False,
    )

    config = json.loads((report_dir / "config.json").read_text(encoding="utf-8"))
    assert "fee_rate" not in config
    assert "fee_round_trip" not in config
    assert "slippage" not in config
    assert "slippage_bps" not in config
    assert "fees" not in config
    assert "execution" not in config
    assert config["effective_fees"]["requested_fee_rate"] == 0.0005
    assert config["effective_fees"]["requested_fee_convention"] == "one_way"
    assert config["effective_fees"]["legacy_fee_round_trip_ignored"] == 0.0004
    assert config["effective_fees"]["custom_fee_rate_applied_to_nautilus"] is False
    assert config["effective_execution"]["requested_slippage_rate"] == 0.0002
    assert config["effective_execution"]["custom_slippage_applied_to_nautilus"] is False
    assert config["effective_sizing"]["contract_size_note"].startswith("contract_size is a multiplier")
    assert config["effective_sizing"]["quantity_constraints"]["note"].startswith("Use qty_step")


def test_pct_equity_nautilus_diagnostic_flags_non_apples_to_apples_settings():
    result = _synthetic_result()
    idx = result.equity.index
    data = pd.DataFrame({"close": result.closes["Close_BTCUSDT-PERP.BINANCE"]}, index=idx)
    signal = pd.Series([0.0, 1.0, 1.0, 0.0, 0.0, -1.0, -1.0, 0.0], index=idx)

    report = build_nautilus_pct_equity_diagnostic(
        result,
        data=data,
        signal=signal,
        native_fee_round_trip=0.0005,
        native_use_funding=True,
        native_slippage=0.0002,
    )

    assert report["status"] == "diff"
    assert report["checks"]["fee_convention_matches_native"] is False
    assert report["checks"]["custom_fee_rate_applied_to_nautilus"] is False
    assert report["checks"]["funding_matches_native"] is False
    assert report["checks"]["slippage_matches_native"] is False
    assert report["signal"]["effective_transition_count"] == 4
    assert report["orders"]["orders_count"] == 3
    assert report["orders"]["missing_order_events_vs_transitions"] == 1
    assert report["instrument_constraints"]["qty_step"] == "0.001"
    assert "contract_size is a multiplier" in report["instrument_constraints"]["contract_size_note"]


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


def test_quantstats_periods_per_year_defaults_to_crypto_365(tmp_path, monkeypatch):
    result = _synthetic_result()
    captured = {}

    def fake_html(returns, benchmark=None, output=None, title=None, periods_per_year=None, **kwargs):
        captured["periods_per_year"] = periods_per_year
        with open(output, "w", encoding="utf-8") as handle:
            handle.write("<html>fake quantstats</html>")

    monkeypatch.setitem(__import__("sys").modules, "quantstats", types.SimpleNamespace(reports=types.SimpleNamespace(html=fake_html)))

    report_dir = export_nautilus_report_bundle(
        result=result,
        output_dir=tmp_path,
        strategy_id="crypto",
        make_quantstats=True,
    )

    manifest = pd.read_json(report_dir / "run_manifest.json", typ="series")
    assert captured["periods_per_year"] == 365
    assert manifest["quantstats_periods_per_year"] == 365
