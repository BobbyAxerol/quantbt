from __future__ import annotations

import importlib.util
import sys
from types import ModuleType

import numpy as np
import pandas as pd
import pytest

from quantbt import OrderAction, OrderCommand, OrderSide, OrderType, TimeInForce
from quantbt.backends._native_event_rust import (
    NativeEventRustBackendError,
    compile_rust_r1_command_batch,
    validate_rust_r1_support,
)
from quantbt.core.constraints import build_quantity_constraints

from .conftest import ScheduledCommandStrategy, assert_native_event_full_parity, bars, run_reactive


def _interner():
    codes = {}

    def intern(value):
        if value is None:
            return -1
        return codes.setdefault(value, len(codes))

    return intern


def _nullable(value):
    return None if pd.isna(value) else value


def _session_event_records(events):
    return [
        (
            pd.Timestamp(event.timestamp),
            int(event.bar),
            event.event_name,
            int(event.status),
            event.order_id,
            event.target_order_id,
        )
        for event in events
    ]


def _replay_event_records(result):
    frame = result.metadata["order_events"]
    return [
        (
            pd.Timestamp(row["timestamp"]),
            int(row["bar"]),
            str(row["event_name"]),
            int(row["status"]),
            _nullable(row.get("order_id")),
            _nullable(row.get("target_order_id")),
        )
        for row in frame.to_dict("records")
    ]


def test_rust_r1_compiles_contiguous_place_cancel_buffers() -> None:
    df = bars(4)
    commands = (
        OrderCommand(
            timestamp=df.index[0],
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            qty=1.25,
            price=99.5,
            tif=TimeInForce.GTC,
            order_id="entry",
        ),
        OrderCommand(timestamp=df.index[0], action=OrderAction.CANCEL, target_order_id="entry"),
    )
    batch = compile_rust_r1_command_batch(commands, symbol="BTC", intern_id=_interner())

    assert batch.codes.dtype == np.int64
    assert batch.values.dtype == np.float64
    assert batch.codes.flags.c_contiguous
    assert batch.values.flags.c_contiguous
    assert batch.codes.shape == (2, 8)
    assert batch.values.shape == (2, 3)
    np.testing.assert_array_equal(batch.codes[:, 0], np.array([0, 1], dtype=np.int64))
    np.testing.assert_allclose(batch.values[0], np.array([1.25, 99.5, 0.0]))


def test_rust_r1_rejects_features_not_in_certified_scope() -> None:
    constraints = build_quantity_constraints(["BTC"])
    with pytest.raises(NativeEventRustBackendError, match="exactly one symbol"):
        validate_rust_r1_support(
            symbols=["BTC", "ETH"], constraints=constraints, use_funding=False, maintenance_ratio=0.0
        )
    with pytest.raises(NativeEventRustBackendError, match="funding"):
        validate_rust_r1_support(symbols=["BTC"], constraints=constraints, use_funding=True, maintenance_ratio=0.0)
    with pytest.raises(NativeEventRustBackendError, match="liquidation"):
        validate_rust_r1_support(symbols=["BTC"], constraints=constraints, use_funding=False, maintenance_ratio=0.005)


def test_rust_r1_rejects_non_gtc_or_contingent_commands() -> None:
    df = bars(4)
    with pytest.raises(NativeEventRustBackendError, match="GTC"):
        compile_rust_r1_command_batch(
            [
                OrderCommand(
                    timestamp=df.index[0],
                    symbol="BTC",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    qty=1.0,
                    tif=TimeInForce.IOC,
                )
            ],
            symbol="BTC",
            intern_id=_interner(),
        )


def test_rust_r2_compiles_stop_amend_replace_reduce_only_and_quantity_constraints() -> None:
    df = bars(4)
    commands = (
        OrderCommand(
            timestamp=df.index[0],
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.STOP_MARKET,
            qty=1.25,
            trigger_price=101.0,
            tif=TimeInForce.GTC,
            order_id="entry-stop",
        ),
        OrderCommand(
            timestamp=df.index[0],
            action=OrderAction.AMEND,
            target_order_id="entry-stop",
            trigger_price=102.0,
        ),
        OrderCommand(
            timestamp=df.index[0],
            action=OrderAction.REPLACE,
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.STOP_LIMIT,
            qty=1.5,
            price=102.0,
            trigger_price=103.0,
            tif=TimeInForce.GTC,
            order_id="entry-replaced",
            target_order_id="entry-stop",
        ),
        OrderCommand(
            timestamp=df.index[0],
            symbol="BTC",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            qty=2.0,
            tif=TimeInForce.GTC,
            reduce_only=True,
            order_id="reduce",
        ),
    )
    batch = compile_rust_r1_command_batch(commands, symbol="BTC", intern_id=_interner())

    np.testing.assert_array_equal(batch.codes[:, 0], np.array([0, 2, 3, 0], dtype=np.int64))
    assert batch.codes[0, 2] == 2
    assert batch.codes[2, 2] == 3
    assert batch.codes[1, 6] == 4
    assert batch.codes[3, 3] == 1
    np.testing.assert_allclose(batch.values[0], np.array([1.25, 0.0, 101.0]))
    np.testing.assert_allclose(batch.values[1], np.array([0.0, 0.0, 102.0]))


def test_rust_r2_accepts_shared_quantity_constraints() -> None:
    constraints = build_quantity_constraints(["BTC"], qty_step=0.25, min_qty=0.25, min_notional=10.0)
    validate_rust_r1_support(symbols=["BTC"], constraints=constraints, use_funding=False, maintenance_ratio=0.0)


def test_native_event_r1_routes_a_compatible_extension_through_callback_boundaries(monkeypatch) -> None:
    class FakeReactiveSessionCore:
        def __init__(self, *args):
            self.equity = float(args[11])

        def step(self, bar_index, command_codes, command_values, command_expiry):
            return {
                "equity": self.equity,
                "position": 0.0,
                "fee": 0.0,
                "turnover": 0.0,
                "initial_margin": 0.0,
                "maintenance_margin": 0.0,
                "fills": [],
                "events": [],
                "active_orders": [],
            }

    module = ModuleType("_quantbt_native")
    module.version = lambda: "0.3.0"
    module.api_version = lambda: "0.3"
    module.capabilities = lambda: {
        "r0_import_smoke": True,
        "reactive_session": True,
        "r2_stop_amend_replace_reduce_only_constraints": True,
    }
    module.ReactiveSessionCore = FakeReactiveSessionCore
    monkeypatch.setitem(sys.modules, "_quantbt_native", module)
    monkeypatch.setenv("QUANTBT_NATIVE_BACKEND", "rust")

    result = run_reactive(
        "single_pass",
        ScheduledCommandStrategy({}),
        data=bars(5),
        maintenance_ratio=0.0,
        use_funding=False,
        report_level="minimal",
        reactive_execution_mode="fast",
    )

    assert result.metadata["native_event_backend_resolved"] == "rust"
    assert result.metadata["reactive_kernel_mode"] == "single_pass"


@pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native R1 wheel is not installed in this environment",
)
def test_native_event_rust_r1_matches_replay_for_market_limit_and_cancel(monkeypatch) -> None:
    df = bars(10)
    t0 = df.index[0]
    schedule = {
        0: [
            OrderCommand(
                timestamp=t0,
                symbol="BTC",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                qty=1.0,
                tif=TimeInForce.GTC,
                order_id="entry",
            ),
            OrderCommand(
                timestamp=t0,
                symbol="BTC",
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                qty=0.5,
                price=500.0,
                tif=TimeInForce.GTC,
                order_id="cancel-me",
            ),
        ],
        1: [OrderCommand(timestamp=t0, action=OrderAction.CANCEL, target_order_id="cancel-me")],
        3: [
            OrderCommand(
                timestamp=t0,
                symbol="BTC",
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                qty=1.0,
                price=float(df["high"].iloc[4] - 0.1),
                tif=TimeInForce.GTC,
                order_id="exit",
            )
        ],
    }
    kwargs = {
        "initial_capital": 10_000,
        "leverage": 5,
        "maintenance_ratio": 0.0,
        "use_funding": False,
        "fee_rate": 0.0002,
        "report_level": "standard",
        "reactive_execution_mode": "fast",
    }
    monkeypatch.setenv("QUANTBT_NATIVE_BACKEND", "rust")
    rust = run_reactive("single_pass", ScheduledCommandStrategy(schedule), data=df, **kwargs)
    monkeypatch.setenv("QUANTBT_NATIVE_BACKEND", "replay_certified")
    replay = run_reactive("single_pass", ScheduledCommandStrategy(schedule), data=df, **kwargs)

    assert rust.metadata["native_event_backend_resolved"] == "rust"
    assert_native_event_full_parity(rust, replay)
    assert [(fill.order_id, fill.qty, fill.price, fill.fee) for fill in rust.metadata["rust_r1_session_fills"]] == [
        (fill.order_id, fill.qty, fill.price, fill.fee) for fill in replay.fills
    ]
    assert _session_event_records(rust.metadata["rust_r1_session_events"]) == _replay_event_records(replay)


@pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native R2 wheel is not installed in this environment",
)
def test_native_event_rust_r2_matches_replay_for_stop_amend_replace_reduce_only_and_constraints(monkeypatch) -> None:
    df = bars(12)
    t0 = df.index[0]
    schedule = {
        0: [
            OrderCommand(
                timestamp=t0,
                symbol="BTC",
                side=OrderSide.BUY,
                order_type=OrderType.STOP_MARKET,
                qty=1.37,
                trigger_price=float(df["high"].iloc[1] - 0.1),
                tif=TimeInForce.GTC,
                order_id="entry-stop",
            ),
        ],
        1: [
            OrderCommand(
                timestamp=t0,
                action=OrderAction.AMEND,
                target_order_id="entry-stop",
                trigger_price=float(df["high"].iloc[2] - 0.1),
            ),
        ],
        2: [
            OrderCommand(
                timestamp=t0,
                action=OrderAction.REPLACE,
                symbol="BTC",
                side=OrderSide.BUY,
                order_type=OrderType.STOP_LIMIT,
                qty=1.63,
                price=float(df["low"].iloc[3] + 0.1),
                trigger_price=float(df["high"].iloc[3] - 0.1),
                tif=TimeInForce.GTC,
                order_id="entry-replaced",
                target_order_id="entry-stop",
            ),
        ],
        4: [
            OrderCommand(
                timestamp=t0,
                symbol="BTC",
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                qty=3.0,
                tif=TimeInForce.GTC,
                reduce_only=True,
                order_id="reduce",
            ),
        ],
    }
    kwargs = {
        "initial_capital": 10_000,
        "leverage": 5,
        "maintenance_ratio": 0.0,
        "use_funding": False,
        "fee_rate": 0.0002,
        "qty_step": 0.25,
        "min_qty": 0.25,
        "report_level": "standard",
        "reactive_execution_mode": "fast",
    }
    monkeypatch.setenv("QUANTBT_NATIVE_BACKEND", "rust")
    rust = run_reactive("single_pass", ScheduledCommandStrategy(schedule), data=df, **kwargs)
    monkeypatch.setenv("QUANTBT_NATIVE_BACKEND", "replay_certified")
    replay = run_reactive("single_pass", ScheduledCommandStrategy(schedule), data=df, **kwargs)

    assert rust.metadata["native_event_backend_resolved"] == "rust"
    assert_native_event_full_parity(rust, replay)
    assert [(fill.order_id, fill.qty, fill.price, fill.fee) for fill in rust.metadata["rust_r1_session_fills"]] == [
        (fill.order_id, fill.qty, fill.price, fill.fee) for fill in replay.fills
    ]
    assert _session_event_records(rust.metadata["rust_r1_session_events"]) == _replay_event_records(replay)
