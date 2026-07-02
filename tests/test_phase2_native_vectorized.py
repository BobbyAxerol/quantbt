from __future__ import annotations

import pandas as pd

from quantbt import NativeVectorizedBackend, NativeVectorizedConfig
from quantbt.core.schema import AccountConfig, ExecutionConfig
from quantbt.core.vectorized import REJECT_INSUFFICIENT_MARGIN


def _backend(initial_capital=10_000.0, leverage=10.0, fee_rate=0.0, slippage_bps=0.0):
    return NativeVectorizedBackend(
        NativeVectorizedConfig(
            account=AccountConfig(initial_capital=initial_capital, leverage=leverage),
            execution=ExecutionConfig(slippage_bps=slippage_bps),
            fee_rate=fee_rate,
            use_funding=False,
        )
    )


def test_native_vectorized_backend_returns_actual_positions_and_margin_diagnostics():
    idx = pd.date_range("2024-01-01", periods=3, freq="1D", tz="UTC")
    target = pd.Series([0.0, 500.0, 500.0], index=idx)
    close = pd.Series([100.0, 100.0, 110.0], index=idx)

    result = _backend(leverage=10.0).run_target_units(
        datetime_index=idx,
        target_units={"BTC": target},
        closes={"BTC": close},
        highs={"BTC": close},
        lows={"BTC": close},
    )

    assert result.metadata["backend"] == "native_vectorized"
    assert result.positions["Position_BTC"].iloc[1] == 500.0
    assert result.equity.iloc[2] == 15_000.0
    assert result.margin["initial_margin"].iloc[1] == 5_000.0
    assert result.margin["maintenance_margin"].iloc[1] == 250.0
    assert result.diagnostics["rejected_orders"].sum() == 0


def test_native_vectorized_backend_rejects_orders_above_buying_power():
    idx = pd.date_range("2024-01-01", periods=3, freq="1D", tz="UTC")
    target = pd.Series([0.0, 500.0, 500.0], index=idx)
    close = pd.Series([100.0, 100.0, 110.0], index=idx)

    result = _backend(leverage=1.0).run_target_units(
        datetime_index=idx,
        target_units={"BTC": target},
        closes={"BTC": close},
        highs={"BTC": close},
        lows={"BTC": close},
    )

    assert result.positions["Position_BTC"].iloc[1] == 0.0
    assert result.equity.iloc[2] == 10_000.0
    assert result.diagnostics["rejected_orders"].iloc[1] == 1
    assert result.diagnostics["reject_code"].iloc[1] == REJECT_INSUFFICIENT_MARGIN


def test_native_vectorized_backend_records_fee_and_turnover_costs():
    idx = pd.date_range("2024-01-01", periods=3, freq="1D", tz="UTC")
    target = pd.Series([0.0, 10.0, 0.0], index=idx)
    close = pd.Series([100.0, 100.0, 110.0], index=idx)

    result = _backend(leverage=10.0, fee_rate=0.001).run_target_units(
        datetime_index=idx,
        target_units={"BTC": target},
        closes={"BTC": close},
        highs={"BTC": close},
        lows={"BTC": close},
    )

    assert result.diagnostics["turnover"].iloc[1] == 1_000.0
    assert result.fees.iloc[1] == 1.0
    assert result.diagnostics["turnover"].iloc[2] == 1_100.0
    assert result.fees.iloc[2] == 1.1
    assert result.equity.iloc[2] == 10_097.9


def test_native_vectorized_backend_scales_raw_signal_notional_signals():
    idx = pd.date_range("2024-01-01", periods=4, freq="1D", tz="UTC")
    signal = pd.Series([0.0, 1.0, 1.0, 0.5], index=idx)
    close = pd.Series([100.0, 100.0, 110.0, 120.0], index=idx)

    result = _backend(leverage=10.0).run_signals(
        datetime_index=idx,
        positions={"BTC": signal},
        closes={"BTC": close},
        highs={"BTC": close},
        lows={"BTC": close},
        alloc_per_trade=1_000.0,
        hedge_type="signal_notional",
    )

    assert result.positions["Position_BTC"].iloc[1] == 10.0
    assert result.positions["Position_BTC"].iloc[2] == 10.0
    assert result.positions["Position_BTC"].iloc[3] == 1_000.0 / 120.0 * 0.5
