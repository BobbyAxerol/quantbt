from __future__ import annotations

import pandas as pd

from quantbt import (
    BacktestResultV2,
    DcaGridSpec,
    NautilusExecutionDepthConfig,
    OrderIntent,
    OrderSide,
    OrderType,
    build_dca_grid_order_plan,
    build_nautilus_depth_execution_report,
    build_nautilus_depth_parity_summary,
    simulate_nautilus_order_package_depth,
)


def _idx():
    return pd.date_range("2024-01-01", periods=6, freq="1h", tz="UTC")


def _ohlcv(close, high=None, low=None, volume=100.0):
    idx = _idx()
    close = pd.Series(close, index=idx, dtype=float)
    return pd.DataFrame(
        {
            "open": close,
            "high": pd.Series(high if high is not None else close, index=idx, dtype=float),
            "low": pd.Series(low if low is not None else close, index=idx, dtype=float),
            "close": close,
            "volume": pd.Series(volume if isinstance(volume, list) else [volume] * len(idx), index=idx, dtype=float),
        },
        index=idx,
    )


def test_phase5_4_dynamic_dca_lifecycle_is_validated_by_preflight_state():
    idx = _idx()
    frame = _ohlcv(
        [100.0, 100.0, 101.0, 100.0, 100.0, 100.0],
        high=[100.0, 101.0, 103.0, 100.0, 100.0, 100.0],
        low=[100.0, 98.5, 94.0, 100.0, 100.0, 100.0],
    )
    spec = DcaGridSpec(
        symbol="BTC",
        entry_timestamp=idx[1],
        exit_timestamp=idx[2],
        side=OrderSide.BUY,
        base_notional=1_000.0,
        safety_notional=1_000.0,
        safety_order_count=2,
        step_pct=0.01,
        step_scale=1.0,
        take_profit_price=102.0,
        stop_loss_price=95.0,
    )
    plan = build_dca_grid_order_plan(spec, close=frame["close"])

    result = simulate_nautilus_order_package_depth(plan.orders, {"BTC": frame})
    report = result.order_report

    assert [order.metadata["leg_role"] for order in result.orders] == ["base", "safety", "take_profit"]
    assert report["status"].tolist() == ["filled", "filled", "rejected", "partial", "canceled"]
    assert report.iloc[2]["reject_reason"] == "limit_not_touched"
    assert report.iloc[4]["reject_reason"] == "oco_sibling_already_filled"
    filled_entry_qty = report.iloc[0]["filled_qty"] + report.iloc[1]["filled_qty"]
    assert result.orders[-1].qty == filled_entry_qty


def test_phase5_4_queue_depth_test_documents_ohlcv_volume_cap_not_l2_book():
    idx = _idx()
    frame = _ohlcv([100.0] * len(idx), volume=[1_000.0] * len(idx))
    order = OrderIntent(
        timestamp=idx[1],
        symbol="BTC",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        qty=100.0,
    )

    result = simulate_nautilus_order_package_depth(
        [order],
        {"BTC": frame},
        NautilusExecutionDepthConfig(
            allow_partial_fills=True,
            max_participation_rate=0.05,
            queue_ahead_qty=10.0,
        ),
    )

    assert result.metadata["depth_model"] == "ohlcv_volume_cap"
    assert result.orders[0].qty == 40.0
    assert result.order_report.iloc[0]["available_qty"] == 40.0


def test_phase5_4_depth_execution_report_passes_on_matching_fill_price_and_qty():
    result = _depth_result(fill_prices=[100.0, 101.0], fill_qty=[1.0, 2.0])

    report = build_nautilus_depth_execution_report(result)
    summary = build_nautilus_depth_parity_summary(result)

    assert report["fill_price_diff"].tolist() == [0.0, 0.0]
    assert report["filled_qty_diff"].tolist() == [0.0, 0.0]
    assert summary["status"] == "pass"
    assert summary["max_abs_fill_price_diff"] == 0.0
    assert summary["max_abs_filled_qty_diff"] == 0.0


def test_phase5_4_depth_execution_report_fails_on_fill_price_or_qty_diff():
    result = _depth_result(fill_prices=[100.5, 101.0], fill_qty=[1.0, 1.5])

    summary = build_nautilus_depth_parity_summary(result, fill_price_tolerance=1e-9, qty_tolerance=1e-9)

    assert summary["status"] == "execution_diff"
    assert summary["passed"] is False
    assert summary["max_abs_fill_price_diff"] == 0.5
    assert summary["max_abs_filled_qty_diff"] == 0.5


def _depth_result(fill_prices, fill_qty):
    idx = _idx()
    depth_report = pd.DataFrame(
        {
            "timestamp": [idx[1], idx[2]],
            "effective_timestamp": [idx[1], idx[2]],
            "symbol": ["BTC", "ETH"],
            "side": ["buy", "sell"],
            "order_type": ["market", "market"],
            "qty": [1.0, 2.0],
            "filled_qty": [1.0, 2.0],
            "fill_price": [100.0, 101.0],
            "status": ["filled", "filled"],
            "reject_reason": ["", ""],
        }
    )
    fills_report = pd.DataFrame(
        {
            "timestamp": [idx[1], idx[2]],
            "symbol": ["BTC", "ETH"],
            "side": ["buy", "sell"],
            "filled_qty": fill_qty,
            "avg_px": fill_prices,
            "fee": [0.0, 0.0],
            "status": ["FILLED", "FILLED"],
        }
    )
    package_order_map = pd.DataFrame(
        {
            "timestamp": [idx[1], idx[2]],
            "symbol": ["BTC", "ETH"],
            "side": ["buy", "sell"],
            "qty": [1.0, 2.0],
        }
    )
    equity = pd.Series(10_000.0, index=idx, name="equity")
    return BacktestResultV2(
        equity=equity,
        returns=pd.Series(0.0, index=idx, name="returns"),
        positions=pd.DataFrame({"Position_BTC": 0.0, "Position_ETH": 0.0}, index=idx),
        closes=pd.DataFrame({"Close_BTC": 100.0, "Close_ETH": 101.0}, index=idx),
        symbols=["BTC", "ETH"],
        initial_capital=10_000.0,
        metadata={
            "backend": "nautilus",
            "engine": "nautilus_package_orders",
            "input_mode": "basket_package",
            "nautilus_depth_enabled": True,
            "nautilus_depth_order_report": depth_report,
            "nautilus_depth_package_report": pd.DataFrame(),
            "package_order_map": package_order_map,
            "fills_report": fills_report,
            "orders_count": 2,
            "fills_count": 2,
            "order_count_before_depth": 2,
            "order_count_after_depth": 2,
        },
    )
