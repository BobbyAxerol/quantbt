from __future__ import annotations

import pandas as pd

from quantbt import NativeEventBackend, NativeEventConfig
from quantbt.core.basket import build_frozen_basket_orders
from quantbt.core.schema import AccountConfig, BasketLegSpec, BasketSpec, OrderSide


def _basket():
    return BasketSpec(
        basket_id="PAIR-001",
        legs=(
            BasketLegSpec(symbol="BASE", ratio=1.0),
            BasketLegSpec(symbol="HEDGE", ratio=-0.5),
        ),
        gross_notional=600.0,
    )


def _data():
    idx = pd.date_range("2024-01-01", periods=4, freq="1D", tz="UTC")
    closes = {
        "BASE": pd.Series([10.0, 10.0, 20.0, 20.0], index=idx),
        "HEDGE": pd.Series([100.0, 100.0, 120.0, 120.0], index=idx),
    }
    return idx, closes


def test_frozen_basket_plan_enters_holds_and_exits_exact_units():
    idx, closes = _data()
    signal = pd.Series([0.0, 1.0, 1.0, 0.0], index=idx)

    plan = build_frozen_basket_orders(
        datetime_index=idx,
        basket=_basket(),
        signal=signal,
        closes=closes,
    )

    assert len(plan.orders) == 4
    assert plan.orders[0].symbol == "BASE"
    assert plan.orders[0].side is OrderSide.BUY
    assert plan.orders[0].qty == 10.0
    assert plan.orders[1].symbol == "HEDGE"
    assert plan.orders[1].side is OrderSide.SELL
    assert plan.orders[1].qty == 5.0

    assert plan.target_units.loc[idx[1], "BASE"] == 10.0
    assert plan.target_units.loc[idx[1], "HEDGE"] == -5.0
    assert plan.target_units.loc[idx[2], "BASE"] == 10.0
    assert plan.target_units.loc[idx[2], "HEDGE"] == -5.0
    assert plan.target_units.loc[idx[3], "BASE"] == 0.0
    assert plan.target_units.loc[idx[3], "HEDGE"] == 0.0

    assert plan.orders[2].symbol == "BASE"
    assert plan.orders[2].side is OrderSide.SELL
    assert plan.orders[2].qty == 10.0
    assert plan.orders[3].symbol == "HEDGE"
    assert plan.orders[3].side is OrderSide.BUY
    assert plan.orders[3].qty == 5.0


def test_frozen_basket_ignores_dynamic_ratio_drift_until_signal_change():
    idx, closes = _data()
    signal = pd.Series([0.0, 1.0, 1.0, 0.0], index=idx)
    hedge_ratios = {
        "BASE": pd.Series([1.0, 1.0, 1.0, 1.0], index=idx),
        "HEDGE": pd.Series([-0.5, -0.5, -2.0, -2.0], index=idx),
    }

    plan = build_frozen_basket_orders(
        datetime_index=idx,
        basket=_basket(),
        signal=signal,
        closes=closes,
        hedge_ratios=hedge_ratios,
    )

    assert plan.target_units.loc[idx[1], "HEDGE"] == -5.0
    assert plan.target_units.loc[idx[2], "HEDGE"] == -5.0
    assert len(plan.orders) == 4


def test_native_event_backend_runs_frozen_basket_orders():
    idx, closes = _data()
    signal = pd.Series([0.0, 1.0, 1.0, 0.0], index=idx)
    backend = NativeEventBackend(
        NativeEventConfig(account=AccountConfig(initial_capital=10_000.0, leverage=10.0), use_funding=False)
    )

    result = backend.run_basket(
        datetime_index=idx,
        basket=_basket(),
        signal=signal,
        closes=closes,
        highs=closes,
        lows=closes,
    )

    assert len(result.fills) == 4
    assert result.positions["Position_BASE"].iloc[1] == 10.0
    assert result.positions["Position_HEDGE"].iloc[1] == -5.0
    assert result.positions["Position_BASE"].iloc[2] == 10.0
    assert result.positions["Position_HEDGE"].iloc[2] == -5.0
    assert result.positions["Position_BASE"].iloc[3] == 0.0
    assert result.positions["Position_HEDGE"].iloc[3] == 0.0
    assert result.equity.iloc[3] == 10_000.0
    assert result.metadata["basket_target_units"].loc[idx[2], "HEDGE"] == -5.0
