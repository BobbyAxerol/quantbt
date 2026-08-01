from __future__ import annotations

import gc
import importlib.util

import numpy as np
import pytest

import quantbt.backends._native_event_rust as rust_adapter
from quantbt import OrderAction, OrderCommand, OrderSide, OrderType, TimeInForce
from quantbt.backends._native_event_rust import RustBatchedRunner

from .test_rust_batched_full_tape import _bars


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native batched wheel is not installed in this environment",
)


def _replacement_fixture():
    frame = _bars(16)
    index = frame.index
    from quantbt import AccountConfig, ExecutionConfig, NativeEventBackend, NativeEventConfig

    backend = NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=10_000.0, leverage=5.0, maintenance_ratio=0.0),
            execution=ExecutionConfig(slippage_bps=2.0),
            fee_rate=0.0002,
            use_funding=False,
        )
    )
    market = backend.prepare_market_arrays(
        datetime_index=index,
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        symbols=["BTC"],
    )
    commands = (
        OrderCommand(
            timestamp=index[1],
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            qty=1.0,
            price=50.0,
            tif=TimeInForce.GTC,
            order_id="a",
        ),
        OrderCommand(
            timestamp=index[2],
            action=OrderAction.REPLACE,
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            qty=1.0,
            price=51.0,
            tif=TimeInForce.GTC,
            order_id="b",
            target_order_id="a",
        ),
        OrderCommand(
            timestamp=index[3],
            action=OrderAction.REPLACE,
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            qty=1.0,
            price=52.0,
            tif=TimeInForce.GTC,
            order_id="c",
            target_order_id="b",
        ),
        OrderCommand(
            timestamp=index[4],
            action=OrderAction.CANCEL,
            target_order_id="a",
        ),
    )
    compiled = backend.compile_order_commands(index, commands, symbols=["BTC"])
    runner = RustBatchedRunner(
        idx=index,
        symbols=["BTC"],
        market_arrays=market,
        contract_size=1.0,
        leverage=5.0,
        fee_rate=0.0002,
        initial_capital=10_000.0,
        slippage=0.0002,
        use_funding=False,
    )
    return backend, frame, market, commands, compiled, runner


def test_phase46d_prepared_market_copy_survives_python_input_release():
    _, _, market, _, compiled, runner = _replacement_fixture()
    del market
    gc.collect()
    score = runner.run_tape_score(compiled)
    assert score.bars == len(runner.idx)
    assert np.isfinite(score.final_equity)


def test_phase46d_score_boundary_is_typed_and_has_no_audit_payload():
    _, _, _, _, compiled, runner = _replacement_fixture()
    ptr, codes, values, expiry = runner._tape_arrays(compiled)
    payload = runner._new_session().run_tape_score(ptr, codes, values, expiry)
    assert type(payload).__name__ == "BatchedScoreResultCore"
    assert payload.bars == len(runner.idx)
    assert not hasattr(payload, "equity")
    assert not hasattr(payload, "fills")


def test_phase46d_tape_cache_is_fingerprint_bounded_and_clearable():
    _, _, market, _, compiled, runner = _replacement_fixture()
    runner.run_tape_score(compiled)
    assert runner.tape_cache_bytes > 0
    runner.clear_tape_cache()
    assert runner.tape_cache_bytes == 0

    bounded = RustBatchedRunner(
        idx=runner.idx,
        symbols=runner.symbols,
        market_arrays=market,
        contract_size=runner.contract_size,
        leverage=runner.leverage,
        fee_rate=runner.fee_rate,
        initial_capital=runner.initial_capital,
        slippage=runner.slippage,
        use_funding=False,
        max_tape_cache_bytes=1,
    )
    bounded.run_tape_score(compiled)
    assert bounded.tape_cache_bytes == 0


def test_phase46d_compiled_tape_fingerprint_is_precomputed_and_arrays_are_read_only():
    _, _, _, _, compiled, _ = _replacement_fixture()
    assert compiled.tape_fingerprint
    for name in (
        "command_ptr",
        "command_bar",
        "command_action",
        "command_symbol",
        "command_side",
        "command_type",
        "command_qty",
        "command_price",
        "command_trigger_price",
        "command_tif",
        "command_reduce_only",
        "command_order_id",
        "command_target_order_id",
        "command_parent_order_id",
        "command_group_id",
        "command_oco_group_id",
        "command_activation",
        "command_expires_bar",
        "original_index",
    ):
        assert getattr(compiled, name).flags.writeable is False


def test_phase46d_score_cache_does_not_rehash_compiled_tape(monkeypatch):
    _, _, _, _, compiled, runner = _replacement_fixture()
    runner.run_tape_score(compiled)

    def fail_if_rehashed(_):
        raise AssertionError("compiled tape was rehashed on the cache-hit path")

    monkeypatch.setattr(rust_adapter, "_command_tape_fingerprint", fail_if_rehashed)
    second = runner.run_tape_score(compiled)
    assert second.bars == len(runner.idx)


def test_phase46d_replacement_chain_preserves_audit_accounting():
    backend, frame, market, commands, compiled, runner = _replacement_fixture()
    rust = runner.run_tape_audit(compiled)
    python = backend.run_order_commands(
        datetime_index=frame.index,
        commands=commands,
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        symbols=["BTC"],
        market_arrays=market,
        compiled_commands=compiled,
        report_level="minimal",
    )
    np.testing.assert_allclose(rust.equity, python.equity.to_numpy(), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(rust.positions, python.positions["Position_BTC"].to_numpy(), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(rust.fees, python.fees.to_numpy(), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(rust.total_turnover, python.diagnostics["turnover"].sum(), rtol=0.0, atol=1e-12)
    assert rust.fill_count == 0
    assert rust.canceled_count == 1


def test_phase46d_cycle_alias_is_finite_and_does_not_fill():
    backend, frame, market, _, _, runner = _replacement_fixture()
    index = frame.index
    commands = (
        OrderCommand(
            timestamp=index[1],
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            qty=1.0,
            price=50.0,
            tif=TimeInForce.GTC,
            order_id="a",
        ),
        OrderCommand(
            timestamp=index[2],
            action=OrderAction.REPLACE,
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            qty=1.0,
            price=51.0,
            tif=TimeInForce.GTC,
            order_id="b",
            target_order_id="a",
        ),
        OrderCommand(
            timestamp=index[3],
            action=OrderAction.REPLACE,
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            qty=1.0,
            price=52.0,
            tif=TimeInForce.GTC,
            order_id="a",
            target_order_id="b",
        ),
        OrderCommand(timestamp=index[4], action=OrderAction.CANCEL, target_order_id="a"),
    )
    compiled = backend.compile_order_commands(index, commands, symbols=["BTC"])
    result = runner.run_tape_audit(compiled)
    assert result.fill_count == 0
    assert result.event_count == 6
    assert np.isfinite(result.final_equity if hasattr(result, "final_equity") else result.equity[-1])


def test_phase46d_sparse_session_reset_reuses_state_and_preserves_parity():
    _, _, _, _, compiled, runner = _replacement_fixture()
    session = runner.open_sparse_session(compiled)
    first = session.run_until(len(runner.idx) - 1)
    session.reset()
    second = session.run_until(len(runner.idx) - 1)
    assert session.next_bar == len(runner.idx)
    for name in (
        "final_equity",
        "final_position",
        "total_fee",
        "total_turnover",
        "fill_count",
        "event_count",
        "rejected_count",
        "canceled_count",
    ):
        assert getattr(first, name) == getattr(second, name)
    for name in (
        "wake_bar",
        "wake_kind",
        "fill_bar",
        "fill_order_id",
        "event_bar",
        "event_kind",
        "event_status",
    ):
        np.testing.assert_array_equal(getattr(first, name), getattr(second, name))
