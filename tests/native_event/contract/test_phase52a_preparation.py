from __future__ import annotations

from dataclasses import fields

import numpy as np
import pandas as pd

from quantbt import AccountConfig, ExecutionConfig, InstrumentSpec, OrderCommand, OrderSide, OrderType
from quantbt.planning import BacktestRequest, RunProfile, StrategyMode, WorkloadClass, resolve_execution_plan
from quantbt.preparation import prepare_native_event_lifecycle


def _inputs(*, funding=0.0, volume_scale=1.0):
    index = pd.date_range("2026-01-01", periods=8, freq="1h", tz="UTC")
    close = pd.Series([100.0, 102.0, 104.0, 101.0, 98.0, 103.0, 106.0, 105.0], index=index)
    frame = pd.DataFrame(
        {
            "open": close - 0.5,
            "high": close + 2.0,
            "low": close - 2.0,
            "close": close,
            "volume": np.arange(1.0, 9.0) * volume_scale,
        },
        index=index,
    )
    commands = (
        OrderCommand(
            timestamp=index[1], symbol="BTC", side=OrderSide.BUY,
            order_type=OrderType.MARKET, qty=0.0199, order_id="entry",
        ),
        OrderCommand(
            timestamp=index[5], symbol="BTC", side=OrderSide.SELL,
            order_type=OrderType.MARKET, qty=0.0199, order_id="exit",
        ),
    )
    request = BacktestRequest(
        endpoint_mode="orders",
        input_mode="orders",
        requested_backend="python",
        execution_contract_id="event_lifecycle_v3_next_open",
        strategy_mode=StrategyMode.STATIC_COMMANDS,
        workload=WorkloadClass.STATIC_COMMAND_TAPE,
        profile=RunProfile.AUDIT,
        report_level="audit",
        audit_sink="memory",
        symbols=("BTC",),
        command_count=len(commands),
        trace_requested=True,
    )
    return index, frame, commands, resolve_execution_plan(request), funding


def _prepare(*, funding=0.0, volume_scale=1.0):
    index, frame, commands, plan, funding_rate = _inputs(funding=funding, volume_scale=volume_scale)
    return prepare_native_event_lifecycle(
        plan=plan,
        datetime_index=index,
        commands=commands,
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        opens={"BTC": frame["open"]},
        volumes={"BTC": frame["volume"]},
        funding_rate=funding_rate,
        symbols=["BTC"],
        instruments={
            "BTC": InstrumentSpec(
                symbol="BTC", tick_size=0.1, lot_size=0.001,
                min_qty=0.005, min_notional=1.0,
            )
        },
        contract_size=10.0,
        leverage=5.0,
        fee_rate=0.0005,
        account=AccountConfig(initial_capital=10_000.0, leverage=5.0),
        execution=ExecutionConfig(slippage_bps=3.0),
        use_funding=True,
    )


def test_preparation_is_one_pass_readonly_and_pandas_free_at_engine_boundary():
    preparation = _prepare()
    prepared = preparation.prepared

    assert prepared.diagnostics.market_normalizations == 1
    assert prepared.diagnostics.instrument_normalizations == 1
    assert prepared.diagnostics.command_compilations == 1
    assert prepared.diagnostics.output_projections == 1
    assert prepared.diagnostics.backend_resolutions == 1
    assert prepared.command_tape.n_commands == 2
    assert preparation.quantity_preflight["changed_count"] == 2
    assert [command.qty for command in preparation.effective_commands] == [0.019, 0.019]

    for component in (prepared.market, prepared.instruments, prepared.command_tape):
        for item in fields(component):
            value = getattr(component, item.name)
            if isinstance(value, np.ndarray):
                assert value.flags.c_contiguous
                assert not value.flags.writeable
            assert not isinstance(value, (pd.Series, pd.DataFrame, pd.Index))


def test_preparation_fingerprints_are_reproducible_and_cover_volume_funding():
    first = _prepare()
    repeated = _prepare()
    volume_changed = _prepare(volume_scale=2.0)
    funding_changed = _prepare(funding=0.001)

    assert first.prepared.keys == repeated.prepared.keys
    assert first.prepared.keys.market != volume_changed.prepared.keys.market
    assert first.prepared.keys.market != funding_changed.prepared.keys.market
    assert first.prepared.keys.combined != volume_changed.prepared.keys.combined
    assert first.prepared.keys.combined != funding_changed.prepared.keys.combined


def test_prepared_command_tape_matches_effective_command_order_and_plan():
    preparation = _prepare()
    prepared = preparation.prepared

    assert prepared.keys.plan == prepared.plan.plan_fingerprint
    assert prepared.keys.commands == prepared.command_tape.fingerprint
    np.testing.assert_array_equal(prepared.command_tape.command_bar, [1, 5])
    np.testing.assert_array_equal(prepared.command_tape.command_qty, [0.019, 0.019])
    assert prepared.market.symbols == prepared.instruments.table.symbols
    assert prepared.market.symbols == prepared.command_tape.symbols
