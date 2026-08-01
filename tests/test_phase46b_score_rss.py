from __future__ import annotations

from pathlib import Path

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
from quantbt.backends._native_event_rust import RustBatchedRunner, NativeEventRustBackendError


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _fixture(rows: int = 48):
    index = pd.date_range("2024-01-01", periods=rows, freq="1h", tz="UTC")
    close = pd.Series(100.0 + np.arange(rows, dtype=np.float64) * 0.25, index=index)
    frame = pd.DataFrame(
        {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1_000.0,
        },
        index=index,
    )
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
            timestamp=index[2],
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            qty=1.0,
            tif=TimeInForce.GTC,
            order_id="entry",
        ),
        OrderCommand(
            timestamp=index[21],
            symbol="BTC",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            qty=1.0,
            tif=TimeInForce.GTC,
            reduce_only=True,
            order_id="exit",
        ),
    )
    compiled = backend.compile_order_commands(index, commands, symbols=["BTC"])
    return backend, frame, market, commands, compiled


def test_phase46b_python_compiled_score_matches_public_audit_scalars():
    backend, frame, market, commands, compiled = _fixture()
    scalar = backend.run_compiled_tape_score(frame.index, compiled, market_arrays=market)
    audit = backend.run_order_commands(
        datetime_index=frame.index,
        commands=commands,
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        symbols=["BTC"],
        market_arrays=market,
        compiled_commands=compiled,
        report_level="audit",
    )

    np.testing.assert_allclose(scalar.final_equity, audit.equity.iloc[-1], rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(scalar.final_positions[0], audit.positions["Position_BTC"].iloc[-1], rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(scalar.total_fee, audit.fees.sum(), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(scalar.total_turnover, audit.diagnostics["turnover"].sum(), rtol=0.0, atol=1e-12)
    assert scalar.fill_count == int(audit.metadata["lifecycle_counters"]["fill_count"])
    assert scalar.event_count == int(audit.metadata["lifecycle_counters"]["event_count"])
    assert scalar.rejected_count == int(audit.metadata["lifecycle_counters"]["rejected_count"])
    assert scalar.canceled_count == int(audit.metadata["lifecycle_counters"]["canceled_count"])
    np.testing.assert_allclose(scalar.max_initial_margin, audit.margin["initial_margin"].max(), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(scalar.max_maintenance_margin, audit.margin["maintenance_margin"].max(), rtol=0.0, atol=1e-12)
    assert scalar.metadata["score_pandas_materialized"] is False
    assert scalar.metadata["score_full_ledgers_materialized"] is False
    assert "accounting" not in scalar.__dict__ if hasattr(scalar, "__dict__") else True


def test_phase46b_prepared_and_compiled_signatures_are_hard_gates():
    backend, frame, market, _, compiled = _fixture()
    with pytest.raises(ValueError, match="prepared market_arrays"):
        backend.run_compiled_tape_score(frame.index, compiled, market_arrays=None)

    wrong_index = frame.index + pd.Timedelta(minutes=1)
    with pytest.raises(ValueError, match="prepared market arrays"):
        backend.run_compiled_tape_score(wrong_index, compiled, market_arrays=market)

    other_backend, other_frame, other_market, _, other_compiled = _fixture(rows=49)
    assert other_backend is not backend
    with pytest.raises(ValueError, match="prepared market arrays"):
        backend.run_compiled_tape_score(frame.index, other_compiled, market_arrays=other_market)


def test_phase46b_rust_scalar_matches_python_scalar_when_wheel_is_available():
    backend, frame, market, _, compiled = _fixture()
    try:
        runner = RustBatchedRunner(
            idx=frame.index,
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
    except (ImportError, OSError, NativeEventRustBackendError) as exc:
        pytest.skip(f"optional Rust wheel unavailable: {exc}")

    python_scalar = backend.run_compiled_tape_score(frame.index, compiled, market_arrays=market)
    rust_scalar = runner.run_tape_score(compiled)
    np.testing.assert_allclose(python_scalar.final_equity, rust_scalar.final_equity, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(python_scalar.final_positions[0], rust_scalar.final_position, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(python_scalar.total_fee, rust_scalar.total_fee, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(python_scalar.total_turnover, rust_scalar.total_turnover, rtol=0.0, atol=1e-12)
    assert python_scalar.fill_count == rust_scalar.fill_count
    assert python_scalar.event_count == rust_scalar.event_count
    assert python_scalar.rejected_count == rust_scalar.rejected_count
    assert python_scalar.canceled_count == rust_scalar.canceled_count
    np.testing.assert_allclose(python_scalar.max_initial_margin, rust_scalar.max_initial_margin, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(python_scalar.max_maintenance_margin, rust_scalar.max_maintenance_margin, rtol=0.0, atol=1e-12)


def test_phase46b_benchmark_declares_staged_rss_and_scalar_contract():
    script = (PROJECT_ROOT / "benchmarks/native_event/benchmark_phase46b_score_rss.py").read_text(encoding="utf-8")
    for field in (
        "rss_interpreter",
        "rss_after_import_quantbt",
        "rss_after_market_prepare",
        "rss_after_command_compile",
        "rss_after_runner_prepare",
        "peak_rss_during_run",
        "rss_after_run",
        "incremental_prepared_rss",
        "incremental_execution_peak",
        "full_parity_passed",
        "oracle_fingerprint",
        "python_fingerprint",
        "rust_fingerprint",
    ): 
        assert field in script
    assert "--repeats" in script
    assert "PLATEAU_REPEATS = 100" in script
