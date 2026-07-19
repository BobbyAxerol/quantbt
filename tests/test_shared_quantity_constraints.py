from __future__ import annotations

import pandas as pd
import pytest

from quantbt import (
    BacktestEngine,
    BacktestEngineV2,
    InstrumentSpec,
    OrderIntent,
    OrderSide,
    OrderType,
    QuantBTEndpoint,
    TimeInForce,
    build_quantity_constraints,
)


def _frame():
    idx = pd.date_range("2024-01-01", periods=6, freq="1h", tz="UTC")
    close = pd.Series([100, 101, 102, 103, 104, 105], index=idx, dtype=float)
    frame = pd.DataFrame(
        {
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1.0,
        },
        index=idx,
    )
    signal = pd.Series([0, 1, 1, 0, -1, 0], index=idx, dtype=float)
    return idx, close, frame, signal


def test_quantity_constraints_accept_lot_size_slot_size_and_instrument_spec():
    constraints = build_quantity_constraints(
        ["ETHUSDT", "DOGEUSDT"],
        instruments={"ETHUSDT": InstrumentSpec("ETHUSDT", lot_size=0.001, min_qty=0.001, min_notional=10)},
        slot_size={"DOGEUSDT": 1.0},
        min_notional={"DOGEUSDT": 5.0},
    )

    assert constraints.as_dict()["ETHUSDT"] == {
        "qty_step": 0.001,
        "lot_size": 0.001,
        "min_qty": 0.001,
        "min_notional": 10.0,
    }
    assert constraints.as_dict()["DOGEUSDT"]["qty_step"] == 1.0
    assert constraints.as_dict()["DOGEUSDT"]["min_notional"] == 5.0


def test_legacy_signal_notional_quantizes_target_units_without_contract_size_abuse():
    idx, close, _, signal = _frame()

    bt = BacktestEngine(
        Datetime=idx,
        Position=signal,
        Close=close,
        fee=0.0,
        use_funding_rate=False,
        initial_capital=1_000,
        leverage=10,
        alloc_per_trade=333.0,
        hedge_type="signal_notional",
        slippage=0.0,
        qty_step=0.1,
        min_qty=0.1,
        contract_size=1.0,
    )

    pos = bt.result.positions["Position_DEFAULT"]
    assert pos.iloc[1] == 3.2
    assert pos.iloc[4] == -3.2
    assert bt.result.metadata["quantity_constraints"]["DEFAULT"]["qty_step"] == 0.1


def test_native_vectorized_endpoint_quantizes_target_units():
    _, _, frame, signal = _frame()

    endpoint = QuantBTEndpoint.signal_notional(
        backend="native_vectorized",
        initial_capital=1_000,
        leverage=10,
        alloc_per_trade=333.0,
        fee=0.0,
        slippage_bps=0.0,
        use_funding=False,
        qty_step=0.1,
        min_qty=0.1,
    )
    result = endpoint.backtest(data=frame, signal=signal, symbols=["ETHUSDT"])

    pos = result.positions["Position_ETHUSDT"]
    assert pos.iloc[1] == 3.2
    assert pos.iloc[4] == -3.2
    assert result.metadata["quantity_constraints"]["ETHUSDT"]["lot_size"] == 0.1


def test_native_event_quantizes_and_drops_orders_by_exchange_constraints():
    idx, _, frame, _ = _frame()
    orders = [
        OrderIntent(idx[1], "ETHUSDT", OrderSide.BUY, OrderType.MARKET, qty=0.156, tif=TimeInForce.IOC),
        OrderIntent(idx[2], "ETHUSDT", OrderSide.BUY, OrderType.MARKET, qty=0.04, tif=TimeInForce.IOC),
    ]

    engine = BacktestEngineV2(
        data=frame,
        backend="native_event",
        orders=orders,
        symbols=["ETHUSDT"],
        fee_rate=0.0,
        use_funding=False,
        qty_step=0.1,
        min_qty=0.1,
        min_notional=10.0,
    )

    result = engine.result
    assert [fill.qty for fill in result.fills] == [0.1]
    assert result.metadata["quantity_preflight"]["changed_count"] == 1
    assert result.metadata["quantity_preflight"]["dropped_count"] == 1


def test_native_portfolio_quantizes_per_symbol_target_units():
    idx, close, _, signal = _frame()
    positions = {"ETHUSDT": signal, "BTCUSDT": -signal}
    closes = {"ETHUSDT": close, "BTCUSDT": close * 2.0}

    endpoint = QuantBTEndpoint.portfolio(
        initial_capital=1_000,
        leverage=10,
        alloc_per_trade={"ETHUSDT": 333.0, "BTCUSDT": 333.0},
        fee=0.0,
        use_funding=False,
        qty_step={"ETHUSDT": 0.1, "BTCUSDT": 0.01},
        min_qty=0.01,
    )
    result = endpoint.backtest(
        positions=positions,
        closes=closes,
        datetime_index=idx,
        symbols=["ETHUSDT", "BTCUSDT"],
    )

    target = result.metadata["target_units_report"]
    assert target.loc[idx[1], "ETHUSDT"] == 3.2
    assert target.loc[idx[1], "BTCUSDT"] == pytest.approx(-1.64)
    assert result.metadata["quantity_constraints"]["BTCUSDT"]["qty_step"] == 0.01
