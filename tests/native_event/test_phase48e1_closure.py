from __future__ import annotations

import importlib.util

import numpy as np
import pandas as pd
import pytest

import _quantbt_native

from quantbt import OrderCommand, OrderSide, OrderType, TimeInForce
from quantbt.backends._native_event_rust import RustFullRunner

from .test_phase48e_reuse import _bars, _runner


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native full-contract wheel is not installed in this environment",
)


def _prepared_core(frame: pd.DataFrame):
    n = len(frame)
    return _quantbt_native.FullPreparedMarketCore(
        np.ascontiguousarray(frame.index.asi8, dtype=np.int64),
        np.ascontiguousarray(frame[["open"]].to_numpy(), dtype=np.float64),
        np.ascontiguousarray(frame[["high"]].to_numpy(), dtype=np.float64),
        np.ascontiguousarray(frame[["low"]].to_numpy(), dtype=np.float64),
        np.ascontiguousarray(frame[["close"]].to_numpy(), dtype=np.float64),
        np.ascontiguousarray(frame[["volume"]].to_numpy(), dtype=np.float64),
        np.zeros((n, 1), dtype=np.float64),
        np.zeros(n, dtype=np.bool_),
    )


def _session(frame: pd.DataFrame):
    return _quantbt_native.FullReactiveSessionCore.from_prepared(
        _prepared_core(frame),
        np.array([1.0], dtype=np.float64),
        np.array([5.0], dtype=np.float64),
        np.array([0.0002], dtype=np.float64),
        10_000.0,
        0.0,
        0.0002,
        False,
    )


def _entry_batch():
    codes = np.full((1, 16), -1, dtype=np.int64)
    values = np.zeros((1, 3), dtype=np.float64)
    expiry = np.full(1, -1, dtype=np.int64)
    codes[0, :7] = [0, 0, 1, 0, 0, 0, 7]
    codes[0, 11] = 0
    codes[0, 12] = 0
    values[0, 0] = 1.0
    return codes, values, expiry


def test_phase48e1_typed_score_is_count_only_and_typed_audit_projects_rows():
    frame = _bars(4)
    codes, values, expiry = _entry_batch()

    score_session = _session(frame)
    score_session.set_output_mask(1)
    score = score_session.step_typed(0, codes, values, expiry)
    assert type(score).__name__ == "FullStepResultCore"
    assert score.fill_count == 1
    assert score.event_count >= 2
    assert score.positions == [1.0]
    assert score.fills is None
    assert score.events is None
    assert score.active_orders is None
    assert score_session.step_buffer_capacities() == (0, 0, 0)

    audit_session = _session(frame)
    audit_session.set_output_mask(15)
    audit = audit_session.step_typed(0, codes, values, expiry)
    assert audit.positions == [1.0]
    assert len(audit.fills) == 1
    assert len(audit.events) >= 2
    assert audit.active_orders == []
    assert audit_session.step_buffer_capacities()[0] >= 1
    assert audit_session.step_buffer_capacities()[1] >= 2

    scalar_fingerprints = []
    for mask in (0, 1, 2, 4, 8, 3, 5, 15):
        session = _session(frame)
        session.set_output_mask(mask)
        result = session.step_typed(0, codes, values, expiry)
        scalar_fingerprints.append(
            (result.equity, result.fee, result.turnover, result.fill_count, result.event_count)
        )
        assert (result.positions is None) is not bool(mask & 1)
        assert (result.fills is None) is not bool(mask & 2)
        assert (result.events is None) is not bool(mask & 4)
        assert (result.active_orders is None) is not bool(mask & 8)
    assert all(fingerprint == scalar_fingerprints[0] for fingerprint in scalar_fingerprints)


def test_phase48e1_static_audit_uses_distinct_command_and_lifecycle_reports():
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
            metadata={"campaign_id": "phase48e1", "level_id": 1},
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
    audit = runner.run_tape_audit(compiled)
    result = audit.to_backtest_result(
        datetime_index=frame.index,
        closes=pd.DataFrame({"BTC": frame["close"]}, index=frame.index),
        symbols=["BTC"],
        initial_capital=10_000.0,
        leverage=5.0,
    )
    command_report = result.metadata["command_report"]
    order_report = result.metadata["order_report"]
    fills_report = result.metadata["fills_report"]
    assert command_report is not order_report
    assert not command_report.empty
    assert set(command_report["report_kind"]) == {"command_intent"}
    assert "event_kind" in order_report.columns
    assert "tag" in fills_report.columns
    assert fills_report.loc[fills_report["order_id"] == "entry", "campaign_id"].iloc[0] == "phase48e1"


def test_phase48e1_reset_and_compaction_relationships_keep_fresh_parity():
    frame = _bars(96)
    commands = tuple(
        OrderCommand(
            timestamp=frame.index[bar],
            symbol="BTC",
            side=OrderSide.BUY if bar % 2 else OrderSide.SELL,
            order_type=OrderType.MARKET,
            qty=1.0,
            tif=TimeInForce.GTC,
            order_id=f"order-{bar}",
        )
        for bar in range(1, len(frame))
    )
    runner, compiled = _runner(frame, commands)
    first = runner.run_tape_audit(compiled)
    first_fingerprint = (first.final_equity, first.fill_count, first.event_count)
    second = runner.run_tape_audit(compiled)
    assert (second.final_equity, second.fill_count, second.event_count) == first_fingerprint
    info = runner.cache_info()
    assert info["order_compactions"] >= 1
    assert info["terminal_orders_removed"] >= 64


def test_phase48e1_score_reset_has_bounded_reuse_for_100_runs():
    frame = _bars(64)
    commands = (
        OrderCommand(
            timestamp=frame.index[1],
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            qty=1.0,
            order_id="entry",
        ),
    )
    runner, compiled = _runner(frame, commands)
    first = runner.run_tape_score(compiled)
    first_info = runner.cache_info()
    for _ in range(100):
        current = runner.run_tape_score(compiled)
        assert current["final_equity"] == first["final_equity"]
        assert current["fill_count"] == first["fill_count"]
    final_info = runner.cache_info()
    assert final_info["tape_cache_entries"] == 1
    assert final_info["command_buffer_capacity"] == first_info["command_buffer_capacity"]
    assert final_info["command_buffer_growth_count"] == first_info["command_buffer_growth_count"]
    assert final_info.get("step_fill_buffer_capacity", 0) == 0
    assert final_info.get("step_event_buffer_capacity", 0) == 0
