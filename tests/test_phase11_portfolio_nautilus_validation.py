from __future__ import annotations

import pandas as pd

from quantbt import BacktestResultV2, build_portfolio_nautilus_validation_report


def test_phase11d_portfolio_nautilus_validation_report_passes_matching_package():
    idx = pd.date_range("2024-01-01", periods=4, freq="1D", tz="UTC")
    target_units = pd.DataFrame({"BTC": [0.0, 1.0, 1.0, 0.0], "ETH": [0.0, -2.0, -2.0, 0.0]}, index=idx)
    positions = pd.DataFrame({"Position_BTC": [0.0, 1.0, 1.0, 0.0], "Position_ETH": [0.0, -2.0, -2.0, 0.0]}, index=idx)
    closes = pd.DataFrame({"Close_BTC": [100.0, 100.0, 101.0, 101.0], "Close_ETH": [50.0, 50.0, 49.0, 49.0]}, index=idx)
    equity = pd.Series([10_000.0, 10_000.0, 10_003.0, 10_003.0], index=idx)
    native = BacktestResultV2(
        equity=equity,
        returns=equity.pct_change().fillna(0.0),
        positions=positions,
        closes=closes,
        symbols=["BTC", "ETH"],
        initial_capital=10_000.0,
        metadata={"backend": "native_portfolio", "target_units_report": target_units},
    )
    nautilus = BacktestResultV2(
        equity=equity.copy(),
        returns=equity.pct_change().fillna(0.0),
        positions=positions.copy(),
        closes=closes.copy(),
        symbols=["BTC", "ETH"],
        initial_capital=10_000.0,
        metadata={
            "backend": "nautilus",
            "engine": "nautilus_portfolio_matrix",
            "input_mode": "portfolio_matrix",
            "portfolio_target_units": target_units.copy(),
            "orders_count": 4,
            "fills_count": 4,
        },
    )

    report = build_portfolio_nautilus_validation_report(native, nautilus)

    assert report["status"] == "pass"
    assert report["passed"] is True
    assert report["expected_order_count"] == 4
    assert report["max_abs_target_units_diff"] == 0.0
    assert report["max_abs_position_diff"] == 0.0
    assert report["final_equity_diff"] == 0.0


def test_phase11d_portfolio_nautilus_validation_report_detects_position_diff():
    idx = pd.date_range("2024-01-01", periods=3, freq="1D", tz="UTC")
    target_units = pd.DataFrame({"BTC": [0.0, 1.0, 1.0]}, index=idx)
    native = BacktestResultV2(
        equity=pd.Series([10_000.0, 10_000.0, 10_010.0], index=idx),
        returns=pd.Series([0.0, 0.0, 0.001], index=idx),
        positions=pd.DataFrame({"Position_BTC": [0.0, 1.0, 1.0]}, index=idx),
        closes=pd.DataFrame({"Close_BTC": [100.0, 100.0, 110.0]}, index=idx),
        symbols=["BTC"],
        initial_capital=10_000.0,
        metadata={"backend": "native_portfolio", "target_units_report": target_units},
    )
    nautilus = BacktestResultV2(
        equity=pd.Series([10_000.0, 10_000.0, 10_010.0], index=idx),
        returns=pd.Series([0.0, 0.0, 0.001], index=idx),
        positions=pd.DataFrame({"Position_BTC": [0.0, 0.0, 0.0]}, index=idx),
        closes=pd.DataFrame({"Close_BTC": [100.0, 100.0, 110.0]}, index=idx),
        symbols=["BTC"],
        initial_capital=10_000.0,
        metadata={
            "backend": "nautilus",
            "engine": "nautilus_portfolio_matrix",
            "input_mode": "portfolio_matrix",
            "portfolio_target_units": target_units,
            "orders_count": 1,
            "fills_count": 1,
        },
    )

    report = build_portfolio_nautilus_validation_report(native, nautilus)

    assert report["passed"] is False
    assert report["checks"]["positions_within_tolerance"] is False
    assert report["max_abs_position_diff"] == 1.0
