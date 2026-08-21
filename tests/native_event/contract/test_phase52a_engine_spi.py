from __future__ import annotations

from dataclasses import fields

import numpy as np
import pandas as pd
import pytest

from quantbt import AccountConfig, ExecutionConfig, OrderCommand, OrderSide, OrderType
from quantbt.backends._native_event_rust import probe_native_event_rust_extension
from quantbt.engine_spi import EngineRunRequest, create_backend
from quantbt.planning import (
    BacktestRequest,
    RunProfile,
    StrategyMode,
    WorkloadClass,
    resolve_execution_plan,
)
from quantbt.preparation import prepare_native_event_lifecycle


def _prepared(backend: str, profile: RunProfile = RunProfile.AUDIT):
    index = pd.date_range("2026-01-01", periods=10, freq="1h", tz="UTC")
    close = pd.Series([100.0, 102.0, 104.0, 101.0, 98.0, 103.0, 106.0, 105.0, 107.0, 106.0], index=index)
    frame = pd.DataFrame(
        {
            "open": close - 0.5,
            "high": close + 2.0,
            "low": close - 2.0,
            "close": close,
            "volume": 10.0,
        },
        index=index,
    )
    commands = (
        OrderCommand(
            timestamp=index[1], symbol="BTC", side=OrderSide.BUY,
            order_type=OrderType.MARKET, qty=2.0, order_id="entry",
        ),
        OrderCommand(
            timestamp=index[4], symbol="BTC", side=OrderSide.SELL,
            order_type=OrderType.LIMIT, qty=1.0, price=100.0, order_id="reduce",
        ),
        OrderCommand(
            timestamp=index[7], symbol="BTC", side=OrderSide.SELL,
            order_type=OrderType.MARKET, qty=1.0, order_id="close",
        ),
    )
    request = BacktestRequest(
        endpoint_mode="orders",
        input_mode="orders",
        requested_backend=backend,
        execution_contract_id="event_lifecycle_v3_next_open",
        strategy_mode=StrategyMode.STATIC_COMMANDS,
        workload=WorkloadClass.STATIC_COMMAND_TAPE,
        profile=profile,
        report_level=profile.value,
        audit_sink="memory" if profile is RunProfile.AUDIT else "none",
        symbols=("BTC",),
        command_count=len(commands),
        trace_requested=profile is RunProfile.AUDIT,
        public_result=profile is not RunProfile.SCORE,
        required_capabilities=(
            "native_event_v2_full_contract",
            "event_lifecycle_v3_next_open",
        ) if backend == "rust" else (),
    )
    plan = resolve_execution_plan(request)
    preparation = prepare_native_event_lifecycle(
        plan=plan,
        datetime_index=index,
        commands=commands,
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        opens={"BTC": frame["open"]},
        volumes={"BTC": frame["volume"]},
        funding_rate=0.0001,
        symbols=["BTC"],
        contract_size=10.0,
        leverage=5.0,
        fee_rate=0.0005,
        account=AccountConfig(initial_capital=10_000.0, leverage=5.0),
        execution=ExecutionConfig(slippage_bps=3.0),
        use_funding=True,
    )
    return plan, preparation


def _run(backend: str, profile: RunProfile = RunProfile.AUDIT):
    plan, preparation = _prepared(backend, profile)
    engine = create_backend(plan.backend)
    session = engine.prepare(plan, preparation.prepared)
    raw = session.run(EngineRunRequest(run_id=1, output=plan.output, trace=plan.trace))
    return raw, session, plan, preparation


def _assert_no_pandas(value):
    assert not isinstance(value, (pd.Series, pd.DataFrame, pd.Index))
    if hasattr(value, "__dataclass_fields__"):
        for item in fields(value):
            _assert_no_pandas(getattr(value, item.name))
    elif isinstance(value, (tuple, list)):
        for item in value:
            _assert_no_pandas(item)


def test_python_spi_returns_readonly_pandas_free_raw_result():
    raw, _, plan, preparation = _run("python")

    _assert_no_pandas(raw)
    assert raw.plan_fingerprint == plan.plan_fingerprint
    assert raw.prepared_fingerprint == preparation.prepared.keys.combined
    assert raw.summary.fill_count == 3
    assert raw.paths is not None
    assert raw.fills is not None
    assert raw.events is not None
    assert raw.command_states is not None
    assert not raw.paths.equity.flags.writeable
    assert raw.diagnostics.prepare_calls == 1
    assert raw.diagnostics.run_calls == 1


def test_score_projection_retains_counts_without_detail_or_dense_paths():
    raw, _, plan, _ = _run("python", RunProfile.SCORE)

    assert raw.paths is None
    assert raw.fills is None
    assert raw.events is None
    assert raw.command_states is None
    assert raw.summary.fill_count == 3
    assert raw.summary.event_count > 0
    assert raw.diagnostics.retained_path_bytes == 0
    assert raw.diagnostics.retained_fill_bytes == 0
    assert raw.diagnostics.retained_event_bytes == 0
    assert raw.diagnostics.output_projection_fingerprint == plan.projection_fingerprint


def test_python_session_reset_rerun_is_exact_and_close_is_terminal():
    raw, session, plan, _ = _run("python")
    session.reset()
    repeated = session.run(EngineRunRequest(run_id=2, output=plan.output, trace=plan.trace))

    np.testing.assert_array_equal(raw.paths.equity, repeated.paths.equity)
    np.testing.assert_array_equal(raw.paths.positions, repeated.paths.positions)
    np.testing.assert_array_equal(raw.fills.price, repeated.fills.price)
    session.close()
    with pytest.raises(RuntimeError, match="closed"):
        session.run(EngineRunRequest(run_id=3, output=plan.output, trace=plan.trace))


@pytest.mark.skipif(
    not probe_native_event_rust_extension().executable,
    reason="installed native API 0.4 extension is unavailable",
)
def test_python_rust_spi_exact_paths_fills_and_score_summary():
    python, _, _, _ = _run("python")
    rust, _, _, _ = _run("rust")

    np.testing.assert_allclose(python.paths.equity, rust.paths.equity, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(python.paths.positions, rust.paths.positions, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(python.paths.fees, rust.paths.fees, rtol=0.0, atol=1e-12)
    np.testing.assert_array_equal(python.fills.bar, rust.fills.bar)
    np.testing.assert_allclose(python.fills.price, rust.fills.price, rtol=0.0, atol=1e-12)
    assert python.summary == rust.summary

    python_score, _, _, _ = _run("python", RunProfile.SCORE)
    rust_score, _, _, _ = _run("rust", RunProfile.SCORE)
    assert python_score.summary == rust_score.summary
