"""Phase 71 runtime-governance and productization gates."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from copy import deepcopy
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from quantbt import (
    AccountConfig,
    ExecutionConfig,
    NativeEventBackend,
    NativeEventConfig,
    NativeIRFold,
    NativeStrategyIR,
    NativeStrategyKind,
    NativeStrategyParameters,
    OrderCommand,
    OrderSide,
    OrderType,
    QuantBTEndpoint,
    RustNativeIRRunner,
    TimeInForce,
)
from quantbt.backends._native_event_rust import NativeEventRustBackendError
from quantbt.backends.native_wfo import NativeWfoRuntimeV2
from quantbt.core.runtime_governance import (
    BoundedAuditSinkV1,
    ParallelismPlanV1,
    RuntimeBudgetError,
    RuntimeBudgetV1,
    RuntimeCancellationV1,
    RuntimeIdentityV1,
    RuntimeTelemetryV1,
    review_a5_candidate,
)
from quantbt.core.generated_product_contracts import NATIVE_EVENT_PRODUCT_REGISTRY
from quantbt.core.native_event_promotion import NativePromotionContext, resolve_native_event_promotion


HAS_NATIVE = importlib.util.find_spec("_quantbt_native") is not None


def _native_runtime(*, budget: RuntimeBudgetV1 | None = None, workers: int = 1):
    index = pd.date_range("2025-01-01", periods=24, freq="1h", tz="UTC")
    close = pd.Series(100.0 + np.arange(24) * 0.1, index=index)
    backend = NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=10_000.0, leverage=5.0),
            execution=ExecutionConfig(slippage_bps=1.0),
            fee_rate=0.0002,
            use_funding=False,
        )
    )
    full = backend.prepare_rust_batched_runner(
        index,
        closes={"BTC": close},
        highs={"BTC": close + 1.0},
        lows={"BTC": close - 1.0},
        opens={"BTC": close},
        symbols=["BTC"],
        contract_size=1.0,
    )
    runner = RustNativeIRRunner(
        full,
        NativeStrategyIR(
            NativeStrategyKind.SIGNAL_TARGET,
            "BTC",
            parameters=NativeStrategyParameters(quantity=1.0),
        ),
    )
    folds = (
        NativeIRFold(1, 0, 0, 8, 8, 16),
        NativeIRFold(2, 0, 0, 16, 16, 24),
    )
    return NativeWfoRuntimeV2(runner, folds, workers=workers, runtime_budget=budget)


def _signals(rows: int = 3) -> np.ndarray:
    base = np.where(np.arange(24) % 4 < 2, 1.0, -1.0)
    return np.ascontiguousarray(np.vstack([np.roll(base, row) for row in range(rows)]))


def test_runtime_budget_and_parallelism_contracts_fail_closed():
    with pytest.raises(ValueError, match="positive integer"):
        RuntimeBudgetV1(max_bars=0)
    budget = RuntimeBudgetV1(max_bars=10, max_workers=2)
    with pytest.raises(RuntimeBudgetError) as error:
        budget.require_preflight(bars=11, workers=1)
    assert error.value.code == "MAX_BARS"

    plan = ParallelismPlanV1.resolve(
        python_processes=2,
        rust_workers=8,
        max_total_threads=8,
        max_rust_workers=3,
        host_cpus=16,
    )
    assert plan.rust_workers == 3
    assert plan.blas_threads == plan.openmp_threads == plan.numba_threads == 1
    assert set(plan.environment) == {
        "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS", "NUMBA_NUM_THREADS"
    }


def test_cancellation_identity_and_bounded_audit_sink_are_deterministic():
    token = RuntimeCancellationV1()
    token.cancel("operator")
    assert token.canceled and token.reason == "operator"
    token.clear()
    assert not token.canceled and token.reason is None

    identity = RuntimeIdentityV1.create()
    assert identity.next_generation().session_id == identity.session_id
    assert identity.next_generation().generation == 2

    exported = []
    sink = BoundedAuditSinkV1(max_rows=3, chunk_rows=2, export_hook=exported.append)
    sink.extend({"sequence": value} for value in range(5))
    sink.close()
    assert [row[0]["sequence"] for row in exported] == [0, 2]
    assert sink.header == {
        "audit_rows_retained": 3,
        "audit_rows_dropped": 2,
        "audit_rows_exported": 3,
        "audit_chunks_exported": 2,
        "audit_truncated": True,
    }


def test_shadow_mismatch_emits_bundle_and_activates_kill_switch(tmp_path):
    telemetry = RuntimeTelemetryV1()
    assert telemetry.record_shadow(
        route_id="static",
        primary_fingerprint="same",
        oracle_fingerprint="same",
    )
    assert not telemetry.record_shadow(
        route_id="static",
        primary_fingerprint="rust",
        oracle_fingerprint="python",
        evidence_dir=tmp_path,
        details={"bar": 7},
    )
    snapshot = telemetry.snapshot()
    assert snapshot["shadow_runs"] == 2
    assert snapshot["shadow_matches"] == snapshot["shadow_mismatches"] == 1
    assert snapshot["native_kill_switch"] is True
    bundle = Path(str(snapshot["last_mismatch_bundle"]))
    assert json.loads(bundle.read_text(encoding="utf-8"))["details"] == {"bar": 7}


def test_a5_review_requires_soak_shadow_rollback_and_explicit_approval():
    candidate = {
        "replacement_paths": ["src/quantbt"],
        "migration_docs": ["docs/migration.md"],
        "tests": ["tests/test_route.py"],
        "rollback": "pin previous package",
        "deletion_approved": False,
    }
    eligible, reasons = review_a5_candidate(
        candidate,
        stable_release_cycles=1,
        unexplained_mismatches=0,
        fallback_rate=0.0,
    )
    assert not eligible
    assert reasons == ("explicit_deletion_approval_required",)
    eligible, reasons = review_a5_candidate(
        {**candidate, "deletion_approved": True},
        stable_release_cycles=1,
        unexplained_mismatches=0,
        fallback_rate=0.0,
    )
    assert eligible and not reasons


def test_auto_promotion_requires_generated_performance_and_rss_evidence():
    registry = deepcopy(NATIVE_EVENT_PRODUCT_REGISTRY)
    rule = next(
        row
        for row in registry["promotion_policy"]["rules"]
        if row["workload_id"] == "event_static_tape_v2_v3"
    )
    assert resolve_native_event_promotion(
        NativePromotionContext(
            requested_backend="auto",
            backend_policy="certified_only",
            workload_id="event_static_tape_v2_v3",
            execution_contract_id="event_lifecycle_v2_next_bar_close",
            strategy_mode="static_commands",
            profile="score",
            account_model="linear_quote_settled_gross_cross",
            bars=10_000,
            symbol_count=1,
            native_available=True,
            native_compatible=True,
            native_executable=True,
            native_capabilities=tuple(rule["required_capabilities"]),
            platform_tags=("cpython-3.12+", "linux-x86_64-local"),
        ),
        registry=registry,
        policy_table=registry["promotion_policy"],
    ).reason == "measurement_evidence_not_current"

    rule["enabled"] = True
    workload = next(row for row in registry["workloads"] if row["id"] == "event_static_tape_v2_v3")
    workload["maturity"] = "promoted"
    workload["auto_promotion"] = True
    registry["performance_evidence"]["event_static_tape_v2_v3"].update(
        {
            "status": "pass",
            "measurement_status": "current_candidate_verified",
            "identity_status": "current_candidate",
            "promotion_eligible": True,
        }
    )
    context = NativePromotionContext(
        requested_backend="auto",
        backend_policy="certified_only",
        workload_id="event_static_tape_v2_v3",
        execution_contract_id="event_lifecycle_v2_next_bar_close",
        strategy_mode="static_commands",
        profile="score",
        account_model="linear_quote_settled_gross_cross",
        bars=10_000,
        symbol_count=1,
        native_available=True,
        native_compatible=True,
        native_executable=True,
        native_capabilities=tuple(rule["required_capabilities"]),
        platform_tags=("cpython-3.12+", "linux-x86_64-local"),
    )
    promoted = resolve_native_event_promotion(
        context,
        registry=registry,
        policy_table=registry["promotion_policy"],
    )
    # Phase 72 deliberately rejects a bare status flip: current evidence also
    # needs matching comparator, wheel, hash, and measured-artifact fields.
    assert promoted.resolved_backend == "python"
    assert promoted.reason == "measurement_evidence_not_current"

    registry["performance_evidence"]["event_static_tape_v2_v3"][
        "end_to_end_faster_than_python"
    ] = False
    held = resolve_native_event_promotion(
        context,
        registry=registry,
        policy_table=registry["promotion_policy"],
    )
    assert held.resolved_backend == "python"
    assert held.reason == "measurement_evidence_not_current"


def test_checked_a5_manifest_has_no_unapproved_deletion_claim():
    root = Path(__file__).resolve().parents[1]
    review = json.loads(
        (root / "contracts/native_event_a5_review.json").read_text(encoding="utf-8")
    )
    deletion = json.loads(
        (root / "contracts/native_event_deletion_manifest.json").read_text(encoding="utf-8")
    )
    assert review["deletions_performed"] == []
    assert all(not row["a5_eligible"] for row in review["routes"])
    assert all(not row["deletion_approved"] for row in deletion["candidates"])


def test_a5_validator_and_platform_wheel_matrix_are_checked_assets():
    root = Path(__file__).resolve().parents[1]
    tool_path = root / "tools/check_native_a5_review.py"
    spec = importlib.util.spec_from_file_location("check_native_a5_review", tool_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.validate_a5_review() == []

    workflow = (root / ".github/workflows/native-platform-matrix.yml").read_text(encoding="utf-8")
    for platform in (
        "linux-x86_64",
        "linux-aarch64",
        "macos-x86_64",
        "macos-arm64",
        "windows-x86_64",
    ):
        assert f"id: {platform}" in workflow
    for version in ("3.11", "3.12", "3.13"):
        assert f'"{version}"' in workflow
    assert "Install and negotiate from wheel outside the source tree" in workflow


def test_event_facade_threads_runtime_budget_and_fails_before_execution():
    data = pd.DataFrame(
        {
            "open": [100.0, 101.0, 102.0],
            "high": [101.0, 102.0, 103.0],
            "low": [99.0, 100.0, 101.0],
            "close": [100.0, 101.0, 102.0],
            "volume": [1_000.0, 1_000.0, 1_000.0],
        },
        index=pd.date_range("2025-01-01", periods=3, freq="1h", tz="UTC"),
    )
    endpoint = QuantBTEndpoint.event_driven(
        input_mode="orders",
        profile="audit",
        backend="python",
        initial_capital=10_000.0,
        use_funding=False,
        runtime_budget=RuntimeBudgetV1(max_bars=2),
    )
    command = OrderCommand(
        timestamp=data.index[0],
        symbol="BTC",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        qty=1.0,
        tif=TimeInForce.IOC,
        order_id="entry",
    )
    with pytest.raises(RuntimeBudgetError) as error:
        endpoint.simulate(data=data, order_commands=[command], symbols=["BTC"])
    assert error.value.code == "MAX_BARS"


def test_shadow_kill_switch_falls_back_for_auto_and_rejects_explicit_rust(tmp_path):
    backend = NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=10_000.0),
            native_backend="auto",
            shadow_evidence_dir=str(tmp_path),
        )
    )
    assert not backend._runtime_telemetry.record_shadow(
        route_id="injected",
        primary_fingerprint="rust",
        oracle_fingerprint="python",
        evidence_dir=tmp_path,
    )
    pretend_rust = replace(backend._backend_selection, requested="auto", resolved="rust")
    fallback = backend._runtime_route_selection(pretend_rust)
    assert fallback.requested == "auto"
    assert fallback.resolved == "python"
    assert backend.runtime_diagnostics["telemetry"]["fallback_runs"] == 1

    explicit = replace(pretend_rust, requested="rust")
    with pytest.raises(NativeEventRustBackendError, match="shadow-oracle mismatch"):
        backend._runtime_route_selection(explicit)


@pytest.mark.skipif(not HAS_NATIVE, reason="quantbt-native extension is not installed")
def test_native_wfo_budget_handle_generation_cancel_and_replay():
    budget = RuntimeBudgetV1(
        max_bars=24,
        max_workers=2,
        max_commands=100,
        max_orders=100,
        max_active_orders=100,
        max_fills=100,
        max_audit_rows=4,
        max_native_memory_bytes=1_000_000,
        max_metric_rows=16,
        max_error_rows=4,
    )
    runtime = _native_runtime(budget=budget, workers=2)
    same_plan_runtime = _native_runtime(budget=budget, workers=2)
    batch = runtime.prepare_shared(_signals())
    try:
        first = runtime.score_prepared_batch(batch)
        before = runtime.diagnostics()
        runtime.reset()
        after = runtime.diagnostics()
        replay = runtime.score_prepared_batch(batch)
        assert after["worker_generation"] == before["worker_generation"] + 1
        assert first.terminal_fingerprint == replay.terminal_fingerprint
        with pytest.raises(ValueError, match="different runtime session"):
            same_plan_runtime.score_prepared_batch(batch)

        runtime.cancel()
        canceled = runtime.score_prepared_batch(batch)
        assert set(canceled.status.tolist()) == {7}
        runtime.clear_cancellation()
        assert set(runtime.score_prepared_batch(batch).status.tolist()) == {0}

        with pytest.raises(RuntimeBudgetError) as error:
            runtime.audit_prepared_batch(
                batch,
                selected_candidate_ids=np.asarray([0, 1, 2], dtype=np.uint64),
                expected_intent_fingerprint=batch.intent_fingerprint,
            )
        assert error.value.code == "MAX_AUDIT_ROWS"
    finally:
        batch.close()
        runtime.close()
        same_plan_runtime.close()
    with pytest.raises(RuntimeError, match="closed"):
        batch.intent_fingerprint
    with pytest.raises(RuntimeError, match="closed"):
        runtime.score_prepared_batch(batch)


@pytest.mark.skipif(not HAS_NATIVE, reason="quantbt-native extension is not installed")
def test_native_wfo_preflight_and_execution_budgets_have_typed_failures():
    with pytest.raises(RuntimeBudgetError) as error:
        _native_runtime(budget=RuntimeBudgetV1(max_bars=23), workers=1)
    assert error.value.code == "MAX_BARS"

    runtime = _native_runtime(
        budget=RuntimeBudgetV1(max_workers=1, max_commands=1, max_metric_rows=16),
        workers=1,
    )
    try:
        result = runtime.score_shared(_signals(1))
        assert set(result.status.tolist()) == {8}
    finally:
        runtime.close()


@pytest.mark.skipif(not HAS_NATIVE, reason="quantbt-native extension is not installed")
def test_per_fold_metric_budget_counts_candidates_times_folds_not_folds_squared():
    folds = 2
    candidates = 3
    runtime = _native_runtime(
        budget=RuntimeBudgetV1(max_workers=1, max_metric_rows=candidates * folds),
        workers=1,
    )
    cube = np.stack([_signals(candidates), _signals(candidates)], axis=0)
    try:
        batch = runtime.prepare_per_fold(
            cube,
            candidate_ids=np.arange(candidates, dtype=np.uint64),
        )
        try:
            assert len(runtime.score_prepared_batch(batch).candidate_id) == candidates * folds
        finally:
            batch.close()
    finally:
        runtime.close()

    rejected = _native_runtime(
        budget=RuntimeBudgetV1(max_workers=1, max_metric_rows=candidates * folds - 1),
        workers=1,
    )
    try:
        with pytest.raises(RuntimeBudgetError) as error:
            rejected.prepare_per_fold(
                cube,
                candidate_ids=np.arange(candidates, dtype=np.uint64),
            )
        assert error.value.code == "MAX_METRIC_ROWS"
    finally:
        rejected.close()
