from __future__ import annotations

import inspect

import numpy as np
import pandas as pd
import pytest

from quantbt import (
    QuantBTEndpoint,
    StrategyContextRequirements,
    TimeInForce,
)
from quantbt.backends._native_event_rust import RustReactiveSessionAdapter
from quantbt.preparation import CachePolicy, PreparedObjectCache, ResetScope


def _bars(n: int = 32) -> pd.DataFrame:
    index = pd.date_range("2026-02-01", periods=n, freq="h", tz="UTC")
    close = 100.0 + np.sin(np.arange(n) / 4.0) * 3.0 + np.arange(n) * 0.1
    return pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.full(n, 20.0),
        },
        index=index,
    )


class NumericRoundTrip:
    quantbt_requirements = StrategyContextRequirements(
        market=("close",),
        account=("equity", "initial_margin", "maintenance_margin", "liquidated"),
        positions=("qty",),
        fills="new_only",
        events="new_only",
        active_orders="snapshot",
        context_mode="numeric",
    )

    def on_bar_close(self, context, out):
        if context.bar_index == 2:
            out.market(0, 1, 1.0, order_handle=1, tif=TimeInForce.IOC)
        elif context.bar_index == 18:
            out.market(0, -1, 1.0, order_handle=2, tif=TimeInForce.IOC, reduce_only=True)


def _prepared(backend: str):
    endpoint = QuantBTEndpoint.native_event_strategy(
        initial_capital=10_000.0,
        leverage=5.0,
        fee_rate=0.0002,
        use_funding=False,
        slippage=0.0001,
        native_backend=backend,
        reactive_kernel_mode="single_pass",
        report_level="audit",
        audit_sink="memory",
    )
    return endpoint.prepare_native_event_strategy(data=_bars(), symbols=["BTC"])


def test_rust_is_single_authoritative_state_and_matches_python_primary_trace():
    python = _prepared("python").run(NumericRoundTrip(), report_level="audit")
    rust = _prepared("rust").run(NumericRoundTrip(), report_level="audit")

    np.testing.assert_allclose(rust.equity, python.equity, rtol=0.0, atol=1e-9)
    np.testing.assert_allclose(rust.positions, python.positions, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(rust.fees, python.fees, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(rust.margin, python.margin, rtol=0.0, atol=1e-12)
    assert rust.metadata["state_owner"] == "rust"
    assert rust.metadata["authoritative_mutable_state_count"] == 1
    assert rust.metadata["python_shadow_accounting"] is False
    assert rust.metadata["primary_engine_runs"] == 1
    assert rust.metadata["oracle_engine_runs"] == 0
    assert rust.metadata["canonical_trace_fingerprint"] == python.metadata["canonical_trace_fingerprint"]
    counters = rust.metadata["execution_counters"]
    assert counters["pyo3_calls"] == len(rust.equity)
    assert counters["position_delta_rows"] == 2
    assert counters["callback_projection_bytes"] > 0


def test_rust_adapter_source_has_no_python_account_or_order_shadow_assignment():
    source = inspect.getsource(RustReactiveSessionAdapter)
    forbidden = (
        "self.equity =",
        "self.current_pos =",
        "self.pending =",
        "self.orders =",
        "self.total_fee +=",
        "self.total_funding +=",
        "self.total_turnover +=",
    )
    assert not [token for token in forbidden if token in source]


def test_rust_reset_rerun_matches_fresh_and_result_survives_reset(monkeypatch):
    prepared = _prepared("rust")
    captured = []
    original = prepared.backend._create_reactive_session

    def capture(**kwargs):
        session = original(**kwargs)
        captured.append(session)
        return session

    monkeypatch.setattr(prepared.backend, "_create_reactive_session", capture)
    result = prepared.run(NumericRoundTrip(), report_level="audit")
    retained_equity = result.equity.to_numpy(copy=True)
    session = captured[-1]
    commands = tuple(result.metadata["emitted_command_tape"])

    session.reset(ResetScope.ACCOUNT_AND_ORDERS)
    for command in commands:
        bar = int(session.idx.searchsorted(pd.Timestamp(command.timestamp), side="left"))
        if bar < len(session.idx):
            session.schedule(bar, (command,))
    session.process_bar(len(session.idx) - 1)

    np.testing.assert_allclose(session.equity_path, retained_equity, rtol=0.0, atol=1e-9)
    np.testing.assert_array_equal(result.equity.to_numpy(), retained_equity)
    assert session.reset_count == 1
    assert session.poisoned is False
    with pytest.raises(NotImplementedError):
        session.reset(ResetScope.ACCOUNT_ONLY)


def test_prepared_market_cache_is_bounded_content_addressed_and_reused():
    prepared = _prepared("rust")
    first = prepared.run(NumericRoundTrip(), report_level="minimal")
    second = prepared.run(NumericRoundTrip(), report_level="minimal")
    first_cache = first.metadata["prepared_market_cache"]
    second_cache = second.metadata["prepared_market_cache"]
    assert first_cache["entry_count"] == 1
    assert second_cache["entry_count"] == 1
    assert second_cache["cache_hit"] >= 1
    assert second_cache["reuse_count"] >= 1

    cache = PreparedObjectCache(CachePolicy(max_bytes=8, max_entries=1))
    assert cache.put(("a",), object(), size_bytes=8)
    assert cache.put(("b",), object(), size_bytes=8)
    assert cache.diagnostics["entry_count"] == 1
    assert cache.diagnostics["eviction_count"] == 1


def test_oracle_verifier_is_explicit_and_never_replaces_primary_result(monkeypatch):
    prepared = _prepared("replay_certified")
    result = prepared.run(NumericRoundTrip(), report_level="audit")
    assert result.metadata["audit_mode"] == "verify_against_oracle"
    assert result.metadata["primary_engine_runs"] == 1
    assert result.metadata["oracle_engine_runs"] == 1
    assert result.metadata["oracle_verified"] is True
    assert result.metadata["single_pass_accounting_source"] == "reactive_session_state"

    def divergence(*args, **kwargs):
        raise AssertionError("injected oracle divergence")

    monkeypatch.setattr(prepared.backend, "_assert_reactive_session_replay_parity", divergence)
    with pytest.raises(AssertionError, match="injected oracle divergence"):
        prepared.run(NumericRoundTrip(), report_level="audit")
