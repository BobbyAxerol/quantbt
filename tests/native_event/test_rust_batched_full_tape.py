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
    RustBatchedRunner,
    TimeInForce,
)
from quantbt.backends._native_event_rust import (
    NativeEventRustBackendError,
    compile_rust_batched_tape,
    probe_native_event_rust_extension,
)


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native batched wheel is not installed in this environment",
)


def _bars(n: int = 12) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    close = pd.Series(100.0 + np.arange(n, dtype=np.float64) * 0.5, index=index)
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


def _fixture():
    frame = _bars()
    index = frame.index
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
            order_type=OrderType.MARKET,
            qty=1.0,
            tif=TimeInForce.GTC,
            order_id="entry",
        ),
        OrderCommand(
            timestamp=index[2],
            action=OrderAction.PLACE,
            symbol="BTC",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            qty=0.5,
            price=103.0,
            tif=TimeInForce.GTC,
            order_id="partial-exit",
        ),
        OrderCommand(
            timestamp=index[3],
            action=OrderAction.CANCEL,
            target_order_id="partial-exit",
        ),
        OrderCommand(
            timestamp=index[4],
            symbol="BTC",
            side=OrderSide.SELL,
            order_type=OrderType.STOP_MARKET,
            qty=1.0,
            trigger_price=102.0,
            tif=TimeInForce.GTC,
            reduce_only=True,
            order_id="stop-exit",
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
        maintenance_ratio=0.0,
        slippage=0.0002,
        use_funding=False,
    )
    return backend, frame, market, commands, compiled, runner


def test_extension_advertises_batched_tape_contract():
    status = probe_native_event_rust_extension()
    assert status.available and status.compatible and status.executable
    assert status.capabilities["rust_batched_tape"] is True
    assert status.capabilities["rust_batched_tape_score"] is True
    assert status.capabilities["rust_batched_tape_audit"] is True


def test_tape_compilation_is_contiguous_and_bar_indexed():
    _, _, _, _, compiled, _ = _fixture()
    ptr, codes, values, expiry = compile_rust_batched_tape(compiled, symbol="BTC")
    assert ptr.flags.c_contiguous
    assert codes.flags.c_contiguous
    assert values.flags.c_contiguous
    assert expiry.flags.c_contiguous
    assert ptr.shape == (13,)
    assert ptr[-1] == len(compiled.sorted_commands)
    assert codes.shape == (4, 8)
    assert values.shape == (4, 3)
    np.testing.assert_array_equal(codes[:, 7], np.arange(4, dtype=np.int64))
    np.testing.assert_array_equal(np.flatnonzero(np.diff(ptr)), np.array([1, 2, 3, 4]))


def test_rust_batched_score_and_audit_have_exact_internal_parity():
    _, _, _, _, compiled, runner = _fixture()
    score = runner.run_tape_score(compiled)
    audit = runner.run_tape_audit(compiled)

    assert score.metadata == {"backend": "rust_batched", "mode": "score", "pycalls": 1}
    assert audit.metadata == {"backend": "rust_batched", "mode": "audit", "pycalls": 1}
    np.testing.assert_allclose(score.final_equity, audit.equity[-1], rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(score.final_position, audit.positions[-1], rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(score.total_fee, audit.total_fee, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(score.total_turnover, audit.total_turnover, rtol=0.0, atol=1e-12)
    assert score.fill_count == audit.fill_count
    assert score.event_count == audit.event_count
    assert score.rejected_count == audit.rejected_count
    assert score.canceled_count == audit.canceled_count
    for name in (
        "equity",
        "positions",
        "fees",
        "turnover",
        "initial_margin",
        "maintenance_margin",
        "fill_bar",
        "fill_order_id",
        "fill_side",
        "fill_qty",
        "fill_price",
        "fill_fee",
        "event_bar",
        "event_kind",
        "event_status",
        "event_order_id",
        "event_target_id",
    ):
        assert getattr(audit, name).flags.c_contiguous


def test_rust_batched_matches_python_v2_for_certified_tape():
    backend, frame, market, commands, compiled, runner = _fixture()
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
        contract_size=1.0,
        leverage=5.0,
        fee_rate=0.0002,
        report_level="minimal",
    )

    np.testing.assert_allclose(rust.equity, python.equity.to_numpy(), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(rust.positions, python.positions["Position_BTC"].to_numpy(), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(rust.fees, python.fees.to_numpy(), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(rust.turnover, python.diagnostics["turnover"].to_numpy(), rtol=0.0, atol=1e-12)
    assert rust.fill_count == int(python.metadata["lifecycle_counters"]["fill_count"])
    assert rust.event_count == int(python.metadata["lifecycle_counters"]["event_count"])
    assert rust.rejected_count == int(python.metadata["lifecycle_counters"]["rejected_count"])
    np.testing.assert_allclose(rust.total_fee, python.fees.sum(), rtol=0.0, atol=1e-12)


def test_batched_runner_rejects_unsupported_accounting_before_execution():
    _, _, market, _, compiled, _ = _fixture()
    with pytest.raises(NativeEventRustBackendError, match="funding"):
        RustBatchedRunner(
            idx=market.idx,
            symbols=["BTC"],
            market_arrays=market,
            use_funding=True,
        )
    with pytest.raises(NativeEventRustBackendError, match="liquidation"):
        RustBatchedRunner(
            idx=market.idx,
            symbols=["BTC"],
            market_arrays=market,
            maintenance_ratio=0.005,
        )
    assert compiled.n_commands == 4
