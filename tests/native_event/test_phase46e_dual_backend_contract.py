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
    QuantBTEndpoint,
)
from quantbt.backends.native_event import NativeEventScoreRequirements
from quantbt.backends._native_event_rust import (
    NativeEventRustBackendError,
    NativeEventRustExtensionStatus,
    resolve_native_event_backend,
)


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native batched wheel is not installed in this environment",
)


def _bars(n: int = 12) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    close = pd.Series(100.0 + np.arange(n, dtype=np.float64), index=index)
    return pd.DataFrame(
        {"open": close, "high": close + 2.0, "low": close - 2.0, "close": close, "volume": 1_000.0},
        index=index,
    )


def _backend(frame: pd.DataFrame, *, native_backend: str = "python") -> NativeEventBackend:
    return NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=10_000.0, leverage=5.0, maintenance_ratio=0.0),
            execution=ExecutionConfig(slippage_bps=2.0),
            fee_rate=0.0002,
            use_funding=False,
            native_backend=native_backend,
        )
    )


def _commands(index: pd.DatetimeIndex) -> tuple[OrderCommand, ...]:
    return (
        OrderCommand(
            timestamp=index[1],
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            qty=1.0,
            tif=TimeInForce.GTC,
            order_id="entry",
        ),
        OrderCommand(
            timestamp=index[3],
            symbol="BTC",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            qty=1.0,
            price=103.0,
            tif=TimeInForce.GTC,
            order_id="exit",
        ),
    )


def test_phase46e_selector_contract_is_explicit_and_auto_stays_python():
    status = NativeEventRustExtensionStatus(
        available=True,
        compatible=True,
        executable=True,
        version="test",
        api_version="0.3",
        capabilities={"reactive_session": True},
    )
    assert resolve_native_event_backend("python", extension_status=status).resolved == "python"
    assert resolve_native_event_backend("auto", extension_status=status).resolved == "python"
    assert resolve_native_event_backend("replay_certified", extension_status=status).resolved == "replay_certified"
    assert resolve_native_event_backend("rust", extension_status=status).resolved == "rust"


def test_phase46e_rust_explicit_tape_adapts_to_common_result_and_python_parity():
    frame = _bars()
    index = frame.index
    python_backend = _backend(frame, native_backend="python")
    market = python_backend.prepare_market_arrays(
        datetime_index=index,
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        symbols=["BTC"],
    )
    commands = _commands(index)
    compiled = python_backend.compile_order_commands(index, commands, symbols=["BTC"])
    python_result = python_backend.run_order_commands(
        datetime_index=index,
        commands=commands,
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        symbols=["BTC"],
        market_arrays=market,
        compiled_commands=compiled,
        report_level="audit",
    )
    rust_result = _backend(frame, native_backend="rust").run_order_commands(
        datetime_index=index,
        commands=commands,
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        symbols=["BTC"],
        market_arrays=market,
        compiled_commands=compiled,
        report_level="audit",
    )
    np.testing.assert_allclose(rust_result.equity, python_result.equity, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(rust_result.positions, python_result.positions, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(rust_result.fees, python_result.fees, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(rust_result.margin, python_result.margin, rtol=0.0, atol=1e-12)
    assert rust_result.metadata["native_event_backend_resolved"] == "rust"
    assert len(rust_result.fills) == 2
    assert len(rust_result.metadata["fills_report"]) == 2
    assert len(rust_result.metadata["order_report"]) >= 2
    report = rust_result.full_report()
    assert np.isfinite(float(report["final_equity"]))


def test_phase47b_rust_backend_executes_full_accounting_contract():
    frame = _bars()
    index = frame.index
    backend = NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=10_000.0, leverage=5.0, maintenance_ratio=0.005),
            execution=ExecutionConfig(),
            fee_rate=0.0002,
            use_funding=True,
            native_backend="rust",
        )
    )
    funding = pd.Series(0.0, index=index)
    funding.iloc[8] = 0.001
    result = backend.run_order_commands(
        datetime_index=index,
        commands=_commands(index),
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        funding_rate=funding,
        symbols=["BTC"],
        report_level="audit",
    )
    assert result.metadata["native_event_backend_resolved"] == "rust"
    assert "native_event_v2_full_contract" in result.metadata["native_event_rust_capabilities"]


class _MetadataOrderStrategy:
    native_context_requirements = {
        "fills": False,
        "events": False,
        "active_orders": False,
        "positions": False,
        "margin": False,
    }

    def on_bar_close(self, context):
        if context.bar_index == 1:
            return [
                OrderCommand(
                    timestamp=context.timestamp,
                    symbol="BTC",
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    qty=1.0,
                    price=1.0,
                    tif=TimeInForce.GTC,
                    order_id="pending",
                    metadata={"large_strategy_payload": "must_not_be_retained"},
                )
            ]
        return ()


def test_phase46e_scalar_contract_marks_compact_python_order_state():
    endpoint = QuantBTEndpoint.native_event_strategy(
        initial_capital=10_000.0,
        leverage=5.0,
        use_funding=False,
        fee_rate=0.0002,
        report_level="audit",
    )
    prepared = endpoint.prepare_native_event_strategy(data=_bars(), symbols=["BTC"])
    strategy = _MetadataOrderStrategy()
    score = prepared.score(
        strategy,
        score_requirements=NativeEventScoreRequirements.from_strategy(
            strategy,
            base=NativeEventScoreRequirements.scalar_score_contract(),
        ),
    )
    assert score.metadata["score_primitive_order_state"] is True
