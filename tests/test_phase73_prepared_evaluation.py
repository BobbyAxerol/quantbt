"""Phase 73 conformance for the shared Rust prepared-evaluation runtime.

The tests exercise every certified request family through one typed batch
boundary. They deliberately compare the matrix rows with each request's
direct Rust result rather than a Python replay, because execution/accounting
authority remains in the specialized native request.
"""

from __future__ import annotations

import importlib.util

import numpy as np
import pandas as pd
import pytest

from quantbt import AccountConfig, ExecutionContract, IntrabarIntentTape, prepare_market_tape
from quantbt.backends.native_intrabar_rust import prepare_rust_intrabar_request
from quantbt.backends.native_prepared_evaluation import (
    NativeEvaluationMetricContractV1,
    NativePreparedEvaluationRuntimeV1,
    NativePreparedWorkloadV1,
)
from quantbt.core.runtime_governance import RuntimeBudgetError, RuntimeBudgetV1
from quantbt.preparation.native_execution import CachePolicy, NativeExecutionPreparationCache


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native extension is not installed in this environment",
)


def _prepared_fixture():
    """Build a compact two-symbol cache plus every Phase 73 request family."""

    import _quantbt_native

    bars = 10
    index = pd.date_range("2025-01-01", periods=bars, freq="1h", tz="UTC")
    base = np.array([100.0, 101.0, 102.0, 99.0, 104.0, 103.0, 106.0, 105.0, 107.0, 108.0])
    closes = np.ascontiguousarray(np.column_stack((base, base + 20.0)), dtype=np.float64)
    cache = NativeExecutionPreparationCache(CachePolicy(max_bytes=4_000_000, max_entries=32))
    market = cache.prepare_market(
        timestamps_ns=np.ascontiguousarray(index.asi8, dtype=np.int64),
        opens=closes,
        highs=np.ascontiguousarray(closes + 2.0),
        lows=np.ascontiguousarray(closes - 2.0),
        closes=closes,
        volumes=np.full_like(closes, 10.0),
        funding=np.zeros_like(closes),
        funding_mask=np.zeros(bars, dtype=np.bool_),
        symbols=["A", "B"],
    )
    template = cache.prepare_template(
        market,
        contract_sizes=np.ones(2, dtype=np.float64),
        leverages=np.full(2, 3.0, dtype=np.float64),
        fee_rates=np.full(2, 0.0005, dtype=np.float64),
        initial_capital=10_000.0,
        maintenance_ratio=0.005,
        slippage_rate=0.0001,
        use_funding=False,
    )

    command_ptr = np.zeros(bars + 1, dtype=np.int64)
    command_ptr[1:] = 1
    command_ptr[4:] = 2
    command_codes = np.full((2, 16), -1, dtype=np.int64)
    command_values = np.zeros((2, 3), dtype=np.float64)
    command_expiry = np.full(2, -1, dtype=np.int64)
    command_codes[0] = [0, 0, 1, 0, 0, 0, 101, -1, -1, -1, -1, 0, 0, 0, 0, 0]
    command_values[0, 0] = 1.0
    command_codes[1] = [0, 0, -1, 0, 0, 1, 102, -1, -1, -1, -1, 0, 1, 0, 0, 0]
    command_values[1, 0] = 1.0

    requests: list[tuple[NativePreparedWorkloadV1, object]] = [
        (
            NativePreparedWorkloadV1.STATIC_COMMAND,
            cache.command_request(
                template,
                command_ptr=command_ptr,
                command_codes=command_codes,
                command_values=command_values,
                command_expiry=command_expiry,
                output_profile=0,
            ),
        )
    ]
    program = _quantbt_native.NativeStrategyProgramCore(2, quantity=0.5, dca_period=1, max_levels=2)
    requests.append(
        (
            NativePreparedWorkloadV1.STRATEGY_IR,
            cache.strategy_ir_request(
                template,
                program=program,
                signal=np.array([0.0, 1.0, 1.0, -1.0, -1.0, 0.0, 0.0, 1.0, 0.0, 0.0]),
                output_profile=0,
            ),
        )
    )

    units = np.zeros((bars, 2), dtype=np.float64)
    units[1:4] = [1.0, -0.5]
    direct_specs = (
        (NativePreparedWorkloadV1.TARGET_UNITS, units, "units", {}),
        (NativePreparedWorkloadV1.TARGET_NOTIONAL, units * 100.0, "notional", {}),
        (NativePreparedWorkloadV1.TARGET_WEIGHT, units * 0.1, "weight", {}),
        (
            NativePreparedWorkloadV1.TARGET_EQUITY_FRACTION,
            np.sign(units),
            "equity_fraction",
            {"equity_fraction": np.array([0.10, 0.05], dtype=np.float64)},
        ),
    )
    for workload, targets, target_kind, kwargs in direct_specs:
        requests.append(
            (
                workload,
                cache.direct_target_request(
                    template,
                    targets=targets,
                    target_kind=target_kind,
                    output_profile=0,
                    **kwargs,
                ),
            )
        )

    requests.extend(
        (
            (
                NativePreparedWorkloadV1.PORTFOLIO_TARGET,
                cache.shared_portfolio_target_request(
                    template,
                    targets=units,
                    target_kind="units",
                    admission_policy="reduce_first_then_increase",
                    output_profile=0,
                ),
            ),
            (
                NativePreparedWorkloadV1.PORTFOLIO_TARGET,
                cache.portfolio_target_market_request(
                    template,
                    target_units=units,
                    tradable=np.ones_like(units, dtype=np.bool_),
                    stale=np.zeros_like(units, dtype=np.bool_),
                    min_qty=np.zeros(2, dtype=np.float64),
                    min_notional=np.zeros(2, dtype=np.float64),
                    output_profile=0,
                ),
            ),
            (
                NativePreparedWorkloadV1.BOUNDED_PACKAGE,
                cache.package_atomic_market_request(
                    template,
                    command_bar=2,
                    package_id=7,
                    order_ids=np.array([10, 11], dtype=np.int64),
                    symbol_ids=np.array([0, 1], dtype=np.uint32),
                    signed_qty=np.array([1.0, -0.5], dtype=np.float64),
                    source_age_ns=np.zeros(2, dtype=np.int64),
                    venue_codes=np.ones(2, dtype=np.uint16),
                    venue_sequence=np.arange(2, dtype=np.uint32),
                    min_qty=np.zeros(2, dtype=np.float64),
                    min_notional=np.zeros(2, dtype=np.float64),
                    output_profile=0,
                ),
            ),
            (
                NativePreparedWorkloadV1.BOUNDED_PACKAGE,
                cache.package_market_v2_request(
                    template,
                    command_bars=np.array([2], dtype=np.uint64),
                    package_ids=np.array([8], dtype=np.uint64),
                    package_leg_offsets=np.array([0, 2], dtype=np.uint64),
                    execution_policies=np.array(["sequential"]),
                    residual_policies=np.array(["record"]),
                    max_staleness_ns=np.zeros(1, dtype=np.int64),
                    order_ids=np.array([20, 21], dtype=np.int64),
                    symbol_ids=np.array([0, 1], dtype=np.uint32),
                    signed_qty=np.array([1.0, -0.5], dtype=np.float64),
                    quantity_sources=np.array(["fixed", "fixed"]),
                    source_legs=np.array([-1, -1], dtype=np.int64),
                    quantity_ratios=np.ones(2, dtype=np.float64),
                    fill_fractions=np.ones(2, dtype=np.float64),
                    qty_step=np.zeros(2, dtype=np.float64),
                    min_qty=np.zeros(2, dtype=np.float64),
                    min_notional=np.zeros(2, dtype=np.float64),
                    source_age_ns=np.zeros(2, dtype=np.int64),
                    venue_codes=np.ones(2, dtype=np.uint16),
                    venue_sequence=np.arange(2, dtype=np.uint32),
                    output_profile=0,
                ),
            ),
        )
    )

    intrabar_frame = pd.DataFrame(
        {
            "open": base,
            "high": base + 2.0,
            "low": base - 2.0,
            "close": base,
            "volume": np.ones(bars),
        },
        index=index,
    )
    intrabar = prepare_rust_intrabar_request(
        tape=prepare_market_tape(data=intrabar_frame, symbols=["I"], use_funding=False),
        intent=IntrabarIntentTape.from_arrays(
            entry_side=[0, 1, 0, 0, 0, 0, 0, 0, 0, 0],
            entry_size=[0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            technical_exit=[False] * bars,
        ),
        account=AccountConfig(initial_capital=10_000.0, leverage=3.0),
        contract=ExecutionContract.intrabar_bracket(close_on_last_bar=True),
        fee_rate=0.0005,
        slippage_rate=0.0001,
        report_level="score",
        native_preparation_cache=cache,
    )
    requests.append((NativePreparedWorkloadV1.INTRABAR, intrabar.request))
    return cache, template, requests


def _raw_score(request) -> dict[str, object]:
    return dict(request.core.execute())


def _as_scalar(payload: dict[str, object], key: str) -> float:
    values = np.asarray(payload[key], dtype=np.float64)
    return float(values.reshape(-1)[-1])


def _assert_row_matches_direct(row, payload: dict[str, object]) -> None:
    for row_field, payload_key in (
        ("final_equity", "final_equity"),
        ("total_fee", "total_fee"),
        ("total_funding", "total_funding"),
        ("turnover", "total_turnover"),
        ("total_return", "native_metric_total_return"),
        ("sharpe", "native_metric_sharpe"),
        ("sortino", "native_metric_sortino"),
        ("max_drawdown", "native_metric_max_drawdown"),
        ("cagr", "native_metric_cagr"),
        ("calmar", "native_metric_calmar"),
        ("omega", "native_metric_omega"),
        ("profit_factor", "native_metric_profit_factor"),
        ("average_gross_exposure", "native_metric_average_gross_exposure"),
    ):
        assert getattr(row, row_field) == pytest.approx(_as_scalar(payload, payload_key), abs=1e-10)
    for row_field, payload_key in (
        ("fill_count", "fill_count"),
        ("event_count", "event_count"),
        ("rejected_count", "rejected_count"),
        ("canceled_count", "canceled_count"),
        ("sample_count", "native_metric_sample_count"),
    ):
        assert getattr(row, row_field) == int(_as_scalar(payload, payload_key))
    assert row.native_metric_contract_version == int(payload["native_metric_contract_version"])
    assert row.native_metric_annualization_factor == pytest.approx(
        float(payload["native_metric_annualization_factor"])
    )
    assert row.liquidated is bool(payload["liquidated"])
    assert row.request_fingerprint == payload["native_execution_request_fingerprint"]
    assert row.terminal_fingerprint == payload["native_execution_terminal_fingerprint"]


def test_phase73_all_certified_requests_use_one_native_batch_boundary() -> None:
    cache, _template, requests = _prepared_fixture()
    assert len(requests) == 11
    direct = [_raw_score(request) for _workload, request in requests]
    runtime = NativePreparedEvaluationRuntimeV1(cache, workers=2)
    try:
        bindings = [
            runtime.bind_request(
                request,
                workload=workload,
                candidate_id=100 + index,
                fold_id=index % 3,
                scenario_id=0,
                estimated_cost=(len(requests) - index) * 100,
            )
            for index, (workload, request) in enumerate(requests)
        ]
        reference_counts = [binding.native_binding.request_reference_count for binding in bindings]
        assert all(count >= 2 for count in reference_counts)
        result = runtime.evaluate(tuple(reversed(bindings)))
        assert result.errors == ()
        assert [row.candidate_id for row in result.rows] == list(range(100, 100 + len(requests)))
        assert result.metadata["native_boundary_calls"] == 1
        assert result.metadata["native_execution_passes"] == 1
        assert result.metadata["worker_pool_creations"] == 1
        assert result.metadata["native_request_executions"] == len(requests)
        assert result.metadata["prepared_market_copies_per_execution"] == 0
        assert result.metadata["prepared_intent_copies_per_execution"] == 0
        assert result.metadata["scheduler"] == "cost_descending_dynamic_queue_v1"
        for row, payload in zip(result.rows, direct, strict=True):
            assert row.status == "success"
            _assert_row_matches_direct(row, payload)
        assert [binding.native_binding.request_reference_count for binding in bindings] == reference_counts
        diagnostics = runtime.diagnostics()
        assert diagnostics["worker_pool_creations"] == 1
        assert diagnostics["score_batches"] == 1
        assert diagnostics["native_request_executions"] == len(requests)
    finally:
        runtime.close()


def test_phase73_worker_releases_request_owner_before_batch_result_is_observed() -> None:
    """A completed batch must not retain a worker-local request Arc.

    The response channel can wake the caller before a worker naturally leaves
    its match arm. Keep this small repeat test so that worker-task lifetime
    remains deterministic rather than making the ownership assertion timing
    dependent under multi-worker scheduling.
    """

    cache, _template, requests = _prepared_fixture()
    runtime = NativePreparedEvaluationRuntimeV1(cache, workers=2)
    try:
        bindings = [
            runtime.bind_request(
                request,
                workload=workload,
                candidate_id=300 + index,
                fold_id=index % 3,
                scenario_id=1,
                estimated_cost=(len(requests) - index) * 100,
            )
            for index, (workload, request) in enumerate(requests)
        ]
        reference_counts = [binding.native_binding.request_reference_count for binding in bindings]
        for _ in range(4):
            result = runtime.evaluate(tuple(reversed(bindings)))
            assert result.errors == ()
            assert [binding.native_binding.request_reference_count for binding in bindings] == reference_counts
        assert runtime.diagnostics()["score_batches"] == 4
    finally:
        runtime.close()


def test_phase73_score_audit_parity_and_lifecycle_are_explicit() -> None:
    cache, template, _requests = _prepared_fixture()
    targets = np.zeros((int(template.core.bars), 2), dtype=np.float64)
    targets[1:4] = [1.0, -0.5]
    score_request = cache.direct_target_request(template, targets=targets, output_profile=0)
    audit_request = cache.direct_target_request(template, targets=targets, output_profile=2)
    score_runtime = NativePreparedEvaluationRuntimeV1(cache, workers=1)
    audit_runtime = NativePreparedEvaluationRuntimeV1(cache, workers=1)
    try:
        score_binding = score_runtime.bind_request(
            score_request,
            workload="target_units",
            candidate_id=7,
            fold_id=2,
        )
        audit_binding = audit_runtime.bind_request(
            audit_request,
            workload="target_units",
            candidate_id=7,
            fold_id=2,
        )
        score = score_runtime.evaluate([score_binding])
        audit = audit_runtime.evaluate([audit_binding])
        score.assert_terminal_parity(audit)
        assert score.rows[0].request_fingerprint != audit.rows[0].request_fingerprint

        with pytest.raises(NotImplementedError, match="annualization"):
            NativeEvaluationMetricContractV1(trading_days=252)
        with pytest.raises(NotImplementedError, match="full local tape"):
            score_runtime.bind_request(
                score_request,
                workload="target_units",
                candidate_id=8,
                evaluation_start=1,
            )

        with pytest.raises(ValueError, match="different runtime"):
            audit_runtime.evaluate([score_binding])
        score_runtime.reset()
        with pytest.raises(ValueError, match="earlier runtime generation"):
            score_runtime.evaluate([score_binding])
        reset_binding = score_runtime.bind_request(
            score_request,
            workload="target_units",
            candidate_id=9,
        )
        assert score_runtime.evaluate([reset_binding]).rows[0].status == "success"

        cache.clear()
        with pytest.raises(ValueError, match="invalidated"):
            score_runtime.evaluate([reset_binding])
    finally:
        score_runtime.close()
        audit_runtime.close()


def test_phase73_cancel_budget_window_and_signature_guards() -> None:
    cache, template, _requests = _prepared_fixture()
    targets = np.zeros((int(template.core.bars), 2), dtype=np.float64)
    targets[1:4] = [1.0, -0.5]
    request = cache.direct_target_request(template, targets=targets, output_profile=0)
    runtime = NativePreparedEvaluationRuntimeV1(cache, workers=1)
    try:
        pending = runtime.bind_request(request, workload="target_units", candidate_id=1)
        runtime.cancel("test cancellation")
        canceled = runtime.evaluate([pending])
        assert canceled.rows[0].status == "canceled"
        assert canceled.rows[0].terminal_fingerprint == ""
        runtime.reset()
        recovered = runtime.bind_request(request, workload="target_units", candidate_id=2)
        assert runtime.evaluate([recovered]).rows[0].status == "success"

        window = cache.window_template(template, start=2, end=6)
        local_targets = targets[2:6]
        local = cache.direct_target_request(window, targets=local_targets, output_profile=0)
        local_binding = runtime.bind_request(local, workload="target_units", candidate_id=3)
        assert runtime.evaluate([local_binding]).rows[0].status == "success"
    finally:
        runtime.close()

    bounded = NativePreparedEvaluationRuntimeV1(
        cache,
        workers=1,
        runtime_budget=RuntimeBudgetV1(max_workers=1, max_metric_rows=1),
    )
    try:
        first = bounded.bind_request(request, workload="target_units", candidate_id=10)
        second = bounded.bind_request(request, workload="target_units", candidate_id=11)
        with pytest.raises(RuntimeBudgetError, match="metric rows"):
            bounded.evaluate([first, second])
    finally:
        bounded.close()

    source_index = pd.date_range("2025-06-01", periods=5, freq="1h", tz="UTC")
    source_close = np.ascontiguousarray((100.0 + np.arange(5, dtype=np.float64))[:, None])
    signature_cache = NativeExecutionPreparationCache()
    market = signature_cache.prepare_market(
        timestamps_ns=np.ascontiguousarray(source_index.asi8, dtype=np.int64),
        opens=source_close,
        highs=np.ascontiguousarray(source_close + 1.0),
        lows=np.ascontiguousarray(source_close - 1.0),
        closes=source_close,
        volumes=np.ones_like(source_close),
        funding=np.zeros_like(source_close),
        funding_mask=np.zeros(5, dtype=np.bool_),
        symbols=["S"],
    )
    changed_volume = signature_cache.prepare_market(
        timestamps_ns=np.ascontiguousarray(source_index.asi8, dtype=np.int64),
        opens=source_close,
        highs=np.ascontiguousarray(source_close + 1.0),
        lows=np.ascontiguousarray(source_close - 1.0),
        closes=source_close,
        volumes=np.full_like(source_close, 2.0),
        funding=np.zeros_like(source_close),
        funding_mask=np.zeros(5, dtype=np.bool_),
        symbols=["S"],
    )
    changed_funding = signature_cache.prepare_market(
        timestamps_ns=np.ascontiguousarray(source_index.asi8, dtype=np.int64),
        opens=source_close,
        highs=np.ascontiguousarray(source_close + 1.0),
        lows=np.ascontiguousarray(source_close - 1.0),
        closes=source_close,
        volumes=np.ones_like(source_close),
        funding=np.full_like(source_close, 0.0001),
        funding_mask=np.ones(5, dtype=np.bool_),
        symbols=["S"],
    )
    assert market.signature != changed_volume.signature
    assert market.signature != changed_funding.signature


def test_phase73_ingress_detaches_source_arrays_and_keeps_request_identity() -> None:
    """Prepared Rust owners must not borrow mutable NumPy ingress arrays."""

    bars = 7
    index = pd.date_range("2025-07-01", periods=bars, freq="1h", tz="UTC")
    close = np.ascontiguousarray((100.0 + np.arange(bars, dtype=np.float64))[:, None])
    targets = np.zeros((bars, 1), dtype=np.float64)
    targets[1:4, 0] = 1.0
    cache = NativeExecutionPreparationCache(CachePolicy(max_bytes=2_000_000, max_entries=8))
    market = cache.prepare_market(
        timestamps_ns=np.ascontiguousarray(index.asi8, dtype=np.int64),
        opens=close,
        highs=np.ascontiguousarray(close + 1.0),
        lows=np.ascontiguousarray(close - 1.0),
        closes=close,
        volumes=np.ones_like(close),
        funding=np.zeros_like(close),
        funding_mask=np.zeros(bars, dtype=np.bool_),
        symbols=["S"],
    )
    template = cache.prepare_template(
        market,
        contract_sizes=np.ones(1, dtype=np.float64),
        leverages=np.full(1, 3.0, dtype=np.float64),
        fee_rates=np.full(1, 0.0005, dtype=np.float64),
        initial_capital=10_000.0,
        maintenance_ratio=0.005,
        slippage_rate=0.0001,
        use_funding=False,
    )
    request = cache.direct_target_request(template, targets=targets, output_profile=0)
    before = _raw_score(request)

    # Mutating caller-owned arrays after ingress cannot change an existing
    # Rust market/request. A later cache call observes the changed content.
    close[:] = 1.0
    targets[:] = -2.0
    after = _raw_score(request)
    assert request.signature == str(before["native_execution_request_fingerprint"])
    assert after["native_execution_request_fingerprint"] == before[
        "native_execution_request_fingerprint"
    ]
    assert _as_scalar(after, "final_equity") == pytest.approx(
        _as_scalar(before, "final_equity"), abs=1e-10
    )

    changed_request = cache.direct_target_request(template, targets=targets, output_profile=0)
    assert changed_request.signature != request.signature
    changed_market = cache.prepare_market(
        timestamps_ns=np.ascontiguousarray(index.asi8, dtype=np.int64),
        opens=close,
        highs=np.ascontiguousarray(close + 1.0),
        lows=np.ascontiguousarray(close - 1.0),
        closes=close,
        volumes=np.ones_like(close),
        funding=np.zeros_like(close),
        funding_mask=np.zeros(bars, dtype=np.bool_),
        symbols=["S"],
    )
    assert changed_market.signature != market.signature
