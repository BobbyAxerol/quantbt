"""PERF-02 reset, retained-output, and prepared-session conformance."""

from __future__ import annotations

import importlib.util

import numpy as np
import pandas as pd
import pytest

from quantbt.preparation import CachePolicy, NativeExecutionPreparationCache


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native extension is not installed in this environment",
)


NEXT_OPEN = 3


def _template(cache: NativeExecutionPreparationCache, *, bars: int = 12):
    index = pd.date_range("2026-10-01", periods=bars, freq="1h", tz="UTC")
    close = np.ascontiguousarray(100.0 + np.arange(bars, dtype=np.float64))
    market = cache.prepare_market(
        timestamps_ns=np.ascontiguousarray(index.asi8, dtype=np.int64),
        opens=close[:, None].copy(),
        highs=(close + 1.0)[:, None].copy(),
        lows=(close - 1.0)[:, None].copy(),
        closes=close[:, None].copy(),
        volumes=np.full((bars, 1), 10_000.0, dtype=np.float64),
        funding=np.zeros((bars, 1), dtype=np.float64),
        funding_mask=np.zeros(bars, dtype=np.bool_),
        symbols=["BTCUSDT"],
    )
    return cache.prepare_template(
        market,
        contract_sizes=np.array([1.0], dtype=np.float64),
        leverages=np.array([5.0], dtype=np.float64),
        fee_rates=np.array([0.0002], dtype=np.float64),
        initial_capital=10_000.0,
        maintenance_ratio=0.005,
        slippage_rate=0.0001,
        use_funding=False,
        event_contract_code=NEXT_OPEN,
    )


def _outlier_passive_limit_request(cache: NativeExecutionPreparationCache, *, orders: int = 96):
    template = _template(cache)
    bars = int(template.core.bars)
    ptr = np.zeros(bars + 1, dtype=np.int64)
    # Static typed execution preserves bar zero as a frozen snapshot, so all
    # outlier orders enter at local bar one and stay passive through the tape.
    ptr[2:] = int(orders)
    codes = np.full((orders, 16), -1, dtype=np.int64)
    values = np.zeros((orders, 3), dtype=np.float64)
    expiry = np.full(orders, -1, dtype=np.int64)
    codes[:, 0] = 0  # PLACE
    codes[:, 1] = 0  # BTCUSDT
    codes[:, 2] = 1  # BUY
    codes[:, 3] = 1  # LIMIT
    codes[:, 4] = 0  # GTC
    codes[:, 6] = np.arange(10_000, 10_000 + orders, dtype=np.int64)
    codes[:, 11] = 0  # immediate activation
    values[:, 0] = 1.0
    values[:, 1] = 1.0  # never touched by the fixture market
    return cache.command_request(
        template,
        command_ptr=ptr,
        command_codes=np.ascontiguousarray(codes),
        command_values=np.ascontiguousarray(values),
        command_expiry=expiry,
        output_profile=2,
    )


def _retained_arrays(output) -> dict[str, np.ndarray]:
    return {
        field: np.array(getattr(output, field), copy=True)
        for field in (
            "equity",
            "positions",
            "fees",
            "turnover",
            "funding",
            "initial_margin",
            "maintenance_margin",
            "fill_bar",
            "event_bar",
        )
    }


def test_perf02_prepared_runner_reuse_has_no_residual_state_or_output_alias():
    cache = NativeExecutionPreparationCache(CachePolicy(max_bytes=4_000_000, max_entries=8))
    request = _outlier_passive_limit_request(cache)
    fresh = cache.new_runner(request).execute_typed()
    runner = cache.new_runner(request)

    retained = runner.execute_typed()
    saved = _retained_arrays(retained)
    reuse_cycles = 128
    for _ in range(reuse_cycles):
        reused = runner.execute_typed()
        np.testing.assert_allclose(reused.equity, fresh.equity, rtol=0.0, atol=1e-12)
        np.testing.assert_allclose(reused.positions, fresh.positions, rtol=0.0, atol=1e-12)
        assert reused.terminal_fingerprint == fresh.terminal_fingerprint

    diagnostics = dict(runner.diagnostics())
    assert diagnostics["reset_manifest"] == "quantbt-native-reset-manifest-v1"
    assert diagnostics["retained_output_policy"] == "owned_transfer_no_lease_v1"
    assert diagnostics["carried_account_reset_allowed"] is False
    assert diagnostics["run_count"] == reuse_cycles + 1
    assert diagnostics["session_reset_count"] == reuse_cycles + 1
    assert diagnostics["order_arena_slots"] == 96
    assert diagnostics["derived_account_recomputes"] > 0

    # Scratch release is permitted only because typed results own their NumPy
    # allocations. The first audit output remains byte-for-byte stable.
    runner.reset("result_buffers", max_capacity=0)
    for field, expected in saved.items():
        np.testing.assert_allclose(getattr(retained, field), expected, rtol=0.0, atol=0.0)
