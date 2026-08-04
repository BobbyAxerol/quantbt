from __future__ import annotations

import importlib.util

import numpy as np
import pytest

from quantbt import OrderCommand, OrderSide, OrderType, TimeInForce

from .conftest import SEED, ScheduledCommandStrategy, assert_native_event_full_parity, bars, run_reactive


def test_native_event_python_vs_replay_randomized():
    rng = np.random.default_rng(SEED)
    df = bars(64)
    schedule = {}
    long = False
    order_seq = 0
    for bar in range(0, len(df) - 2):
        commands = []
        if not long and rng.random() < 0.22:
            order_seq += 1
            order_type = OrderType.MARKET if rng.random() < 0.7 else OrderType.LIMIT
            commands.append(
                OrderCommand(
                    timestamp=df.index[bar],
                    symbol="BTC",
                    side=OrderSide.BUY,
                    order_type=order_type,
                    qty=float(rng.choice([0.25, 0.5, 1.0])),
                    price=float(df["close"].iloc[bar]) if order_type is OrderType.LIMIT else None,
                    tif=TimeInForce.IOC,
                    order_id=f"rnd-entry-{order_seq}",
                )
            )
            long = True
        elif long and rng.random() < 0.25:
            order_seq += 1
            commands.append(
                OrderCommand(
                    timestamp=df.index[bar],
                    symbol="BTC",
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    qty=0.25,
                    tif=TimeInForce.IOC,
                    reduce_only=True,
                    order_id=f"rnd-exit-{order_seq}",
                )
            )
            long = False
        if commands:
            schedule[bar] = commands

    strategy = ScheduledCommandStrategy(schedule)
    oracle = run_reactive("replay_certified", strategy, data=df)
    candidate = run_reactive("single_pass", ScheduledCommandStrategy(schedule), data=df)
    try:
        assert_native_event_full_parity(candidate, oracle)
    except AssertionError as exc:
        raise AssertionError(f"seed={SEED}") from exc


def test_native_event_rust_vs_replay_randomized():
    if importlib.util.find_spec("quantbt_native") is None and importlib.util.find_spec("_quantbt_native") is None:
        pytest.skip("quantbt-native extension is Phase 44; rust parity activates when the wheel exists")
    pytest.skip("rust native-event routing is not exposed until Phase 44")


def test_native_event_backend_fallback_without_extension():
    df = bars(8)
    strategy = ScheduledCommandStrategy(
        {
            0: [
                OrderCommand(
                    timestamp=df.index[0],
                    symbol="BTC",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    qty=1.0,
                    tif=TimeInForce.IOC,
                    order_id="entry",
                )
            ]
        }
    )

    result = run_reactive("single_pass", strategy, data=df)
    assert result.metadata["engine"] == "event_v2_reactive_single_pass"
    assert result.metadata["reactive_kernel_mode"] == "single_pass"


def test_native_event_backend_version_mismatch_falls_back():
    if importlib.util.find_spec("quantbt_native") is None and importlib.util.find_spec("_quantbt_native") is None:
        pytest.skip("native extension version negotiation is Phase 44; Python fallback is current baseline")
    pytest.skip("version mismatch fallback requires a native wheel test fixture")
