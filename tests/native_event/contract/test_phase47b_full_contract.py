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
    OrderAction,
    OrderCommand,
    OrderSide,
    OrderType,
    TimeInForce,
)


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native full-contract wheel is not installed",
)


def _market(n: int = 24):
    index = pd.date_range("2024-01-01 07:00", periods=n, freq="1h", tz="UTC")
    a = pd.Series(100.0 + np.arange(n, dtype=np.float64) * 0.25, index=index)
    b = pd.Series(200.0 - np.arange(n, dtype=np.float64) * 0.10, index=index)
    return index, {"A": a, "B": b}, {
        "A": a + 2.0, "B": b + 2.0,
    }, {"A": a - 2.0, "B": b - 2.0}


def _backend(backend: str, *, initial_capital: float = 10_000.0, leverage: float = 5.0, maintenance_ratio: float = 0.005):
    return NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=initial_capital, leverage=leverage, maintenance_ratio=maintenance_ratio),
            execution=ExecutionConfig(slippage_bps=2.0),
            fee_rate=0.0002,
            use_funding=True,
            native_backend=backend,
            report_level="audit",
        )
    )


def _run(
    backend: str,
    index,
    closes,
    highs,
    lows,
    funding,
    commands,
    *,
    qty_step=None,
    min_qty=None,
    min_notional=None,
    **account,
):
    engine = _backend(backend, **account)
    market = engine.prepare_market_arrays(
        index, closes=closes, highs=highs, lows=lows,
        funding_rate=funding, symbols=["A", "B"],
    )
    compiled = engine.compile_order_commands(index, commands, symbols=["A", "B"])
    return engine.run_order_commands(
        datetime_index=index,
        commands=commands,
        closes=closes,
        highs=highs,
        lows=lows,
        funding_rate=funding,
        contract_size={"A": 1.0, "B": 1.0},
        symbols=["A", "B"],
        market_arrays=market,
        compiled_commands=compiled,
        report_level="audit",
        qty_step=qty_step,
        min_qty=min_qty,
        min_notional=min_notional,
    )


def _event_signature(result):
    """Normalize the Python compact ledger and Rust report to one ABI view."""

    metadata = result.metadata
    if "compact_order_event_ledger" in metadata:
        ledger = metadata["compact_order_event_ledger"]
        commands = metadata["compact_command_ledger"]
        ids = tuple(metadata["id_values"])

        def command_id(command_index):
            if int(command_index) < 0:
                return None
            code = int(commands.order_id_code[int(command_index)])
            return ids[code] if 0 <= code < len(ids) else None

        return tuple(
            (
                int(bar),
                int(kind),
                int(status),
                command_id(command_index),
                command_id(related_index),
                int(commands.reject_code[int(command_index)]) if int(command_index) >= 0 else 0,
            )
            for bar, kind, status, command_index, related_index in zip(
                ledger.bar,
                ledger.event_type,
                ledger.status,
                ledger.command_index,
                ledger.related_command_index,
            )
        )

    report = metadata["order_report"]
    return tuple(
        (
            int(row.bar),
            int(row.event_kind),
            int(row.event_status),
            row.order_id,
            row.target_order_id,
            int(row.reject_code),
        )
        for row in report.itertuples(index=False)
    )


def _assert_numeric_parity(left, right):
    np.testing.assert_allclose(left.equity.to_numpy(), right.equity.to_numpy(), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(left.positions.to_numpy(), right.positions.to_numpy(), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(left.fees.to_numpy(), right.fees.to_numpy(), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(left.funding.to_numpy(), right.funding.to_numpy(), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(left.margin.to_numpy(), right.margin.to_numpy(), rtol=0.0, atol=1e-12)
    assert len(left.fills) == len(right.fills)
    assert _event_signature(left) == _event_signature(right)
    assert _fill_signature(left) == _fill_signature(right)


def _fill_signature(result):
    metadata = result.metadata
    if "compact_fill_ledger" in metadata:
        ledger = metadata["compact_fill_ledger"]
        ids = tuple(metadata["id_values"])
        symbols = tuple(ledger.symbols)

        def decode(values, code):
            code = int(code)
            return values[code] if 0 <= code < len(values) else None

        return tuple(
            (
                int(bar),
                decode(ids, order_code),
                decode(symbols, symbol_code),
                int(side),
                float(qty),
                float(price),
                float(fee),
            )
            for bar, order_code, symbol_code, side, qty, price, fee in zip(
                ledger.bar,
                ledger.order_id_code,
                ledger.symbol_code,
                ledger.side,
                ledger.qty,
                ledger.price,
                ledger.fee,
            )
        )

    report = metadata["fills_report"]
    return tuple(
        (
            int(row.bar), row.order_id, row.symbol,
            1 if row.side == "BUY" else -1,
            float(row.qty), float(row.price), float(row.fee),
        )
        for row in report.itertuples(index=False)
    )
    left_counters = left.metadata["lifecycle_counters"]
    right_counters = right.metadata["lifecycle_counters"]
    for key in ("fill_count", "event_count", "rejected_count", "canceled_count"):
        assert left_counters[key] == right_counters[key]


def test_phase47b_full_contract_multisymbol_funding_parent_and_oco_parity():
    index, closes, highs, lows = _market()
    funding = {
        "A": pd.Series(0.0, index=index),
        "B": pd.Series(0.0, index=index),
    }
    funding["A"].iloc[9] = 0.001  # 16:00 UTC, after the entry at 08:00.
    commands = (
        OrderCommand(
            timestamp=index[1], symbol="A", side=OrderSide.BUY,
            order_type=OrderType.MARKET, qty=2.0, order_id="entry-a",
        ),
        OrderCommand(
            timestamp=index[1], symbol="B", side=OrderSide.SELL,
            order_type=OrderType.MARKET, qty=1.0, order_id="entry-b",
        ),
        OrderCommand(
            timestamp=index[2], symbol="A", side=OrderSide.SELL,
            order_type=OrderType.LIMIT, qty=2.0, price=100.25,
            reduce_only=True, order_id="tp-a", parent_order_id="entry-a",
            activation_policy="on_parent_first_fill", oco_group_id="exit-a",
        ),
        OrderCommand(
            timestamp=index[2], symbol="A", side=OrderSide.SELL,
            order_type=OrderType.STOP_MARKET, qty=2.0, trigger_price=99.0,
            reduce_only=True, order_id="sl-a", parent_order_id="entry-a",
            activation_policy="on_parent_first_fill", oco_group_id="exit-a",
        ),
    )
    python = _run("python", index, closes, highs, lows, funding, commands)
    rust = _run("rust", index, closes, highs, lows, funding, commands)
    _assert_numeric_parity(python, rust)
    assert rust.metadata["rust_contract"] == "native_event_v2_full_contract"
    assert float(rust.funding.sum()) > 0.0


def test_phase47b_full_contract_tif_expiry_cancel_all_parity():
    index, closes, highs, lows = _market(12)
    zero = {symbol: pd.Series(0.0, index=index) for symbol in closes}
    commands = (
        OrderCommand(
            timestamp=index[1], symbol="A", side=OrderSide.BUY,
            order_type=OrderType.LIMIT, qty=1.0, price=1.0,
            tif=TimeInForce.IOC, order_id="ioc",
        ),
        OrderCommand(
            timestamp=index[1], symbol="A", side=OrderSide.BUY,
            order_type=OrderType.LIMIT, qty=1.0, price=1.0,
            tif=TimeInForce.GTD, expires_at=index[4], order_id="gtd",
        ),
        OrderCommand(
            timestamp=index[3], action=OrderAction.CANCEL_ALL,
            symbol="A", order_id="cancel-all",
        ),
    )
    python = _run("python", index, closes, highs, lows, zero, commands)
    rust = _run("rust", index, closes, highs, lows, zero, commands)
    _assert_numeric_parity(python, rust)
    assert python.metadata["lifecycle_counters"]["canceled_count"] == rust.metadata["lifecycle_counters"]["canceled_count"]


def test_phase47b_full_contract_gtd_expiry_event_parity():
    index, closes, highs, lows = _market(10)
    zero = {symbol: pd.Series(0.0, index=index) for symbol in closes}
    commands = (
        OrderCommand(
            timestamp=index[1], symbol="A", side=OrderSide.BUY,
            order_type=OrderType.LIMIT, qty=1.0, price=1.0,
            tif=TimeInForce.GTD, expires_at=index[4], order_id="expires",
        ),
    )
    python = _run("python", index, closes, highs, lows, zero, commands)
    rust = _run("rust", index, closes, highs, lows, zero, commands)
    _assert_numeric_parity(python, rust)
    assert rust.metadata["lifecycle_counters"]["event_count"] == 2


def test_phase47b_full_contract_intrabar_liquidation_parity():
    index = pd.date_range("2024-01-01", periods=5, freq="1h", tz="UTC")
    close = pd.Series([100.0, 100.0, 100.0, 100.0, 100.0], index=index)
    high = close + 1.0
    low = pd.Series([99.0, 99.0, 10.0, 99.0, 99.0], index=index)
    closes = {"A": close, "B": close}
    highs = {"A": high, "B": high}
    lows = {"A": low, "B": low}
    zero = {"A": pd.Series(0.0, index=index), "B": pd.Series(0.0, index=index)}
    commands = (
        OrderCommand(timestamp=index[1], symbol="A", side=OrderSide.BUY,
                     order_type=OrderType.MARKET, qty=2.0, order_id="levered-long"),
    )
    python = _run("python", index, closes, highs, lows, zero, commands, initial_capital=100.0, leverage=10.0)
    rust = _run("rust", index, closes, highs, lows, zero, commands, initial_capital=100.0, leverage=10.0)
    _assert_numeric_parity(python, rust)
    assert python.liquidated is True
    assert rust.liquidated is True
    assert python.metadata["liquidation_reason"] == rust.metadata["liquidation_reason"]


def test_phase47b_full_contract_replace_alias_and_amend_parity():
    index, closes, highs, lows = _market(10)
    zero = {symbol: pd.Series(0.0, index=index) for symbol in closes}
    commands = (
        OrderCommand(
            timestamp=index[1], symbol="A", side=OrderSide.BUY,
            order_type=OrderType.LIMIT, qty=1.0, price=1.0, order_id="old",
        ),
        OrderCommand(
            timestamp=index[2], symbol="A", side=OrderSide.BUY,
            order_type=OrderType.LIMIT, qty=2.0, price=1.0,
            order_id="new", target_order_id="old", action=OrderAction.REPLACE,
        ),
        # Python's compiler aliases the replaced target to the replacement
        # slot. This cancel must therefore cancel ``new`` in both backends.
        OrderCommand(
            timestamp=index[3], symbol="A", action=OrderAction.CANCEL,
            target_order_id="old",
        ),
    )
    python = _run("python", index, closes, highs, lows, zero, commands)
    rust = _run("rust", index, closes, highs, lows, zero, commands)
    _assert_numeric_parity(python, rust)


def test_phase47b_full_contract_order_types_tif_reduce_only_and_constraints_parity():
    index, closes, highs, lows = _market(14)
    zero = {symbol: pd.Series(0.0, index=index) for symbol in closes}
    commands = (
        OrderCommand(
            timestamp=index[1], symbol="A", side=OrderSide.BUY,
            order_type=OrderType.MARKET, qty=1.37, order_id="market-a",
        ),
        OrderCommand(
            timestamp=index[1], symbol="B", side=OrderSide.SELL,
            order_type=OrderType.LIMIT, qty=2.49, price=199.0,
            tif=TimeInForce.FOK, order_id="fok-b",
        ),
        OrderCommand(
            timestamp=index[2], symbol="A", side=OrderSide.SELL,
            order_type=OrderType.STOP_MARKET, qty=1.0, trigger_price=99.0,
            reduce_only=True, order_id="stop-a",
        ),
        OrderCommand(
            timestamp=index[2], symbol="B", side=OrderSide.SELL,
            order_type=OrderType.STOP_LIMIT, qty=1.0, price=199.5,
            trigger_price=199.8, tif=TimeInForce.IOC, order_id="stop-limit-b",
        ),
    )
    kwargs = {"A": 0.1, "B": 0.5}
    python = _run(
        "python", index, closes, highs, lows, zero, commands,
        qty_step=kwargs, min_qty={"A": 0.1, "B": 0.5},
    )
    rust = _run(
        "rust", index, closes, highs, lows, zero, commands,
        qty_step=kwargs, min_qty={"A": 0.1, "B": 0.5},
    )
    _assert_numeric_parity(python, rust)


def test_phase47b_full_capability_is_explicit_and_old_api_is_not_silent_fallback():
    import _quantbt_native

    capabilities = _quantbt_native.capabilities()
    required = {
        "native_event_v2_full_contract", "native_event_v2_multisymbol",
        "native_event_v2_funding", "native_event_v2_liquidation",
        "native_event_v2_cancel_all_oco", "native_event_v2_tif_expiry",
        "native_event_v2_relationships",
    }
    assert required.issubset({name for name, enabled in capabilities.items() if enabled})
    assert _quantbt_native.api_version() == "0.4"


def test_phase47b_reactive_rust_and_python_context_path_parity():
    index, closes, highs, lows = _market(16)
    funding = {symbol: pd.Series(0.0, index=index) for symbol in closes}

    class Strategy:
        def initialize(self, context):
            return (
                OrderCommand(timestamp=context.timestamp, symbol="A", side=OrderSide.BUY,
                             order_type=OrderType.MARKET, qty=1.0, order_id="a"),
                OrderCommand(timestamp=context.timestamp, symbol="B", side=OrderSide.SELL,
                             order_type=OrderType.MARKET, qty=1.0, order_id="b"),
            )

        def on_bar_close(self, context):
            if context.bar_index == 3:
                return (OrderCommand(timestamp=context.timestamp, action=OrderAction.CANCEL_ALL, symbol="A"),)
            return ()

    def run(backend):
        return NativeEventBackend(
            NativeEventConfig(
                account=AccountConfig(initial_capital=10_000.0, leverage=5.0, maintenance_ratio=0.005),
                execution=ExecutionConfig(slippage_bps=2.0), fee_rate=0.0002,
                use_funding=True, native_backend=backend, report_level="minimal",
            )
        ).run_strategy(
            index, Strategy(), closes, highs, lows, funding,
            symbols=["A", "B"], execution_mode="fast", reactive_kernel_mode="single_pass",
        )

    python = run("python")
    rust = run("rust")
    np.testing.assert_allclose(python.equity.to_numpy(), rust.equity.to_numpy(), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(python.positions.to_numpy(), rust.positions.to_numpy(), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(python.fees.to_numpy(), rust.fees.to_numpy(), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(python.funding.to_numpy(), rust.funding.to_numpy(), rtol=0.0, atol=1e-12)


def test_phase47b_reactive_active_snapshot_relationship_metadata_parity():
    index, closes, highs, lows = _market(8)
    zero = {symbol: pd.Series(0.0, index=index) for symbol in closes}

    class Strategy:
        def __init__(self):
            self.observed = []

        def initialize(self, context):
            return (
                OrderCommand(
                    timestamp=context.timestamp, symbol="A", side=OrderSide.BUY,
                    order_type=OrderType.MARKET, qty=1.0, order_id="parent",
                ),
                OrderCommand(
                    timestamp=context.timestamp, symbol="A", side=OrderSide.SELL,
                    order_type=OrderType.LIMIT, qty=1.0, price=1_000.0,
                    reduce_only=True, order_id="take-profit", parent_order_id="parent",
                    group_id="bracket", oco_group_id="bracket",
                    activation_policy="on_parent_first_fill",
                    tag="tp", metadata={"campaign_id": "grid-1", "level_id": "tp0"},
                ),
                OrderCommand(
                    timestamp=context.timestamp, symbol="A", side=OrderSide.SELL,
                    order_type=OrderType.STOP_MARKET, qty=1.0, trigger_price=1.0,
                    reduce_only=True, order_id="stop-loss", parent_order_id="parent",
                    group_id="bracket", oco_group_id="bracket",
                    activation_policy="on_parent_first_fill",
                    tag="sl", metadata={"campaign_id": "grid-1", "level_id": "sl0"},
                ),
            )

        def on_bar_close(self, context):
            if context.bar_index == 1:
                self.observed = [
                    (
                        order.order_id,
                        order.parent_order_id,
                        order.group_id,
                        order.oco_group_id,
                        order.tag,
                        order.campaign_id,
                        order.level_id,
                    )
                    for order in context.active_orders
                ]
            return ()

    def run(backend):
        strategy = Strategy()
        result = NativeEventBackend(
            NativeEventConfig(
                account=AccountConfig(initial_capital=10_000.0, leverage=5.0),
                execution=ExecutionConfig(slippage_bps=2.0), fee_rate=0.0002,
                use_funding=False, native_backend=backend, report_level="minimal",
            )
        ).run_strategy(
            index, strategy, closes, highs, lows, zero,
            symbols=["A", "B"], execution_mode="fast", reactive_kernel_mode="single_pass",
        )
        return result, tuple(sorted(strategy.observed))

    python, python_active = run("python")
    rust, rust_active = run("rust")
    np.testing.assert_allclose(python.equity.to_numpy(), rust.equity.to_numpy(), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(python.positions.to_numpy(), rust.positions.to_numpy(), rtol=0.0, atol=1e-12)
    assert python_active == rust_active == (
        ("stop-loss", "parent", "bracket", "bracket", "sl", "grid-1", "sl0"),
        ("take-profit", "parent", "bracket", "bracket", "tp", "grid-1", "tp0"),
    )
