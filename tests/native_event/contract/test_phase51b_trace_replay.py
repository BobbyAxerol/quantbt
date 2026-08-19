from __future__ import annotations

import pandas as pd
import numpy as np

from quantbt import (
    AccountConfig,
    ExecutionConfig,
    NativeEventBackend,
    NativeEventConfig,
    OrderCommand,
    OrderSide,
    OrderType,
    TRACE_FIELDS,
    TraceReplayer,
    build_canonical_execution_trace,
    canonical_trace_fingerprint,
    compare_canonical_traces,
)
from quantbt.core.event_contracts import EVENT_LIFECYCLE_V3_NEXT_OPEN


def _market(periods: int = 12):
    index = pd.date_range("2026-01-01", periods=periods, freq="1h", tz="UTC")
    close = np.asarray([100.0, 102.0, 104.0, 101.0, 98.0, 103.0, 106.0, 105.0, 107.0, 106.0, 108.0, 109.0])
    return index, pd.DataFrame(
        {"open": close - 0.5, "high": close + 2.0, "low": close - 2.0, "close": close},
        index=index,
    )


def _run(backend: str, commands):
    index, frame = _market()
    engine = NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=10_000.0, leverage=5.0),
            execution=ExecutionConfig(slippage_bps=3.0),
            fee_rate=0.0005,
            report_level="audit",
            native_backend=backend,
            execution_contract=EVENT_LIFECYCLE_V3_NEXT_OPEN,
        )
    )
    return engine.run_order_commands(
        index, commands,
        closes={"BTC": frame["close"]}, highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]}, opens={"BTC": frame["open"]}, symbols=["BTC"],
    )


def _commands():
    index, _ = _market()
    return (
        OrderCommand(timestamp=index[1], symbol="BTC", side=OrderSide.BUY, order_type=OrderType.MARKET, qty=2, order_id="entry"),
        OrderCommand(timestamp=index[4], symbol="BTC", side=OrderSide.SELL, order_type=OrderType.LIMIT, qty=1, price=100, order_id="reduce"),
        OrderCommand(timestamp=index[7], symbol="BTC", side=OrderSide.SELL, order_type=OrderType.MARKET, qty=1, order_id="close"),
    )


def test_canonical_trace_python_rust_exact_discrete_and_numeric_projection():
    python = _run("python", _commands())
    rust = _run("rust", _commands())
    left = python.metadata["canonical_trace_v1"]
    right = rust.metadata["canonical_trace_v1"]

    assert tuple(left.columns) == TRACE_FIELDS
    assert compare_canonical_traces(left, right)["passed"] is True
    assert python.metadata["canonical_trace_fingerprint"] == rust.metadata["canonical_trace_fingerprint"]
    assert canonical_trace_fingerprint(left) == python.metadata["canonical_trace_fingerprint"]


def test_hash_only_projection_matches_materialized_trace_and_is_repeatable():
    result = _run("python", _commands())
    full = build_canonical_execution_trace(result, materialize=True)
    hash_only = build_canonical_execution_trace(result, materialize=False)
    repeated = build_canonical_execution_trace(result, materialize=True)

    assert hash_only.trace.empty
    assert hash_only.row_count == len(full.trace)
    assert hash_only.fingerprint == full.fingerprint == repeated.fingerprint
    pd.testing.assert_frame_equal(full.trace, repeated.trace, check_exact=True)


def test_trace_replayer_reconstructs_terminal_state_without_matcher():
    result = _run("python", _commands())
    trace = result.metadata["canonical_trace_v1"]
    replay = TraceReplayer().replay(trace)

    assert replay.passed is True
    assert replay.final_positions == {"0": float(result.positions["Position_BTC"].iloc[-1])}
    assert replay.final_equity == float(result.equity.iloc[-1])
    assert result.metadata["canonical_trace_replay_v1"]["passed"] is True


def test_trace_diff_reports_first_bar_phase_event_and_field():
    result = _run("python", _commands())
    left = result.metadata["canonical_trace_v1"]
    right = left.copy(deep=True)
    row = right.index[right["event_kind"] == "FILL_ACCOUNTING"][0]
    right.loc[row, "qty_delta"] = float(right.loc[row, "qty_delta"]) + 1.0

    report = compare_canonical_traces(left, right)
    assert report["passed"] is False
    assert report["bar"] == int(left.loc[row, "bar"])
    assert report["phase"] == "FILL_ACCOUNTING"
    assert report["event_kind"] == "FILL_ACCOUNTING"
    assert report["field"] == "qty_delta"


def test_trace_replayer_rejects_corrupt_position_transition():
    result = _run("python", _commands())
    trace = result.metadata["canonical_trace_v1"].copy(deep=True)
    row = trace.index[trace["event_kind"] == "FILL_ACCOUNTING"][0]
    trace.loc[row, "qty_before"] = 99.0

    replay = TraceReplayer().replay(trace)
    assert replay.passed is False
    assert any("fill position transition mismatch" in error for error in replay.errors)
