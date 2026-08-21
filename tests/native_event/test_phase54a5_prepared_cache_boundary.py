"""Phase 54A.5.5 prepared ownership, reset, and boundary-budget locks."""

from __future__ import annotations

import gc
import importlib.util

import numpy as np
import pandas as pd
import pytest

from quantbt.preparation import CachePolicy, NativeExecutionPreparationCache, PreparedObjectCache


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native extension is not installed in this environment",
)


NEXT_OPEN = 3


def _market(n_bars: int = 8) -> dict[str, np.ndarray]:
    index = pd.date_range("2026-04-01", periods=n_bars, freq="1h", tz="UTC")
    close = np.ascontiguousarray(100.0 + np.arange(n_bars, dtype=np.float64))
    funding = np.zeros(n_bars, dtype=np.float64)
    funding[3] = 0.0001
    mask = np.zeros(n_bars, dtype=np.bool_)
    mask[3] = True
    return {
        "timestamps_ns": np.ascontiguousarray(index.asi8, dtype=np.int64),
        "opens": close[:, None].copy(),
        "highs": (close + 1.0)[:, None].copy(),
        "lows": (close - 1.0)[:, None].copy(),
        "closes": close[:, None].copy(),
        "volumes": np.full((n_bars, 1), 20.0, dtype=np.float64),
        "funding": funding[:, None],
        "funding_mask": mask,
    }


def _tape(n_bars: int = 8) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    ptr = np.zeros(n_bars + 1, dtype=np.int64)
    ptr[2:] = 1
    ptr[4:] = 2
    codes = np.full((2, 16), -1, dtype=np.int64)
    values = np.zeros((2, 3), dtype=np.float64)
    expiry = np.full(2, -1, dtype=np.int64)
    # Enter one unit at local bar one, then close at local bar three.
    codes[0] = [0, 0, 1, 0, 0, 0, 101, -1, -1, -1, -1, 0, 0, 0, 0, 0]
    values[0, 0] = 1.0
    codes[1] = [0, 0, -1, 0, 0, 1, 102, -1, -1, -1, -1, 0, 1, 0, 0, 0]
    values[1, 0] = 1.0
    return ptr, np.ascontiguousarray(codes), np.ascontiguousarray(values), expiry


def _cache() -> NativeExecutionPreparationCache:
    return NativeExecutionPreparationCache(CachePolicy(max_bytes=1_000_000, max_entries=8))


def _prepared_template(cache: NativeExecutionPreparationCache):
    market = cache.prepare_market(**_market(), symbols=["ETHUSDT"])
    template = cache.prepare_template(
        market,
        contract_sizes=np.array([1.0], dtype=np.float64),
        leverages=np.array([5.0], dtype=np.float64),
        fee_rates=np.array([0.0002], dtype=np.float64),
        initial_capital=10_000.0,
        maintenance_ratio=0.005,
        slippage_rate=0.0001,
        use_funding=True,
        event_contract_code=NEXT_OPEN,
    )
    return market, template


def test_prepared_cache_reuses_exact_content_and_invalidates_all_result_inputs():
    import _quantbt_native

    cache = _cache()
    source = _market()
    first = cache.prepare_market(**source, symbols=["ETHUSDT"])
    second = cache.prepare_market(**source, symbols=["ETHUSDT"])
    assert second.core is first.core
    assert first.prepared_bytes > 0
    assert first.core.prepared_bytes == first.prepared_bytes

    template = cache.prepare_template(
        first,
        contract_sizes=np.array([1.0]),
        leverages=np.array([5.0]),
        fee_rates=np.array([0.0002]),
        initial_capital=10_000.0,
        maintenance_ratio=0.005,
        slippage_rate=0.0001,
        use_funding=True,
        event_contract_code=NEXT_OPEN,
    )
    same_template = cache.prepare_template(
        second,
        contract_sizes=np.array([1.0]),
        leverages=np.array([5.0]),
        fee_rates=np.array([0.0002]),
        initial_capital=10_000.0,
        maintenance_ratio=0.005,
        slippage_rate=0.0001,
        use_funding=True,
        event_contract_code=NEXT_OPEN,
    )
    assert same_template.core is template.core

    ptr, codes, values, expiry = _tape()
    request = cache.command_request(
        template,
        command_ptr=ptr,
        command_codes=codes,
        command_values=values,
        command_expiry=expiry,
        output_profile=2,
    )
    same_request = cache.command_request(
        same_template,
        command_ptr=ptr,
        command_codes=codes,
        command_values=values,
        command_expiry=expiry,
        output_profile=2,
    )
    assert same_request.core is request.core
    assert request.core.template_fingerprint == template.signature

    # Cached and direct request construction must execute the identical typed
    # contract; cache reuse is a preparation optimization only.
    uncached = _quantbt_native.NativeExecutionRequestCore.from_command_tape(
        first.core,
        ptr,
        codes,
        values,
        expiry,
        np.array([1.0]),
        np.array([5.0]),
        np.array([0.0002]),
        10_000.0,
        0.005,
        0.0001,
        True,
        event_contract_code=NEXT_OPEN,
        output_profile=2,
    )
    cached_output = request.core.execute_typed()
    uncached_output = uncached.execute_typed()
    np.testing.assert_allclose(cached_output.equity, uncached_output.equity, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(cached_output.positions, uncached_output.positions, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(cached_output.fill_price, uncached_output.fill_price, rtol=0.0, atol=1e-12)

    volume_changed = dict(source)
    volume_changed["volumes"] = source["volumes"].copy()
    volume_changed["volumes"][2, 0] += 1.0
    changed_volume = cache.prepare_market(**volume_changed, symbols=["ETHUSDT"])
    assert changed_volume.signature != first.signature

    funding_changed = dict(source)
    funding_changed["funding"] = source["funding"].copy()
    funding_changed["funding"][3, 0] += 0.0001
    changed_funding = cache.prepare_market(**funding_changed, symbols=["ETHUSDT"])
    assert changed_funding.signature != first.signature

    close_changed = dict(source)
    close_changed["closes"] = source["closes"].copy()
    close_changed["closes"][4, 0] += 2.0
    changed_close = cache.prepare_market(**close_changed, symbols=["ETHUSDT"])
    assert changed_close.signature != first.signature

    changed_fee = cache.prepare_template(
        first,
        contract_sizes=np.array([1.0]),
        leverages=np.array([5.0]),
        fee_rates=np.array([0.0003]),
        initial_capital=10_000.0,
        maintenance_ratio=0.005,
        slippage_rate=0.0001,
        use_funding=True,
        event_contract_code=NEXT_OPEN,
    )
    assert changed_fee.signature != template.signature

    changed_contract = cache.prepare_template(
        first,
        contract_sizes=np.array([1.0]),
        leverages=np.array([5.0]),
        fee_rates=np.array([0.0002]),
        initial_capital=10_000.0,
        maintenance_ratio=0.005,
        slippage_rate=0.0001,
        use_funding=True,
        event_contract_code=2,
    )
    assert changed_contract.signature != template.signature

    score_request = cache.command_request(
        template,
        command_ptr=ptr,
        command_codes=codes,
        command_values=values,
        command_expiry=expiry,
        output_profile=0,
    )
    assert score_request.signature != request.signature

    diagnostics = cache.diagnostics
    assert diagnostics["cache_hit"] >= 3
    assert diagnostics["cache_miss"] >= 6
    assert diagnostics["resident_bytes"] <= cache.policy.max_bytes
    assert diagnostics["tier_budgets"]["market"] + diagnostics["tier_budgets"]["template"] + diagnostics["tier_budgets"]["request"] == cache.policy.max_bytes


def test_prepared_object_cache_clear_refuses_active_pin_and_advances_generation():
    cache = PreparedObjectCache(CachePolicy(max_bytes=64, max_entries=2))
    value = object()
    assert cache.put(("active",), value, size_bytes=16)
    assert cache.get(("active",), pin=True) is value
    with pytest.raises(RuntimeError, match="pinned"):
        cache.clear()
    cache.release(("active",))
    released = cache.clear()
    assert released["released_entries"] == 1
    assert released["released_bytes"] == 16
    assert cache.diagnostics["entry_count"] == 0
    assert cache.diagnostics["generation"] == 1


def test_runner_reset_window_and_outputs_have_no_cross_scenario_state():
    cache = _cache()
    market, template = _prepared_template(cache)
    ptr, codes, values, expiry = _tape()
    request = cache.command_request(
        template,
        command_ptr=ptr,
        command_codes=codes,
        command_values=values,
        command_expiry=expiry,
        output_profile=2,
    )
    runner = cache.new_runner(request)
    first = runner.execute_typed()
    second = runner.execute_typed()
    np.testing.assert_allclose(first.equity, second.equity, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(first.positions, second.positions, rtol=0.0, atol=1e-12)
    assert first.execution_generation == 1
    assert second.execution_generation == 2
    assert second.runner_run_count == 2

    runner.reset("account_and_orders")
    after_reset = runner.diagnostics()
    assert after_reset["generation"] == 3
    assert after_reset["explicit_reset_count"] == 1
    third = runner.execute_typed()
    assert third.execution_generation == 4
    np.testing.assert_allclose(third.equity, first.equity, rtol=0.0, atol=1e-12)
    with pytest.raises(NotImplementedError, match="account_only"):
        runner.reset("account_only")

    # Result output owns NumPy buffers, while the runner may release its
    # transient scratch capacity without changing an earlier output.
    saved_equity = first.equity.copy()
    runner.reset("result_buffers", max_capacity=0)
    np.testing.assert_allclose(first.equity, saved_equity, rtol=0.0, atol=0.0)
    runner.reset("full_rebuild")
    after_rebuild = runner.diagnostics()
    assert after_rebuild["generation"] == 5
    assert after_rebuild["full_rebuilds"] == 1
    rebuilt = runner.execute_typed()
    assert rebuilt.execution_generation == 6
    np.testing.assert_allclose(rebuilt.equity, first.equity, rtol=0.0, atol=1e-12)

    window = cache.window_template(template, start=2, end=6)
    assert window.core.bars == 4
    assert window.core.source_market_bytes == template.core.source_market_bytes
    assert window.core.market_reference_count >= 2
    empty_ptr = np.zeros(5, dtype=np.int64)
    empty_request = cache.command_request(
        window,
        command_ptr=empty_ptr,
        command_codes=np.empty((0, 16), dtype=np.int64),
        command_values=np.empty((0, 3), dtype=np.float64),
        command_expiry=np.empty(0, dtype=np.int64),
        output_profile=1,
    )
    window_output = cache.new_runner(empty_request).execute_typed()
    assert window_output.bars == 4
    assert np.allclose(window_output.final_positions, 0.0)

    runner.close()
    assert runner.closed is True
    with pytest.raises(RuntimeError, match="closed"):
        runner.execute_typed()
    assert market.core.reference_count >= 1


def test_cache_clear_does_not_invalidate_detached_output_and_static_ir_boundary_is_o1():
    import _quantbt_native

    cache = _cache()
    _, template = _prepared_template(cache)
    ptr, codes, values, expiry = _tape()
    static = cache.command_request(
        template,
        command_ptr=ptr,
        command_codes=codes,
        command_values=values,
        command_expiry=expiry,
        output_profile=0,
    )
    static_runner = cache.new_runner(static)
    static_output = static_runner.execute_typed()
    static_values = static_output.final_positions.copy()
    assert static_output.as_dict()["boundary_calls"] == 1
    assert static_runner.diagnostics()["boundary_calls"] == 1
    assert static_runner.diagnostics()["python_callbacks"] == 0

    program = _quantbt_native.NativeStrategyProgramCore(1, quantity=0.5, dca_period=1, max_levels=3)
    ir = cache.strategy_ir_request(
        template,
        program=program,
        signal=np.array([0.0, 1.0, 2.0, 1.0, 0.0, 0.0, 0.0, 0.0]),
        output_profile=0,
    )
    ir_runner = cache.new_runner(ir)
    ir_output = ir_runner.execute_typed()
    assert ir_output.as_dict()["boundary_calls"] == 1
    assert ir_runner.diagnostics()["boundary_calls"] == 1
    assert ir_runner.diagnostics()["python_callbacks"] == 0

    released = cache.clear()
    assert released["generation"] == 1
    assert cache.diagnostics["entry_count"] == 0
    gc.collect()
    np.testing.assert_allclose(static_output.final_positions, static_values, rtol=0.0, atol=0.0)
