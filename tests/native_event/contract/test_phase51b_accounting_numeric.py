from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings, strategies as st

from quantbt import (
    AccountConfig,
    AssetType,
    ExecutionConfig,
    InstrumentRejectCode,
    InstrumentSpec,
    NativeEventBackend,
    NativeEventConfig,
    OrderCommand,
    OrderSide,
    OrderType,
    assert_native_accounting_invariants,
    compile_instrument_table,
    quantize_order_value,
)
from quantbt.core.event_contracts import EVENT_LIFECYCLE_V3_NEXT_OPEN


def _market(periods: int = 12):
    index = pd.date_range("2026-01-01", periods=periods, freq="1h", tz="UTC")
    close = np.asarray([100.0, 102.0, 104.0, 101.0, 98.0, 103.0, 106.0, 105.0, 107.0, 106.0, 108.0, 109.0])[:periods]
    return index, pd.DataFrame(
        {
            "open": close - 0.5,
            "high": close + 2.0,
            "low": close - 2.0,
            "close": close,
        },
        index=index,
    )


def _run(backend: str, commands, *, contract_size=1.0, use_funding=False, funding_rate=0.0):
    index, frame = _market()
    engine = NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=10_000.0, leverage=5.0),
            execution=ExecutionConfig(slippage_bps=3.0),
            fee_rate=0.0005,
            use_funding=use_funding,
            report_level="audit",
            native_backend=backend,
            execution_contract=EVENT_LIFECYCLE_V3_NEXT_OPEN,
        )
    )
    return engine.run_order_commands(
        index,
        commands,
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        opens={"BTC": frame["open"]},
        funding_rate=funding_rate,
        contract_size=contract_size,
        symbols=["BTC"],
    )


def test_accounting_ledger_reconciles_scale_reduce_close_and_reverse_python_rust():
    index, _ = _market()
    commands = (
        OrderCommand(timestamp=index[1], symbol="BTC", side=OrderSide.BUY, order_type=OrderType.MARKET, qty=2, order_id="open"),
        OrderCommand(timestamp=index[2], symbol="BTC", side=OrderSide.BUY, order_type=OrderType.MARKET, qty=1, order_id="scale"),
        OrderCommand(timestamp=index[3], symbol="BTC", side=OrderSide.SELL, order_type=OrderType.MARKET, qty=1, order_id="reduce"),
        OrderCommand(timestamp=index[5], symbol="BTC", side=OrderSide.SELL, order_type=OrderType.MARKET, qty=4, order_id="reverse"),
        OrderCommand(timestamp=index[7], symbol="BTC", side=OrderSide.BUY, order_type=OrderType.MARKET, qty=2, order_id="close"),
    )
    python = _run("python", commands, contract_size=10.0)
    rust = _run("rust", commands, contract_size=10.0)

    for result in (python, rust):
        audit = assert_native_accounting_invariants(result, contract_sizes=10.0, tolerance=1e-10)
        assert audit.invariants["passed"] is True
        assert audit.ledger["equity_residual"].abs().max() <= 1e-10
        assert audit.symbol_ledger.iloc[-1]["position_qty"] == 0.0
        assert result.metadata["accounting_policy_v1"]["fee_model"] == "quote_one_way_per_fill"

    pd.testing.assert_frame_equal(
        python.metadata["accounting_ledger_v1"],
        rust.metadata["accounting_ledger_v1"],
        check_exact=False,
        rtol=0.0,
        atol=1e-12,
    )


def test_accounting_funding_sign_and_empty_tape_metamorphic():
    index, _ = _market()
    entry = (
        OrderCommand(timestamp=index[1], symbol="BTC", side=OrderSide.BUY, order_type=OrderType.MARKET, qty=2, order_id="open"),
    )
    funded = _run("python", entry, use_funding=True, funding_rate=0.001)
    no_funding = _run("python", entry, use_funding=True, funding_rate=0.0)
    empty = _run("python", ())

    assert funded.funding.sum() > 0.0
    assert funded.equity.iloc[-1] < no_funding.equity.iloc[-1]
    assert_native_accounting_invariants(funded)
    assert empty.equity.eq(empty.initial_capital).all()
    assert empty.fees.eq(0.0).all()
    assert empty.funding.eq(0.0).all()


def test_prepared_instrument_table_is_contiguous_readonly_and_fail_fast():
    spec = InstrumentSpec(
        symbol="BTCUSDT",
        tick_size=0.1,
        lot_size=0.001,
        min_qty=0.005,
        min_notional=5.0,
        metadata={"venue": "BINANCE", "settlement_currency": "USDT", "max_qty": 100.0},
    )
    table = compile_instrument_table(["BTCUSDT"], {"BTCUSDT": spec})
    assert table.tick_size.flags.c_contiguous and not table.tick_size.flags.writeable
    assert table.qty_step.flags.c_contiguous and not table.qty_step.flags.writeable
    assert table.venue_values == ("BINANCE",)
    assert table.settlement_values == ("USDT",)
    assert len(table.fingerprint) == 64

    with pytest.raises(NotImplementedError):
        compile_instrument_table(
            ["BTCUSD"],
            {"BTCUSD": InstrumentSpec(symbol="BTCUSD", metadata={"contract_type": "inverse"})},
        )
    with pytest.raises(NotImplementedError):
        compile_instrument_table(["CALL"], {"CALL": InstrumentSpec(symbol="CALL", asset_type=AssetType.OPTION)})


@pytest.mark.parametrize(
    ("side", "order_type", "expected"),
    [
        (OrderSide.BUY, OrderType.LIMIT, 100.0),
        (OrderSide.SELL, OrderType.LIMIT, 100.1),
        (OrderSide.BUY, OrderType.STOP_MARKET, 100.1),
        (OrderSide.SELL, OrderType.STOP_MARKET, 100.0),
    ],
)
def test_side_aware_price_quantization(side, order_type, expected):
    output = quantize_order_value(
        side=side,
        order_type=order_type,
        price=100.04,
        qty=0.0199,
        tick_size=0.1,
        qty_step=0.001,
        min_qty=0.001,
        min_notional=1.0,
    )
    assert output.price == pytest.approx(expected)
    assert output.qty == pytest.approx(0.019)
    assert output.reject_code is InstrumentRejectCode.ACCEPTED


def test_minimums_are_checked_after_quantization():
    output = quantize_order_value(
        side="buy",
        order_type="limit",
        price=100.04,
        qty=0.0059,
        tick_size=0.1,
        qty_step=0.001,
        min_qty=0.006,
        min_notional=0.0,
    )
    assert output.qty == pytest.approx(0.005)
    assert output.reject_code is InstrumentRejectCode.MIN_QTY


@settings(max_examples=80, deadline=None)
@given(
    qty=st.floats(min_value=0.001, max_value=1000.0, allow_nan=False, allow_infinity=False),
    step=st.sampled_from([0.001, 0.01, 0.1, 1.0]),
)
def test_quantity_quantization_never_increases_requested_size(qty, step):
    output = quantize_order_value(
        side="buy", order_type="market", price=100.0, qty=qty,
        tick_size=0.01, qty_step=step,
    )
    assert output.qty <= qty + 1e-12
    assert output.qty >= 0.0
