from __future__ import annotations

import numpy as np
import pandas as pd

from quantbt import AccountConfig, BacktestEngineV2, OrderIntent, OrderSide, OrderType, TimeInForce
from quantbt.core.order_compiler import compile_order_intents
from quantbt.core.preprocessor import align_series, build_market_arrays, prepare_funding, validate_datetime
from quantbt.backends import NativeEventBackend, NativeEventConfig
from quantbt.sizing.fast import scale_signal_notional_matrix
from quantbt.sizing.modes import compute_target_units


def _market():
    idx = pd.date_range("2024-01-01", periods=12, freq="1h", tz="UTC")
    close_a = pd.Series([100, 101, 102, 103, 102, 104, 105, 104, 106, 107, 106, 108], index=idx, dtype=float)
    close_b = pd.Series([50, 49, 51, 52, 52, 53, 54, 53, 55, 56, 57, 58], index=idx, dtype=float)
    data = {
        "A": pd.DataFrame({"open": close_a, "high": close_a + 1, "low": close_a - 1, "close": close_a, "volume": 1_000.0}),
        "B": pd.DataFrame({"open": close_b, "high": close_b + 1, "low": close_b - 1, "close": close_b, "volume": 1_000.0}),
    }
    signals = {
        "A": pd.Series([0, 1, 1, 0.5, 0.5, -1, -1, 0, 0, 1.5, 1.5, 0], index=idx, dtype=float),
        "B": pd.Series([0, -0.5, -0.5, -0.5, 0, 0, 1, 1, 0, 0, -1, -1], index=idx, dtype=float),
    }
    return idx, data, signals


def _orders(idx):
    return [
        OrderIntent(idx[1], "A", OrderSide.BUY, OrderType.MARKET, qty=1.0, tif=TimeInForce.IOC),
        OrderIntent(idx[3], "B", OrderSide.SELL, OrderType.LIMIT, qty=2.0, price=53.0, tif=TimeInForce.GTC),
        OrderIntent(idx[3], "A", OrderSide.SELL, OrderType.MARKET, qty=0.5, tif=TimeInForce.IOC),
        OrderIntent(idx[8], "B", OrderSide.BUY, OrderType.MARKET, qty=2.0, tif=TimeInForce.IOC),
    ]


def _legacy_order_arrays(idx, orders, symbol_to_col):
    def bar_index(timestamp):
        ts = pd.Timestamp(timestamp)
        if ts.tz is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        pos = idx.searchsorted(ts, side="left")
        if pos >= len(idx):
            raise ValueError("order timestamp is after the available data")
        return int(pos)

    sorted_orders = sorted(enumerate(orders), key=lambda item: bar_index(item[1].timestamp))
    order_bar = np.zeros(len(sorted_orders), dtype=np.int64)
    order_symbol = np.zeros(len(sorted_orders), dtype=np.int64)
    order_side = np.zeros(len(sorted_orders), dtype=np.int64)
    order_type = np.zeros(len(sorted_orders), dtype=np.int64)
    order_qty = np.zeros(len(sorted_orders), dtype=np.float64)
    order_price = np.zeros(len(sorted_orders), dtype=np.float64)
    order_tif = np.zeros(len(sorted_orders), dtype=np.int64)
    original_index = np.zeros(len(sorted_orders), dtype=np.int64)
    for k, (orig_idx, order) in enumerate(sorted_orders):
        order_bar[k] = bar_index(order.timestamp)
        order_symbol[k] = symbol_to_col[order.symbol]
        order_side[k] = 1 if order.side is OrderSide.BUY else -1
        order_type[k] = 0 if order.order_type is OrderType.MARKET else 1
        order_qty[k] = order.qty
        order_price[k] = 0.0 if order.price is None else order.price
        order_tif[k] = {TimeInForce.GTC: 0, TimeInForce.IOC: 1, TimeInForce.FOK: 2, TimeInForce.GTD: 3}[order.tif]
        original_index[k] = orig_idx
    order_ptr = np.zeros(len(idx) + 1, dtype=np.int64)
    for bar in order_bar:
        order_ptr[bar + 1] += 1
    for i in range(1, len(order_ptr)):
        order_ptr[i] += order_ptr[i - 1]
    return order_ptr, order_symbol, order_side, order_type, order_qty, order_price, order_tif, original_index


def test_signal_notional_matrix_matches_legacy_series_sizing():
    idx, data, signals = _market()
    symbols = ["A", "B"]
    closes_m = np.column_stack([data[s]["close"].to_numpy(dtype=float) for s in symbols])
    signals_m = np.column_stack([signals[s].to_numpy(dtype=float) for s in symbols])
    allocs = np.array([10_000.0, 5_000.0])

    fast = scale_signal_notional_matrix(signals_m, closes_m, allocs, use_pyramiding=True)
    legacy = np.column_stack(
        [
            compute_target_units("signal_notional", signals[s], data[s]["close"], allocs[i], True).to_numpy()
            for i, s in enumerate(symbols)
        ]
    )
    np.testing.assert_allclose(fast, legacy, rtol=0.0, atol=1e-12)

    fast_no_pyr = scale_signal_notional_matrix(signals_m, closes_m, allocs, use_pyramiding=False)
    legacy_no_pyr = np.column_stack(
        [
            compute_target_units("signal_notional", signals[s], data[s]["close"], allocs[i], False).to_numpy()
            for i, s in enumerate(symbols)
        ]
    )
    np.testing.assert_allclose(fast_no_pyr, legacy_no_pyr, rtol=0.0, atol=1e-12)


def test_native_vectorized_fast_path_matches_legacy_target_units_route():
    _, data, signals = _market()
    alloc = {"A": 10_000.0, "B": 5_000.0}
    account = AccountConfig(initial_capital=100_000.0, leverage=5.0)

    fast = BacktestEngineV2(
        data=data,
        signals=signals,
        backend="native_vectorized",
        account=account,
        alloc_per_trade=alloc,
        hedge_type="signal_notional",
        use_funding=False,
    ).result
    target_units = {
        s: compute_target_units("signal_notional", signals[s], data[s]["close"], alloc[s], True)
        for s in signals
    }
    legacy_route = BacktestEngineV2(
        data=data,
        target_units=target_units,
        backend="native_vectorized",
        account=account,
        use_funding=False,
    ).result

    np.testing.assert_allclose(fast.equity.to_numpy(), legacy_route.equity.to_numpy(), rtol=0.0, atol=1e-10)
    np.testing.assert_allclose(fast.positions.to_numpy(), legacy_route.positions.to_numpy(), rtol=0.0, atol=1e-12)


def test_order_compiler_matches_legacy_python_construction_and_result():
    idx, data, _ = _market()
    orders = _orders(idx)
    symbol_to_col = {"A": 0, "B": 1}
    compiled = compile_order_intents(idx, orders, symbol_to_col)
    legacy = _legacy_order_arrays(idx, orders, symbol_to_col)

    np.testing.assert_array_equal(compiled.order_ptr, legacy[0])
    np.testing.assert_array_equal(compiled.order_symbol, legacy[1])
    np.testing.assert_array_equal(compiled.order_side, legacy[2])
    np.testing.assert_array_equal(compiled.order_type, legacy[3])
    np.testing.assert_allclose(compiled.order_qty, legacy[4])
    np.testing.assert_allclose(compiled.order_price, legacy[5])
    np.testing.assert_array_equal(compiled.order_tif, legacy[6])
    np.testing.assert_array_equal(compiled.original_index, legacy[7])

    result = BacktestEngineV2(
        data=data,
        orders=orders,
        backend="native_event",
        account=AccountConfig(initial_capital=100_000.0, leverage=5.0),
        use_funding=False,
    ).result
    report = result.metadata["order_report"].sort_values("original_index")
    assert len(result.fills) == int((report["status"] == 1).sum())
    assert report["original_index"].tolist() == [0, 1, 2, 3]


def test_prepared_market_arrays_and_compiled_orders_reuse_match_normal_event_run():
    idx, data, _ = _market()
    orders = _orders(idx)
    symbols = ["A", "B"]
    closes = {symbol: data[symbol]["close"] for symbol in symbols}
    highs = {symbol: data[symbol]["high"] for symbol in symbols}
    lows = {symbol: data[symbol]["low"] for symbol in symbols}
    backend = NativeEventBackend(NativeEventConfig(account=AccountConfig(initial_capital=100_000.0, leverage=5.0), use_funding=False))

    normal = backend.run_orders(
        datetime_index=idx,
        orders=orders,
        closes=closes,
        highs=highs,
        lows=lows,
        symbols=symbols,
    )

    idx_n = validate_datetime(idx)
    close_dict = align_series(closes, symbols, idx_n)
    high_dict = align_series(highs, symbols, idx_n, fallback=close_dict)
    low_dict = align_series(lows, symbols, idx_n, fallback=close_dict)
    funding_dict = prepare_funding(0.0, symbols, idx_n)
    market_arrays = build_market_arrays(symbols, idx_n, close_dict, high_dict, low_dict, funding_dict)
    compiled = compile_order_intents(idx_n, orders, {"A": 0, "B": 1})

    reused = backend.run_orders(
        datetime_index=idx,
        orders=orders,
        closes=closes,
        highs=highs,
        lows=lows,
        symbols=symbols,
        market_arrays=market_arrays,
        compiled_orders=compiled,
    )

    np.testing.assert_allclose(reused.equity.to_numpy(), normal.equity.to_numpy(), rtol=0.0, atol=1e-10)
    np.testing.assert_allclose(reused.positions.to_numpy(), normal.positions.to_numpy(), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(
        reused.metadata["order_report"].to_numpy(dtype=float),
        normal.metadata["order_report"].to_numpy(dtype=float),
        rtol=0.0,
        atol=1e-12,
    )
    assert len(reused.fills) == len(normal.fills)


def test_prepared_market_arrays_reject_stale_signature():
    idx, data, _ = _market()
    orders = _orders(idx)
    symbols = ["A", "B"]
    closes = {symbol: data[symbol]["close"] for symbol in symbols}
    highs = {symbol: data[symbol]["high"] for symbol in symbols}
    lows = {symbol: data[symbol]["low"] for symbol in symbols}
    idx_n = validate_datetime(idx)
    close_dict = align_series(closes, symbols, idx_n)
    high_dict = align_series(highs, symbols, idx_n, fallback=close_dict)
    low_dict = align_series(lows, symbols, idx_n, fallback=close_dict)
    funding_dict = prepare_funding(0.0, symbols, idx_n)
    market_arrays = build_market_arrays(symbols, idx_n, close_dict, high_dict, low_dict, funding_dict)
    backend = NativeEventBackend(NativeEventConfig(account=AccountConfig(initial_capital=100_000.0, leverage=5.0), use_funding=False))

    stale_idx = idx_n[:-1]
    try:
        backend.run_orders(
            datetime_index=stale_idx,
            orders=orders,
            closes=closes,
            highs=highs,
            lows=lows,
            symbols=symbols,
            market_arrays=market_arrays,
        )
    except ValueError as exc:
        assert "prepared market arrays" in str(exc)
    else:
        raise AssertionError("stale prepared market arrays were accepted")
