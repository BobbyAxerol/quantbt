from __future__ import annotations

import numpy as np
import pandas as pd

from quantbt import BacktestEngine, MultiSymbolPortfolio
from quantbt.core.preprocessor import make_funding_mask
from quantbt.sizing.modes import scale_signal_notional


def test_funding_mask_fires_once_per_8h_window_for_intrahour_bars():
    idx = pd.date_range("2024-01-01 07:58", periods=130, freq="1min", tz="UTC")

    mask = make_funding_mask(idx)
    fired = idx[mask]

    assert list(fired) == [pd.Timestamp("2024-01-01 08:00", tz="UTC")]


def test_signal_notional_freezes_units_until_signal_changes():
    idx = pd.date_range("2024-01-01", periods=5, freq="1D", tz="UTC")
    signal = pd.Series([0.0, 1.0, 1.0, 0.5, 0.5], index=idx)
    close = pd.Series([100.0, 100.0, 110.0, 120.0, 80.0], index=idx)

    units = scale_signal_notional(signal, close, alloc=1_000.0)

    expected = pd.Series([0.0, 10.0, 10.0, 1_000.0 / 120.0 * 0.5, 1_000.0 / 120.0 * 0.5], index=idx)
    np.testing.assert_allclose(units.values, expected.values)


def test_multisymbol_portfolio_leverage_gates_buying_power_not_alloc_size():
    idx = pd.date_range("2024-01-01", periods=3, freq="1D", tz="UTC")
    pos = pd.Series([0.0, 1.0, 1.0], index=idx)
    close = pd.Series([100.0, 100.0, 110.0], index=idx)
    common_kwargs = dict(
        positions={"BTC": pos},
        closes={"BTC": close},
        highs={"BTC": close},
        lows={"BTC": close},
        datetime_index=idx,
        mode="longshort",
        fee_rate=0.0,
        alloc_per_trade=50_000.0,
        initial_capital=10_000.0,
        asset_type="crypto",
        use_funding=False,
    )

    accepted = MultiSymbolPortfolio(leverage=10.0, **common_kwargs)
    rejected = MultiSymbolPortfolio(leverage=1.0, **common_kwargs)

    assert accepted.result.metadata["initial_buying_power"] == 100_000.0
    assert accepted.result.positions["Position_BTC"].iloc[1] == 500.0
    assert accepted.result.equity.iloc[2] == 15_000.0

    assert rejected.result.metadata["initial_buying_power"] == 10_000.0
    assert rejected.result.positions["Position_BTC"].iloc[1] == 0.0
    assert rejected.result.equity.iloc[2] == 10_000.0


def test_multisymbol_portfolio_default_signal_notional_freezes_units_until_signal_changes():
    idx = pd.date_range("2024-01-01", periods=3, freq="1D", tz="UTC")
    pos = pd.Series([0.0, 1.0, 1.0], index=idx)
    close = pd.Series([100.0, 100.0, 200.0], index=idx)

    msp = MultiSymbolPortfolio(
        positions={"BTC": pos},
        closes={"BTC": close},
        highs={"BTC": close},
        lows={"BTC": close},
        datetime_index=idx,
        mode="longshort",
        fee_rate=0.0,
        alloc_per_trade=1_000.0,
        initial_capital=10_000.0,
        leverage=10.0,
        asset_type="crypto",
        use_funding=False,
    )

    assert msp.hedge_type == "signal_notional"
    assert msp.result.positions["Position_BTC"].iloc[1] == 10.0
    assert msp.result.positions["Position_BTC"].iloc[2] == 10.0
    assert msp.result.equity.iloc[2] == 11_000.0


def test_multisymbol_portfolio_market_neutral_scales_by_notional_not_units():
    idx = pd.date_range("2024-01-01", periods=2, freq="1D", tz="UTC")
    positions = {
        "BTC": pd.Series([0.0, 1.0], index=idx),
        "ETH": pd.Series([0.0, -1.0], index=idx),
    }
    closes = {
        "BTC": pd.Series([100.0, 100.0], index=idx),
        "ETH": pd.Series([10.0, 10.0], index=idx),
    }

    msp = MultiSymbolPortfolio(
        positions=positions,
        closes=closes,
        highs=closes,
        lows=closes,
        datetime_index=idx,
        mode="market_neutral",
        fee_rate=0.0,
        alloc_per_trade={"BTC": 1_000.0, "ETH": 2_000.0},
        initial_capital=100_000.0,
        leverage=5.0,
        asset_type="crypto",
        use_funding=False,
    )

    btc_units = msp.result.positions["Position_BTC"].iloc[1]
    eth_units = msp.result.positions["Position_ETH"].iloc[1]
    btc_notional = abs(btc_units * closes["BTC"].iloc[1])
    eth_notional = abs(eth_units * closes["ETH"].iloc[1])

    assert btc_notional == eth_notional
    assert btc_notional == 1_500.0


def test_dca_ladder_fills_safety_order_at_grid_trigger_price():
    idx = pd.date_range("2024-01-01", periods=3, freq="1D", tz="UTC")
    signal = pd.Series([0.0, 2.0, 2.0], index=idx)
    close = pd.Series([100.0, 100.0, 100.0], index=idx)
    high = pd.Series([100.0, 100.0, 101.0], index=idx)
    low = pd.Series([100.0, 100.0, 98.5], index=idx)

    bt = BacktestEngine(
        Datetime=idx,
        Position=signal,
        Close=close,
        High=high,
        Low=low,
        hedge_type="dca_ladder",
        initial_capital=10_000.0,
        leverage=10.0,
        fee=0.0,
        slippage=0.0,
        use_funding_rate=False,
        dca_base_notional=1_000.0,
        dca_safety_notional=1_000.0,
        dca_step_pct=0.01,
        dca_step_scale=1.0,
        dca_volume_scale=1.0,
        dca_max_safety_orders=1,
        dca_take_profit_pct=0.0,
    )

    actual_level = bt.result.metadata["dca_actual_level"]["Level_DEFAULT"]

    assert actual_level.iloc[1] == 1.0
    assert actual_level.iloc[2] == 2.0
    np.testing.assert_allclose(
        bt.result.positions["Position_DEFAULT"].iloc[2],
        1_000.0 / 100.0 + 1_000.0 / 99.0,
    )
