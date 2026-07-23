from __future__ import annotations

import json

import pandas as pd

from quantbt import (
    BacktestResultV2,
    Fill,
    NautilusToleranceProfile,
    OrderIntent,
    OrderSide,
    OrderType,
    TimeInForce,
    build_nautilus_certification_profile,
    write_nautilus_certification_artifacts,
)
from quantbt.benchmarks.run_phase15a_nautilus_certification import make_markdown, run_certification


def test_phase15a_runner_skips_cleanly_without_optional_nautilus(tmp_path):
    report = run_certification(include_nautilus=False, output_dir=tmp_path, rows=24)

    assert report["status"] == "pass"
    assert report["passed_workflows"] == 0
    assert report["skipped_workflows"] == 5
    assert report["failed_workflows"] == 0
    assert {item["workflow"] for item in report["workflows"]} == {
        "pct_equity_signal",
        "explicit_orders",
        "basket_package",
        "portfolio_package",
        "basis_arbitrage_package",
    }
    assert all(item["status"] == "skipped" for item in report["workflows"])

    markdown = make_markdown(report)
    assert "Phase 15A Nautilus Certification Bundles" in markdown
    assert "A skipped workflow is not a pass claim" in markdown


def test_phase15a_tolerance_profile_detects_injected_execution_and_accounting_mismatch(tmp_path):
    native = _synthetic_result(fill_price=100.0, qty=1.0, fee=0.10, final_equity=10_050.0)
    nautilus = _synthetic_result(fill_price=101.0, qty=1.25, fee=0.25, final_equity=10_020.0)

    profile = build_nautilus_certification_profile(
        native,
        nautilus,
        workflow="mismatch_smoke",
        tolerance=NautilusToleranceProfile(
            fill_price_tolerance=0.01,
            fee_tolerance=0.01,
            position_tolerance=0.01,
            equity_tolerance=1.0,
            quantity_tolerance=0.01,
            slippage_tolerance=0.01,
        ),
    )

    assert profile["passed"] is False
    assert profile["status"] == "execution_diff"
    assert profile["checks"]["fill_price_within_tolerance"] is False
    assert profile["checks"]["fee_within_tolerance"] is False
    assert profile["checks"]["equity_within_tolerance"] is False
    assert profile["checks"]["quantity_within_tolerance"] is False

    artifacts = write_nautilus_certification_artifacts(
        native_result=native,
        nautilus_result=nautilus,
        report_dir=tmp_path,
        workflow="mismatch_smoke",
        tolerance=NautilusToleranceProfile(fill_price_tolerance=0.01, quantity_tolerance=0.01),
        known_differences=["Injected mismatch for test coverage."],
    )

    assert artifacts["status"] == "execution_diff"
    assert (tmp_path / "native_vs_nautilus_parity.csv").exists()
    assert (tmp_path / "tolerance_profile.json").exists()
    assert (tmp_path / "known_differences.md").exists()
    assert (tmp_path / "certification_summary.json").exists()
    payload = json.loads((tmp_path / "tolerance_profile.json").read_text(encoding="utf-8"))
    assert payload["workflow"] == "mismatch_smoke"
    assert payload["passed"] is False


def test_phase15a_tolerance_profile_passes_identical_synthetic_results(tmp_path):
    native = _synthetic_result(fill_price=100.0, qty=1.0, fee=0.10, final_equity=10_050.0)
    nautilus = _synthetic_result(fill_price=100.0, qty=1.0, fee=0.10, final_equity=10_050.0)

    artifacts = write_nautilus_certification_artifacts(
        native_result=native,
        nautilus_result=nautilus,
        report_dir=tmp_path,
        workflow="identical_smoke",
    )

    assert artifacts["status"] == "pass"
    assert artifacts["passed"] is True
    profile = json.loads((tmp_path / "tolerance_profile.json").read_text(encoding="utf-8"))
    assert all(profile["checks"].values())


def _synthetic_result(fill_price: float, qty: float, fee: float, final_equity: float) -> BacktestResultV2:
    idx = pd.date_range("2024-01-01", periods=3, freq="1h", tz="UTC")
    equity = pd.Series([10_000.0, 10_000.0, final_equity], index=idx)
    positions = pd.DataFrame({"Position_BTCUSDT-PERP.BINANCE": [0.0, qty, qty]}, index=idx)
    closes = pd.DataFrame({"Close_BTCUSDT-PERP.BINANCE": [99.0, fill_price, fill_price + 1.0]}, index=idx)
    order = OrderIntent(
        timestamp=idx[1],
        symbol="BTCUSDT-PERP.BINANCE",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        qty=qty,
        tif=TimeInForce.IOC,
    )
    fill = Fill(
        timestamp=idx[1],
        symbol="BTCUSDT-PERP.BINANCE",
        side=OrderSide.BUY,
        qty=qty,
        price=fill_price,
        fee=fee,
    )
    fills_report = pd.DataFrame(
        {
            "instrument_id": ["BTCUSDT-PERP.BINANCE"],
            "side": ["BUY"],
            "filled_qty": [qty],
            "avg_px": [fill_price],
            "commissions": [fee],
            "ts_last": [idx[1]],
            "status": ["FILLED"],
        }
    )
    return BacktestResultV2(
        equity=equity,
        returns=equity.pct_change().fillna(0.0),
        positions=positions,
        closes=closes,
        symbols=["BTCUSDT-PERP.BINANCE"],
        initial_capital=10_000.0,
        leverage=2.0,
        orders=(order,),
        fills=(fill,),
        metadata={
            "backend": "nautilus",
            "orders_report": fills_report.copy(),
            "fills_report": fills_report.copy(),
            "orders_count": 1,
            "fills_count": 1,
        },
    )
