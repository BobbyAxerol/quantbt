from __future__ import annotations

import importlib.util

import numpy as np
import pandas as pd
import pytest

from quantbt import (
    AccountConfig,
    ExecutionConfig,
    NativeEventBackend,
    NativeEventConfig,
    OrderCommand,
    OrderSide,
    OrderType,
    TimeInForce,
)
from quantbt.backends._native_event_rust import (
    RustFullCommandBuffer,
    RustFullRunner,
)
from quantbt.backends.native_event import NativeEventScoreRequirements


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native full-contract wheel is not installed in this environment",
)


def _bars(n: int = 16) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    close = pd.Series(100.0 + np.arange(n, dtype=np.float64), index=index)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 2.0,
            "low": close - 2.0,
            "close": close,
            "volume": 1_000.0,
        },
        index=index,
    )


def _runner(frame: pd.DataFrame, commands: tuple[OrderCommand, ...]) -> tuple[RustFullRunner, object]:
    backend = NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=10_000.0, leverage=5.0),
            execution=ExecutionConfig(slippage_bps=2.0),
            fee_rate=0.0002,
            native_backend="rust",
        )
    )
    market = backend.prepare_market_arrays(
        datetime_index=frame.index,
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        symbols=["BTC"],
    )
    compiled = backend.compile_order_commands(frame.index, commands, symbols=["BTC"])
    return (
        RustFullRunner(
            idx=frame.index,
            symbols=["BTC"],
            market_arrays=market,
            contract_sizes=np.array([1.0]),
            leverages=np.array([5.0]),
            fee_rates=np.array([0.0002]),
            initial_capital=10_000.0,
            maintenance_ratio=0.0,
            slippage=0.0002,
            use_funding=False,
        ),
        compiled,
    )


def test_phase48e_full_command_buffer_reuses_capacity_and_clears_explicitly():
    buffer = RustFullCommandBuffer()
    first_codes, first_values, first_expiry = buffer.reserve(3)
    first_codes[0, 0] = 7
    capacity = buffer.capacity
    second_codes, second_values, second_expiry = buffer.reserve(2)
    assert buffer.capacity == capacity
    assert first_codes is not second_codes
    assert second_codes.shape == (2, 16)
    assert second_values.shape == (2, 3)
    assert second_expiry.shape == (2,)
    assert np.all(second_codes == -1)
    assert np.all(second_values == 0.0)
    assert np.all(second_expiry == -1)
    assert buffer.commands_compiled == 5
    buffer.clear()
    assert buffer.capacity == 0
    assert buffer.commands_compiled == 0


def test_phase48e_full_runner_reset_and_tape_cache_are_exactly_reusable():
    frame = _bars()
    commands = (
        OrderCommand(
            timestamp=frame.index[1],
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            qty=1.0,
            tif=TimeInForce.GTC,
            order_id="entry",
        ),
        OrderCommand(
            timestamp=frame.index[4],
            symbol="BTC",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            qty=1.0,
            tif=TimeInForce.GTC,
            order_id="exit",
        ),
    )
    runner, compiled = _runner(frame, commands)
    first = runner.run_tape_score(compiled)
    assert "equity" not in first
    assert "fills" not in first
    info_after_first = runner.cache_info()
    second = runner.run_tape_score(compiled)
    info_after_second = runner.cache_info()
    for key in (
        "final_equity",
        "total_fee",
        "total_turnover",
        "fill_count",
        "event_count",
        "rejected_count",
        "canceled_count",
        "liquidated",
    ):
        assert getattr(first, key, first[key] if isinstance(first, dict) else None) == getattr(
            second, key, second[key] if isinstance(second, dict) else None
        )
    assert info_after_first["tape_cache_entries"] == 1
    assert info_after_second["tape_cache_entries"] == 1
    assert info_after_second["commands_compiled"] == info_after_first["commands_compiled"]
    runner.clear_caches()
    assert runner.cache_info()["tape_cache_bytes"] == 0
    assert runner.cache_info()["tape_cache_entries"] == 0


def test_phase48e_context_projection_mask_does_not_materialize_unused_state():
    frame = _bars()
    backend = NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=10_000.0, leverage=5.0),
            execution=ExecutionConfig(),
            fee_rate=0.0002,
            native_backend="rust",
        )
    )

    class ScalarStrategy:
        native_context_requirements = {
            "fills": False,
            "events": False,
            "active_orders": False,
            "positions": False,
            "margin": False,
        }

        def on_bar_close(self, context):
            assert context.fills_this_bar == ()
            assert context.order_events_this_bar == ()
            assert context.active_orders == ()
            assert context.positions == {}
            assert context.initial_margin == 0.0
            assert context.maintenance_margin == 0.0
            return ()

    strategy = ScalarStrategy()
    requirements = NativeEventScoreRequirements.from_strategy(
        strategy,
        base=NativeEventScoreRequirements.scalar_score_contract(),
    )
    score = backend.run_strategy_score(
        datetime_index=frame.index,
        strategy=strategy,
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        symbols=["BTC"],
        score_requirements=requirements,
    )
    counters = score.metadata["execution_counters"]
    assert counters["active_snapshot_materializations"] == 0
    # The runner may ask for bar zero once before and once during the normal
    # callback loop; the important contract is that no active snapshots cross
    # the boundary for this declaration.
    assert counters["contexts_materialized"] >= len(frame)
    assert score.metadata["score_primitive_order_state"] is True


def test_phase53a_terminal_arena_release_preserves_full_contract_parity():
    frame = _bars(192)
    commands = tuple(
        OrderCommand(
            timestamp=frame.index[bar],
            symbol="BTC",
            side=OrderSide.BUY if bar % 2 == 0 else OrderSide.SELL,
            order_type=OrderType.MARKET,
            qty=1.0,
            tif=TimeInForce.GTC,
            order_id=f"order-{bar}",
        )
        for bar in range(1, len(frame))
    )
    runner, compiled = _runner(frame, commands)
    rust = runner.run_tape_audit(compiled)
    arena = runner.cache_info()
    backend = NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=10_000.0, leverage=5.0),
            execution=ExecutionConfig(slippage_bps=2.0),
            fee_rate=0.0002,
        )
    )
    market = backend.prepare_market_arrays(
        datetime_index=frame.index,
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        symbols=["BTC"],
    )
    python = backend.run_order_commands(
        datetime_index=frame.index,
        commands=commands,
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        symbols=["BTC"],
        market_arrays=market,
        report_level="minimal",
    )
    np.testing.assert_allclose(rust.equity, python.equity.to_numpy(), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(
        rust.positions[:, 0],
        python.positions["Position_BTC"].to_numpy(),
        rtol=0.0,
        atol=1e-12,
    )
    np.testing.assert_allclose(rust.fees, python.fees.to_numpy(), rtol=0.0, atol=1e-12)
    assert rust.fill_count == len(commands)
    # Phase 53A replaces history-scaled compaction with generation-safe slot
    # release. The live book stays empty and the arena capacity plateaus even
    # though this tape created nearly two hundred terminal orders.
    assert arena["order_compactions"] == 0
    assert arena["terminal_orders_removed"] == len(commands)
    assert arena["order_arena_slots"] == 0
    assert arena["order_arena_capacity"] <= 4


def test_phase53a_score_compact_and_audit_profiles_preserve_accounting():
    frame = _bars(12)
    commands = (
        OrderCommand(
            timestamp=frame.index[1],
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            qty=1.0,
            tif=TimeInForce.GTC,
            order_id="entry",
        ),
        OrderCommand(
            timestamp=frame.index[4],
            symbol="BTC",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            qty=1.0,
            tif=TimeInForce.GTC,
            order_id="exit",
        ),
    )
    runner, compiled = _runner(frame, commands)
    score = runner.run_tape_score(compiled)
    compact = runner.run_tape_compact(compiled)
    audit = runner.run_tape_audit(compiled)

    assert "fill_bar" not in compact
    assert "event_bar" not in compact
    np.testing.assert_allclose(compact["equity"], audit.equity, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(compact["positions"], audit.positions, rtol=0.0, atol=1e-12)
    assert float(compact["final_equity"]) == float(score["final_equity"])
    assert int(compact["fill_count"]) == int(audit.fill_count)
    assert int(compact["event_count"]) == int(audit.event_count)
