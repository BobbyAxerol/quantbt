from __future__ import annotations

import inspect
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from quantbt import (
    AuditMismatchError,
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
        active_orders="none",
        context_mode="numeric",
    )

    def on_bar_close(self, context, out):
        if context.bar_index == 2:
            out.market(0, 1, 1.0, order_handle=1, tif=TimeInForce.IOC)
        elif context.bar_index == 18:
            out.market(0, -1, 1.0, order_handle=2, tif=TimeInForce.IOC, reduce_only=True)


class NumericConstrainedEntry:
    quantbt_requirements = StrategyContextRequirements(
        market=("close",),
        account=("equity",),
        positions=("qty",),
        fills="none",
        events="none",
        active_orders="none",
        context_mode="numeric",
    )

    def on_bar_close(self, context, out):
        if context.bar_index == 2:
            out.market(0, 1, 1.13, order_handle=9, tif=TimeInForce.IOC)


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


def test_rust_numeric_minimal_uses_primitive_writer_without_order_objects():
    python = _prepared("python").run(NumericRoundTrip(), report_level="minimal")
    rust = _prepared("rust").run(NumericRoundTrip(), report_level="minimal")

    np.testing.assert_allclose(rust.equity, python.equity, rtol=0.0, atol=1e-9)
    np.testing.assert_allclose(rust.positions, python.positions, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(rust.fees, python.fees, rtol=0.0, atol=1e-12)
    boundary = rust.metadata["strategy_boundary"]
    counters = rust.metadata["execution_counters"]
    assert boundary["writer_command_rows"] == 2
    assert boundary["writer_materialized_command_objects"] == 0
    assert counters["primitive_command_batches"] == 2
    assert counters["primitive_command_rows"] == 2
    assert counters["writer_python_command_objects"] == 0
    assert counters["active_snapshot_materializations"] == 0


def test_rust_numeric_standard_materializes_only_the_requested_public_report():
    result = _prepared("rust").run(NumericRoundTrip(), report_level="standard")

    assert len(result.metadata["command_report"]) == 2
    assert result.metadata["strategy_boundary"]["writer_materialized_command_objects"] == 2
    assert result.metadata["execution_counters"]["primitive_command_rows"] == 2


def test_rust_numeric_constraint_preflight_matches_python_and_keeps_drop_audit():
    kwargs = {"qty_step": {"BTC": 0.25}, "min_qty": {"BTC": 1.25}}
    python_endpoint = QuantBTEndpoint.native_event_strategy(
        initial_capital=10_000.0,
        leverage=5.0,
        fee_rate=0.0002,
        use_funding=False,
        native_backend="python",
        reactive_kernel_mode="single_pass",
        report_level="audit",
        **kwargs,
    )
    rust_endpoint = QuantBTEndpoint.native_event_strategy(
        initial_capital=10_000.0,
        leverage=5.0,
        fee_rate=0.0002,
        use_funding=False,
        native_backend="rust",
        reactive_kernel_mode="single_pass",
        report_level="audit",
        **kwargs,
    )
    python = python_endpoint.simulate(data=_bars(), strategy=NumericConstrainedEntry(), symbols=["BTC"])
    rust = rust_endpoint.simulate(data=_bars(), strategy=NumericConstrainedEntry(), symbols=["BTC"])

    np.testing.assert_allclose(rust.equity, python.equity, rtol=0.0, atol=1e-9)
    np.testing.assert_allclose(rust.positions, python.positions, rtol=0.0, atol=1e-12)
    assert rust.metadata["quantity_preflight"] == python.metadata["quantity_preflight"]
    assert rust.metadata["emitted_command_count"] == python.metadata["emitted_command_count"] == 1
    assert rust.metadata["execution_counters"]["primitive_command_rows"] == 0


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


def test_prepared_cache_pin_prevents_eviction_until_release():
    cache = PreparedObjectCache(CachePolicy(max_bytes=8, max_entries=1))
    first = object()
    assert cache.put(("first",), first, size_bytes=8)
    assert cache.get(("first",), pin=True) is first
    assert cache.put(("second",), object(), size_bytes=8) is False
    assert cache.diagnostics["pinned_entries"] == 1
    cache.release(("first",))
    assert cache.put(("second",), object(), size_bytes=8)
    assert cache.diagnostics["entry_count"] == 1


def test_prepared_market_key_changes_with_volume_and_funding(monkeypatch):
    prepared = _prepared("rust")
    captured = []
    original = prepared.backend._create_reactive_session

    def capture(**kwargs):
        captured.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(prepared.backend, "_create_reactive_session", capture)
    prepared.run(NumericRoundTrip(), report_level="minimal")
    kwargs = dict(captured[-1])
    base_key = prepared.backend._reactive_market_cache_key(kwargs)

    volume_changed = dict(kwargs)
    volume_changed["volumes_arr"] = np.asarray(kwargs["volumes_arr"]).copy()
    volume_changed["volumes_arr"][0, 0] += 1.0
    assert prepared.backend._reactive_market_cache_key(volume_changed) != base_key

    market = kwargs["market_arrays"]
    funding = np.asarray(market.funding).copy()
    funding[0, 0] += 0.0001
    funding_changed = dict(kwargs)
    funding_changed["market_arrays"] = replace(market, funding=funding)
    assert prepared.backend._reactive_market_cache_key(funding_changed) != base_key


def test_prepared_cache_parallel_reads_are_consistent():
    cache = PreparedObjectCache(CachePolicy(max_bytes=1_024, max_entries=4))
    value = object()
    assert cache.put(("shared",), value, size_bytes=64)

    with ThreadPoolExecutor(max_workers=8) as executor:
        observed = list(executor.map(lambda _: cache.get(("shared",)), range(1_000)))
    assert all(item is value for item in observed)
    assert cache.diagnostics["cache_hit"] == 1_000


def test_oracle_verifier_is_explicit_and_never_replaces_primary_result(monkeypatch):
    prepared = _prepared("replay_certified")
    result = prepared.run(NumericRoundTrip(), report_level="audit")
    assert result.metadata["audit_mode"] == "verify_against_oracle"
    assert result.metadata["primary_engine_runs"] == 1
    assert result.metadata["oracle_engine_runs"] == 1
    assert result.metadata["oracle_verified"] is True
    assert result.metadata["single_pass_accounting_source"] == "reactive_session_state"

    def divergence(*args, **kwargs):
        raise AuditMismatchError("injected oracle divergence")

    monkeypatch.setattr(prepared.backend, "_assert_reactive_session_replay_parity", divergence)
    with pytest.raises(AuditMismatchError, match="injected oracle divergence"):
        prepared.run(NumericRoundTrip(), report_level="audit")


@pytest.mark.parametrize(
    ("sample_rate", "expected_mode", "expected_oracle_runs"),
    ((0.0, "native_trace", 0), (1.0, "verify_against_oracle", 1)),
)
def test_sampled_audit_is_deterministic_and_keeps_primary_result(
    sample_rate, expected_mode, expected_oracle_runs
):
    endpoint = QuantBTEndpoint.native_event_strategy(
        initial_capital=10_000.0,
        leverage=5.0,
        fee_rate=0.0002,
        use_funding=False,
        native_backend="rust",
        reactive_kernel_mode="single_pass",
        audit_mode="dual_run_sampled",
        oracle_sample_rate=sample_rate,
        oracle_sample_seed=52,
        report_level="audit",
        audit_sink="memory",
    )
    result = endpoint.simulate(data=_bars(), strategy=NumericRoundTrip(), symbols=["BTC"])

    assert result.metadata["audit_mode_requested"] == "dual_run_sampled"
    assert result.metadata["audit_mode"] == expected_mode
    assert result.metadata["oracle_engine_runs"] == expected_oracle_runs
    assert result.metadata["primary_engine_runs"] == 1
    assert result.metadata["single_pass_accounting_source"] == "reactive_session_state"
