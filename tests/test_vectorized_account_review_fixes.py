"""Independent account arithmetic for the close-target V2 compatibility route."""

import numpy as np
import pandas as pd
import pytest

from quantbt import NativeVectorizedBackend, NativeVectorizedConfig
from quantbt.backends import native_vectorized
from quantbt.core.schema import AccountConfig, ExecutionConfig
from quantbt.core.vectorized import _engine_units_v2


@pytest.fixture(params=["python", "numba"])
def kernel_runtime(request, monkeypatch):
    kernel = _engine_units_v2.py_func if request.param == "python" else _engine_units_v2
    monkeypatch.setattr(native_vectorized, "_engine_units_v2", kernel)
    return kernel


def _run(
    closes,
    targets,
    *,
    capital=1000.0,
    leverage=1.0,
    fee_rate=0.0,
    slippage_bps=0.0,
    highs=None,
    lows=None,
    **kwargs,
):
    prices = np.asarray(closes, dtype=np.float64)
    units = np.asarray(targets, dtype=np.float64)
    if prices.ndim == 1:
        prices = prices.reshape(-1, 1)
    if units.ndim == 1:
        units = units.reshape(-1, 1)
    index = pd.date_range("2024-01-01 01:00", periods=len(prices), freq="1h", tz="UTC")
    symbols = [f"S{s}" for s in range(prices.shape[1])]

    def series_map(values):
        matrix = np.asarray(values, dtype=np.float64).reshape(prices.shape)
        return {symbol: pd.Series(matrix[:, s], index=index) for s, symbol in enumerate(symbols)}

    backend = NativeVectorizedBackend(NativeVectorizedConfig(
        account=AccountConfig(initial_capital=capital, leverage=leverage),
        execution=ExecutionConfig(slippage_bps=slippage_bps),
        fee_rate=fee_rate,
        use_funding=False,
        target_runtime="numba",
    ))
    result = backend.run_target_units(
        datetime_index=index,
        symbols=symbols,
        target_units=series_map(units),
        closes=series_map(prices),
        highs=series_map(prices if highs is None else highs),
        lows=series_map(prices if lows is None else lows),
        **kwargs,
    )
    assert result.metadata["target_runtime"] == "numba_units_v2"
    return result


@pytest.mark.parametrize(
    "sign,leverage,close,capital,final_equity,final_im,exit_fee",
    [
        (-1, 1, 110, 2000, 1809.196, 1980, 0.044),
        (1, 2, 90, 1000, 809.204, 810, 0.036),
    ],
)
def test_affordable_partial_reduction_below_im_and_target_minima(
    kernel_runtime, sign, leverage, close, capital, final_equity, final_im, exit_fee,
):
    result = _run(
        [100, 100, close], [0, sign * 19, sign * 18], capital=capital,
        leverage=leverage, fee_rate=0.0004, min_qty=18.5, min_notional=1850,
    )
    np.testing.assert_allclose(result.positions.iloc[:, 0], [0, sign * 19, sign * 18])
    np.testing.assert_allclose(result.equity, [capital, capital - 0.76, final_equity])
    np.testing.assert_allclose(result.fees, [0, 0.76, exit_fee])
    np.testing.assert_allclose(result.diagnostics.turnover, [0, 1900, close])
    assert result.margin.initial_margin.iloc[-1] == pytest.approx(final_im)
    assert result.margin.maintenance_margin.iloc[-1] == pytest.approx(18 * close * 0.005)
    assert result.equity.iloc[-1] < result.margin.initial_margin.iloc[-1]
    assert result.diagnostics.rejected_orders.sum() == 0
    assert not result.liquidated


@pytest.mark.parametrize("target", [-20, 18])
def test_increases_and_reversals_keep_existing_margin_gate(kernel_runtime, target):
    result = _run(
        [100, 100, 110], [0, -19, target], capital=2000, fee_rate=0.0004,
    )
    np.testing.assert_allclose(result.positions.iloc[:, 0], [0, -19, -19])
    np.testing.assert_allclose(result.equity, [2000, 1999.24, 1809.24])
    np.testing.assert_allclose(result.fees, [0, 0.76, 0])
    np.testing.assert_array_equal(result.diagnostics.rejected_orders, [0, 0, 1])
    assert result.diagnostics.reject_code.iloc[-1] == 1
    assert not result.liquidated


@pytest.mark.parametrize(
    "reduced,next_qty,accepted,final_equity,final_im",
    [
        (-18, 0.1, 0, 1809.196, 1980),
        (-16, 0.1, 0.1, 1809.104, 1770),
        (-16, 0.5, 0, 1809.108, 1760),
    ],
)
def test_reduction_recomputes_actual_buying_power_for_next_symbol(
    kernel_runtime, reduced, next_qty, accepted, final_equity, final_im,
):
    # Before reduction: equity 1809.24, IM 2090. Released IM must first
    # cover that deficit; the -16 control leaves only 49.108 for S1.
    result = _run(
        [[100, 100], [100, 100], [110, 100]],
        [[0, 0], [-19, 0], [reduced, next_qty]],
        capital=2000, fee_rate=0.0004,
    )
    np.testing.assert_allclose(result.positions.iloc[-1], [reduced, accepted])
    assert result.equity.iloc[-1] == pytest.approx(final_equity)
    assert result.margin.initial_margin.iloc[-1] == pytest.approx(final_im)
    assert result.diagnostics.rejected_orders.iloc[-1] == int(accepted == 0)
    assert not result.liquidated


@pytest.mark.parametrize(
    "fee_rate,slippage_bps,close,equity,entry_fee",
    [(0.6, 0, 200, 40, 60), (0, 2000, 270, 10, 0)],
)
def test_reduction_must_afford_fees_and_slippage_from_equity(
    kernel_runtime, fee_rate, slippage_bps, close, equity, entry_fee,
):
    result = _run(
        [100, 100, close], [0, -1, -0.5], capital=200,
        fee_rate=fee_rate, slippage_bps=slippage_bps,
    )
    np.testing.assert_allclose(result.positions.iloc[:, 0], [0, -1, -1])
    assert result.equity.iloc[-1] == pytest.approx(equity)
    np.testing.assert_allclose(result.fees, [0, entry_fee, 0])
    assert result.diagnostics.turnover.iloc[-1] == 0
    assert result.diagnostics.rejected_orders.iloc[-1] == 1
    assert result.diagnostics.reject_code.iloc[-1] == 1
    assert not result.liquidated


@pytest.mark.parametrize("sign", [-1, 1])
@pytest.mark.parametrize("minimum,code", [({"min_qty": 0.5}, 7), ({"min_notional": 100}, 8)])
def test_minimums_use_actual_delta_not_retained_position(kernel_runtime, sign, minimum, code):
    result = _run(
        [100] * 6, np.asarray([0, 1, 1.1, 0.1, -0.1, 0]) * sign,
        fee_rate=0.001, contract_size=2, qty_step=0.1, **minimum,
    )
    np.testing.assert_allclose(result.positions.iloc[:, 0], np.asarray([0, 1, 1, 0.1, 0.1, 0]) * sign)
    np.testing.assert_allclose(result.equity, [1000, 999.8, 999.8, 999.62, 999.62, 999.6])
    np.testing.assert_allclose(result.fees, [0, 0.2, 0, 0.18, 0, 0.02])
    np.testing.assert_allclose(result.diagnostics.turnover, [0, 200, 0, 180, 0, 20])
    np.testing.assert_array_equal(result.diagnostics.rejected_orders, [0, 0, 1, 0, 1, 0])
    np.testing.assert_array_equal(result.diagnostics.reject_code, [0, 0, code, 0, code, 0])
    assert not result.liquidated


@pytest.mark.parametrize("minimum", [{"min_qty": 0.55}, {"min_notional": 55}])
def test_delta_minimums_follow_target_lot_rounding(kernel_runtime, minimum):
    result = _run([100] * 3, [0, 1, 1.59], qty_step=0.1, **minimum)
    np.testing.assert_allclose(result.positions.iloc[:, 0], [0, 1, 1])
    np.testing.assert_allclose(result.diagnostics.turnover, [0, 100, 0])
    assert result.diagnostics.rejected_orders.iloc[-1] == 1


@pytest.mark.parametrize("sign", [-1, 1])
@pytest.mark.parametrize("minimum,accepted,equity", [(50, 1.5, 998.5), (50.25, 1, 999)])
def test_notional_minimum_is_at_close_mark_not_slipped_fill(
    kernel_runtime, sign, minimum, accepted, equity,
):
    result = _run(
        [100] * 3, [0, sign, sign * 1.5],
        slippage_bps=100, min_notional=minimum,
    )
    assert result.positions.iloc[-1, 0] == pytest.approx(sign * accepted)
    assert result.equity.iloc[-1] == pytest.approx(equity)
    assert result.diagnostics.rejected_orders.iloc[-1] == int(accepted == 1)


@pytest.mark.parametrize(
    "targets,expected",
    [([0, 0, 1, 1], [0, 0, 0, 1]), ([0, 1, 0, 0], [0, 1, 1, 0])],
)
def test_raw_missing_price_blocks_entry_and_exit(kernel_runtime, targets, expected):
    result = _run([100, 100, np.nan, 100], targets)
    np.testing.assert_allclose(result.positions.iloc[:, 0], expected)
    np.testing.assert_allclose(result.equity, [1000] * 4)
    assert result.diagnostics.rejected_orders.iloc[2] == 1
    assert result.diagnostics.reject_code.iloc[2] == 3
    assert not result.liquidated


def test_optional_tradable_blocks_fills_without_blocking_carried_marks(kernel_runtime):
    closes = np.asarray([[100.0], [100.0], [110.0], [120.0]])
    kwargs = dict(
        n_bars=4, n_syms=1, highs=closes, lows=closes, closes=closes,
        target_units=np.asarray([[0.0], [1.0], [0.0], [0.0]]),
        funding_rates=np.zeros((4, 1)), is_funding_bar=np.zeros(4, dtype=np.bool_),
        init_capital=1000.0, leverages=np.ones(1), maint_ratio=0.005,
        fee_rates=np.zeros(1), contract_sizes=np.ones(1), slippage=0.0, use_funding=False,
    )
    old_call = kernel_runtime(**kwargs)
    np.testing.assert_allclose(old_call[0], [1000, 1000, 1010, 1010])
    masked = kernel_runtime(**kwargs, tradable=np.asarray([[True], [True], [False], [True]]))
    np.testing.assert_allclose(masked[0], [1000, 1000, 1010, 1020])
    np.testing.assert_allclose(masked[1][:, 0], [0, 1, 1, 0])
    np.testing.assert_allclose(masked[3], [0, 100, 0, 120])
    np.testing.assert_array_equal(masked[7], [0, 0, 1, 0])
    np.testing.assert_array_equal(masked[8], [0, 0, 3, 0])


def test_first_bar_and_close_to_close_order_timing_are_unchanged(kernel_runtime):
    result = _run([100, 100, 110], [99, 1, 0], fee_rate=0.001)
    np.testing.assert_allclose(result.positions.iloc[:, 0], [0, 1, 0])
    np.testing.assert_allclose(result.equity, [1000, 999.9, 1009.79])
    np.testing.assert_allclose(result.fees, [0, 0.1, 0.11])


def test_intrabar_liquidation_still_precedes_requested_close(kernel_runtime):
    result = _run(
        [100] * 4, [0, 10, 0, 0], capital=100, leverage=20,
        lows=[100, 100, 1, 100],
    )
    np.testing.assert_allclose(result.positions.iloc[:, 0], [0, 10, 0, 0])
    np.testing.assert_allclose(result.equity, [100, 100, 0, 0])
    np.testing.assert_allclose(result.diagnostics.turnover, [0, 1000, 0, 0])
    assert result.liquidated
    assert result.liquidation_bar == 2
    assert result.metadata["liquidation_reason"] == 1
